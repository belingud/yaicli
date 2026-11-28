# Research: 第三阶段运行时与配置交接

- Query: 基于第二阶段实际服务边界，以最少结构实现每应用配置和惰性 PlanSession，如何划分并行所有权并保持工具、保存和锁语义？
- Scope: internal；只读代码研究，不启动第三阶段、不修改产品。
- Date: 2026-11-27
- Snapshot: 第二阶段实现中的工作区；planning 核心和集成测试已交接，CLI/application/命令仍可能调整。以下引用同时给出函数名，开始第三阶段时应以最终验收提交重核行号。

## Findings

### 1. 可以沿用的新边界

| 文件与位置 | 已核对事实 | 第三阶段含义 |
| --- | --- | --- |
| `yaicli/cli.py:213` `CLI.__init__` | 已组装 RunState、MachineOutput、SessionController；给后两者传的是同一个默认 cfg。 | 只需把配置来源换成应用拥有的有效映射，不应再次搬动服务。 |
| `yaicli/application/session.py:15` `SessionController.__init__` | 已接收 config、manager、state、console 和 history_changed；聊天、重试、capture/worker 引用集中在此。 | 注入同一应用映射即可；工作线程启动/取消仍属于 CLI，不能迁到配置上下文。 |
| `yaicli/application/output.py` `MachineOutput` | 已通过 config、RunState 和惰性 live_client 得到用量、结果和退出状态。 | 保留 live_client 的惰性，不为绑定运行时而读 `cli.client` 提前构造 provider。 |
| `yaicli/cli.py:646` `planning` | PlanCoordinator 惰性创建，接收 config、sessions、state、output、console、printer getter 和 PlanTurns。 | 在此增加一个明确的会话上下文依赖；不把整个 CLI 注入。 |
| `yaicli/planning/coordinator.py:57` `get_plan_session` | 从 service.get_plan_session() 取进程默认对象，再按当前 config、cwd、聊天 date 配置并保存在 coordinator.plan_session。 | 此处是创建/配置所属计划状态的主要接缝。上下文负责唯一对象，协调器保留实际 configure 所需聊天/目录业务。 |
| `yaicli/planning/coordinator.py:85` `sync_plan_tool_mode` | 根据 mode 计算 plan/execution/None，写全局 tools.set_plan_tool_mode，再通知 client。 | 显式实例路径应从同一个 PlanSession 派生工具模式，删除产品路径的全局副本同步。旧 setter 留给默认兼容入口。 |
| `yaicli/cli.py:658` `plan_session` 属性及 `:726` `_sync_client_plan_session` | CLI 的计划属性已委托协调器，client.plan_session 仍在存在时单独同步。 | 可把这些兼容属性委托到上下文同一引用，不能保留两个可独立更换的计划对象。 |
| `yaicli/planning/service.py:55` `get_plan_session`、`:139` `handle_submit_plan`、`:274` `handle_todo_write` | 默认会话只存一处，但两个会话工具处理函数仍主动取得默认对象。 | 给实际状态操作增加明确的内部 session 参数；默认调用保留旧行为，产品执行器必须传所属对象。 |
| `yaicli/llms/client.py:132` `LLMClient.__init__` | 保存传入 config，并把同一对象交给 ProviderFactory；plan_session 是另一个 slot。 | 工厂主路径传同一上下文/映射即可，不能让 runtime 参数继续穿过 **kwargs 进入 SDK。 |
| `yaicli/llms/client.py:766` `_execute_tools_and_continue` | policy 已用 self.config 和 self.plan_session，但 selected=tool_enabled(...)、execute_tool_call(...) 仍取无参默认入口。 | 只改 client.config 不够：选择、声明、执行必须一起绑定所属依赖。保留确认 yield/send、审计和消息配对顺序。 |

### 2. 共享接口应先定，再并行实现

建议只增加一个轻量会话上下文，例如 `yaicli/runtime.py::SessionContext`；下面是职责契约，不要求照抄名称或新增另一个工具状态容器：

- `config`：应用拥有的 dict。CLI 组装边界从已解析配置 `deepcopy(dict(source))` 一次，隔离嵌套 dict/list。各服务、client、provider 都引用它，不能各自再次复制、各自重新读文件/环境。
- `peek_plan_session()`：返回当前引用或 None，不导入 planning、不创建对象。
- `get_plan_session()`：第一次需要时局部导入并创建 PlanSession；以后返回同一个对象。根据聊天身份、目录和配置调用 configure 的业务仍由协调器负责，不能让上下文依赖 Chat/CLI。
- `tool_mode`：由已有会话 mode 即时计算；researching/revising -> plan，executing -> execution，其余及未创建 -> None。不要另存 `_plan_mode`。
- 配置绑定（确有必要时）：在同一轻量模块提供一个只承载有效映射的 ContextVar 作用域/读取函数，使保存、脱敏、limits、approval、MCP 等低层助手能读取所属配置。它不解析配置、不持有环境锁、不作为字符串服务定位器。默认未绑定时，兼容函数仍读其既有 cfg。

两个实现代理开工前应固定五点：配置对象是否在此已归应用拥有；peek/get 的惰性区别；mode 的唯一推导规则；默认兼容和显式路径的区别；低层配置绑定的函数名及恢复语义。上下文文件由一名代理独占，另一个只消费接口。

不要默认再建一个拥有第二份配置/计划字段的 ToolRuntime。工具 helper 可以接收同一个上下文；若需要一个绑定工具操作的适配对象，它只能持有该上下文引用，不复制状态。

注意既有注入语义：LLMClient 目前直接保存调用方传入的 config，预算钳制也可写入此对象。应用快照应在 CLI 组装边界完成，避免在 client/provider 再复制一次导致现有参数写回契约改变。外部注入的 ready client 保留对象及构造生命周期，不为统一路径擅自重建 SDK。

### 3. 声明和会话工具的绑定点

| 位置 | 需要绑定的内容 |
| --- | --- |
| `tools/schemas.py:51/82/206/244` | readonly-shell 开关、ENABLED_TOOLS、plan/execution 可见性及缓存键使用所属配置/状态。不可修改共用基础 schema 字典；缓存键覆盖 provider 格式、模式、选择条件、readonly-shell 及声明来源。 |
| `tools/function.py:252/264/280` | Gemini callable builder 仍读全局 mode/配置；缓存目前只按 mode。绑定具体会话的闭包不能进跨应用共享的 mode-only 缓存。可缓存不变函数/声明，再为当前实例生成绑定适配。 |
| `tools/session_tools.py:106/179/231/244` | 两个 schema 类的 execute 最终进入默认 service；Gemini 也包装这两个类方法。内部执行适配须接收所属 session，Gemini callback 须绑定它；模型参数、tool 名称、schema 字段和独立 execute 签名保持原样。 |
| `tools/executor.py:120/255` | 模式分派和 read-only shell 也必须使用所属会话；不要让客户端允许 A，执行器又查询 B 的默认计划对象。 |
| `providers/openai_provider.py:118`、`anthropic_provider.py:162`、`ollama_provider.py:160`、`cohere_provider.py:130`、`mistral_provider.py:86` | 这些 provider 当前调用无参 schema helper；绑定应发生在共同 provider/声明适配边界，避免逐个重写 completion。OpenAI 家族继承已有基类即可复用。 |
| `providers/gemini_provider.py:196` | 普通 callable 和 MCP 都在此聚合。绑定 callback 时保留现有 wraps/函数名/文档/签名，不把 runtime/session 注入模型参数。 |

可给 service 的内部状态处理函数增加 keyword-only session/config 参数，未传时才取旧默认；session_tools 用同一执行核心供默认类方法和显式适配复用。不要复制 submit/todo 的校验或状态转换业务，也不要通过临时 set_plan_session 或交换模块全局对象实现绑定。

必须继续冻结 provider 差异：Gemini 当前 callable builder 不应用 ENABLED_TOOLS，且直接聚合 MCP；本阶段不把它顺手改成 OpenAI/Anthropic 的筛选语义。A/B 测试应分别按各 provider 的既有契约断言模式和状态归属。

### 4. 原预审之外还要纳入的配置读取

已有 `runtime-config-review.md` 列出了 limits、redaction、approval、workspace.plan root 和 checkpoint audit；新服务形成后还应追踪以下实际入口：

| 文件与位置 | 当前读取/副作用 | 最小处理方向 |
| --- | --- | --- |
| `cli.py:759` `configure_headless` | max_turns 写默认 cfg；`_create_client:2047` 又传默认 cfg。 | 都改为所属映射；仍按原时机重建/失效本会话客户端。 |
| `cli.py` `_prompt_model_name`（本次复核约 `:1026`）与 `application/output.py:402` `prompt_model_name` | CLI 仍保留 static cfg 读取，输出服务已有接收 self.config 的等价短模型名格式化。 | 提示行/欢迎模型名也要使用所属配置，优先复用输出服务已有实现；不能只绑定 client 和 JSON payload。 |
| `cli.py:1162` `_get_project_context` -> `project_context.py:243/251/259` | 项目说明的启用和字符上限仍从默认 cfg 取得。 | 请求消息来源也需使用所属配置；显式 config 参数或已绑定配置作用域均可，不重新发现文件时改变现有缓存时机。 |
| `cmd_handler.py:127/146/691/702/974` | 预算、设置读写、计划启用仍使用默认配置 helper。 | 通过本会话命名服务/映射读写；不能只改 CLI 工厂后留下命令写全局。相关函数仍在 S2 收尾，应以最终接口核对。 |
| `planning/service.py:80` `_audit_enabled` | 计划审计是否开启仍看默认 cfg。 | 审计与当前计划状态使用同一所属配置。 |
| `tools/mcp.py:79/100/105` | 每次操作超时和工具数上限懒读默认 cfg。 | 绑定实际操作配置即可；无须为此重写 MCP 连接管理器。 |
| `planning/coordinator.py:124` `persist_chat_plan` | 直接 Chat.save；并非每个保存都经 SessionController.save_chat。 | 保存/脱敏配置绑定必须覆盖此路径、checkpoint commit 回调和普通 save，不要只包一个公开保存方法。 |
| `chat.py:286/452` | Chat.save -> to_dict -> 既有 redaction；FileChatManager.save_chat 使用 manager.chat_dir。 | 配置作用域可保持 Chat 现有数据/序列化 API；同时核对默认管理器目录问题，见末尾 caveat。 |

`tools/limits.py:84/98`、`redaction.py:236`、`tools/approval.py:75`、`tools/workspace.py:283`、`checkpoints.py:979` 的默认 cfg 读取也要同时覆盖。重点是实际运行中的数据流，不是把所有 `cfg` 文本替换掉。

MCP_MAX_TOOLS 的缓存语义已进一步核对：`mcp.py:453` list_tools 缓存完整服务端列表，`:531` _ensure_tools_map 缓存完整映射；`:220/230` 的 cap 在 `tools:529`、`tools_map:556` 每次访问时重新计算。`MCP_TIMEOUT` 在 `_list_tools_async:466`、`_call_tool_async:498` 的实际操作中读取，没有固化成 client 实例的 timeout 字段。因此应在声明转换和实际调用两个边界绑定当前配置，保留完整缓存及当前按名称排序/截断语义；不可让初次声明时的 A 配置固化进全局 manager。

Gemini 的 MCP callback 同样可能在声明作用域结束后执行，需绑定所属映射；不能只给 submit_plan/todo_write 闭包传 session 而漏掉普通/MCP callable 的实际操作配置。仍保留 Gemini 现有直接 MCP 聚合和 ENABLED_TOOLS 差异。

### 5. 环境适配与锁：必须区分两种作用域

当前 `tools/executor.py:25/45` 管理四个键：TOOL_TIMEOUT、TOOL_ENV_INHERIT、WORKSPACE_ROOT、TOOL_OUTPUT_MAX_CHARS 对应的 YAI_*。它永久写环境、跳过空值；`:255` 的实际执行先同步，再进入 `workspace.mutation_lock()`。计划工具分派在这次同步之前返回，因此新适配也要覆盖计划 read-only shell 的实际执行。

建议的最小适配是一个 contextmanager，加一个进程级可重入锁：

1. 在实际工具执行线程中取得环境锁，保存四个键原先是否存在及其值。
2. 应用所属配置的完整托管视图；None/空/default 要明确移除该键并使用既有工具默认值，不能沿用上一应用值。bool 仍转为 true/false。
3. 在其内部执行原有 guard -> workspace mutation lock -> capture.prepare -> tool.execute -> record/undo -> 结果处理。
4. finally 恢复原环境并在同一线程释放锁；不能清空 API_KEY、PATH 或其他未托管变量，不能改变既有独立工具继承白名单。

这只是环境桥接，不能取代显式 session/config 传递。低层配置 ContextVar 作用域与环境锁分开：前者可以覆盖消息构建/保存，后者只覆盖需要环境的实际工具/undo 操作。

已核对的锁和线程事实：

- `workspace.py:72` mutation_lock 根据显式 root 或 YAI_WORKSPACE_ROOT/cwd 取锁；`:558` undo_last 在其内部回退。因此 undo 的环境作用域应在调用 undo_last 之前建立。
- `checkpoints.py:396` begin_turn 持有会话 writer lock 到 finish/abandon；`:626` rewind 在 writer lock 后持有 mutation_lock(self.root)，并在此内部调用 commit_chat。
- `application/session.py:252` checkpoint_store 已从 **self.config 的 WORKSPACE_ROOT** 显式取 root；不需要等首个工具更新环境。store 内已有显式 root 的路径不必再为环境适配反向取锁。
- `application/session.py:33/325` 保存和重置、`planning/coordinator.py:124` 计划保存、CLI 的 checkpoint commit 都可能调用 Chat.save。它们可以使用无锁配置作用域供脱敏读取；不能让 rewind 的 commit_chat 在已持有 workspace lock 时再去取得环境锁。
- `cli.py:1517` 的整轮 checkpoint 包装可能启动流式 worker，并在 worker.alive 时保留 pending/capture；此语义要保留。
- `stream_bridge.py:120-131` start 已用 contextvars.copy_context() 启动 worker。配置绑定在正确的 worker 启动位置建立即可复用该机制，无须增加另一套线程局部状态。

特别禁止把环境 RLock 包住整个 `_process_user_input`、provider generator 或确认等待：主线程持锁再等待 worker，而 worker 执行工具又取此锁，会形成死锁。取消时若真实工具仍未结束，环境作用域须留在执行线程直到实际返回，保持已有 busy/barrier 处理，不能由主线程提前“恢复”它。

### 6. 可直接采用的并行所有权

| 实现线 | 唯一写所有权建议 | 交接边界 |
| --- | --- | --- |
| A：应用/计划状态 | 共享 `runtime.py`；CLI、application/*、commands/cmd_handler；planning/coordinator.py、service.py；必要 chat/project_context 配置入口及其既有测试 | 先公布上下文的 config、peek/get、tool_mode、配置作用域 API；service 的显式 session 参数由 A 定义，B 只调用。 |
| B：模型/工具运行 | llms/client.py、provider.py 及必要 provider 声明适配；tools/schemas/executor/function/session_tools/mcp/limits/approval/workspace；redaction.py 和 checkpoints.py 的审计配置读取；工具/权限/provider 既有测试 | 不编辑 runtime.py 或应用服务；使用 A 的同一上下文。环境桥接及其专用锁由 B 独占，先小范围证明锁顺序。 |
| C：独立隔离测试 | 新的 runtime-isolation 与 config-only-root 跨进程测试文件 | 先与 A/B 固定构造 API；对默认旧实现应暴露污染，完成后验证实际声明、状态、文件和环境。不要修改 A/B 的既有测试文件。 |

先冻结共享接口，再并行；共享测试文件临时需要修改时指定一名编辑者。B 不要等到所有 provider 重写后才验证，应按 schema -> session tools -> gate/executor -> 环境/下层配置逐批走实际链路。最终检查仍由独立 check 代理汇合完成。

### 7. 必要验收用例

1. 同一进程真实 A -> B -> A：两个独立配置快照（含嵌套值）、两个懒建计划状态；交替切换模式，生成三种 provider 声明，调用 submit_plan/todo_write，断言对方状态和模式不变。不能通过 set/reset 默认计划会话清场。
2. 在 B 声明之后再执行 A 的 Gemini 会话 callback，确认绑定仍属于 A；检查 signature/schema 无新增 runtime/session/config 字段。
3. 工具选择、readonly/trusted、输出 cap、spill/保存脱敏分别使用不同配置，并覆盖同一应用模型/角色切换、客户端重建和恢复。至少一项 A 的嵌套配置改变后 B 不受影响。
4. 两个实际 workspace root 交替真实写入；异常、拒绝和空/default 之后再调用，不能继承另一应用 root/timeout/输出上限。每次检查四个环境键恢复，未托管键保持不变。
5. 环境适配包含 undo；checkpoint rewind 内保存回调不反向取环境锁。继续使用 Event 控制取消前/后实际写入，验证 pending、文件、锁和下一轮安全基线。
6. 子进程只用配置文件指定 root，cwd 为子目录，去掉继承 YAI_WORKSPACE_ROOT；sync/stream 均验证保存、重新打开和实际回退字节。测试过程只使用私有临时 HOME/config。
7. 将旧 get_plan_session/get_plan_tool_mode 路径设为报错，显式产品路径仍可声明和执行；默认兼容入口单独验证。新进程启动不多读配置/存储、不提前导入计划/终端/SDK。

研究没有运行测试，也不把 S2 进行中的代码当作 S3 已实现；完整测试、格式、三版本和性能由最终验收负责。

### 8. 应保留的共享对象

保留 Config/get_config/cfg 的默认加载入口、静态路径/默认常量、只读函数加载结果、完整键区分的基础声明缓存、现有 MCP 连接管理器，以及不属于本阶段目标的 console、undo stack、output history。不要以“清理全局”为由扩展成全面重写。role/context 管理器也不应无关重构；但其请求路径若读取有效配置，则应在消费处绑定所属配置。

### Related specs

- `.trellis/spec/py/config-and-context.md`：解析优先级、惰性写入、SessionController、保存与配置约束。
- `.trellis/spec/py/function-tool-guidelines.md`：独立 builtin/user 签名、单次截断、workspace/undo、确认和 MCP。
- `.trellis/spec/py/provider-guidelines.md`：ProviderFactory、继承与 SDK 懒加载、声明与工具消息转换。
- `.trellis/spec/py/checkpoints.md`：writer/mutation 锁、commit callback、取消和恢复格式。
- 第三阶段 `prd.md`、`design.md`、`implement.md` 及其既有 `research/runtime-config-review.md`。

### External references

无外部资料引用。结论来自本地源码及现有任务/规范，未查询实时库文档或真实服务。

## Caveats / Not Found

- 第二阶段 application/cmd_handler 仍在收尾。本文没有对它做重复兼容审查，相关方法行号和最终命名须在 S2 验收提交后复核。
- 第三阶段 design.md 的开头仍写“前两阶段已合并”，末尾仍写最后一个实现 PR；这与已更新的 PRD/父任务“同分支串行提交、最终统一 PR”不一致。主线程应在 start S3 前修正文案，本研究不能修改其他任务目录。
- 默认 chat manager 的目录要单独确认：`cli.py:213` 当前重用模块级 chat_mgr 并改 manager.chat_dir；`chat.py:34` resolve_default_chat_dir 读默认 cfg，`:452` save_chat 使用 manager.chat_dir。两个默认 CLI 先后构造时，仅复制 config 并不能自动隔离这个可变目录。若实际工厂也要保证不同 CHAT_HISTORY_DIR，应在组装边界创建/绑定所属管理器或提供显式配置解析，保留用户注入 manager；不要依靠测试总是传独立 manager 掩盖问题。此项是 S3 接缝风险，不是要求扩大成所有管理器的并发隔离。
- role/render/console 的默认配置读取仍存在，Role.__post_init__ 在 `role.py:23` 已把 OS/shell 变量格式化进 prompt。应明确本阶段有效配置所需的消费边界；不能为移除每个 cfg 引用重写这些无关单例。
- 未承诺同进程多应用并行、并发 cwd、跨实例 undo/output-history 所有权隔离；本研究的环境锁方案只支撑当前任务承诺的串行/交替使用及现有 worker 生命周期。
