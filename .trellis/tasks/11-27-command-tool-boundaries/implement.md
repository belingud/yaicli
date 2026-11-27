# 第一阶段执行清单

## Before implementation

- [x] 用户已在上一轮最终规划摘要后明确要求实现。
- [x] 用户于 2026-11-27 批准补测优先及命令/工具并行的更新方案，规划评审通过。
- [x] 确认父任务和本任务文档、实现/检查清单通过校验；已读适用规范。
- [x] 已获取远端 master，确认仍为 d0cbb8f；建立 chore/refactor-command-tools，PR 目标 master。
- [x] 通过隔离环境记录完整 pytest、代表性机器输出契约和启动基线；初轮环境/测试隔离问题已记录，不访问真实用户配置。
- [x] 使用本任务上下文调度三个 Trellis implement 子代理；任务提示以 Active task: 开头，分别限定命令、工具和共享集成测试所有权。

## Implementation order

- [x] 先按父任务 research/test-safety-review.md 补齐关键接缝，并在旧实现上通过：独立固定命令契约、持久授权失败回退、权限到真实执行器、大输出元数据、真实工具 NDJSON 及取消/检查点组合边界。
- [x] 修正相关测试的恒真断言、失效集合引用、provider patch 目标及遗漏 DNS mock；已记录临时路径长度对固定字符上限测试的影响，不修改产品语义。
- [x] 补齐命令 token、别名、参数保留和近似名称的特征测试；expected 不从新注册表反推，保留无参命令尾部文本与 /checkpoints 参数校验的区别。
- [x] 统一命令定义与分发表生成；帮助/补全从同一来源获取，保持 CmdHandler 入口。
- [x] 提取声明、筛选与缓存，分别冻结 OpenAI/Anthropic/Gemini/MCP 原有输出和懒加载；保留研究记录中的 Gemini 既有差异，不顺手统一语义。
- [x] 提取权限评估，保留客户端确认生成器、授权处理、审计和配对消息时序。
- [x] 提取 executor/display，维持 workspace lock、capture、undo、截断与输出历史的实际边界。
- [x] 清理重复缓存和废弃的内部转发，公共兼容入口保持薄且可用；显式保留当前 cfg/console 注入。
- [x] 更新 docs/dev/architecture.md、相关工具/provider/CLI 规范；后续阶段以 tools/schemas.py、policy.py、executor.py、display.py 及 commands/registry.py 为已实现边界，合并后再更新上下文。

## Parallel ownership

2026-11-27 更新方案已获批准，第一阶段按以下两条实现线并行：

- 命令线使用 Trellis implement 子代理，负责 commands/registry.py、cmd_handler.py 及命令/补全专属测试；不修改 tools、llms/client.py 或 CLI 的运行循环。
- 工具线使用另一个 Trellis implement 子代理，负责 tools 的声明/权限/执行/展示提取、llms/client.py 的对应适配及工具/权限专属测试；不修改命令分发文件。
- 真实 NDJSON、取消/检查点组合测试及架构/规范文档由主线程统筹，指定唯一编辑者，避免两个子代理同时修改共享测试；既有产品缺陷先记录，不顺手改变行为。
- 两条实现线完成后汇合，冻结修改范围，再调度独立 Trellis check 子代理做跨层审查和完整门禁。发现依赖关系时串行衔接，不为并行拆分共享状态或制造重复兼容层。

各代理须明确所有权并保留他人改动。第二、三阶段仍等待前置 PR 合并后再重新核对，不能与本阶段并行改产品代码。

## Focused tests

以下命令遵守父 implement.md 的隔离启动要求；不直接读取个人配置。

~~~bash
uv run --no-sync pytest tests/test_command_handler.py tests/test_completer.py tests/test_checkpoint_commands.py tests/test_plan_commands.py -q
uv run --no-sync pytest tests/tools tests/test_tool_schema_filter.py tests/test_permissions.py tests/test_tool_policy.py tests/test_plan_shell_gate.py -q
uv run --no-sync pytest tests/llms tests/test_context_budget.py tests/test_workspace_safety.py tests/test_checkpoint_integration.py -q
uv run --no-sync pytest tests/test_printer.py tests/test_tool_output_viewer.py tests/test_stream_bridge.py tests/test_worker_console.py tests/test_headless_contract.py -q
~~~

## Check / finish

- [x] 使用 Trellis check 子代理检查 S1-A1—S1-A5；核对行为及副作用，不只检查模块导入成功。独立审查无阻塞项。
- [x] 完整 pytest 3152 passed；Ruff --no-fix、27 个改动文件格式/isort、Python 3.10 语法、strict docs、wheel/sdist、六项启动门禁及 git diff --check 通过。
- [x] verification.md 写明基线提交、命令、环境隔离方式、结果和未覆盖风险；冻结后 212 个 Python 文件哈希一致。
- [ ] 分支提交和 PR 记录中包含原因、测试证据和回退方法；CI 通过后等待用户明确授权合并。
- [ ] 合并后更新父任务、重新核对第二阶段规划；本阶段不自动开始后续开发。

## Rollback points

命令定义、schema 迁移、policy 提取、executor/display 提取分别作为可审查步骤。不能通过删除旧行为测试、放宽权限/缓存断言或降低启动门禁来完成迁移。若需要改变用户行为，停止本次实现并单独评审需求。
