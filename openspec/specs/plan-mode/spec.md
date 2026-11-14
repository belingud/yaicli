## Purpose

Define the persistent **plan mode** (v0.24 K23): the agent first researches a task read-only, submits a
structured plan with `submit_plan`, the user approves it, and execution is then driven step by step by
`todo_write`. Plans are persisted as Markdown files outside the project, can be revised in place while
executing, and survive across sessions only as an explicit user choice (`/plan review` / `/plan resume`).

The behavior contract with concrete terminal examples lives in `docs/usage/plan-mode.md`; the exact
validation limits are in `docs/usage/plan-mode.md#submit_plan`.

## Requirements

### Requirement: Plan mode is a read-only tool scope selected by the user

While planning (`researching` / `revising`), the system SHALL offer the model only the read/network
builtin tools, the controlled read-only `execute_shell_command` (when `PLAN_ALLOW_READONLY_SHELL` is
true) and `submit_plan`. File-writing tools, MCP tools and user/custom functions SHALL NOT be
advertised. A model call to a tool outside that scope SHALL be refused without executing it, with the
structured in-band result `{"error": "tool_not_available_in_mode", "reason": ...}`, and SHALL be
written to the tool audit log. No plan phase SHALL write to the workspace.

#### Scenario: Write tools are not offered while planning
- **WHEN** the model builds a request in plan mode
- **THEN** the tool schema SHALL contain only the plan allowlist plus `submit_plan`, and SHALL contain no `fs_write_file`, `fs_edit_file`, `fs_file_operations` or MCP tool

#### Scenario: Hard call to a hidden tool is refused and audited
- **WHEN** the model calls `fs_write_file` while in plan mode
- **THEN** the call SHALL NOT run, the model SHALL receive `tool_not_available_in_mode`, and one audit line with `source=plan_mode` SHALL be appended

### Requirement: Plan mode is reachable from the REPL and from headless runs

`Shift+Tab` and `/plan` SHALL toggle between normal mode and plan mode. The prompt SHALL show
`[plan] 💬 >` and the status line `plan mode · read-only` SHALL be printed on entry. `--plan` SHALL
force a one-shot planning run that saves the plan and exits without executing it. `PLAN_ENABLED=false`
SHALL hide the behavior behind one explicit notice.

#### Scenario: Shift+Tab toggles plan mode
- **WHEN** the user presses Shift+Tab in the REPL
- **THEN** the prompt becomes `[plan] 💬 >`, the read-only tool scope applies, and pressing it again leaves plan mode

#### Scenario: Plan mode is never entered automatically
- **WHEN** a new or resumed session starts
- **THEN** the session SHALL start in normal mode and plan mode SHALL only activate on an explicit toggle, `/plan` command or `--plan`

### Requirement: The model ends planning only through a validated `submit_plan`

`submit_plan` SHALL accept `goal` (required, ≤500 chars), `assumptions`, `risks`, `not_doing`, and
`steps` (1..`PLAN_MAX_STEPS`, default 20; each step requires `title` and `acceptance`). The serialized
plan SHALL be at most 8 KB; step IDs are assigned by the CLI as `S1..Sn` for a first plan. Invalid
submissions SHALL return a structured `invalid_plan` error (reason + hint) with no state change, so the
model can retry. A second submission while the approval panel is open SHALL return
`plan_already_submitted`.

#### Scenario: Invalid plan is refused without writing anything
- **WHEN** the model submits a plan with no goal, no steps, a step without acceptance criteria, more steps than `PLAN_MAX_STEPS`, or more than 8 KB of serialized content
- **THEN** the model SHALL receive `invalid_plan`, no plan file SHALL be written, and the session SHALL remain in the planning phase

### Requirement: Approval is explicit and approving a plan does not pre-approve tool calls

After a valid `submit_plan` the CLI SHALL write the plan file (status `draft`) and show the approval
panel: `[a]pprove & execute`, `[e]dit`, `[r]edo`, `[s]ave only`, `Esc`/`Shift+Tab` cancel. `[a]` SHALL
write `status=in-progress` + `approved_at`, exit plan mode, restore the normal tool schema and the
session's `TOOL_POLICY`, seed the steps 1:1 as todos with `S1` in progress, and start execution. Tool
approval/confirmation semantics SHALL remain unchanged for every executed tool.

#### Scenario: Approve exits plan mode and seeds todos
- **WHEN** the user approves a first plan with 4 steps
- **THEN** the system SHALL print `✓ plan approved · exiting plan mode · todo seeded (4 steps)`, the normal tools SHALL be offered again, and the todo list SHALL contain the 4 steps with the first in progress

#### Scenario: Save only keeps a draft
- **WHEN** the user chooses `[s]ave only`
- **THEN** the plan file SHALL remain `status=draft`, the session SHALL return to normal mode, and `/plan review` SHALL be able to reopen the approval panel

### Requirement: `todo_write` drives execution and is 1:1 with the current plan revision

During execution the model SHALL update progress through `todo_write` with a full replacement list whose
ids and contents match the current plan revision exactly; the system SHALL reject additions, removals,
content changes, more than one `in_progress` entry, and a `blocked` entry without a reason. Every
accepted update SHALL be persisted in the session and reflected in the plan file's checkboxes
(`[x]` / `[ ]`, `blocked: reason` suffix).

#### Scenario: Execution completes the plan
- **WHEN** all todos reach `completed`
- **THEN** the plan file SHALL be written with `status=done` and the system SHALL print `✓ plan done · N/N steps`

### Requirement: An executing plan can be revised in place through plan mode

Pressing `Shift+Tab` (or `/plan`) while a plan is executing SHALL enter the read-only revision phase
with the current plan and todos injected into the model context. A revision submission SHALL require
`revision = current + 1` and a `change_summary`, may reuse existing step ids or append `S{n+1}..`, and
SHALL be shown as a diff panel (`Changes: +N step  ~N step  -N steps` plus todo impact). Approving a
revision SHALL update the **same** plan file (no new file), increment `revision`, refresh `updated`,
preserve the status of completed steps whose ids survive, rebuild the todo list and continue execution.

#### Scenario: Revision updates the same file
- **WHEN** the user approves revision 2 of a plan
- **THEN** the existing plan file SHALL be rewritten with `revision: 2`, the plan file count for the project SHALL be unchanged, and completed steps whose ids were kept SHALL remain completed

### Requirement: Plan files are CLI-owned, project-isolated and pruned by retention

Plan files SHALL live under `<config-dir>/plans/<project-key>/` (`PLAN_DIR` overrides the root), with
directories `0700` and files `0600`; the project key SHALL be `sha256(resolved cwd)[:16]`. The CLI SHALL
be the only writer; agent filesystem tools SHALL refuse writes under the plans root. Frontmatter SHALL
record `id`, `status`, `revision`, `session_id`, `created`, `updated`, `cwd`, `project_key`, `model`,
`base_rev` and (when set) `approved_at` / `change_summary`. Retention SHALL keep at most `PLAN_KEEP`
(default 80) terminal plans per project, deleting oldest `updated` first; `draft` / `in-progress` plans
SHALL never be pruned automatically. Plan files SHALL NOT be created in the project directory.

#### Scenario: Plans stay out of the project directory
- **WHEN** a plan is submitted, approved, executed and finished in a project
- **THEN** the project directory SHALL contain no plan files and exactly the plan file under the plans root SHALL be written

### Requirement: Resume never restores plan mode

`--resume` SHALL restore the conversation and the active-plan pointer (session JSON `plan` field) but
SHALL always start in normal mode. An unfinished plan SHALL only print a two-line hint:
`⚠ unfinished plan found: <id> (draft, revision N)` + `Use /plan review ...` for drafts, and the
`in-progress` variant with `Use /plan resume ...`. A plan pointer whose file is missing, corrupt, or
bound to another session SHALL be ignored with one notice and normal mode continues.

#### Scenario: Resume shows a hint and stays read-write
- **WHEN** a session with an in-progress plan is resumed
- **THEN** the session SHALL start in normal mode with the normal tool set, print the in-progress hint, and only `/plan resume` SHALL continue the plan

### Requirement: Headless `--plan` produces a plan and never executes it

`-p ... --plan` SHALL force one planning turn, write the plan as a draft, and exit 0 without executing
any step. `--output-format json` SHALL emit exactly one JSON object including top-level `plan`,
`plan_path` and `revision` (the normal JSON key set is unchanged for runs without `--plan`);
`stream-json` SHALL emit `plan_start`, `plan_ready` and one `done` event. A run where the model never
submits a plan SHALL exit 1 with `error.kind=plan_not_submitted`. `--plan` with `--shell`/`--code`, or
with `PLAN_ENABLED=false`, SHALL be a usage error (exit 2).

#### Scenario: Headless plan JSON
- **WHEN** `ai -p "..." --plan --output-format json` runs and the model submits a plan
- **THEN** stdout SHALL contain one JSON object with `plan`, `plan_path` and `revision`, the plan file SHALL be a draft, no tool SHALL execute, and the exit code SHALL be 0

### Requirement: Configuration

The following configuration keys SHALL exist in the config map and the shipped template:
`PLAN_ENABLED` (`YAI_PLAN_ENABLED`, bool, default true), `PLAN_MAX_STEPS` (`YAI_PLAN_MAX_STEPS`, int,
default 20), `PLAN_KEEP` (`YAI_PLAN_KEEP`, int, default 80), `PLAN_ALLOW_READONLY_SHELL`
(`YAI_PLAN_ALLOW_READONLY_SHELL`, bool, default true), `PLAN_DIR` (`YAI_PLAN_DIR`, string, empty =
`<config-dir>/plans`).

#### Scenario: Normal runs do not pay for plan mode
- **WHEN** a normal (non-plan) run starts
- **THEN** the plan modules SHALL NOT be imported and the REPL/headless output SHALL be byte-identical to the pre-feature behavior

## Feature examples

The verbatim terminal contracts are maintained in `docs/usage/plan-mode.md` (approval panel, revision
diff, `/plan` commands, resume hints) and `docs/usage/headless.md` (`--plan` JSON/text/stream-json).
Representative excerpts:

```text
 💬 > Add a --dry-run flag to fs_write_file
<press Shift+Tab>
[plan] exploring (read-only) …
plan mode · read-only
[plan] 💬 > 
  @Function call: fs_read_file({"file_paths": ["yaicli/tools/__init__.py"]})
  @Function call: submit_plan({"goal": "Add a --dry-run flag ...", "steps": [...]})

╭─ Plan ready: 20261114-004512-fs-dry-run ─────────────────────────────────────╮
│ Goal: Add a --dry-run flag to fs_write_file                                  │
│ Steps:                                                                       │
│  1. Locate the fs_write_file schema and execution path                       │
│  2. Add the dry_run parameter and short-circuit the write                    │
│  3. Add tests                                                                │
│ File: ~/.config/yaicli/plans/3f9a1c2d…/20261114-004512-fs-dry-run.md         │
╰──────────────────────────────────────────────────────────────────────────────╯
[a]pprove & execute  [e]dit  [r]edo  [s]ave only  [Esc]cancel: a
✓ plan approved · exiting plan mode · todo seeded (3 steps)

[todo 1/3] S1 Locate the fs_write_file schema and execution path
  @Function call: fs_read_file({"file_paths": ["yaicli/tools/__init__.py"]})
…
✓ plan done · 3/3 steps
```

```text
[plan] 💬 > git status | head -5
  @Function call: execute_shell_command({"command": "git status | head -5"})
  ✗ plan_shell_denied: shell metacharacters are not allowed in plan mode (use `git status` or fs_read_file)
```

Known boundaries (deliberately out of scope): K24 auto-checks and K25 checkpoint integration are later
milestones; plan mode is never entered automatically; the read-only shell allowlist is a convenience,
not a security boundary; no sub-agents or MCP tools while planning; no multi-terminal locking.
