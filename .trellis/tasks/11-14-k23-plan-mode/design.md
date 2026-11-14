# K23 Design — 持久 plan mode + submit_plan + todo（v3）

> 约束：`.trellis/spec/py/function-tool-guidelines.md`、`cli-and-rendering.md`、`config-and-context.md`、`.trellis/spec/repo/feature-spec-writing.md`；用户可见契约见 `prd.md` 的 `## Feature examples`。
> 状态：**design v3.1 定稿**（2026-11-14：`PLAN_KEEP=80` 按项目/无时间限制、`--resume` 回默认 normal 模式、plan 阶段受控只读 shell（白名单 v1 固定，拒绝=结构化错误+REPL 一行）、修订单文件原地更新；3 个开放问题已确认，见 §14）。
> 参考实现：Claude Code plan mode（官方文档与 issue，见 §13）。

## 1. 模块边界

```
cmd_handler.py ── /plan 系列、/todo ──┐
cli.py ── Shift+Tab 绑定、提示符、批准后执行、--resume 恢复 ──┤
printer.py ── 计划面板 / 修订 diff 面板 / todo 进度行 ──┤
                              ▼
                     yaicli/plan_mode.py   （模式状态机 + 工具可见性 + 系统提示 + 修订计算）
                              │
                              ├── yaicli/plan_store.py （路径/文件读写/frontmatter/status/revision/prune）
                              ├── yaicli/plan_shell.py （plan 模式只读 shell 白名单校验）
                              ├── yaicli/tools/session_tools.py （submit_plan / todo_write 执行器）
                              └── llms/client.py （请求前工具过滤 + 计划上下文注入）
entry.py ── --plan（headless）、--resume ──┘
```

- **`plan_store.py`**（stdlib-only 叶子）：路径解析（`PLAN_DIR`/config dir/project-key）、frontmatter 读写、status/revision、`PLAN_KEEP=80` 清理、列表与清理。不 import rich/typer/cfg 单例。
- **`plan_shell.py`**（stdlib-only）：`validate_readonly_command(argv) -> (allowed, reason)`，白名单 + 危险参数 + shell 元字符校验；不执行、不 import rich。
- **`plan_mode.py`**：状态机、工具白名单、系统提示、修订 diff 计算。可 import `plan_store`/`plan_shell`/`const`，不 import CLI。
- **`tools/session_tools.py`**：`submit_plan` / `todo_write` schema 与执行器（会话状态工具，不走 `functions/buildin/` 无状态加载器）。
- **`llms/client.py`**：按模式过滤工具 schema、注入计划上下文（≤2KB）；执行阶段注入 todo 摘要（≤500B）。
- **`cli.py`**：`Keys.BackTab` 绑定；提示符/状态行；批准/修订面板驱动；`--resume` 恢复后进入 normal + 提示。
- **`cmd_handler.py`**：`/plan` 系列与 `/todo`；命令表/补全同步。
- **`entry.py`**：`--plan`、headless 分支、`--resume` 联合逻辑；`--shell`/`--code` 拒绝 plan。
- **`printer.py`**：计划面板、修订 diff 面板、todo 进度行。

启动影响：计划模块只在进入模式/执行计划时 import；normal 路径零导入（`--help`/`--version` 子进程 import 断言 + bench gate）。

## 2. 状态机与会话状态

```python
class PlanMode(StrEnum):
    NORMAL = "normal"
    RESEARCHING = "researching"   # 只读调研（首次）
    REVISING = "revising"         # 执行中修订
    REVIEWING = "reviewing"       # 计划已提交，等待批准（首次或修订）
```

| 当前 | 事件 | 下一状态 | 副作用 |
|---|---|---|---|
| NORMAL（无 active plan） | Shift+Tab / `/plan` | RESEARCHING | 模式提示、工具过滤（含只读 shell）、审计 `plan.mode_enter` |
| NORMAL（active plan 执行中） | Shift+Tab / `/plan` | REVISING | 注入当前计划+todo；审计 `plan.revise_enter` |
| RESEARCHING | `submit_plan`（校验通过） | REVIEWING | 写新计划文件（revision=1）；审计 `plan.submit` |
| REVISING | `submit_plan`（校验通过） | REVIEWING | 计算 diff；暂存修订；审计 `plan.revise_submit` |
| RESEARCHING/REVISING | `submit_plan` 校验失败 | 原状态 | 结构化错误给模型 |
| RESEARCHING/REVISING | Shift+Tab / Esc / `/plan` | NORMAL | 丢弃草稿（不写文件）；恢复工具 schema；审计 `plan.mode_exit` |
| REVIEWING | `[a]` | NORMAL + 执行 | 首次：status→in-progress；修订：应用 diff（保留已完成步骤）→ **同一文件原地更新**（revision++）；审计 `plan.approve` / `plan.revise_apply` |
| REVIEWING | `[e]` | REVIEWING | `$EDITOR` 打开 plan.md；保存后重新解析校验 |
| REVIEWING | `[r]` | RESEARCHING/REVISING | 保留调研上下文重出计划 |
| REVIEWING | `[s]` | NORMAL | status 保持 draft（修订则丢弃修订草稿）；提示 `/plan review`；审计 `plan.save` |
| REVIEWING | `[Esc]` / Shift+Tab | NORMAL | draft 文件保留（首次）或修订丢弃（修订）；提示路径 |
| 执行中 | 全部 completed | NORMAL | plan.md→done；汇总；审计 `plan.done` |
| 执行中 | Ctrl-C | 暂停（NORMAL） | todo 保留；提示 `/plan resume` / `/plan abort` |
| 执行中 | `/plan abort` | NORMAL | status→aborted；todo 清除；审计 `plan.abort` |
| **`--resume`** | 任意 | **NORMAL** | 不自动进入 plan mode；有未完成计划时打印提示（draft→`/plan review`；in-progress→`/plan resume`）；审计 `plan.resume_hint` |

**会话状态**（session JSON 的 `plan` 字段 + 进程内状态）：

```json
{
  "plan": {
    "id": "20261114-004230-token-estimator",
    "path": "/Users/vic/.config/yaicli/plans/3f9a1c2d…/20261114-004230-token-estimator.md",
    "status": "in-progress",
    "revision": 2,
    "session_id": "3c1f…",
    "todos": [{"id": "S1", "content": "...", "status": "completed"}],
    "base_rev": "c51f7a3"
  }
}
```

- **模式状态不持久化**：`--resume` 始终从 NORMAL 开始；只恢复 active plan 指针 + todo，并提示用户显式 `/plan review` 或 `/plan resume`。
- 多终端：plan 文件 status 是跨进程真相；同一计划被另一进程执行中时，`/plan resume` 提示冲突（`--force` 才覆盖）。

## 3. 工具契约

### 3.1 工具可见性（按模式过滤 schema）

| 模式 | 暴露的工具 |
|---|---|
| NORMAL | 现有 12 builtin + MCP（不变） |
| RESEARCHING / REVISING | read/network builtin（`fs_read_file`、`fs_list_directory`、`fs_search_files`、`fs_get_filesystem_info`、`fs_read_image`、`fetch_webpage`、`web_search`、`get_weather`）+ **受控只读 `execute_shell_command`** + `submit_plan` |
| 执行阶段 | NORMAL 工具集 + `todo_write` |

模型硬发不可见工具：`execute_tool_call` 返回 `{"error": "tool_not_available_in_mode"}` 并写审计（不执行）。
`submit_plan` / `todo_write` 是会话状态工具：不触碰 workspace、不走写审批（TOOL_CONFIRM），但每次调用/结果进审计；计划文件由 CLI 在 `submit_plan` 成功后写入。

### 3.2 `submit_plan`

```json
{
  "goal": "…", "assumptions": ["…"],
  "steps": [{"id": "S1", "title": "…", "detail": "…", "acceptance": "…"}],
  "risks": ["…"], "not_doing": ["…"],
  "revision": 2, "change_summary": "支持 per-provider estimator 覆盖"
}
```

校验：
- `goal` 非空（≤500）；steps 1..`PLAN_MAX_STEPS`（默认 20）；每步 `title`/`acceptance` 非空；序列化 ≤8KB；
- **首次**（RESEARCHING，无 active plan）：忽略 `revision`/`change_summary`；步骤 id 由 CLI 分配 `S1..Sn`；
- **修订**（REVISING）：`revision` = 当前 revision+1；`change_summary` 必填（≤500）；id 必须在当前集合内或新增 `S{n+1}...`（不重复、不空）；
- 仅 RESEARCHING/REVISING 可调用；REVIEWING 再调返回 `plan_already_submitted`；
- 修订 diff 由 CLI 计算（added/removed/changed/unchanged）并预计算 todo 影响。

### 3.3 `todo_write`

```json
{"items": [{"id": "S1", "content": "…", "status": "pending|in_progress|completed|blocked", "reason": "…"}]}
```

- 全量替换；id 集合 = **当前 revision** 步骤集合（不可增删/改 content；`blocked` 带 reason ≤500）；
- 至多一个 `in_progress`；仅执行阶段可见；
- CLI：更新会话状态 → 回写 plan.md 复选框（`[x]`/`[ ]`，blocked 行尾 ` (blocked: reason)`）→ 刷新进度行 → 审计 `todo.update`。
- 修订应用后按 diff 重建 todo（保留 completed 且未删除；changed 保留状态；removed 记录到 “Removed” 小节；added pending；当前 in_progress 被删则暂停并提示模型重启步骤）。

### 3.4 plan 模式受控只读 shell（`plan_shell.py`）

- 只有 `PLAN_ALLOW_READONLY_SHELL=true`（默认）时暴露；`false` 时 plan 模式完全无 shell。
- **执行方式**：`shlex.split` + 直接 argv 启动（绝不 `shell=True`）；命令字符串里出现 shell 元字符（`; & | > < $( )`、反引号、换行、`||`、`&&`、`2>` 等）→ 直接拒绝（不做解释执行）。
- **白名单**（v1 固定）：
  - 基础：`ls`、`pwd`、`cat`、`head`、`tail`、`wc`、`grep`、`rg`、`find`、`file`、`stat`、`tree`、`which`；
  - git 只读子命令：`git status`、`git diff`、`git log`、`git show`、`git ls-files`、`git blame`、`git rev-parse`、`git describe`、`git branch --list`；
  - 危险参数拒绝：`find -delete/-exec/-execdir/-ok/-okdir/-fprint*`、`rg --pre*`/`--pre-glob`、`git -c`/`--exec-path`/`--config`/`--upload-pack`、`grep -P`?（允许）等。
  - 其他命令（含 `rm/mv/cp/mkdir/touch/curl/wget/python/node/make/test`）一律拒绝。
- **环境与护栏**：cwd=workspace；env 过滤、timeout、输出上限沿用 shell 工具；每次调用审计 `plan.shell`（allow/deny + reason + command）。
- **拒绝返回值**：`{"error": "plan_shell_denied", "reason": "...", "hint": "use fs_read_file / leave plan mode with Shift+Tab"}`。
- **拒绝展示**：结构化错误随工具结果回给模型；同时 REPL 额外显示一行 `✗ plan_shell_denied: <reason>`（TTY 下为 stdout 状态行；`--output-format json/stream-json` 或非 TTY 时只走 stderr，不污染 stdout）。
- **白名单固定**：v1 不提供 `PLAN_SHELL_ALLOWLIST` 之类的用户扩展命令（避免把危险命令加进“只读前门”），后续再评估。
- **残留风险**：白名单是“尽力只读”，不是内核级保证（例如 `cat` 可读任意可读路径；`grep -r` 会耗时）。因此：(a) 不开放用户可配置扩展命令（v1）；(b) 每次超时/输出上限；(c) 审计可追；(d) 文档写明“只读 shell 非安全边界”。

## 4. 计划文件（plan_store.py）

**路径解析**：

```
config_dir = const.get_config_dir()                      # YAI_CONFIG_DIR / XDG / platform
plans_root = cfg["PLAN_DIR"] or config_dir / "plans"     # 对应 Claude Code plansDirectory
project_key = sha256(resolved_cwd)[:16]                  # 与 sessions 项目隔离键一致
plan_dir = plans_root / project_key                      # 0700
plan_path = plan_dir / f"{YYYYMMDD-HHMMSS}-{slug}.md"    # 0600
```

- `slug` 来自 goal 安全化（`[a-z0-9-]`，≤40），冲突追加 `-2`。
- **CLI 是唯一写入者**；agent fs 工具写入 plans 目录必须被拒（`tools/workspace.py` 保护列表增加“绝对路径位于 plans_root 之下”）。
- frontmatter：

```markdown
---
id: 20261114-004230-token-estimator
status: draft            # draft | in-progress | done | aborted
revision: 2
session_id: 3c1f…       # 创建它的会话；用于恢复提示/防跨会话串计划
created: 2026-11-14T00:42:30+08:00
updated: 2026-11-14T01:10:05+08:00
cwd: /Users/vic/Documents/codes/git/yaicli
project_key: 3f9a1c2d…
model: gpt-5.2
base_rev: c51f7a3
approved_at: 2026-11-14T00:45:00+08:00
---

# Plan: <goal>

## Goal
## Assumptions
## Steps
- [x] **S1** <title> — 验收：<acceptance>
  <detail>
- [ ] **S2** …
## Risks
## Not doing
```

- **修订 = 同一文件原地更新**（参考 Claude Code）：覆盖 `## Goal/Assumptions/Steps/Risks/Not doing` 与 frontmatter `revision`/`updated`；不新建 `-rN.md`、不追加历史小节（变更历史在审计 `plan.revise_submit`/`plan.revise_apply` 里，含 `change_summary` 与 step diff）。
- status 生命周期：`draft` →（`[a]`）`in-progress` → `done` /（abort）`aborted`；`[s]` 保持 `draft`；修订不改变 status（draft 阶段修订仍 draft）。
- 解析失败（手改坏）：`/plan review` 或 `/plan resume` 报错并给路径；执行中不重读文件（以内存为准）。
- **清理**：`PLAN_KEEP` 默认 **80/项目**，无时间限制；只清理终态（done/aborted），按 `updated` 从旧到新删；draft/in-progress 永不自动删；触发点：写新计划前、`/plan list`；`/plan clear [--done|--all]` 手动清理（需确认）。
- 安全：目录 0700/文件 0600；不含密钥；不写入项目目录。

## 5. 批准面板

**首次计划**（REVIEWING）：

- 内容：goal、steps（含验收）、文件路径、`base_rev` 警告（若 HEAD 变化）；
- 键位：`[a]pprove & execute  [e]dit  [r]edo  [s]ave only  [Esc]cancel`；
- 对应 Claude Code：`[a]` ≈ "Yes, manually approve edits"、`[e]` ≈ Ctrl+G、`[r]` ≈ "No, keep planning"。

**修订计划**（REVISING → REVIEWING）：

- 内容：`Changes: +N step  ~N step  −N step`、逐条变更、todo 影响（保留哪些完成状态）、当前→新 revision；
- 键位：`[a]pply & continue  [e]dit  [r]edo  [Esc]cancel revision`；
- `[a]`：**原地更新** plan.md（revision++、updated）、重建 todo、立即继续执行；
- `Esc`：丢弃修订草案，回到执行（计划不变）。

`[e]` 细节：`$EDITOR`（回退 `vi`；不可用则提示并回面板）；保存后重新解析并校验，失败提示行号；成功刷新面板（不重新调用模型）。

## 6. 执行阶段

- 批准后：`todo = [S1 in_progress, S2.. pending]`；plan.md status=in-progress、approved_at；退出模式、恢复原策略/工具 schema。
- 主循环：每轮注入 todo 摘要（≤500B）；模型用 `todo_write` 推进；CLI 渲染 `[todo 2/4] S2 …` 并回写 md。
- 完成推进由模型在 `todo_write` 中完成（不自动推进）。
- **修订（re-plan）**：执行中 `Shift+Tab` → REVISING（当前计划+todo 注入）→ `submit_plan(revision)` → 面板 → `[a]` 原地更新并继续；`Esc` 恢复执行；`todo_write` 不能增删步骤。
- 结束：全部 completed → 若 K24 配置 checks 则先跑（失败回灌，受 `MAX_TOOL_CALL_DEPTH` 限制）；通过 → plan.md `done` + 汇总 → 审计 `plan.done`。
- 中断/失败：Ctrl-C 暂停（todo 保留）；`blocked` + reason，用户 `[r]etry [s]kip [a]bort`；skip 记入 md 的 “Skipped” 小节并在汇总单列。

## 7. 命令与配置

| 命令 | 行为 |
|---|---|
| `/plan` | 无 active plan：NORMAL↔RESEARCHING；执行中：进入 REVISING；REVIEWING：取消提交回原模式 |
| `/plan <task>` | NORMAL/RESEARCHING 发送任务；执行中进入 REVISING 并以该任务为修订目标；REVIEWING 拒绝并提示先处理当前计划 |
| `/plan list [--all]` | 当前项目计划列表（默认）；`--all` 全部项目；显示 status/revision |
| `/plan show [id]` | 计划内容与状态 |
| `/plan edit` | 打开当前计划 `$EDITOR` 并重新校验（draft/in-progress） |
| `/plan review [id]` | 重新打开批准面板（draft）或查看当前计划 |
| `/plan resume [id]` | 载入 draft（走批准面板）或 in-progress（继续执行） |
| `/plan clear`（`--done` 或 `--all`） | 手动清理终态计划（需确认） |
| `/plan abort` | 放弃当前计划（status=aborted，todo 清除） |
| `/todo` | 当前 todo 表格 + 计划状态/revision |

配置键（`DEFAULT_CONFIG_MAP` + `YAI_*` env）：`PLAN_ENABLED`（true）、`PLAN_MAX_STEPS`（20）、`PLAN_KEEP`（**80**）、`PLAN_ALLOW_READONLY_SHELL`（true）、`PLAN_DIR`（空 = `<config-dir>/plans`）。`PLAN_ENABLED=false` 时隐藏命令/快捷键并给一行提示。

## 8. headless 与 stream-json

- `-p/--print` 或机器输出时：`--plan` 强制 RESEARCHING，最多 `PLAN_MAX_STEPS` 轮；模型必须 `submit_plan`，否则 exit 1（`error.kind=plan_not_submitted`）。
- JSON 结果新增：`plan`（goal/assumptions/steps/risks/not_doing/revision/status）+ `plan_path`。
- stream-json 新事件：`plan_start`、`plan_ready`（path/revision/steps 数）、`todo_update`（执行阶段）、`plan_done`；未知类型忽略。
- `--plan` 与 `--verify` 冲突：stderr warning + 按 `--plan`；`--shell`/`--code` + `--plan` → exit 2。
- 修订/执行不在 headless `--plan` 范围内（无交互批准）。

## 9. 与现有系统的交互

| 系统 | 交互 |
|---|---|
| 权限/审批/审计 | plan 模式 = 作用域 readonly + schema 过滤（含只读 shell 白名单）；批准计划不改变工具审批；所有切换/提交/修订/批准/清理/被拒 shell 进审计 |
| `--resume` | **始终 NORMAL**；恢复对话 + `plan` 字段（active plan/todo）；有未完成计划打印提示（draft→`/plan review`，in-progress→`/plan resume`）；校验文件存在/status/session_id，不一致则忽略并提示；不自动进入 plan mode |
| `/compact` | 计划上下文块 ≤2KB（goal+当前 steps）；compact 不删会话 `plan` 字段 |
| K24 checks | 执行结束（或最后一步）触发；失败回灌；`finish_reason=checks_failed` |
| K25 checkpoint | 快照含 `plan` 会话字段（含 revision）；rewind 时计划状态一起恢复并提示 |
| `--yes`/`--allowed-tools` | 执行阶段沿用现有语义；plan 阶段无写工具 |
| MCP / 自定义函数 | plan 模式不暴露（v1）；后续可配 `PLAN_ALLOW_MCP` |

## 10. 错误与边界

| 场景 | 用户可见消息 | 状态/退出码 |
|---|---|---|
| 模型不调 `submit_plan` 直到 max turns | `plan mode ended: model did not submit a plan` | 保持原模式；提示重试 |
| `submit_plan` 校验失败 | 结构化错误回模型 | 原状态 |
| 已提交后再提交 | `plan_already_submitted` | 原状态 |
| 修订 revision 不匹配 / 改 id / 缺 change_summary | `invalid_revision: ...` | REVISING |
| plan 模式 shell 含元字符/管道/重定向 | `plan_shell_denied: shell metacharacters are not allowed in plan mode ...` | 不执行；结果入上下文 |
| plan 模式 shell 非白名单/危险参数 | `plan_shell_denied: <cmd/flag> is not allowed in plan mode ...` | 不执行 |
| plans 目录不可写 | `cannot write plan file: <path> (<errno>)`，拒绝进入 REVIEWING | 原模式 |
| `$EDITOR` 不可用 | `cannot open editor; plan unchanged` | REVIEWING |
| 手改坏 frontmatter | `/plan review` 或 `/plan resume` → `invalid plan file: <path>: <reason>` | 不 crash |
| resume 时 plan 文件缺失/不一致 | `saved plan not found/inconsistent; starting in normal mode` | NORMAL |
| 并发执行同一计划 | `plan is already in progress in another session`（`--force` 才覆盖） | 拒绝 |
| 原策略 readonly 批准执行 | `current TOOL_POLICY=readonly would deny writes; switch to standard? [y/N]` | 拒绝则回 REVIEWING |
| 清理保留限制 | `/plan clear` 需确认；自动清理仅终态、按 80/项目 | — |

## 11. 测试矩阵

- `tests/test_plan_store.py`：路径/PLAN_DIR/project_key/0700·0600/frontmatter/status/revision/PLAN_KEEP 清理/损坏文件/session_id 绑定。
- `tests/test_plan_mode.py`：状态机（含 REVISING）、Shift+Tab/`/plan`、工具过滤、submit_plan 校验、只读隔离、取消/暂停、max turns。
- `tests/test_plan_shell.py`：白名单 allow/deny、元字符/管道/重定向拒绝、危险参数拒绝、REPL 拒绝行、审计事件、超时/输出上限、关闭开关时完全不暴露。
- `tests/test_plan_commands.py`：`/plan` 系列（含 review/clear）、`/todo`、提示符/状态行、banner/help。
- `tests/test_todo_write.py`：1:1（当前 revision）、单 in_progress、blocked、回写 md、会话持久化。
- `tests/test_plan_revision.py`：diff 计算、原地更新（文件不新增）、完成状态保留、删除已完成步骤提示、修订批准后继续、todo 重建。
- `tests/test_plan_resume.py`：`--resume` 始终 NORMAL、未完成计划提示、stale/corrupt 降级、不加载其它会话计划。
- `tests/test_plan_execution.py`：批准→执行→done、checks 集成、中断恢复、abort、readonly 提示。
- `tests/test_headless_plan.py`：`--plan` JSON/stream-json/退出码/冲突/未提交。
- 回归：全量 pytest、`ruff check --no-fix`、`mkdocs build --strict`、`scripts/bench.py --gate`；`--help/--version` import 断言。

## 12. 实施拆分（W1 内部 PR 顺序）

1. **PR1 `feat/plan-store`**：`plan_store.py` + 配置键 + 路径/权限/frontmatter/status/revision/prune + 测试。
2. **PR2 `feat/plan-mode-core`**：`plan_mode.py` 状态机（含 REVISING）+ 工具 schema 过滤 + `submit_plan`（首次/修订）+ diff + 审计 + 测试。
3. **PR3 `feat/plan-shell`**：`plan_shell.py` 白名单校验 + plan 模式 shell 执行路径 + 审计 + 测试。
4. **PR4 `feat/plan-mode-ux`**：BackTab 绑定、提示符/状态行、批准面板 + 修订 diff 面板、`/plan` 命令、`$EDITOR`。
5. **PR5 `feat/plan-todo`**：`todo_write` + 执行循环 + plan.md 回写 + `/todo` + revision 应用 + `/plan resume`。
6. **PR6 `feat/plan-resume-headless`**：`--resume`（回 normal+提示）、`--plan` JSON/stream-json/退出码、文档与 Feature examples 对齐测试。

依赖：PR2 依赖 PR1；PR3/PR4 依赖 PR2；PR5 依赖 PR2；PR6 依赖 PR1–PR5。合并后在 `release/v0.24.0` 集成。

## 13. Claude Code 行为对照（借鉴与改进）

| 行为 | Claude Code（官方文档/issue 事实） | YAICLI 采用方式 |
|---|---|---|
| 模式切换 | `Shift+Tab` 循环权限模式，状态栏 `⏸ plan mode on`；也可 `/plan` 前缀或 `--permission-mode plan` | `Shift+Tab` 直接 normal↔plan；`/plan` 等价；提示符 `[plan] 💬 >` + 状态行 |
| 计划阶段能力 | 读文件、跑 shell 探索、写计划；禁止编辑源码。shell：只读命令直接跑，其他提示/分类器 | 读/网络 + **受控只读 shell**（固定白名单、禁元字符、argv 直启；拒绝=结构化错误 + REPL 一行）+ `submit_plan` |
| 批准选项 | `Yes, and use auto mode` / `Yes, manually approve edits` / `No, keep planning`；`Ctrl+G` 编辑计划 | `[a]`（逐工具审批不变）/ `[e]`（`$EDITOR`）/ `[r]`（继续计划）；`[s]`/`Esc` 增强 |
| 批准后的模式 | 退出 plan mode，切到所选执行权限模式，开始编辑 | `[a]` 退出模式、恢复原 `TOOL_POLICY`、todo 驱动执行 |
| 执行中更新计划 | `Shift+Tab` 回 plan mode 或下条 prompt 加 `/plan` 重新规划、再批准 | `Shift+Tab` → REVISING → `submit_plan(revision)` → diff → `[a]` 原地更新并继续 |
| 计划文件位置 | `~/.claude/plans/`，可用 `plansDirectory` 改；当前会话自己的计划文件是保护路径写例外 | `PLAN_DIR`/`<config-dir>/plans/<project-key>/`；CLI 唯一写入者，agent 写入拒绝 |
| 计划清理 | **不自动删除**（issue #12505：累积数百文件、compact/resume 后旧计划复活） | 修复：`PLAN_KEEP=80/项目` 按 updated 清理终态（无时间限制）+ `/plan clear` |
| 修订记录 | 同一会话复用同一计划文件（原地更新，社区反馈会残留旧内容） | 原地更新 + `revision` 计数 + 审计记录 diff 摘要（不新建文件） |
| 会话恢复 | 恢复会话会恢复权限模式（ended-in-plan → plan mode） | **按用户决策：`--resume` 始终回 normal**；只提示未完成计划，用户显式 `/plan review` 或 `/plan resume` |

参考链接：
- [Claude Code · 权限模式（plan mode / 批准 / Ctrl+G）](https://code.claude.com/docs/en/permission-modes#analyze-before-you-edit-with-plan-mode)
- [Claude Code · 恢复会话时的权限模式](https://code.claude.com/docs/en/sessions#permission-mode-on-resume)
- [Claude Code · plansDirectory 设置](https://code.claude.com/docs/en/settings-reference#plansdirectory)
- [GitHub issue #12505 · 计划文件跨会话/压缩后残留](https://github.com/anthropics/claude-code/issues/12505)

## 14. 已确认（2026-11-14）

1. plan 模式只读 shell：**默认开启**（`PLAN_ALLOW_READONLY_SHELL=true`）；白名单 **v1 固定**（不提供 `PLAN_SHELL_ALLOWLIST` 用户扩展）。
2. 只读 shell 被拒：**结构化错误给模型 + REPL 额外一行 `✗ plan_shell_denied: ...`**（机器模式提示走 stderr）。
3. `PLAN_KEEP=80` **按项目计**（只清理 done/aborted；无时间限制；draft/in-progress 永不自动删）。
