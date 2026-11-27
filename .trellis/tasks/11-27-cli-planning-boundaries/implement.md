# 第二阶段执行清单

## Before implementation

- [ ] 第一阶段已合并并记录 PR/commit；同步最新 master，刷新本阶段证据、接口和上下文。
- [ ] 向用户展示本阶段最终规划摘要，获得明确实现批准；任务校验通过后再 start。
- [ ] 创建 chore/refactor-cli-planning，PR 目标 master；使用 Trellis implement/check 子代理。
- [ ] 按父 implement.md 建立隔离 HOME、配置和工作区，记录本阶段起始测试与行为基线。

## Implementation order

- [ ] 从 CLI 提取机器输出和退出映射，保留公共状态属性；核对完整字段、NDJSON 和 stdout/stderr。
- [ ] 明确会话状态及 SessionController 的输入/输出，再迁移保存、加载、恢复和检查点协调。
- [ ] 迁移计划模型、校验和存储到 planning/，保证类身份及历史格式一致。
- [ ] 迁移服务、提示词、编辑器和计划协调，删除 CLI 中重复的计划业务。
- [ ] 让会话/计划/设置/重试命令调用明确服务，去除对应 CLI 私有访问。
- [ ] 检查薄兼容入口、无重复可变状态、无反向导入及无启动时额外导入。
- [ ] 更新架构文档、CLI/计划/检查点等受影响规范和第三阶段设计。

## Focused tests

通过父任务规定的隔离启动器执行：

~~~bash
uv run --no-sync pytest tests/test_cli.py tests/test_entry.py tests/test_command_handler.py tests/test_headless_contract.py tests/test_headless_plan.py tests/test_usage.py -q
uv run --no-sync pytest tests/test_chat_manage.py tests/test_session_isolation.py tests/test_checkpoints.py tests/test_checkpoint_commands.py tests/test_checkpoint_integration.py -q
uv run --no-sync pytest -k "plan or todo" -q
uv run --no-sync pytest tests/test_stream_bridge.py tests/test_generation_keys.py tests/test_worker_console.py tests/test_tool_output_viewer.py tests/test_printer.py tests/test_runtime_bootstrap.py -q
~~~

## Check / finish

- [ ] S2-A1—S2-A5 均有源码边界检查与行为证据，服务测试不依赖整个 CLI mock。
- [ ] 完整 pytest、Ruff --no-fix、改动文件格式/isort、strict docs、启动门禁和 git diff --check 通过。
- [ ] verification.md 记录旧数据恢复、文件字节、错误/取消场景、测试基线和性能。
- [ ] 检查迁移未改变用户文案、权限、持久化格式或加入新配置/依赖。
- [ ] 提交分支 PR，CI 通过后等待用户明确授权合并；记录父任务进度。
- [ ] 合并后重核第三阶段规划，不自动开始第三阶段。

## Rollback points

机器输出、会话协调、计划包迁移和命令适配分别作为可审查步骤；不用大范围格式化掩盖移动。仅替换模块路径的测试调整不得删除历史数据、工作线程或确认协议断言。后续阶段已合并时按依赖逆序回退。
