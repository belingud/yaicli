# 执行计划：代码组织渐进式重构

## Planning status

- [x] 完成只读评估并记录证据。
- [x] 用户批准建任务；创建父任务和三个顺序子任务。
- [x] 编写各任务 PRD、技术设计和执行清单。
- [x] 用户在上一轮最终规划摘要之后明确要求开始第一阶段实现，并鼓励合理并行。
- [x] 三个只读子代理完成测试保护审查，主线程复核并建立隔离完整测试基线：3070 passed；见 research/test-safety-review.md。
- [x] 用户于 2026-11-27 批准新增回归门禁及并行方案，可启动第一阶段。
- [x] 第一阶段开始前，补齐代表性输出与性能基线。

父任务维护规划与集成验收。2026-11-27 用户授权自主完成全部重构；三阶段改为同一分支串行实施、独立提交，最终统一 PR。阶段转换以设计重核、独立审查及本地完整验收为前提，保留合并前的用户确认。

## Delivery order

- [x] 第一阶段：11-27-command-tool-boundaries，实现 R1，覆盖 A1/A4/A5；本地验收通过并提交 b7d3ce4，远端 CI/统一 PR 待后续完成。
- [x] 第一阶段验收提交后，更新第二阶段的证据、受影响文件及上下文；用户已授权串行推进全部阶段。
- [x] 第二阶段：11-27-cli-planning-boundaries，实现 R2，覆盖 A2/A4/A5；本地独立验收通过，完整测试 3173 passed，提交 66db062。
- [x] 第二阶段验收提交后，更新第三阶段的证据、接口及14项上下文。
- [x] 第三阶段：11-27-session-state-boundaries，实现 R3，覆盖 A3/A4/A5；独立本地验收及三版本完整矩阵通过，待本阶段提交。
- [x] 父任务最终技术审查：A1—A5、A6技术部分、完整集成回归及架构图均通过，详见 verification.md。
- [ ] 最终交付：记录第三阶段提交、统一 PR 及远端 CI；用户明确批准合并后再关闭与归档。

2026-11-27：第一阶段本地实现及独立审查已完成，完整测试 3152 passed；lint、格式、严格文档、构建和现有启动门禁均通过，详见 [第一阶段验证记录](../11-27-command-tool-boundaries/verification.md)。已提交 b7d3ce4，按用户最新授权继续第二阶段。

不能因后置任务目录已存在就跳过前置阶段验收或并行修改依赖阶段。父任务没有独立产品实现工作，不应启动为实现目标。

## Common execution gate

每个子任务实施时执行：

1. 读取前一阶段验收提交和子任务规划，检查工作区，保留无关改动；需求或行为范围有实质变化则先回到评审。
2. 在共同分支 chore/refactor-command-tools 上顺序实施，PR 目标为 master。使用 Trellis implement/check 子代理，注入本子任务的上下文清单；不并行修改有依赖的阶段。
3. 补齐必要的行为特征测试，再分责任迁移代码；每个可回退步骤运行对应测试。
4. 检查完整测试、格式、lint、导入及启动性能，更新规范和架构文档。
5. 审查 diff，确认没有新配置、用户行为变化、数据迁移或无关格式化；记录证据后再提交、创建 PR。
6. CI 通过后向用户报告 PR 和检查结果；只有用户明确批准才能合并。

## Validation commands

以下命令必须由隔离进程启动器执行。启动器创建临时 HOME、配置与工作区，移除继承 YAI_*、XDG_*、PYTHONPATH，设置临时 YAI_CONFIG_DIR、UV_CACHE_DIR；测试凭据由现有 fixtures 提供。不要先导入应用再改环境。

~~~bash
uv run --no-sync pytest -q
uv run --no-sync ruff check --no-fix yaicli tests
uv run --no-sync python scripts/bench.py --gate -n 3
uv run --no-sync mkdocs build --strict
uv build --out-dir /tmp/yaicli-refactor-dist
git diff --check
~~~

格式只检查/修正本阶段改动的 Python 文件：ruff format --check 与 isort --check-only。不要对全仓进行与任务无关的格式化。实际使用的隔离启动器、命令、Python 版本、耗时和结果写入各子任务 verification.md；规划文档中的命令不是已通过的测试证据。

## Integration acceptance

- [x] A1：命令定义一致，工具声明与执行契约一致；普通、自定义和 MCP 路径均覆盖。
- [x] A2：CLI 对提取组件使用明确依赖；对应命令不再访问 CLI 私有状态；计划包无反向 CLI 依赖。
- [x] A3：两个应用实例交替调用互不污染；配置变更只影响所属会话；独立工具环境桥接按有效配置工作。
- [x] A4：TTY/非 TTY、确认、取消、错误、事件、会话恢复与实际文件回退均维持原行为。
- [x] A5：完整测试、lint、格式、文档、构建、Python 兼容及现有启动门禁通过；不放宽性能阈值。
- [ ] A6：记录三个阶段提交、统一 PR、规范变化、最终调用链和逆序回退方案。

## Follow-up / deferred

不创建下一项功能任务，不把旧规范的无关错误顺手改写。只更新本次职责变化直接涉及的规范段落；其他文档问题记录到研究笔记待单独处理。
