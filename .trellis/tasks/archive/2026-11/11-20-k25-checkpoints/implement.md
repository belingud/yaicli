# K25 实施计划

需求和终端文案以 [PRD](prd.md) 为准。存储和恢复协议见 [技术设计](design.md)。

## 开工检查

- [x] 需求评审完成后使用 Trellis 启动该任务。在 `feat/checkpoints` 实施，PR 目标为 `master`。已核对实现基线 `1896597`。
- [x] 读取任务的 `implement.jsonl` 和 `check.jsonl` 所列规范。使用 Python 3.10 兼容语法，保留现有工具 API 和机器输出契约；实际测试环境见 [verification.md](verification.md)。

## 实施顺序

| 步骤 | 实施和验收 |
| --- | --- |
| 1. 持久化存储 | 在 `checkpoints.py` 与 `chat.py` 实现会话身份、快照记录、原子保存以及按条数和字节清理。先用临时目录覆盖同名会话、旧会话、跨项目、越界、损坏记录、脱敏和权限。对应 A1、A5。 |
| 2. 轮次和文件记录 | 将生命周期接到持久化 REPL 用户轮次和会话加载。记录器从工具执行位置复用现有备份，覆盖重复写入、移动、无操作、失败有副作用、线程停留与进程中断。接入 `/undo`、`/clear`、`/retry`、`/compact` 和计划状态边界。对应 A1、A3、A4。 |
| 3. 回退和分支 | 实现全量预检、确认后复核、文件恢复、会话提交与失败补偿。测试文件被改、备份缺失、目录或符号链接替换、并发访问、恢复部分失败和分支标题冲突。先验证无文件副作用的预览，再验证实际恢复。对应 A2、A3。 |
| 4. 命令和输出 | 注册三个命令、帮助和补全。把普通聊天重启恢复、并行会话、非 TTY、只读策略和 `--plan` 作为集成场景。通过模拟提供商校验实际命令输出。对应 A1–A4。 |
| 5. 文档与门禁 | 更新 `README.md`、会话、命令、配置和工作区保护文档。同步计划模式页面里的适用范围，记录与 `/undo`、`/fork` 和非交互行为的关系。按项目要求同步当前功能规范。对应 A6。 |

存储先于 UI 实施。工作区恢复与会话提交必须在同一变更批次验证，避免发布只有命令入口或无法完整恢复的版本。若跨进程场景发现一致性问题，保留现有 `/undo` 路径和旧会话兼容行为，先修正记录协议再接入命令。分支审查应关注会话写入、工作区恢复和故障补偿三处。

## 验证命令

先运行新增的跨进程、恢复失败和命令测试，再执行相关回归与全量门禁。测试使用模拟提供商和临时会话目录。

```bash
uv run pytest -q tests/test_checkpoints.py tests/test_checkpoint_commands.py tests/test_session_isolation.py tests/test_workspace_safety.py tests/test_command_handler.py tests/test_stream_bridge.py tests/test_plan_execution.py tests/test_plan_resume.py tests/test_headless_plan.py
uv run pytest
uv run ruff check --no-fix yaicli tests
uv run mkdocs build --strict
uv run python scripts/bench.py -n 5 --gate
```

- [x] 单独验证 `--help`、`--version`、临时聊天以及 headless 不创建检查点目录，启动路径不加载检查点模块，机器输出字节格式与主线一致。
- [x] 用同一环境跑基线和实现分支的启动基准。对纯对话、普通文件新建以及连续改写同一文件记录轮末保存的中位耗时与检查点字节数。保留预算限制按 PRD 验证，核对模型请求无需附带检查点数据。结果见 [verification.md](verification.md)。
- [x] 在评审前查验现有会话恢复、计划恢复、输出视图及 `/undo` 的行为，完整测试与质量门禁通过。
- [x] 用户已于 2026-11-26 确认 [commit-plan.md](commit-plan.md)，按确认范围纳入本地工作提交。
- [x] 按项目流程创建 PR #59。
- [x] 最新提交的 CI 通过后，按用户授权合并 PR #59，合并提交为 `f68affa`。

## 发布前修复（2026-11-27）

- [x] 独立复核以真实 PTY 确认 `ai -c <title>` 无需 `/save`，创建文件及两次修改生成 #0–#3。
- [x] 复现仅配置文件指定 `WORKSPACE_ROOT` 时根目录在首轮工具调用前后变化、查询丢失检查点的问题。
- [x] 显式使用有效配置解析根目录，补同步/流式、跨进程恢复及真实文件回退的先失败后通过回归，并完成独立检查。
- [x] 将修复推送 PR #59，CI 通过后按用户授权合并，再从 master 发布 v0.26.0；PyPI 发布、主分支 CI、启动性能门禁和文档站部署均通过。

## Feature examples

验收操作对应 PRD A1 和 A2。测试预置两个持久化轮次，第二轮编辑 `trip.md` 并新建 `packing.md`。从新进程启动后核对终端结果、会话文件和文件内容。

```text
$ ai --resume
💬 > /fork 1 Weekend draft
Save the current chat as "Weekend draft" and rewind to checkpoint #1?
  Restore: trip.md
  Remove:  packing.md
  Drop:    1 turn from the current chat
Proceed? [y/N]: y
Chat saved as "Weekend draft". Rewound to #1.
💬 >
```

交互结果在 stdout，错误在 stderr。验收要核对 `Weekend draft` 仍可加载且包含第二轮消息，当前会话回到第一轮，`trip.md` 恢复并且 `packing.md` 已移除。重跑时输入 `n`，终端应输出 `Cancelled.`，现有会话和文件保持原状。对同样的输入运行 `-p --output-format json` 时按普通消息处理，保持现有机器输出和退出码约定。
