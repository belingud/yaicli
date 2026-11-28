# 代码组织评估证据

## Baseline and method

2026-11-27，只读检查 v0.26.0 发布后的 master，提交 d0cbb8f。通过 pathlib/ast 读取 yaicli/ 和 tests/ 的 Python 源文件，核对核心方法、依赖及已有行为测试。96 个产品 Python 文件共 31159 个物理行；108 个测试 Python 文件共 44968 行。行数只用于定位，不作为质量判断或验收阈值。

本轮没有运行产品测试或性能测试。既往 K25 通过的结果不冒充本轮重构基线。创建任务之前的无关工作区改动包括 .trellis/.template-hashes.json、三个 Trellis skill 目录及 .codex/；不得提交或覆盖。

## Findings and stage mapping

| 问题 | 证据 | 处理阶段 |
| --- | --- | --- |
| 命令定义分散 | cmd_handler.py:71—158 的帮助/补全元数据、164—201 的 handler 表、1333—1358 的带参数白名单 | 1 |
| tools 包入口职责混合 | tools/__init__.py:339—441 声明与缓存、501—557 展示、560—686 计划分派、689—854 执行 | 1 |
| 权限/执行与轮次混合 | llms/client.py:868—1128；后半仍负责消息追加和继续请求 | 1：提取权限判断，保留客户端 generator |
| CLI 单体与双向对象依赖 | cli.py 2964 行；cmd_handler 直接访问 CLI 的 28 个不同属性，含 18 个私有名称（不含动态 getattr） | 2 |
| 计划模块职责过多 | plan_mode.py 1651 行，包含状态、校验、存储副作用、提示词、编辑器；plan_store.py 已有独立存储代码 | 2 |
| 状态镜像及配置来源混用 | cli.py:873—919 同步计划状态；plan_mode.py:526—549 全局实例；tools/__init__.py:70—101 全局模式；LLMClient 接收 config 而工具读取 cfg | 3 |

较大但相对内聚的 CheckpointStore、ProviderFactory、provider 文件不按行数优先重写。保留 functions/buildin/ 拼写及用户工具覆盖机制。

## Existing executable contracts

| 边界 | 相关测试 |
| --- | --- |
| 命令匹配、帮助/补全、未知提示词、参数保留 | tests/test_command_handler.py、test_completer.py、test_checkpoint_commands.py、test_plan_commands.py |
| 工具加载、声明、缓存、覆盖、MCP | tests/tools/test_tools_init.py、test_function_loading.py、test_function_schema.py、test_mcp.py；tests/test_tool_schema_filter.py |
| 权限和危险 shell 优先级、generator.send | tests/test_permissions.py、test_tool_policy.py、test_plan_shell_gate.py；tests/llms/test_tool_confirmation.py |
| 模型调用、工具轮次、消息配对、预算 | tests/llms/test_client.py、test_multi_tool_calls.py、test_streaming.py；tests/test_context_budget.py |
| 机器输出、退出码、管道、元命令 | tests/test_headless_contract.py、test_headless_plan.py、test_runtime_bootstrap.py、test_startup.py |
| 交互和工作线程、确认、Ctrl+O、取消 | tests/test_stream_bridge.py、test_generation_keys.py、test_worker_console.py、test_tool_output_viewer.py、test_printer.py |
| 会话和检查点真实副作用 | tests/test_chat_manage.py、test_session_isolation.py、test_checkpoints.py、test_checkpoint_commands.py、test_checkpoint_integration.py、test_workspace_safety.py |
| 计划状态、存储、修订和恢复 | tests/test_plan_*.py、tests/test_todo_write.py |

## Important constraints

- CLI 的懒加载模块属性兼有既有测试注入用途；迁移前检查实际导入位置。不要为测试保留所有内部实现，但也不能让兼容导出变成无效转发。
- 工具声明 OpenAI/Anthropic 来自 pydantic schema，Gemini 读取 callable 签名；不能只验证一种 provider。
- MCP 执行会原地去除 ToolCall.name 前缀；gate-time 审计名、结果消息名和调用 ID 要分别维持现有语义，本任务不顺手修复该副作用。
- 独立用户工具不能依赖 YAICLI 内部配置对象；环境桥接有兼容目的。内部显式依赖和外部环境适配必须分别设计。
- CheckpointStore 已使用 ContextVar 关联轮次；线程取消、遗留工作线程、文件锁和保存回调不能因模块迁移改变顺序。
- 本任务的会话隔离是实例状态及串行/交替执行隔离，不承诺并行修改同一进程 cwd/环境的多应用并发支持。

## Documentation discrepancies

部分旧规范包含历史描述：quality-guidelines.md 仍写没有测试 CI、测试文件数 60；实际存在 .github/workflows/test.yml 和 bench.yml。cli-and-rendering.md 有早期 JSON 字段及用量描述，现有 CLI._build_result 包含 finish_reason，且已接入用量统计。function-tool-guidelines.md 的部分缓存描述早于计划模式缓存失效机制。

实施时以代码、现有测试和较新专项规范确认冻结行为，再更新本次实际改动涉及的段落；不要把历史文档误当成改变现有行为的授权。配置优先级规则保持，只调整实例内依赖获取方式。

## Planning conclusions

采用三个顺序、独立 PR 的阶段；具体要求由父 PRD R1—R4 维护。最先整理命令和工具边界，再提取 CLI/计划协调，最后改变状态所有权，避免在一批移动中同时改变所有依赖来源。无新增依赖、数据迁移或功能配置。
