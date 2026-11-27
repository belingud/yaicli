# K25 提交计划

分支：`feat/checkpoints`；目标分支：`master`。用户已于 2026-11-26 确认本计划，执行本地提交。

## 提交 1

```text
feat(checkpoints): add persistent rewind and fork
```

同一功能的实现、测试、产品文档和开发规范作为一个提交。测试证据见 [verification.md](verification.md)。

纳入的文件：

```text
yaicli/checkpoints.py
yaicli/checkpoint_lock.py
yaicli/chat.py
yaicli/cli.py
yaicli/cmd_handler.py
yaicli/const.py
yaicli/stream_bridge.py
yaicli/tools/__init__.py
yaicli/tools/workspace.py
tests/test_checkpoints.py
tests/test_checkpoint_commands.py
tests/test_checkpoint_integration.py
README.md
docs/usage/commands.md
docs/usage/configuration.md
docs/usage/plan-mode.md
docs/usage/sessions.md
docs/usage/workspace-safety.md
.trellis/spec/py/index.md
.trellis/spec/py/checkpoints.md
.trellis/tasks/11-20-k25-checkpoints/task.json
.trellis/tasks/11-20-k25-checkpoints/prd.md
.trellis/tasks/11-20-k25-checkpoints/design.md
.trellis/tasks/11-20-k25-checkpoints/implement.md
.trellis/tasks/11-20-k25-checkpoints/implement.jsonl
.trellis/tasks/11-20-k25-checkpoints/check.jsonl
.trellis/tasks/11-20-k25-checkpoints/verification.md
.trellis/tasks/11-20-k25-checkpoints/commit-plan.md
```

## 提交 2：发布前配置根目录修复

```text
fix(checkpoints): honor configured workspace root from first turn
```

用户已要求提交、发布，并于 2026-11-27 明确授权合并 PR #59。此提交修复发布复核确定复现的配置根目录不一致问题，同时记录回归证据与规范。

```text
yaicli/cli.py
tests/test_checkpoint_integration.py
.trellis/spec/py/checkpoints.md
.trellis/tasks/11-20-k25-checkpoints/design.md
.trellis/tasks/11-20-k25-checkpoints/implement.md
.trellis/tasks/11-20-k25-checkpoints/prd.md
.trellis/tasks/11-20-k25-checkpoints/task.json
.trellis/tasks/11-20-k25-checkpoints/verification.md
.trellis/tasks/11-20-k25-checkpoints/commit-plan.md
```

## 原有其他改动

以下路径在本次实现之前已处于未提交状态，不纳入本计划：

```text
.trellis/.template-hashes.json
.agents/skills/trellis-continue/
.agents/skills/trellis-finish-work/
.agents/skills/trellis-start/
.codex/
uv.lock
```

## 确认与后续

本次执行上述已获确认的本地提交。提交与 PR、合并分别遵循仓库流程；任务归档及会话日志在 PR 合并后处理。
提交前一次性确认来自 `.trellis/workflow.md` Phase 3.4：
`Present the plan once, ask for one-shot confirmation`。
