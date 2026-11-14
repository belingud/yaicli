# Plan Mode (Read-Only Planning)

Plan mode separates **thinking from doing**: the model first researches the task read-only and
submits a structured plan for your approval; only after you approve does it get the normal tool set
back and start executing, step by step, driven by a todo list.

Nothing in the workspace is written while planning. The plan itself is saved to a plan file outside
the project directory, and execution still uses the normal `TOOL_POLICY` / confirmation / audit
model — **approving a plan does not pre-approve tool calls**.

| In plan mode (read-only) | After approval (execution) |
| --- | --- |
| Read/network tools, a fixed read-only shell allowlist and `submit_plan` | The normal tool set + `todo_write` |
| Prompt `[plan] 💬 >`, status line `plan mode · read-only` | Normal prompt; `[todo 2/4] S2 <title>` progress lines |
| No writes, no test/build execution, no MCP/custom functions | Same permissions as any other turn |

## Entering and leaving plan mode

Plan mode is available in the interactive REPL only. Press `Shift+Tab` (or run `/plan` with no
argument) to toggle between normal mode and plan mode:

```text
 💬 > Add a --dry-run flag to fs_write_file
<press Shift+Tab>
[plan] exploring (read-only) …
plan mode · read-only
[plan] 💬 > 
```

- The status line `plan mode · read-only` is printed when plan mode is entered; the prompt becomes
  `[plan] 💬 >`.
- A plan run starts as `[plan] exploring (read-only) …`. While an approved plan is executing,
  `Shift+Tab` starts a revision instead: `[plan] revising (read-only) …`.
- `Shift+Tab` / `/plan` again leaves plan mode (`plan mode off`) and discards the unsubmitted draft.
- In execute mode (`🚀`), `Shift+Tab` returns to chat mode first and then enters plan mode. Use
  `/mode chat|exec` to switch between chat and execute modes explicitly.
- While the approval panel is open, `Esc` cancels the submission and keeps the plan file as a
  draft (see [Approval panel](#approval-panel)).
- Plan mode is never entered automatically. When `PLAN_ENABLED=false`, toggling prints
  `plan mode is disabled (PLAN_ENABLED=false)` instead.

Plan mode is not persisted across sessions: after `--resume` you always start in the normal mode
(see [Resuming a session](#resuming-a-session)).

## What the model can use while planning

The tool schemas offered to the model are filtered by mode. In plan mode it sees:

| Tool | Notes |
| --- | --- |
| `fs_read_file`, `fs_list_directory`, `fs_search_files`, `fs_get_filesystem_info`, `fs_read_image` | Filesystem read-only inspection |
| `fetch_webpage`, `web_search`, `get_weather` | Network read tools |
| `execute_shell_command` | Only the fixed read-only allowlist below (when `PLAN_ALLOW_READONLY_SHELL=true`, the default) |
| `submit_plan` | The only way to end the planning phase |

Not available in plan mode: file-writing tools (`fs_write_file`, `fs_edit_file`,
`fs_file_operations`), MCP tools and custom/user functions (v1). If the model calls a tool that is
not available, it receives a structured `tool_not_available_in_mode` error, the tool is not run,
and the refusal is written to the audit log.

### What the model is told (and what happens if it ignores it)

Plan mode is enforced in the request, not only in the UI: a bounded (≤ 2 KB) block of plan-mode rules is
appended to the request's **system prompt** together with the current plan/revision/todo state. It is
part of the first system message on purpose — some providers only transmit a single system prompt
(Anthropic and Gemini both do), so a separate system message would be dropped and plan mode would
silently behave like normal chat. The block tells the model to stay read-only, to **never write the
implementation or the final answer while planning**, and that `submit_plan` is the only way to end the
phase.

If the model still answers in plain text without calling any tool (for example it prints the HTML page
you asked for instead of planning), the REPL prints one warning line instead of pretending a plan
exists:

```text
[plan] no plan submitted — this turn answered in text without using tools; ask again to research and
submit a plan, or press Shift+Tab to leave plan mode.
```

The rules are re-sent on every plan-mode turn, so simply asking again (or restating the task) is usually
enough. Press `Shift+Tab` to leave plan mode when you want a normal answer instead of a plan.

## Controlled read-only shell

`PLAN_ALLOW_READONLY_SHELL` (default `true`) exposes `execute_shell_command` in plan mode, but only
for a **fixed allowlist**:

| Allowlist | Commands |
| --- | --- |
| Basic | `ls`, `pwd`, `cat`, `head`, `tail`, `wc`, `grep`, `rg`, `find`, `file`, `stat`, `tree`, `which` |
| Git (read-only) | `git status`, `git diff`, `git log`, `git show`, `git ls-files`, `git blame`, `git rev-parse`, `git describe`, `git branch --list` |

The command is parsed with `shlex` and executed as an argv list directly — there is **no shell
interpretation** (`shell=True` is never used). Rejected:

- shell metacharacters and composition: `; & | > < $( )`, backticks and newlines (no pipes,
  redirection or command substitution);
- commands outside the allowlist (`rm`, `mv`, `curl`, `python`, `make`, `pytest`, ...);
- dangerous arguments such as `find -delete` / `-exec`, `rg --pre`, `tree -o`, `file -C`, and
  git global options (`git -c`, `--config`, `--exec-path`, ...);
- `git branch` without `--list` (it could delete branches).

A denial returns a structured `plan_shell_denied` error to the model with a reason and hint, and the
REPL prints one extra line:

```text
  @Function call: execute_shell_command({"command": "git status | head -5"})
  ✗ plan_shell_denied: shell metacharacters are not allowed in plan mode (use `git status` or fs_read_file)
```

In machine/non-TTY output that line goes to stderr so stdout stays parseable. The shell tool's
existing guardrails apply (workspace-confined `cwd`, filtered environment, timeout, output cap) and
every allowed or denied call is written to the audit log. Set
`PLAN_ALLOW_READONLY_SHELL=false` to remove the shell tool from plan mode entirely.

> **Not a security boundary.** The allowlist is a best-effort convenience for read-only
> exploration: `cat` can read any path you can read, `grep -r` can be slow, and the allowlist is
> fixed in v1 (there is no user-extensible command list). The real guarantee is the reduced tool
> schema: write/exec tools are not offered, and forced calls are refused.

## `submit_plan`

`submit_plan` is called by the model, not typed by you. The plan it submits contains:

- `goal` — one-paragraph objective (required, at most 500 characters);
- `assumptions`, `risks`, `not_doing` — optional lists;
- `steps` — 1..`PLAN_MAX_STEPS` (default `20`) steps, each with a `title` and an `acceptance`
  criterion (both required), plus an optional `detail`;
- for revisions only: `revision` (must be the current revision + 1) and `change_summary`
  (required, at most 500 characters).

The serialized plan must be at most 8 KB. First plans get step IDs `S1`..`Sn` assigned by the CLI;
in a revision each step ID must be an existing ID or the next new ID (`S{n+1}` and up), and IDs
cannot repeat. Invalid submissions return a structured `invalid_plan` error with a reason and hint,
so the model can correct itself; while the approval panel is open a repeated `submit_plan` returns
`plan_already_submitted`.

The plan is then shown in the approval panel.

## Approval panel

```text
╭─ Plan ready: 20261114-004230-fs-dry-run ─────────────────────────────────────╮
│ Goal: Add a --dry-run flag to fs_write_file                                  │
│ Steps:                                                                       │
│  1. Locate the fs_write_file schema and execution path                       │
│  2. Add dry_run and short-circuit in the execution layer                     │
│  3. Add tests                                                                │
│ File: ~/.config/yaicli/plans/3f9a1c2d…/20261114-004230-fs-dry-run.md         │
╰──────────────────────────────────────────────────────────────────────────────╯
[a]pprove & execute  [e]dit  [r]edo  [s]ave only  [Esc]cancel: 
```

| Key | Action | Result |
| --- | --- | --- |
| `a` | Approve and execute | Leaves plan mode, restores the normal tool set, seeds the todo list and starts executing: `✓ plan approved · exiting plan mode · todo seeded (N steps)` |
| `e` | Edit the plan in `$EDITOR` (fallback `vi`) | The edited file is re-parsed and validated, then the panel is shown again; no model call |
| `r` | Redo — keep planning | Discards the draft and returns to plan mode with the research context kept |
| `s` | Save only | Keeps the plan file as a draft and exits plan mode: `✓ saved as draft (<path>) · exit plan mode` |
| `Esc` | Cancel the submission | Keeps the plan file as a draft and exits plan mode: `plan cancelled; draft saved at <path>` |

Reopen a saved draft later with `/plan review`. If the session's `TOOL_POLICY` is `readonly`,
approving first asks `current TOOL_POLICY=readonly would deny writes; switch to standard? [y/N]`;
answering no leaves you in the approval panel.

A revised plan (submitted while execution is in progress) uses a diff panel instead:

```text
╭─ Plan revision 2: 20261114-004230-fs-dry-run ────────────────────────────────╮
│ Changes: +1 step  ~1 step  -0 steps                                          │
│  + S4 Add tests for the dry-run output                                       │
│  ~ S2 Add dry_run and short-circuit …                                        │
│ Todo impact: S1–S2 completed kept; S3 pending; S4 pending                    │
╰──────────────────────────────────────────────────────────────────────────────╯
[a]pply & continue  [e]dit  [r]edo  [Esc]cancel revision: 
```

`a` applies the revision **in place**: the same plan file gets the new steps, `revision` is
incremented and `updated` refreshed, completed steps that were not removed keep their status, and
execution resumes (`✓ revision N applied · plan.md updated in place · resuming execution at <Sx>`).
`Esc` discards the revision and returns to the running plan unchanged (`revision discarded`).

## Execution with todos

After approval:

- the plan's status becomes `in-progress` and the plan file records `approved_at`;
- the steps are injected 1:1 as todos: `S1` is `in_progress`, the rest are `pending`;
- progress is printed as `[todo 2/4] S2 <title>`;
- the model updates all todo states with `todo_write` (full-state replacement):

| Todo status | Meaning |
| --- | --- |
| `pending` | Not started |
| `in_progress` | Being worked on (at most one at a time) |
| `completed` | Step done |
| `blocked` | Cannot proceed; a `reason` (at most 500 characters) is required |

`todo_write` is bound to the **current revision** of the plan: it cannot add, remove or reword
steps (that requires an approved revision) and it must send every step exactly once. The CLI writes
the states back into the plan file: completed steps get `[x]` and blocked steps end with
` (blocked: reason)`.

When every step is completed the plan is marked `done` and the run prints
`✓ plan done · N/N steps`. Execution is bounded: if progress stalls or the turn budget is reached,
the plan pauses with todos kept and prints
`[plan] execution paused at N/M steps · /plan resume to continue · /plan abort to abandon`.
Ctrl+C during execution pauses the plan the same way; `/plan resume` continues it and `/plan abort`
abandons it (`plan aborted · todos cleared`).

Approving a plan does not change your tool policy: every tool call during execution goes through
the normal confirmation/allowlist/audit path.

## Re-planning during execution

If the task changes mid-execution, press `Shift+Tab` (or run `/plan`): the model re-enters the
read-only mode with the current plan and todo state in context (`[plan] revising (read-only) …`).
Ask for the change; when the model calls `submit_plan` with `revision: N+1` the diff panel above is
shown. Approving updates the existing plan file in place — no new file, no `-r2` copy — and
execution continues from the unchanged progress. Cancelling the revision returns to execution with
the plan untouched.

## Plan files

Plans are stored per project, outside the working tree:

```text
<config-dir>/plans/<project-key>/<YYYYMMDD-HHMMSS>-<slug>.md
```

- `<config-dir>` is the YAICLI configuration directory (`~/.config/yaicli` by default, see
  [Configuration](configuration.md#location)); set `PLAN_DIR` to override the `plans` root.
- `<project-key>` is `sha256(resolved working directory)[:16]`, so plans are isolated per project
  even when they share the plans root.
- Directories are created `0700` and plan files are written atomically with mode `0600`. The CLI is
  the only writer: the built-in file tools refuse to write under the plans root.
- Each file is Markdown with a small frontmatter block: `id`, `status`
  (`draft` / `in-progress` / `done` / `aborted`), `revision`, `session_id`, `created`, `updated`,
  `cwd`, `project_key`, `model`, `base_rev`, `approved_at` and `change_summary`.
- Plan files are bound to the session that created them (`session_id`), so a resumed session only
  restores its own plan and never resurrects a stale one from another project or session.
- Cleanup keeps the `PLAN_KEEP` (default `80`) most recently updated **finished** plans per project;
  older `done`/`aborted` files are removed. `draft` and `in-progress` plans are never removed
  automatically. Use `/plan clear --done` or `/plan clear --all` to clean up by hand (it asks for
  confirmation).

## Commands

| Command | Behaviour |
| --- | --- |
| `/plan` | Toggle plan mode: normal ↔ plan; when a plan is executing, enter revision mode; while reviewing, cancel the review |
| `/plan <task>` | Enter plan mode if needed and send `<task>` as the prompt (the model explores and submits a plan); refused while a plan is waiting for review: `a plan is waiting for review; approve or cancel it first` |
| `/plan list [--all]` | Table of plans for this project (`ID`, `STATUS`, `REV`, `UPDATED`, `GOAL`); `--all` lists every project; `no plans yet` when empty |
| `/plan show [id]` | Show a plan (default: the current one); `plan not found: <id>` when missing |
| `/plan edit` | Open the current plan in `$EDITOR` and re-validate it |
| `/plan review [id]` | Open a saved draft in the approval panel |
| `/plan resume [id]` | Continue an `in-progress` plan (or reopen a draft in the approval panel); prints `plan is already in progress in another session` when the plan belongs to a different session |
| `/plan clear [--done\|--all]` | Delete plan files after confirmation (`--done`: finished plans only; `--all`: everything in this project) |
| `/plan abort` | Abandon the current plan (`status=aborted`, todos cleared) |
| `/todo` | Show the current todo table and the plan id/status/revision; `no plan in this session` when none |

All command strings are fixed:

```text
no plans yet
plan not found: <id>
no plan in this session
a plan is waiting for review; approve or cancel it first
plan is already in progress in another session
plan clear needs an interactive confirmation
plan aborted · todos cleared
```

## Example: plan first, then execute (F1)

```text
 💬 > Add a --dry-run flag to fs_write_file
<press Shift+Tab>
[plan] exploring (read-only) …
plan mode · read-only
[plan] 💬 > Plan the change first
  @Function call: fs_search_files({"pattern": "fs_write_file", "path": "yaicli"})
  @Function call: fs_read_file({"file_paths": ["yaicli/functions/buildin/fs_write_file.py"]})
  @Function call: execute_shell_command({"command": "git log --oneline -5 -- yaicli/functions/buildin/fs_write_file.py"})
  @Function call: submit_plan({"goal": "Add a --dry-run flag to fs_write_file", ...})

╭─ Plan ready: 20261114-004512-fs-dry-run ─────────────────────────────────────╮
│ Goal: Add a --dry-run flag to fs_write_file                                  │
│ Steps:                                                                       │
│  1. Locate the fs_write_file schema and execution path                       │
│  2. Add dry_run and short-circuit in the execution layer                     │
│  3. Add tests                                                                │
│ File: ~/.config/yaicli/plans/3f9a1c2d…/20261114-004512-fs-dry-run.md         │
╰──────────────────────────────────────────────────────────────────────────────╯
[a]pprove & execute  [e]dit  [r]edo  [s]ave only  [Esc]cancel: a
✓ plan approved · exiting plan mode · todo seeded (3 steps)
[todo 1/3] S1 Locate the fs_write_file schema
  @Function call: fs_edit_file({"file_path": "yaicli/functions/buildin/fs_write_file.py", ...})
[todo 2/3] S2 Add dry_run and short-circuit
  @Function call: execute_shell_command({"command": "uv run pytest -q tests/test_functions.py"})
[todo 3/3] S3 Add tests
✓ plan done · 3/3 steps
```

While plan mode is active, shell usage outside the allowlist is denied exactly as shown in
[Controlled read-only shell](#controlled-read-only-shell).

## Headless planning: `--plan` (F6)

`--plan` forces a single planning run in one-shot mode: YAICLI explores read-only, saves the plan
as a draft and **exits without executing it**.

```bash
$ ai -p "Add a --dry-run flag to fs_write_file" --plan --output-format json | jq '{plan_path, revision, steps: [.plan.steps[].title]}'
{
  "plan_path": "/Users/vic/.config/yaicli/plans/3f9a1c2d…/20261114-004512-fs-dry-run.md",
  "revision": 1,
  "steps": ["Locate the fs_write_file schema and execution path", "Add dry_run and short-circuit in the execution layer", "Add tests"]
}
$ echo $?   # 0
```

The JSON result adds the top-level keys `plan` (the full plan object), `plan_path` and `revision`;
the normal JSON keys are unchanged. Exit codes:

| Situation | Result |
| --- | --- |
| The model called `submit_plan` | Plan saved as `draft`, `plan`/`plan_path`/`revision` in the JSON, exit `0` |
| The model never called `submit_plan` | exit `1`, `error.kind = "plan_not_submitted"`, message `plan mode ended: model did not submit a plan` |
| `--plan` combined with `--shell` or `--code` | usage error, exit `2` |
| `PLAN_ENABLED=false` | usage error, exit `2` |

The approval panel and execution are interactive-only; `--plan` never executes the plan. `--chat`
and `--resume` are ignored with a warning under `--plan`. See
[Headless & Scripting](headless.md) for the full output contract, including
the stream-json `plan_start` / `plan_ready` events.

## Resuming a session

`--resume` and `--chat "<title>"` always return you to the **normal** mode, never to plan mode. If
the resumed session has an unfinished plan, YAICLI prints a hint after the resume notice:

```text
  ⚠ unfinished plan found: 20261114-004230-fs-dry-run (draft, revision 1)
  Use /plan review to continue it, or /plan list to see all plans.
```

An `in-progress` plan prints the same warning with `Use /plan resume to continue it, ...`. The hint
is informational: nothing is loaded into the tool set until you explicitly run `/plan review` or
`/plan resume`. If the plan file is missing, unreadable or bound to another session, YAICLI prints
`saved plan not found/inconsistent; starting in normal mode` to stderr and continues normally.

## Configuration

| Option | Description | Default |
| --- | --- | --- |
| `PLAN_ENABLED` | Enable plan mode (`Shift+Tab` / `/plan`; `false` hides it and `--plan` exits `2`) | `true` |
| `PLAN_MAX_STEPS` | Maximum number of steps accepted in one submitted plan | `20` |
| `PLAN_KEEP` | Finished plan files kept per project; older ones are pruned | `80` |
| `PLAN_ALLOW_READONLY_SHELL` | Expose the fixed read-only shell allowlist while planning | `true` |
| `PLAN_DIR` | Plans root directory (empty = `<config-dir>/plans`) | - |

Each option also has a `YAI_PLAN_*` environment variable; see
[Configuration](configuration.md#configuration-options-reference).

## Known boundaries (v0.24)

- **K24 verification loop and K25 checkpoints are not part of this release.** Finishing a plan does
  not run configured checks and does not create a checkpoint; those roadmap items are deferred.
- The read-only shell is **not a security boundary** (see above). It is a convenience with a fixed
  allowlist, a filtered environment and an audit trail.
- There is no automatic plan mode: simple tasks keep the fast normal path.
- Plan mode has no MCP tools, custom functions or sub-agents (v1).
- `todo_write` cannot add or remove steps; changes go through an approved plan revision.
- There is no cross-project plan library management beyond `--all` listing, and no multi-terminal
  lock: `/plan resume` only warns when the plan belongs to another session.
- Headless `--plan` produces a plan but never approves or executes it (there is no interactive
  approval in headless mode).

## See Also

- [Command Reference](commands.md) — all flags, `/plan` and `/todo`
- [Headless & Scripting](headless.md) — `--plan`, JSON output and exit codes
- [Chat Sessions & Resume](sessions.md) — `--resume` and session metadata
- [Permissions & Safety](permissions.md) — tool policy, approvals and the audit log
- [Mode Switching (Chat / Execute)](modes.md) — chat/execute modes and `/mode`
- [Configuration Guide](configuration.md) — the `PLAN_*` keys
