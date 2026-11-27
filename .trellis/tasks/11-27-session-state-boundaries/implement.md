# 第三阶段执行清单

## Before implementation

- [ ] 前两阶段已验收并提交；以前置提交为基线，重核所有配置读取及计划/工具模式数据流。
- [x] 用户于 2026-11-27 授权自主完成整个重构；阶段开始前仍须核对设计及上下文。
- [ ] 在共同分支 chore/refactor-command-tools 继续，PR 目标 master，使用 Trellis implement/check 子代理。
- [ ] 按父 implement.md 建立隔离 HOME/配置/工作区和本阶段基线。
- [ ] 验证环境适配与现有 workspace/undo/checkpoint 锁的顺序；不在未验证的假设上扩大迁移。

## Implementation order

- [ ] 先加入两个不同配置/计划实例交替运行的回归，确认能暴露旧全局污染。
- [ ] 创建轻量会话上下文并接入已提取的协调器，保留旧默认入口。
- [ ] 让应用组装、内建客户端、权限、工具选择/执行使用所属配置；保留 ready client 注入。
- [ ] 计划状态改为唯一实例来源，schema 从状态派生，删除产品路径的全局同步副本。
- [ ] 绑定 submit_plan/todo_write 和三种 provider 工具声明的所属会话。
- [ ] 集中独立工具环境适配，覆盖空/默认值、交替 root、异常恢复、undo、shell 和工作线程取消。
- [ ] 清理已失效的兼容分支和全局重置依赖，不全面清理无关单例。
- [ ] 更新配置/CLI/工具/计划/检查点规范及 docs/dev/architecture.md 的最终调用链。

## Focused tests

通过父任务要求的隔离启动器执行；新隔离测试的实际文件名随实现记录，单独进程验证不依赖全局 reset。

~~~bash
uv run --no-sync pytest tests/test_config.py tests/test_session_isolation.py tests/test_model_limits.py tests/test_context_budget.py tests/test_redaction.py tests/test_spill_redaction.py -q
uv run --no-sync pytest tests/tools tests/llms/test_client.py tests/llms/test_tool_confirmation.py tests/test_tool_schema_filter.py tests/test_tool_policy.py tests/test_permissions.py -q
uv run --no-sync pytest -k "plan or todo or checkpoint or workspace" -q
uv run --no-sync pytest tests/test_headless_contract.py tests/test_runtime_bootstrap.py tests/test_startup.py tests/test_stream_bridge.py tests/test_worker_console.py -q
~~~

## Check / finish

- [ ] S3-A1—S3-A6 均有证据；交替配置、异常后下一调用、配置 root 首次生效和无全局 reset 场景通过。
- [ ] 实际检查显式产品路径不调用旧全局计划/工具模式入口；默认兼容入口单独覆盖。
- [ ] 完整 pytest、Ruff --no-fix、改动文件格式/isort、strict docs、构建、Python 兼容、启动门禁及 git diff --check 通过。
- [ ] verification.md 记录用例、命令、环境、锁顺序检查、数据格式未变及剩余限制。
- [ ] 完成父任务 A1—A6 最终集成审查和架构图，不以局部通过替代全链路验证。
- [ ] 提交 PR，CI 通过后等待用户明确授权合并；记录父任务及三个子任务证据。
- [ ] 全部合并后按 Trellis 规范记录会话与归档；不自动发布新版本。

## Rollback points

先绑定实例，再替换全局读取，最后清理兼容内部路径；各步可分别回退。发现数据协议或用户语义需要改变时返回规划，不添加新开关掩盖设计问题。回退第三阶段后仍保留前两阶段清晰的模块边界。
