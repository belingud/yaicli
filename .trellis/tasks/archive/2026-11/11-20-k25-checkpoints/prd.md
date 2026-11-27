# K25 会话检查点与回退

主体实现 `6758c18` 和配置文件工作区根解析修复 `662a60c` 已通过 PR #59 合并至 `master`（`f68affa`）。2026-11-27 已发布 v0.26.0，PyPI 发布、主分支 CI、启动性能门禁与文档站部署均通过。需求以评审确认的 K25 为基础。测试与发布证据见 [verification.md](verification.md)。

## 目标

用户在与 YAICLI 共同修改旅行清单、整理资料或做其他文件任务时，可以回到较早一轮继续尝试。一次回退同时恢复那一轮结束时的对话和这之后由 YAICLI 记录的文件变更。保存过的会话重新打开后也能使用检查点。

## 背景

`/undo` 依赖进程内的撤销栈，一次撤销一笔文件工具操作。已有会话可通过 `/save`、`/load`、`--resume` 保存和重新打开。K25 在这些已有入口上增加按轮次恢复的能力。见 [工作区保护](../../../docs/usage/workspace-safety.md) 和 [会话文档](../../../docs/usage/sessions.md)。

## 需求

| 编号 | 用户可见行为 |
| --- | --- |
| R1 | 支持带终端的持久化聊天会话。保存会话时建立基准点，随后每个正常结束的用户轮次记录一个检查点，包括纯对话轮次。首次 `/save` 前的操作从保存当时起算。有版本记录的会话可在同一工作目录用 `--resume` 或 `/load` 找回检查点。普通临时对话维持现有保存语义。 |
| R2 | `/checkpoints` 列出当前可回退到的编号、时间、轮次、变更路径数和当前位置。`/rewind [id]` 回到指定点的轮末，省略编号就退到上一个点。回退前列出实际恢复或删除的路径和将舍弃的轮次数。用户明确输入 `y` 后执行。回退成功后移除当前会话较新的检查点，随后可以继续对话。 |
| R3 | `/fork [id] [title]` 使用相同目标和确认规则。确认后先将当前对话保存为独立会话，再将当前会话和受支持文件回退。可从 `/list` 和 `/load` 打开保留的对话。存档会话只保留对话，两个会话仍共用同一工作目录。重名时拒绝，避免覆盖既有会话。 |
| R4 | 首版文件覆盖工作区内由内置守卫记录的普通文件新建、修改、删除、复制和移动，包括可安全识别的隐式新建空父目录。回退只触及所列路径。待恢复路径出现外部改动、路径类型变化、权限限制或缺失备份时，整次回退在预检中拒绝。运行中发生错误时尝试恢复回退前状态，无法恢复的路径明确指出，便于用户处理。 |
| R5 | 目录树操作、符号链接、外部命令、MCP、自定义工具和计划状态变更可能产生无法完整恢复的影响。跨过这些操作的回退不可用，用户仍可在操作结束后从新基准开始。中断或缺失的写入记录也使用相同规则。`/undo` 仍能撤销一笔工具操作，只要它可能改变过工作区，就重建基准。`/clear` 同时清除当前会话可用的检查点。 |
| R6 | `CHECKPOINT_ENABLED` 默认 `true`，按现有 `YAI_*` 环境变量、配置文件、默认值顺序解析。`CHECKPOINT_KEEP` 默认 20，`CHECKPOINT_MAX_MB` 默认 50（MiB），约束每个会话的 K25 存储，包括基准和所持备份。单份对话快照上限 2 MiB，超过上限不生成该检查点并提示。被淘汰或中断的记录不可作为回退目标。 |
| R7 | 启用后按现有项目边界和会话隔离记录，复用会话脱敏规则和私有文件权限。只读工具策略下允许列出检查点，拒绝 `/rewind` 和 `/fork`。无终端或机器输出时不启用这三个交互命令，退出码和机器输出格式沿用现有契约。 |

首版以会话和本地文件为单位。Git 历史、远程系统和外部工具的副作用由原系统管理，K23 的计划文件和 todo 继续使用现有计划命令管理。项目要求的自检仍由用户写在项目说明里，模型按需运行。

## Feature examples

以下为终端输出示例。每个示例的 `💬 >` 表示交互提示符。假设 `trip.md` 在检查点 #1 已存在，第二轮改写它并新建了 `packing.md`。

### E1 重启后回到上一轮

```text
$ ai --resume
💬 > /checkpoints
ID  Time      Turn  Paths  Status
#2  10:05:00     2      2  current
#1  10:04:00     1      1
#0  10:03:00     0      0
💬 > /rewind
Rewind to checkpoint #1 and drop 1 turn?
  Restore: trip.md
  Remove:  packing.md
Proceed? [y/N]: y
Rewound to #1. Restored 1 path, removed 1 path, dropped 1 turn.
💬 >
```

### E2 保留一次尝试，再探索另一个方向

```text
💬 > /fork 1 Weekend draft
Save the current chat as "Weekend draft" and rewind to checkpoint #1?
  Restore: trip.md
  Remove:  packing.md
  Drop:    1 turn from the current chat
Proceed? [y/N]: y
Chat saved as "Weekend draft". Rewound to #1.
💬 >
```

这里的 `Weekend draft` 可在会话列表中重新打开。它保留回退前的对话，工作目录此时已回到 #1 的受记录状态。

### E3 拒绝和取消

| 输入或条件 | 原样输出 |
| --- | --- |
| `/checkpoints`，当前没有记录 | `No checkpoints for this session.` |
| 临时会话运行 `/rewind` | `Save this chat with /save before using checkpoints.` |
| 配置关闭后运行任一命令 | `Checkpoints are disabled (CHECKPOINT_ENABLED=false).` |
| 配置启用但会话已有无法解决的回退残留 | `Checkpoint recovery is incomplete. Resolve the reported paths before rewinding.` |
| `/rewind nope` 或额外参数 | `Usage: /rewind [id]` |
| `/fork nope` | `Usage: /fork [id] [title]` |
| `/checkpoints extra` | `Usage: /checkpoints` |
| `/rewind 99`，目标未保留 | `Checkpoint #99 is unavailable.` |
| `/rewind`，当前点之前没有目标 | `No earlier checkpoint is available.` |
| 显式指定当前点 | `Already at checkpoint #2.` |
| `trip.md` 在对话之外已更改 | `Cannot rewind: trip.md changed outside the recorded history.` |
| 预检发现 `trip.md` 缺少备份 | `Cannot rewind: backup for trip.md is missing.` |
| 有其他回退或文件操作在进行 | `Workspace is busy. Try again when its file operations finish.` |
| 无法完整记录上一轮影响 | `Earlier checkpoints are unavailable: a tool change could not be recorded.` |
| `/fork 1 Weekend draft`，标题已使用 | `Chat title already exists: Weekend draft.` |
| 分支保存失败 | `Cannot fork: the current chat could not be saved.` |
| 运行中写入失败，完整补偿成功 | `Rewind failed. The previous workspace and chat were restored.` |
| 补偿失败，涉及 `trip.md` | `Rewind failed. Manual recovery is required for trip.md.` |
| 输入空白、`n`、Ctrl+C 或 EOF | `Cancelled.` |
| `TOOL_POLICY=readonly` | `Rewind and fork are unavailable in readonly mode.` |
| 无确认所需的终端 | `Checkpoints require an interactive terminal.` |
| 超出单份快照上限 | `Checkpoint skipped: chat snapshot exceeds 2 MiB.` |

命令使用纯文本。交互结果、列表和确认提示走 stdout，错误和记录失败提示走 stderr。路径按原始大小写展示，控制字符会被转义。不增加非交互 CLI 入口。比如 `ai -p "/rewind 1" --output-format json` 仍按普通提示处理，使用现有结果结构和退出码，不会直接执行本地回退。交互拒绝和取消均返回提示符，对进程退出码无额外影响。取消不会保存分支或修改文件。

## 验收标准

- [x] A1（R1、R2、E1）用模拟模型创建纯对话轮和文件修改轮。从另一个进程恢复已保存会话后，列表位置一致。退到目标点后比对对话、文件字节和是否存在，确认较新点不可再选择。
- [x] A2（R3、E2）分支保留完整的当前对话并有独立身份，对目标历史和文件的回退与 `/rewind` 一致。取消、标题冲突或存档失败时，当前会话和工作区维持原状。
- [x] A3（R4、R5、E3）同一路径连续改写、重命名、删除和重建后可回退。外部修改、丢失备份、路径越界、权限不足、并发会话或未跟踪副作用下，无法安全执行的回退会拒绝。注入中途 I/O 失败，验证补偿结果或恢复提示。
- [x] A4（R5、R7、E3）计划状态变化、成功 `/undo`、`/clear` 和中断写入均有明确的恢复边界。只读策略、非 TTY、临时对话、禁用配置和旧会话按约定处理。headless stdout 与原有契约一致。
- [x] A5（R6、R7）超出保留条数或字节预算时，清理最旧的可安全删除记录，剩余回退链可用。覆盖同目录的不同会话、共享 `CHAT_HISTORY_DIR`、会话脱敏和私有权限。
- [x] A6（R1–R7）产品文档与命令帮助一致。使用模拟提供商完成端到端验证，现有测试、文档构建和启动性能门禁通过。
- [x] A7（R1、R4、R7）仅通过配置文件设置 `WORKSPACE_ROOT`，启动目录为其子目录且不继承 `YAI_WORKSPACE_ROOT`；同步与流式路径均在首轮文件修改后保留检查点，跨进程恢复保持会话身份与根目录，并能实际回退文件内容。
