# 第一阶段提交计划

## 状态及范围

2026-11-27：本地实现、独立审查及最终验收完成，等待用户一次确认后执行本计划。当前没有提交、推送或 PR；不提前归档，不启动第二、三阶段。

- 分支：chore/refactor-command-tools；PR 目标 master。
- 拟作一个完整的行为保持重构提交：`refactor(core): separate command registry and tool responsibilities`。
- 原因：命令元数据共用一份定义，工具声明、权限评估、执行和展示各自负责明确职责；源码、测试、架构规范及任务证据同时提交，便于审查和整体回退。
- 此提交包括父任务及三个子任务的既有规划文档，只有第一阶段包含产品代码。
- 验证：完整测试 3152 passed；独立 Trellis check 无阻塞；Ruff、27 个改动 Python 文件格式/isort/Python 3.10 语法、strict docs、wheel/sdist、六项启动门禁通过。详见 verification.md。
- 确认后只按以下清单暂存并提交，不 amend、不推送；PR、CI 及合并另行处理。Python 3.10/3.13 实际运行仍待 CI。

## 提交文件清单（61 个）

### 产品源码（9 个）

- yaicli/cmd_handler.py
- yaicli/commands/__init__.py
- yaicli/commands/registry.py
- yaicli/llms/client.py
- yaicli/tools/__init__.py
- yaicli/tools/display.py
- yaicli/tools/executor.py
- yaicli/tools/policy.py
- yaicli/tools/schemas.py

### 测试（18 个）

- tests/llms/test_gemini_provider.py
- tests/test_checkpoint_commands.py
- tests/test_command_handler.py
- tests/test_context_budget.py
- tests/test_markup_safety.py
- tests/test_permissions.py
- tests/test_plan_acceptance.py
- tests/test_plan_shell_gate.py
- tests/test_refactor_integration.py
- tests/test_tool_schema_filter.py
- tests/test_workspace_safety.py
- tests/tools/test_execution_contract.py
- tests/tools/test_fetch_webpage.py
- tests/tools/test_fs_read_file.py
- tests/tools/test_fs_read_image.py
- tests/tools/test_function_loading.py
- tests/tools/test_tool_display.py
- tests/tools/test_tools_init.py

### 架构及规范（6 个）

- docs/dev/architecture.md
- .trellis/spec/py/cli-and-rendering.md
- .trellis/spec/py/function-tool-guidelines.md
- .trellis/spec/py/index.md
- .trellis/spec/py/provider-guidelines.md
- .trellis/spec/py/quality-guidelines.md

### 规划及任务证据（28 个）

- .trellis/tasks/11-27-core-organization-refactor/check.jsonl
- .trellis/tasks/11-27-core-organization-refactor/design.md
- .trellis/tasks/11-27-core-organization-refactor/implement.jsonl
- .trellis/tasks/11-27-core-organization-refactor/implement.md
- .trellis/tasks/11-27-core-organization-refactor/prd.md
- .trellis/tasks/11-27-core-organization-refactor/research/organization-review.md
- .trellis/tasks/11-27-core-organization-refactor/research/test-safety-review.md
- .trellis/tasks/11-27-core-organization-refactor/task.json
- .trellis/tasks/11-27-command-tool-boundaries/check.jsonl
- .trellis/tasks/11-27-command-tool-boundaries/commit-plan.md
- .trellis/tasks/11-27-command-tool-boundaries/design.md
- .trellis/tasks/11-27-command-tool-boundaries/implement.jsonl
- .trellis/tasks/11-27-command-tool-boundaries/implement.md
- .trellis/tasks/11-27-command-tool-boundaries/prd.md
- .trellis/tasks/11-27-command-tool-boundaries/task.json
- .trellis/tasks/11-27-command-tool-boundaries/verification.md
- .trellis/tasks/11-27-cli-planning-boundaries/check.jsonl
- .trellis/tasks/11-27-cli-planning-boundaries/design.md
- .trellis/tasks/11-27-cli-planning-boundaries/implement.jsonl
- .trellis/tasks/11-27-cli-planning-boundaries/implement.md
- .trellis/tasks/11-27-cli-planning-boundaries/prd.md
- .trellis/tasks/11-27-cli-planning-boundaries/task.json
- .trellis/tasks/11-27-session-state-boundaries/check.jsonl
- .trellis/tasks/11-27-session-state-boundaries/design.md
- .trellis/tasks/11-27-session-state-boundaries/implement.jsonl
- .trellis/tasks/11-27-session-state-boundaries/implement.md
- .trellis/tasks/11-27-session-state-boundaries/prd.md
- .trellis/tasks/11-27-session-state-boundaries/task.json

## 明确排除的既有改动

以下路径不属于本阶段编辑范围，不加入本次提交，也不还原其内容：

- .trellis/.template-hashes.json
- .agents/skills/trellis-start/
- .agents/skills/trellis-continue/
- .agents/skills/trellis-finish-work/
- .codex/

## 回退及后续

本阶段没有数据迁移、配置或运行时依赖变更；第二阶段尚未合并时，回退本提交/对应 PR 即恢复原代码组织。第二阶段须等第一阶段 PR 合并后，以最新 master 重新核对规划。

提交前的一次确认由 .trellis/workflow.md 第 3.4 节第 5 步要求："Present the plan once, ask for one-shot confirmation"。合并仍须在 CI 通过后取得用户明确授权。
