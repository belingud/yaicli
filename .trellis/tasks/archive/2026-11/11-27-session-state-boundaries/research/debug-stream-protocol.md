# Research: 工具调用后流式正文重复的 provider/client 协议排查

- Query: 单次 get_weather 调用及结果之后，“今天杭州天气不错，是个晴天 ☀️”重复上百次，最后出现完整正文；检查 provider/client 是否重复 yield、错误处理累计快照或重复递归。
- Scope: internal；只读产品代码及既有测试，在 /tmp 创建隔离假流脚本；不重复另一研究线的 debug 日志、Rich Live、终端渲染调查。
- Date: 2026-11-28
- Baseline: 主会话提供 chore/refactor-command-tools / HEAD 7408c51。研究角色不执行 git 操作，版本比较依据主会话导出的 `/tmp/yaicli-debug-history/protocol-master-head.diff`。

## Findings

### 已验证结论

1. **未能用无重复增量假流在 provider/client 层复现重复正文。** OpenAIProvider、OpenAICompatibleProvider 的单工具续答都只产生两次 provider 请求、一次工具执行、一次 RefreshLive；首句只出现一次。首句后插入 100 个空 chunk 也仍只出现一次。
2. **client 对正文采用增量契约，没有把本地累计正文重新 yield。** 它逐项转发 provider 响应一次，并另外累计到最终 ChatMessage；工具后只递归续调一次。保存会话用的累计变量与往调用方发送的响应不是同一个值。
3. **该层会原样保留上游的重复增量，也会把误放在 delta.content 的累计快照相加。** 两种输入均可造成历史正文真实重复，但这不能反推用户此次必然属于其中一种。
4. **工具后首句已经输出再断流，不会自动重试重播。** 两个 OpenAI 解码器的假流均抛出包含 partial content 的 AgentError，只保留两个实际 provider 请求，工具不重跑，部分 assistant 答复不保存。
5. **与 master 比较，当前重构未修改 provider 的流式正文解码、client 的 `_stream_provider` 或 `completion_with_tools` 正文转发/累计。** provider 变化集中于实例 runtime 的工具声明/配置绑定，client 变化集中于配置所有权和工具权限/执行。不能因此排除所有调用环境变化，但没有发现本次重构引入正文快照重播的代码差异。

### 数据流与代码证据

| 路径 | 契约/行为 | 当前代码 |
| --- | --- | --- |
| provider 到 client | 每个响应代表本次增量；规范要求 `LLMResponse(content=delta)` | `.trellis/spec/py/provider-guidelines.md:87-116` |
| OpenAI 正文解码 | 每轮循环只读取当前 `chunk.choices[0].delta.content`；输出当前 content；末尾 usage 响应正文为空 | `yaicli/llms/providers/openai_provider.py:297-369` |
| OpenAI 工具终止 chunk | 完整调用逐个输出，但该 chunk 正文只附在第一个响应；不会把历史正文带入 | `yaicli/llms/providers/openai_provider.py:345-358` |
| Generic OpenAI compatible | 每轮读取当前 delta.content；工具参数完整后的 pending 分支和普通分支互斥，工具 id 防重复发出 | `yaicli/llms/providers/openai_compatible_provider.py:45-116` |
| Anthropic | 正文仅从 content_block_delta.text 输出；message_delta/message_stop 重发调用列表时 content 为空 | `yaicli/llms/providers/anthropic_provider.py:312-368` |
| Gemini | 当前 chunk 的每个非 function_call part 直接输出；完整工具列表、末尾 usage 不携带正文 | `yaicli/llms/providers/gemini_provider.py:348-404` |
| Ollama | 当前 message.content 输出一次；完整工具列表在循环后单独输出 | `yaicli/llms/providers/ollama_provider.py:231-254` |
| ChatGLM | full_content 的累计用于解析嵌入工具 JSON；实际正文仍是本轮 delta.content | `yaicli/llms/providers/chatglm_provider.py:102-147` |
| AI21 / MiniMax | 正文取当前 delta.content；工具参数有各自累计语义，没有累计正文重播 | `yaicli/llms/providers/ai21_provider.py:45-88`、`yaicli/llms/providers/minimax_provider.py:106-145` |
| LongCat | reasoning 有专门累计及工具解析；content 沿用当前基类响应 | `yaicli/llms/providers/longcat_provider.py:129-166` |
| client 转发 | `yield llm_response`；每个 provider 响应一次 | `yaicli/llms/client.py:564-565` |
| client 保存 | `assistant_response_content += llm_response.content`，只在循环结束后构造一个 assistant 消息 | `yaicli/llms/client.py:579-627` |
| client 工具调用去重 | 仅按工具 id 去重；正文不去重 | `yaicli/llms/client.py:613-627` |
| 续答 | 执行前只发一个 RefreshLive，追加工具结果，再执行一次 `yield from completion_with_tools(...)` | `yaicli/llms/client.py:798-804`、`:892-924` |
| 重试 | 任意 provider 响应已经 yield 后，错误直接转为 AgentError，不再重试 | `yaicli/llms/client.py:456-489` |
| 响应结构 | content 是普通字符串，没有累计/增量标记，无法仅凭内容自动识别协议 | `yaicli/schemas.py:49-90` |

一个工具调用/结果只能证明工具执行次数；同一次后续模型响应仍可能包含很多重复增量。另一方面，屏幕上重复首句也不能证明这些重复字符进入了响应流或保存历史，需要与原始 chunk/保存结果区分。

### 可复现假流

脚本：`/tmp/yaicli_debug_stream_protocol.py`。启动器：`/tmp/yaicli_refactor_run.py`，为每次运行创建独立 HOME/config/cache，移除继承的 YAI/XDG 和常见凭证变量；脚本使用假 provider、假工具、Pydantic ChatCompletionChunk，socket.connect/create_connection 显式禁止网络，不创建真实 SDK 客户端。

运行命令（命令执行时通过 rtk）：

```bash
python3 /tmp/yaicli_refactor_run.py .venv/bin/python /tmp/yaicli_debug_stream_protocol.py
```

结果目录 `/tmp/yr-chitr99b`，退出码 0。两个解码器共 10 个场景：

| 每个解码器的场景 | 输入中的首句次数 | 输出/保存历史中的首句次数 | 请求/工具/RefreshLive |
| --- | --- | --- | --- |
| 正常增量正文，另含合法重复“哈”“哈”“哈” | 1 | 1 / 1 | 2 / 1 / 1 |
| 首句后 100 个空 chunk，再给后文 | 1 | 1 / 1 | 2 / 1 / 1 |
| 上游同一句发送 100 次，随后给完整后文 | 100 | 100 / 100 | 2 / 1 / 1 |
| 三个逐步增长的累计快照放入 delta.content | 3 | 3 / 3 | 2 / 1 / 1 |
| 工具后首句输出，下一次迭代抛 ConnectionError | 1 | 输出 1；部分答复未保存 | 2 / 1 / 1；无自动重试 |

正常场景验证输出字符串、保存的最终 assistant.content 与输入增量连接结果完全一致，并检查续答请求里确实存在一个配对的 weather-1 工具结果，未只断言 mock 调用。

### 既有回归

运行命令（隔离 HOME、假 provider/SDK、无真实 API）：

```bash
python3 /tmp/yaicli_refactor_run.py .venv/bin/python -m pytest tests/llms/test_client.py tests/llms/test_streaming.py tests/llms/test_openai_compatible_provider.py tests/test_context_budget.py::TestClientRetryPolicy -q
```

结果：**45 passed in 1.85s**，退出码 0，证据 `/tmp/yr-9ygr9d3q/stdout.txt` 和 `result.json`。覆盖增量转发、工具递归、OpenAI 实际解码到 client 的并行调用、完整参数提前发出，以及首字后网络错误不重试。

相关既有测试证据：

- `tests/llms/test_client.py:91-114`：两个正文增量按原样各返回一次。
- `tests/llms/test_client.py:116-172`：一个工具，两个 provider 请求，中间一个 RefreshLive。
- `tests/llms/test_client.py:395-479`：真实 OpenAI 解码器接入 client 的工具流续答。
- `tests/llms/test_streaming.py:32-100`：Hello / world / ! 增量逐项输出。
- `tests/test_context_budget.py:838-870`：首字前可重试，首字后错误直接退出。

### master 与当前重构比较

使用主会话导出的差异文件，不执行 git：

- client diff 的相关 hunk 位于导出文件 `:5-108`、`:112-418`，涉及 runtime/config、权限评估和工具执行参数；`_stream_provider`、`completion_with_tools` 没有改动，末尾递归逻辑没有改动。
- provider diff 在导出文件 `:422-575`；OpenAI/Anthropic/Cohere/Gemini/Mistral/Ollama 仅给 schema/callable 添加所属 runtime/config。全部流式 handler 未改动。
- OpenAICompatibleProvider、其余专用 provider、schemas.py 未出现在差异中。
- 因此，本次没有“原本输出增量、重构后输出累计正文”这一直接代码变化。有效配置的实例化改变是否使用户得到不同上游生成结果，需要该次请求证据才能判断，不能从此差异推测。

### 剩余最低信息与后续验证建议

主会话 2026-11-28 告知已读取真实 debug.log：最新一轮仅有 prompt.begin、generation.begin、watcher.start/ready、generation.end、watcher.stop/prompt.begin 等生命周期，没有 chunk、正文长度或 provider 请求边界数据。本研究未直接读取真实日志，不把这些事件当作正文证据。

现有材料不足以在以下两类之间定因：

1. 上游 chunk 中已经存在重复正文/累计快照，因此保存的 assistant 内容也重复。
2. 增量与保存内容正常，但终端捕获含原始 ANSI 重绘或 Live 刷新快照，看起来重复。

最小判据是同一轮保存的 assistant 正文是否真实重复；若重复，再看工具后连续 2—3 个非空 provider chunk 的 delta.content（可仅提供长度和脱敏短前缀/哈希）与 provider key、模型 id、网关主机名。无需密钥、完整请求或整段历史。生命周期日志本身不能回答该问题。

只有确认具体网关违反增量契约、且确实返回累计快照后，才应在该协议适配层讨论定向转换。不要对所有模型输出做通用内容去重；“哈”“哈”“哈”等正常重复以及合法列表/代码会被破坏。也不要在已经输出正文后新增重试，上述回归已证明它会破坏现有不重播约束。

后续真实行为回归应重放脱敏的实际 chunk 序列，断言非空增量序列、最终保存内容、provider 请求次数和工具执行次数；终端重绘应由另一调查线以相同无重复假流做真实 TTY/ANSI 验证。两种证据不能互相代替。

## Files Found

- `yaicli/llms/client.py`：流式转发、保存累计、重试、工具执行及递归续调。
- `yaicli/llms/provider.py`：provider 抽象接口与 runtime 注入工厂。
- `yaicli/llms/providers/openai_provider.py`：OpenAI 增量正文、工具 fragments 及 usage 处理。
- `yaicli/llms/providers/openai_compatible_provider.py`：兼容网关提前完整 JSON 工具调用适配。
- `yaicli/llms/providers/{anthropic,gemini,ollama,chatglm,ai21,minimax,longcat}_provider.py`：不同流式正文/工具载荷语义。
- `yaicli/schemas.py`：统一 LLMResponse/ChatMessage/ToolCall 结构。
- `tests/llms/test_client.py`、`test_streaming.py`、`test_openai_compatible_provider.py`：相关假 provider 与 fake chunk 既有回归。
- `tests/test_context_budget.py`：client 重试及上下文恢复回归。
- `/tmp/yaicli-debug-history/protocol-master-head.diff`：主会话提供的 master 至当前版本差异。
- `/tmp/yaicli_debug_stream_protocol.py`：本次 10 场景短假流复现脚本。

## External References

无。此次只对本仓库实际契约、差异和离线假流形成结论，没有外部请求或真实模型调用。

## Related Specs

- `.trellis/spec/py/provider-guidelines.md:87-116`、`:174-179`：正文必须增量，工具参数完整后发出，首字后失败不重试。
- `.trellis/spec/py/quality-guidelines.md:63-105`：隔离 HOME、在导入前给测试凭证、mock SDK 和 schema 入口。
- `.trellis/spec/guides/cross-layer-thinking-guide.md:19-51`：明确每个边界的输入/输出格式。
- `.trellis/spec/guides/code-reuse-thinking-guide.md:61-82`：数据契约归属应集中在边界。
- 本任务 `prd.md`、`design.md`、`implement.md`：本次为配置/会话状态隔离重构，不授权流式协议改写。
- 已阅读仓库 AGENTS.md、`/Users/vic/.codex/DEVELOP.md` 与 `.trellis/workflow.md`。遵守 research 角色隔离，未读取 implement.jsonl/check.jsonl。

## Caveats / Not Found

- 不知道用户实际 provider、模型/网关，不把 OpenAI 两种假流结果推广为所有 SDK/网关的实测证明；其他 provider 仅源码核对。
- 没有真实 chunk 序列、真实 provider 请求次数、保存的 assistant 正文，不能断言模型在重复，也不能断言 renderer 是根因。
- 没有读真实用户环境文件、配置、密钥或日志；真实日志的信息来自主会话已授权读取后的转述。
- 当前测试无重复输入时未复现的是 provider/client 层；不涵盖 Rich Live、日志捕获、终端重绘。
- 没有修改产品、既有测试、spec 或任务设计；不提交、不 push。此文件及 /tmp 脚本是仅有新增内容。
