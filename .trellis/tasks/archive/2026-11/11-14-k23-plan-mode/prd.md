# K23: 持久 plan mode + submit_plan + todo（v0.24）

> 版本：v0.24.0（roadmap `var/lightweight-audit/10-roadmap-v0.24-v0.26.md` §4.1）
> 关联：K24 验证闭环（执行阶段 checks）、K25 checkpoint（计划状态快照）、K28 子 agent（计划阶段后续扩展）
> 状态：**planning / design 定稿**（2026-11-14 v3.1，3 个开放问题已确认：只读 shell 默认开启且白名单 v1 固定；拒绝时结构化错误 + REPL 一行提示；`PLAN_KEEP=80` 按项目计）
> 借鉴：Claude Code plan mode（模式/批准/re-plan/恢复行为），并修复其计划文件不清理、跨会话 stale plan 的已知缺陷。

## Goal

把 agent 从“收到任务直接改文件”改成：**先进入持久 plan mode 做只读调研（文件 + 网络 + 受控只读 shell），用 `submit_plan` 产出一份可审阅、可持久化的计划（Markdown + frontmatter，存配置目录），用户 `[a]` 批准后退出计划模式、把步骤注入 todo，由 `todo_write` 驱动分步执行并回写计划文件；执行中需要调整时，可重新进入 plan mode 提交修订版、批准后继续。** 计划阶段不做任何写入；执行阶段沿用现有权限/审批/审计模型（批准计划 ≠ 批量批准工具）。

## Background（现状问题）

| 问题 | 证据 |
|---|---|
| 没有 plan/act 分离：模型边想边改，用户来不及审阅方案 | `yaicli/` 无 plan/todo 模块；`cmd_handler.py:89-113` 命令表无 `/plan`；`TOOL_POLICY` 只能整会话设置（`const.py:184-185`） |
| 没有任务清单：多步任务的进度不可见、中断后无法接着做 | 无 todo 模块；`MAX_TOOL_CALL_DEPTH` 只限制轮数（`const.py:179`） |
| 计划不可持久：换会话/换进程后丢失 | 会话只保存对话（`chat.py:37-38`），无计划文件概念 |
| 计划批准后不能调整：任务变化只能中断重来 | 无修订/重新批准机制 |
| 只读能力只有“整会话 readonly”，没有临时、可切换的计划阶段 | `TOOL_POLICY=readonly` 是会话级配置，无法按阶段切换 |
| 批准粒度只有“工具级”，没有“方案级”确认 | `tools/approval.py:1-20` 只按工具/参数审批 |

## Scope

**In**

1. 会话级**持久 plan mode**：`Shift+Tab` 在 normal ↔ plan 间切换（`/plan` 为等价入口与终端兜底）；提示符 `[plan] 💬 >`、状态行 `plan mode · read-only`；模式内暴露 read/network 工具 + **受控只读 shell** + `submit_plan`。
2. **受控只读 shell（plan 模式）**：`PLAN_ALLOW_READONLY_SHELL`（默认 true）开启后，`execute_shell_command` 在 plan 模式只允许**固定只读白名单**（`ls/pwd/cat/head/tail/wc/grep/rg/find/file/stat/tree/which` + `git status/diff/log/show/ls-files/blame/rev-parse/describe/branch --list`；**v1 白名单固定，不提供用户自定义命令**）；拒绝 shell 元字符（`; & | > < $( ) \` 换行`）、管道、重定向、命令替换；`git -c/--exec-path`、`find -delete/-exec`、`rg --pre` 等危险参数一律拒绝；非白名单返回结构化 `plan_shell_denied` 并在 REPL 额外显示一行 `✗ plan_shell_denied: ...`（机器模式提示走 stderr）；cwd/env/timeout/输出上限沿用 shell 护栏；每次调用进审计。不做 shell 解释（argv 直启，非 `shell=True`）。
3. **`submit_plan` 工具**：唯一结束计划阶段的出口；结构化计划（goal/assumptions/steps/risks/not_doing）；校验步骤数、验收字段、大小；成功后 CLI 写计划文件并进入批准面板。
4. **计划文件**：`<config-dir>/plans/<project-key>/<YYYYMMDD-HHMMSS>-<slug>.md`（`PLAN_DIR` 可覆盖 plans 根），Markdown + frontmatter；CLI 是唯一写入者；目录 0700 / 文件 0600；**按项目隔离**（project-key = `sha256(resolved cwd)[:16]`）。
5. **批准面板**：`[a]批准并执行 [e]编辑 [r]重做 [s]只保存 [Esc]取消`；`[e]` 用 `$EDITOR` 编辑后重新校验并回面板。
6. **执行阶段**：`[a]` 后退出 plan mode、恢复原策略/工具 schema、steps 1:1 注入 todo（S1..Sn）、立即开始执行；`todo_write` 全量更新状态（`pending|in_progress|completed|blocked`，`blocked` 带 reason；至多一个 `in_progress`；只能改状态、不能增删步骤），CLI 持久化并回写 plan.md 复选框。
7. **执行中计划修订（re-plan）**：执行中 `Shift+Tab` 回到 plan mode → `submit_plan` 提交修订版（同一计划 id、`revision+1`）→ 面板展示步骤 diff（新增/删除/修改 + todo 影响）→ `[a]` 应用修订（保留已完成且未删除的步骤状态）并继续执行；`[Esc]` 放弃修订回到执行。**修订按 Claude Code 方式：同一计划文件原地更新（不新建 `-r2.md`），`revision` 计数 + `updated` 时间戳，diff 摘要进审计**。
8. **计划生命周期与清理**：frontmatter 记录 `status`（draft/in-progress/done/aborted）+ `revision` + `session_id`；终态计划按 **`PLAN_KEEP=80/项目`** 按 `updated` 从旧到新清理，**无时间限制**；draft/in-progress 永不自动删；`/plan clear [--done|--all]` 手动清理。
9. **会话恢复**：`--resume` 恢复对话后**始终回到默认 normal 模式**（不自动恢复 plan mode）；若存在未完成计划则打印提示行（draft → `/plan review`；in-progress → `/plan resume`），由用户显式继续；恢复时校验 plan 文件存在/id/status/session 绑定，不一致则忽略并提示。
10. **命令**：`/plan`（切换/查看）、`/plan <task>`、`/plan list [--all]`、`/plan show`、`/plan edit`、`/plan review`、`/plan resume`、`/plan clear`、`/plan abort`、`/todo`。
11. **headless**：`-p "..." --plan` 强制 plan mode 跑一轮，必须 `submit_plan`；写文件后输出 `plan` + `plan_path` + `revision`，**不执行**，exit 0；未提交计划 exit 1；`--plan` 与 `--verify` 冲突警告；`--shell`/`--code` 禁用。
12. **配置键**：`PLAN_ENABLED`（true）、`PLAN_MAX_STEPS`（20）、`PLAN_KEEP`（80）、`PLAN_ALLOW_READONLY_SHELL`（true）、`PLAN_DIR`（空 = `<config-dir>/plans`）。
13. 交互：与 sessions/`--resume`、`/compact`、K24 checks、K25 checkpoint 的衔接；文档（commands/cli/headless/README）；单元与集成测试。

**Out（本任务不做）**

- 不做自动进入 plan mode / 自动判定“这个任务该先计划”（显式触发，避免简单任务变慢）。
- `todo_write` 不能增删步骤；增删必须走**已批准的计划修订**。
- plan 阶段不执行写操作、不跑测试/构建（exec）；需要跑测试时退出 plan mode（Shift+Tab）或进入执行阶段。
- plan 阶段不调用子 agent（K28 / v0.25）。
- 不做跨项目 plan 库管理（默认当前项目；`--all` 只读列表）。
- 不改变现有权限模型与审批语义。

## 用户可见契约（概要）

| 场景 | 行为 |
|---|---|
| 进入/退出 | REPL 中 `Shift+Tab` 切换；`/plan` 等价；提示符 `[plan] 💬 >`；状态行 `plan mode · read-only` |
| 计划阶段 | 读文件/网络 + 受控只读 shell（白名单）；写/exec 工具不可见；shell 非白名单立刻拒绝——结构化错误给模型 + REPL 一行 `✗ plan_shell_denied: ...`（机器模式提示走 stderr） |
| 批准面板 | `[a]` 批准并立即执行；`[e]` 编辑；`[r]` 重做；`[s]` 只保存（退出模式，状态 draft）；`Esc` 取消提交（留在 plan mode） |
| 执行中修订 | `Shift+Tab` 回 plan mode → `submit_plan` 修订版 → 面板显示 diff → `[a]` 应用并继续；已完成步骤保留（未被删除时）；计划文件原地更新 |
| 计划文件 | 只写 `<config-dir>/plans/<project-key>/`；当前项目目录零新增文件；终态保留最近 80 个/项目 |
| 执行 | todo 进度 `[2/4] S2 …`；每步状态回写 plan.md；完成后 plan 标 done 并汇总；K24 checks 配置时通过才算 done |
| 中断/恢复 | 执行中 Ctrl-C = 暂停（todo 保留）；`/plan resume` 继续；`--resume` 回 normal 模式 + 未完成计划提示 |
| headless | `--plan` 只出计划不执行；JSON 含 `plan`/`plan_path`/`revision`；exit 0（未提交 exit 1） |

## Feature examples

> 约定：正常提示符 ` 💬 > `；plan mode 提示符 `[plan] 💬 >`；工具调用行沿用 `@Function call: name({...})`；批准面板沿用 Rich 框线。

### F1 进入计划模式 → 只读调研（含只读 shell）→ submit_plan

```
 💬 > 把 tokens 的估算器换成可插拔实现，并补测试
<press Shift+Tab>
[plan] 💬 > 用计划模式重新做上面这件事
[plan] exploring (read-only) …
  @Function call: fs_search_files({"pattern": "estimate_tokens", "path": "yaicli"})
  @Function call: fs_read_file({"file_paths": ["yaicli/tokens.py", "yaicli/llms/client.py"]})
  @Function call: execute_shell_command({"command": "git log --oneline -5 -- yaicli/tokens.py"})
  @Function call: execute_shell_command({"command": "rg -n \"estimate_\" yaicli tests"})
  @Function call: submit_plan({"goal": "将 token 估算器抽象为可插拔接口，默认行为不变", ...})

╭─ Plan ready: 20261114-004230-token-estimator ────────────────────────────────╮
│ Goal: 将 token 估算器抽象为可插拔接口，默认行为与数值保持不变              │
│ Steps:                                                                       │
│  1. 抽出 TokenEstimator 协议 + 默认 HeuristicEstimator                       │
│  2. tokens.estimate_* 委托给当前 estimator（行为不变）                       │
│  3. 新增 tests/test_tokens_estimator.py                                      │
│  4. 跑 pytest + ruff                                                         │
│ File: ~/.config/yaicli/plans/3f9a1c2d…/20261114-004230-token-estimator.md    │
╰──────────────────────────────────────────────────────────────────────────────╯
[a]pprove & execute  [e]dit  [r]edo  [s]ave only  [Esc]cancel: a
✓ plan approved · exiting plan mode · todo seeded (4 steps)
```

只读 shell 被拒绝的例子：

```
[plan] 💬 > 用 shell 看看
  @Function call: execute_shell_command({"command": "git status | head -5"})
  ✗ plan_shell_denied: shell metacharacters are not allowed in plan mode (use `git status` or fs_read_file)
  @Function call: execute_shell_command({"command": "rm -rf build/"})
  ✗ plan_shell_denied: `rm` is not in the plan-mode read-only allowlist
```

### F2 `[a]` 批准并执行 → todo 驱动

```
[todo 1/4] S1 抽出 TokenEstimator 协议
  @Function call: fs_edit_file({"file_path": "yaicli/tokens.py", ...})
[todo 2/4] S2 tokens.estimate_* 委托
  @Function call: fs_edit_file({"file_path": "yaicli/tokens.py", ...})
[todo 3/4] S3 新增 tests/test_tokens_estimator.py
  @Function call: fs_write_file({"file_path": "tests/test_tokens_estimator.py", ...})
[todo 4/4] S4 跑 pytest + ruff
  @Function call: execute_shell_command({"command": "uv run pytest -q && ruff check --no-fix yaicli tests"})

✓ plan done · 4/4 steps · 2 files changed (+182/−37) · checks: 2 passed
```

### F3 执行中修订计划（re-plan，单文件原地更新）

```
[todo 2/4] S2 tokens.estimate_* 委托
<press Shift+Tab>
[plan] 💬 > 需求变了：估算器要支持按 provider 覆盖，更新计划
[plan] revising (read-only) …
  @Function call: fs_read_file({"file_paths": ["yaicli/model_limits.py"]})
  @Function call: submit_plan({"revision": 2, "change_summary": "新增 per-provider estimator 覆盖", "steps": [...]})

╭─ Plan revision 2: 20261114-004230-token-estimator ───────────────────────────╮
│ Changes: +1 step  ~1 step  −0 steps                                           │
│  + S5 支持 provider 级 estimator 覆盖（新增 tests/test_estimator_override）  │
│  ~ S4 改为：pytest + ruff（step id 不变，已完成状态保留）                    │
│ Todo impact: S1–S2 已完成保留；S3 仍为 pending；S5 追加为 pending            │
╰──────────────────────────────────────────────────────────────────────────────╯
[a]pply & continue  [e]dit  [r]edo  [Esc]cancel revision: a
✓ revision 2 applied · plan.md updated in place · resuming execution at S3
```

### F4 `[s]` 只保存 / `Esc` 取消

```
[a]pprove & execute  [e]dit  [r]edo  [s]ave only  [Esc]cancel: s
✓ saved as draft (~/.config/yaicli/plans/3f9a1c2d…/20261114-004230-token-estimator.md) · exit plan mode

 💬 > /plan review
Resuming draft 20261114-004230-token-estimator:
  ⚠ base_rev changed: plan was c51f7a3, HEAD is 8ac1f20 — the plan may be stale.
[a]pprove & execute  [e]dit  [r]edo  [s]ave only  [Esc]cancel:
```

### F5 会话恢复（`--resume` 回默认模式）

```
$ ai --resume
✓ resumed session 20261114-004230 (mode: normal)
  ⚠ unfinished plan found: 20261114-004230-token-estimator (in-progress, revision 2)
  Use /plan resume to continue it, or /plan list to see all plans.
 💬 > 
```

### F6 headless `--plan`（只出计划、不执行）

```bash
$ ai -p "给 fs_write_file 加 --dry-run" --plan --output-format json | jq '{plan_path, revision, steps: [.plan.steps[].title]}'
{
  "plan_path": "/Users/vic/.config/yaicli/plans/3f9a1c2d…/20261114-004512-fs-dry-run.md",
  "revision": 1,
  "steps": ["定位 fs_write_file 的 schema 与执行路径", "新增 dry_run 参数并在执行层短路", "补测试"]
}
$ echo $?   # 0
```

## 表现契约

| 场景 | TTY | 非 TTY / text | json / stream-json | 退出码 |
|---|---|---|---|---|
| 模式切换与提示符 | 提示符 `[plan] 💬 >` + 状态行变化 | 不适用（headless 用 `--plan` 显式指定） | 不适用 | — |
| 调研进度/计划展示 | Rich 面板 + 进度行（stdout） | 计划文本到 stdout，进度到 stderr | `plan` + `plan_path` / `plan_*` 事件；stdout 无装饰 | `--plan` 0；未提交/生成失败 1 |
| plan 模式只读 shell | 工具预览（stderr）+ 结果（stdout） | stderr | `tool_call`/`tool_result` 事件（结果含拒绝原因） | — |
| 批准面板 | 交互 stdin | 不出现（headless `--plan` 只保存不执行） | 不出现 | — |
| 修订面板（执行中） | Rich diff + `[a]pply & continue` | 不适用（无交互执行） | 不适用 | — |
| 会话恢复 | 提示行（未完成计划） | 不适用 | `--resume` 与机器模式互斥（既有契约） | — |
| 写/exec 工具在 plan 模式被调用 | 拒绝并提示 | stderr | error 对象（若模型硬发） | 不改变 |

**逻辑/优先级**：`Shift+Tab` 与 `/plan` 等价；`reviewing` 状态下 `Shift+Tab`=取消提交并退出；执行中 `Shift+Tab`=进入修订（re-plan）；`--resume` 永远 normal；`--plan` 与 `--verify` 冲突时计划优先并警告；原会话 `TOOL_POLICY=readonly` 时批准执行前必须提示切换策略，否则不进入执行。

## Acceptance Criteria

- [ ] ① plan mode 零写入：模式内不暴露写/exec 工具 schema（只读 shell 走白名单）；硬发调用 100% 被拒并进审计
- [ ] ② `Shift+Tab` 与 `/plan` 都能切换；提示符 `[plan] 💬 >` + 状态行可见；`--plan` headless 同样强制模式
- [ ] ③ `submit_plan` 是结束调研的唯一出口；steps 数量/验收字段/大小校验失败返回结构化错误，模型可重试
- [ ] ④ `[a]` 批准后自动退出模式、恢复原策略与工具 schema、steps→todo 并立即执行；批准前无任何写入
- [ ] ⑤ `todo_write` 与**当前 revision** 步骤 1:1（增删必须走已批准修订）、至多一个 in_progress、状态回写 plan.md 复选框
- [ ] ⑥ 计划文件只写 `<config-dir>/plans/<project-key>/`（0700/0600）；`PLAN_KEEP=80/项目` 只清理终态、无时间清理；项目目录零新增文件
- [ ] ⑦ 执行中修订：`Shift+Tab` → `submit_plan(revision)` → diff 面板 → `[a]` 应用（已完成且未删除步骤状态保留）并继续；**计划文件原地更新**（revision 递增、审计记录 diff 摘要）
- [ ] ⑧ `--resume` 始终回 normal 模式；有未完成计划只打印提示（draft→`/plan review`，in-progress→`/plan resume`）；不自动进入 plan mode、不加载其它会话计划
- [ ] ⑨ `-p --plan --output-format json` 输出 `plan`+`plan_path`+`revision`、exit 0；模型未提交计划 exit 1
- [ ] ⑩ plan 模式只读 shell：白名单命令可跑；元字符/管道/重定向/非白名单 100% 拒绝；拒绝 = 结构化 `plan_shell_denied` + REPL 一行 `✗ plan_shell_denied`（机器模式走 stderr）；每次调用进审计；`PLAN_ALLOW_READONLY_SHELL=false` 时完全不暴露
- [ ] ⑪ 默认 normal 路径不回归：`pytest`/`ruff`/`mkdocs --strict` 绿、bench gate 不回归
- [ ] ⑫ 与 `/compact`、K24 checks、K25 checkpoint 的交互测试通过
- [ ] ⑬ 文档四处更新（commands、cli、headless、README）+ 快捷键在 `/help` 与欢迎 banner 可见

## Claude Code 行为借鉴（详见 `design.md` §13）

- **借鉴**：`Shift+Tab` 切换模式；计划阶段只读 + 可跑 shell 探索（只读命令直接跑、其他提示/分类器）；批准后才执行；`[e]` 编辑计划（对应 `Ctrl+G`）；"No, keep planning"（对应 `[r]`）；执行中可重新进入 plan mode 更新计划再批准；计划存配置目录、可用 `plansDirectory` 覆盖；修订同一文件原地更新。
- **按用户决策调整**：`--resume` **回默认 normal 模式**（不照搬 Claude Code 恢复 plan mode）。
- **改进（不照抄已知缺陷）**：计划按项目隔离（Claude Code 全局 `~/.claude/plans/` 跨项目串）；计划文件绑定 `session_id` + `status`，新会话不自动读取旧计划（stale plan bug [#12505](https://github.com/anthropics/claude-code/issues/12505)）；终态计划按 `PLAN_KEEP=80/项目` 清理（Claude Code 不清理）。

## 已确认决策（2026-11-14）

1. plan 模式只读 shell：**默认开启**（`PLAN_ALLOW_READONLY_SHELL=true`）；白名单 **v1 固定**（`ls/pwd/cat/head/tail/wc/grep/rg/find/file/stat/tree/which` + git 只读子命令），**不提供** `PLAN_SHELL_ALLOWLIST` 之类的用户扩展命令（后续再评估）。
2. 只读 shell 被拒：**结构化错误给模型 + REPL 额外显示一行 `✗ plan_shell_denied: ...`**（机器模式提示走 stderr）；不再单独提供开关。
3. `PLAN_KEEP=80` **按项目计**（只清理 done/aborted，无时间限制；draft/in-progress 永不自动删）。
