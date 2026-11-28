# 第三阶段执行清单

## Before implementation

- [x] 前两阶段已验收并提交 b7d3ce4、66db062；以前置提交为基线，重核所有配置读取及计划/工具模式数据流。
- [x] 用户于 2026-11-27 授权自主完成整个重构；阶段开始前仍须核对设计及上下文。
- [x] 在共同分支 chore/refactor-command-tools 继续，PR 目标 master，使用 Trellis implement/check 子代理。
- [x] 按父 implement.md 沿用已验证的隔离 HOME/配置/工作区；基线3173项完整测试通过。
- [x] 环境适配前置3项验证通过：嵌套/异常恢复、guard真实写入及同root undo；env->workspace顺序和checkpoint无锁保存边界已核对。最终完整集成取消/回退及三版本矩阵均通过。

## Implementation order

- [x] 先在66db062独立源码副本加入两项真实应用污染回归，确认模型提示/聊天目录受旧全局状态影响；更完整A/B/A回归仍由C实现。
- [x] 创建轻量会话上下文并接入已提取的协调器，保留旧默认入口。
- [x] 让应用组装、内建客户端、权限、工具选择/执行使用所属配置；保留 ready client 注入。
- [x] 计划状态改为唯一实例来源，schema 从状态派生，删除产品路径的全局同步副本。
- [x] 绑定 submit_plan/todo_write 和三种 provider 工具声明的所属会话。
- [x] 集中独立工具环境适配，覆盖空/默认值、交替 root、异常恢复、undo、shell 和工作线程取消。
- [x] 清理已失效的兼容分支和全局重置依赖，不全面清理无关单例。
- [x] 更新配置/CLI/工具/计划/检查点规范及 docs/dev/architecture.md 的最终调用链。

## Focused tests

通过父任务要求的隔离启动器执行；新隔离测试的实际文件名随实现记录，单独进程验证不依赖全局 reset。

~~~bash
uv run --no-sync pytest tests/test_config.py tests/test_session_isolation.py tests/test_model_limits.py tests/test_context_budget.py tests/test_redaction.py tests/test_spill_redaction.py -q
uv run --no-sync pytest tests/tools tests/llms/test_client.py tests/llms/test_tool_confirmation.py tests/test_tool_schema_filter.py tests/test_tool_policy.py tests/test_permissions.py -q
uv run --no-sync pytest -k "plan or todo or checkpoint or workspace" -q
uv run --no-sync pytest tests/test_headless_contract.py tests/test_runtime_bootstrap.py tests/test_startup.py tests/test_stream_bridge.py tests/test_worker_console.py -q
~~~

## Check / finish

- [x] S3-A1—S3-A5 和 S3-A6 本地技术门禁证据完整；交替配置、异常后下一调用、配置 root 首次生效和无全局 reset 场景通过。交付部分单列待办。
- [x] 实际检查显式产品路径不调用旧全局计划/工具模式入口；默认兼容入口单独覆盖。
- [x] 三版本完整 pytest、Ruff --no-fix、85个改动文件格式/isort/3.10AST、strict docs、构建、包字节、原启动门禁及 git diff --check 通过。
- [x] verification.md 记录用例、命令、环境、锁顺序检查、数据格式未变及剩余限制。
- [x] 完成父任务 A1—A5 最终集成审查、A6技术审查和架构图；A6的提交/PR/CI/合并仍单列待办。
- [x] 提交 PR，CI 通过后等待用户明确授权合并；记录父任务及三个子任务证据。
- [x] 全部合并后按 Trellis 规范记录会话与归档；不自动发布新版本。

## Rollback points

先绑定实例，再替换全局读取，最后清理兼容内部路径；各步可分别回退。发现数据协议或用户语义需要改变时返回规划，不添加新开关掩盖设计问题。回退第三阶段后仍保留前两阶段清晰的模块边界。
