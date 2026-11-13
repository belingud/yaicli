# v0.24.0 — Lite transport：httpx 直连 Chat Completions

> 版本：v0.24.0（roadmap P1-c，K22 之后唯一剩余项；不随本任务 bump/发版）
> 约束 spec：[`.trellis/spec/py/provider-guidelines.md`](../../spec/py/provider-guidelines.md)（实现后补 lite transport 章节）
> 基线：`master c51f7a3`（v0.23.0 已发布），分支 `feat/lite-transport`，PR 目标 `master`

## Goal

给 `openai` / `openai-compatible` 两个 provider 增加一条 **httpx 直连 `POST {base_url}/chat/completions`** 的轻量传输层（lite transport），替代 `openai` SDK 在"普通对话补全"请求路径上的职责。它解决的是 **one-shot 启动延迟**：`import openai` 在请求前花掉约 0.65s（沙箱实测，`-X importtime` 中 `openai` 累计 812ms），而同一路径上 `httpx` 的边际成本只有约 45ms。

SDK 路径完整保留：`LITE_TRANSPORT=false` 一行配置即可回退，其它 provider 不受影响。

## Background（现状与测量）

| 事实 | 证据（本机沙箱 2026-11-13） |
| --- | --- |
| one-shot 本地开销 1.6–1.8s | v0.23 master `scripts/bench.py -n 3` → `oneshot_local: 1759.7`；同树 SDK 回退路径 `-n 5` → **1623.2ms**（2026-11-13） |
| openai SDK 是请求前最大单项 | `-X importtime`：`openai` 累计 812ms（`openai.types` 691ms）；`openai` 边际 import 645–653ms |
| httpx 早已是基础依赖 | `pyproject.toml` dependencies 含 `httpx>=0.28.1`；同一进程内边际 import 约 45ms |
| 现有 provider 只用到两件事 | `client.chat.completions.create(**params)` 与迭代流式 chunk（`openai_provider.py` 552 行） |
| SDK 仅在 OpenAI 家族内部使用 | `openai_provider.py` 的 handler 对 SDK 模型只做鸭子式属性读取（`chunk.choices[0].delta.content` 等） |
| 回退/兼容路径已存在 | `LITE_TRANSPORT=false` 直接走原 SDK；无需改任何其它代码 |

## Scope

**In**

1. 新 `yaicli/llms/lite_transport.py`（httpx only，不 import openai）：`LiteChatClient` 提供与 `openai.OpenAI` 等价的 `client.chat.completions.create(**params)` 接口；返回与 SDK 同形的鸭子对象（`choices[].message/.delta`、`usage`、`tool_calls`、`model_extra`）。
2. 把 OpenAI wire 公共逻辑抽到 `yaicli/llms/openai_wire.py`（模块导入**不得** import 任何 SDK）：参数/工具/schema/消息转换、`completion()` 循环、非流式/流式 handler、错误包装、reasoning 提取。SDK 与 lite 两个后端共享它。
3. `openai_provider.py`：`import openai` 改为懒加载；新增 `create_client()` 按配置选择 lite / SDK；`OpenAIAzure`、自定义 `CLIENT_CLS` handler 子类保持 SDK；`openai_compatible_provider.py` 的 SDK 类型 import 移到 `TYPE_CHECKING`。
4. 新配置键 `LITE_TRANSPORT`（bool，默认 `true`，env `YAI_LITE_TRANSPORT`）：注册进 `DEFAULT_CONFIG_MAP` / `DEFAULT_CONFIG_INI` / `--template` / docs / README（drift guard 必须绿）。
5. `--verbose` 在 provider 构造时输出一行 `Transport: lite (httpx)` / `Transport: openai SDK`（machine 模式在 stderr）。
6. 测试：`tests/llms/test_lite_transport.py`（传输层单测，`httpx.MockTransport`）+ `tests/llms/test_lite_parity.py`（同一 wire payload 经 SDK 模型与 lite 解析后 `LLMResponse` 序列逐项相等）；更新因 openai 懒加载而失效的既有 patch 路径。
7. `scripts/bench.py`：`oneshot_local` gate 从 2200ms 收紧（按实测定，目标 1600ms）；docstring 更新。
8. 文档：`docs/usage/configuration.md`、`docs/advanced/upgrade.md`、`README.md`、相应 provider 页（若有）+ spec 增补。

**Out（本任务不做）**

- 不把 lite 默认扩展到其它 OpenAI-family provider（deepseek/groq/openrouter/... 继续 SDK；后续版本再灰度）。
- 不实现 Azure 的 lite 版本（`openai-azure` 永远 SDK），也不做 lite 的 embeddings/files/responses 等非聊天接口。
- 不改任何 provider 的请求参数语义、工具循环、预算/裁剪、渲染与 headless 契约。
- 不新增第三方依赖；不 bump 版本号、不发版、不改 CHANGELOG（发布时由 git-cliff 生成）。
- 不实现 SDK 的内部重试（408/429/5xx 的 SDK retry）：请求级重试由 `LLMClient` 的 `RETRY_*` 层负责，lite 与 SDK 行为在用户可观察层面一致（错误分类、退避）。

## Requirements

| ID | 要求（MUST） |
| --- | --- |
| R1 | 传输选择：`LITE_TRANSPORT` 为真 **且** provider 类名精确为 `OpenAIProvider` / `OpenAICompatibleProvider` 时使用 lite；其余（含 `OpenAIAzure`、`CerebrasProvider` 等自定义 `CLIENT_CLS` 子类、用户自定义子类）保持 SDK。选择在 provider 构造时一次决定；配置变更需重启进程。 |
| R2 | 请求 parity：`POST {base_url.rstrip('/')}/chat/completions`；`Authorization: Bearer <API_KEY>`；`default_headers`（`X-Title`/`HTTP_Referer`/`EXTRA_HEADERS`）原样发送；`Content-Type: application/json`；body = completion params（`timeout`/`extra_body` 单独处理，`extra_body` 深合并进 body）+ `messages` + 可选 `tools`；`extra_body` 中的键可覆盖基础 body；查询参数（`default_query`）原样附加。 |
| R3 | 响应 parity：非流式与 SSE 流式都解析为与 openai SDK 模型同形的鸭子对象，交给共享 handler；覆盖 text、`reasoning_content`/`reasoning`、并行且碎片化的 `tool_calls`（含无 index 的兼容分支）、`finish_reason`、`usage`（`stream_options.include_usage`、choices-less usage chunk、`prompt_tokens_details.cached_tokens`、`completion_tokens_details.reasoning_tokens`）。SSE 解析必须容忍注释行、空行、`event:` 行、多行 data 与 `[DONE]`。 |
| R4 | 错误 parity：HTTP ≥400 → `LiteAPIError(status_code, 原始 body)` → `wrap_provider_exception` 给出与 SDK 相同的 `kind`/`status_code`/`retryable`/`user_message`；网络/超时（`httpx.ConnectError`/`ReadTimeout`/`ReadError`）同样分类；HTTP 200 但首 chunk 带 `{"error": ...}`、或响应无 choices → `provider_response_error`（绝不把错误当 assistant 内容）；流式请求遇 400 且 body 提及 `stream_options`/`include_usage` 时，去掉参数重试一次。 |
| R5 | 可回退：`LITE_TRANSPORT=false`（config.ini 或 `YAI_LITE_TRANSPORT=false`）即走原 SDK 路径，输出、工具行为、错误分类不变；不需要其它配置。 |
| R6 | 配置/文档同步：`LITE_TRANSPORT` 出现在 `DEFAULT_CONFIG_MAP`、`DEFAULT_CONFIG_INI`、`--template`、`docs/usage/configuration.md` 参考表 + INI 片段、`README.md` 参考表；`tests/test_docs_config.py` 全绿。 |
| R7 | verbose：`--verbose` 时 provider 构造输出 `Transport: lite (httpx)` 或 `Transport: openai SDK` 一行；machine 模式（`-p/--json`）下该行在 stderr，stdout 结构化输出不变。 |
| R8 | 性能：`python scripts/bench.py -n 5` 的 `oneshot_local` P50 相对同树 SDK 回退路径（1623.2ms）下降 ≥ 400ms（目标 ~0.6s）；`version`/`help`/`template`/`entry_import`/`repl_ready` 不超出既有 gate；`oneshot_local` gate 从 2200ms 收紧到 1000ms（对应 roadmap 的「沙箱 ≤1.0s」验收）。 |
| R9 | 测试：新增 lite 传输层单测与 SDK/lite parity 测试；全量 `pytest`、`ruff check --no-fix yaicli tests`、`mkdocs build --strict` 通过；测试不联网、不读写真实 `~/.config/yaicli`。 |
| R10 | 导入边界：`yaicli/llms/lite_transport.py` 与 `yaicli/llms/openai_wire.py` 在模块导入期不得 import `openai`（可用子进程 `python -c "import yaicli.llms.lite_transport; assert 'openai' not in sys.modules"` 断言）；不新增依赖。 |

## Feature examples

> 本仓库 PRD 必须让读者"看到"功能。以下为逐字终端/输出块，实现必须匹配。

### 1. 默认（无需任何配置）：one-shot 变快，输出不变

```bash
$ python scripts/bench.py -n 5 --gate
metric              P50 (ms)  limit (ms)  status
version                 40.1         250  ok
help                   503.4         900  ok
template               506.9         900  ok
entry_import           397.6         900  ok
repl_ready             611.2        1800  ok
oneshot_local          584.3        1000  ok      # SDK 回退 1623.2 → 下降 ~1039ms (-64%)
```

`ai -p "hi"` 的 stdout/stderr、工具调用、`--json` 结构均与 v0.23.0 逐字节相同（只是更快）。

### 2. `--verbose` 显示传输层

```bash
$ ai --verbose -p "hi"
```

stdout（TTY；machine 模式下同样内容在 stderr）：

```text
Transport: lite (httpx)
Messages:
[{'role': 'user', 'content': 'hi'}]
...
```

### 3. 回退到 openai SDK（排障开关）

```ini
# ~/.config/yaicli/config.ini
LITE_TRANSPORT=false
```

```bash
$ ai --verbose -p "hi" 2>&1 | head -1
Transport: openai SDK
```

输出与工具行为不变，仅首次请求慢约 0.6s。

### 4. 错误路径与 SDK 完全一致（stderr，401 示例）

mock provider 返回 401 时，lite 路径与 SDK 路径渲染同一段分类错误（隔离 HOME，`--no-stream`）：

```text
Error Response: {'error': {'message': 'Incorrect API key provided', 'type':
'invalid_request_error', 'code': 'invalid_api_key'}}
Error processing LLM response: auth (HTTP 401): OpenAI API error: {'error':
{'message': 'Incorrect API key provided', 'type': 'invalid_request_error',
'code': 'invalid_api_key'}}
Hint: Check API_KEY / YAI_API_KEY and the provider's base URL.
```

exit code = 1。`--json` 模式下上述文本全部在 stderr，stdout 仍是单行 JSON 错误对象。

### 5. 流式 tool-call 与 reasoning 的 parity（不可见但验收）

同一段 SSE（并行 tool_calls + `reasoning_content` + 末尾 usage chunk）分别喂给 SDK 路径与 lite 路径，`LLMResponse` 序列的 `content`/`reasoning`/`tool_calls`/`finish_reason`/`usage` 逐项相等（测试断言，见 R9）。

## Presentation form

- 传输层切换本身**不改变任何用户可见输出**；唯一新增可见行是 `--verbose` 的 `Transport: ...`。
- 通道：verbose 行随现有 provider 诊断走 console（TTY → stdout；`-p/--json` → stderr）。
- 机器模式：JSON/NDJSON schema 不变，不新增字段。
- 交互/非交互：行为相同；代理由 httpx `trust_env` 继承 `HTTP(S)_PROXY`/`NO_PROXY`，与 SDK 内部的 httpx 传输一致。

## Logic

- 触发：provider 构造时判断 `LITE_TRANSPORT`（config.ini / env `YAI_LITE_TRANSPORT`，默认 true）且类名精确匹配；否则 SDK。
- 优先级：`YAI_LITE_TRANSPORT` env > config.ini > 默认 true（沿用现有 config 层）。
- 状态：每个 provider 实例一个 `LiteChatClient`（内含一个 `httpx.Client`），生命周期随进程/REPL；切换配置需重启。
- 错误体验：对用户来说与 SDK 路径一致（同一分类消息、exit code、重试语义）。
- 副作用：一次 HTTP 请求（与 SDK 相同）；不写盘；无新文件。

## Acceptance

1. `python scripts/bench.py -n 5 --gate`：全项 ok，`oneshot_local` P50 < 1000ms（本地实测 584.3ms；同树 SDK 回退 1623.2ms）。
2. `python -m pytest`：全绿（新增 lite/parity 测试 + 更新后的既有测试）。
3. `python -m ruff check --no-fix yaicli tests`：干净。
4. `python -m mkdocs build --strict`：通过（含新增配置键的 docs drift guard）。
5. `python -c "import yaicli.llms.lite_transport, sys; assert 'openai' not in sys.modules"`：通过。
6. mock server 场景（测试覆盖）：401/429/400-context-length/no-choices/首 chunk error/SSE 中断/超时/`stream_options` 拒绝重试/并行 tool_calls/usage-only chunk。
7. 手工：`YAI_LITE_TRANSPORT=false` 时 `--verbose` 显示 `Transport: openai SDK`；默认显示 `Transport: lite (httpx)`。

## Risks / 缓解

| 风险 | 缓解 |
| --- | --- |
| 兼容代理的 SSE 形态差异（无 finish_reason、错误文档当 chunk、usage 附加在普通 chunk） | 复用 v0.22 的 `ToolCallAccumulator` 与既有 handler；`test_lite_transport.py` 覆盖这些形态；`LITE_TRANSPORT=false` 即时回退 |
| httpx 与 SDK 的超时/代理/重试语义差异 | 请求级重试仍由 `LLMClient` 的 `RETRY_*` 负责（已测试）；httpx 默认 `trust_env=True` 继承代理；超时按 `TIMEOUT` 逐请求传入 |
| 重构 `openai_provider.py` 改变既有行为 | 逻辑移到 `openai_wire.py` 但 handler 代码逐行保留；SDK 测试全部保留 + 新增 parity 测试；`git diff` 只应是"剪切+懒加载"，无逻辑改动 |
| 用户自定义 `OpenAIProvider` 子类失去 lite | 类名精确匹配，未知子类保持 SDK（安全默认）；文档写明 |
| 报错信息 body 读取方式变化 | `LiteAPIError` 携带真实 `httpx.Response`（`.status_code`/`.text`/`.json()`/`.headers`），`wrap_provider_exception`/`retry_after_seconds` 的鸭子读取不变 |

## 决策记录

- 2026-11-13：用户决定 **不发 0.23.1**，直接完成 v0.24.0（本任务不 bump/不发布）。
- 2026-11-13：lite 默认只覆盖 `openai` / `openai-compatible`（用户当前配置即 `openai-compatible`），其它 provider 留待后续灰度。

## 实测结果（2026-11-13，本机沙箱，n=5）

| 指标 | SDK 回退（`YAI_LITE_TRANSPORT=false`） | 默认 lite | 变化 |
| --- | --- | --- | --- |
| oneshot_local | 1623.2 ms | **584.3 ms** | -1039 ms (-64%) |
| entry_import | 419.7 ms | 397.8 ms | 噪声内 |
| repl_ready | 605.9 ms | 599.1 ms | 噪声内 |
| help / template / version | 482 / 483 / 47 ms | 495 / 466 / 45 ms | 噪声内 |

CI `ubuntu-latest` 的 master 基线（2026-11-13，v0.23.0，HTTP 日志 run 43428399717）：
`oneshot_local = 622.3 ms`（SDK 路径）。lite 路径去掉 SDK import 后预期 CI ≈ 250–350ms；
`oneshot_local` gate 设置为 **1000ms**（roadmap 的「沙箱 ≤1.0s」），CI/本机均有 ≥1.6x 余量。

手工验收（mock provider，隔离 `YAI_CONFIG_DIR`）：
- 默认 `ai --verbose -p hi` → `Transport: lite (httpx)`；`YAI_LITE_TRANSPORT=false` → `Transport: openai SDK`；
- `-p --json` 的 stdout 仍是单行 JSON，`Transport:` 行在 stderr；
- 401 时 lite 与 SDK 的 stderr **逐字节相同**（分类消息 + hint），exit code 均为 1；
- 流式/非流式 one-shot 的 stdout（`plain` / `streamed`）两种传输一致。
