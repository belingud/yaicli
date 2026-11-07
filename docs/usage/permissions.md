# Permissions & Safety

An agent runs commands and writes files on your machine, so every tool call is gated. This page
explains what YAICLI asks, how decisions are persisted, how to audit them, and how to run
non-interactively without losing control.

## The default: confirm every tool call

`TOOL_CONFIRM=true` is the default. Before a tool runs, YAICLI shows a faithful preview of what
will actually execute and asks:

```
╭─ Confirm tool call ────────────────────────╮
│ execute_shell_command                      │
│ risk: exec                                 │
│ command: du -sh .                          │
│ dangerous: no                              │
╰────────────────────────────────────────────╯
Execute tool? [y]once, [a]session, [A]always, [n]o:
```

| Key | Meaning |
| --- | --- |
| `y` | Allow this call only |
| `a` | Allow this tool for the rest of the session |
| `A` | Always allow — written to `tool_permissions.json` |
| `n` | Deny — the model receives a structured refusal and can adapt |

Pressing Ctrl+C or sending EOF at the prompt is treated as a denial.

The preview shows the **normalized arguments** that will be executed, not the raw JSON from the
model: JSON is repaired and validated first, shell commands are decoded and summarized with their
risky flags, file edits show a diff excerpt, and file writes show the target path and whether the
file will be created or overwritten. If the preview and the execution ever disagree, that is a bug.

## Risk levels

Every tool has a risk class. The class decides what `--yes`, rules and `TOOL_POLICY` may do with it.

| Risk | Built-in tools | Notes |
| --- | --- | --- |
| `read` | `fs_get_filesystem_info`, `fs_list_directory`, `fs_read_file`, `fs_read_image`, `fs_search_files` | Read-only local access; the only class auto-approved by `--yes` |
| `write` | `fs_write_file`, `fs_edit_file`, `fs_file_operations` | Change files on disk |
| `network` | `fetch_webpage`, `web_search`, `get_weather` | Outbound requests |
| `exec` | `execute_shell_command` | Runs arbitrary shell commands |

MCP and custom tools default to `exec` because YAICLI cannot inspect what they do.

## Permission modes: `TOOL_POLICY`

`TOOL_POLICY` is a session-wide ceiling/floor for the tool gate. Like every setting it is layered:
`YAI_TOOL_POLICY` (environment) > `TOOL_POLICY` in `config.ini` > default `standard`. Values are
case- and whitespace-insensitive.

| Mode | Read / network tools | Write / exec tools | Typical use |
| --- | --- | --- | --- |
| `standard` (default) | Normal flow: rules → `--allowed-tools` → `--yes` → prompt / deny | Same normal flow | Everyday interactive and scripted use; behaves exactly like v0.19/v0.20 |
| `readonly` | **Auto-allowed without a prompt**, interactive or not | **Always denied** — approvals, session grants, `--allowed-tools`, `--yes` and `TOOL_CONFIRM=false` cannot override it | Untrusted tasks, exploration, CI steps that should only read |
| `trusted` | Auto-allowed without a prompt | **Auto-allowed without a prompt** for non-dangerous writes and shell commands | Fully trusted automation where prompts are pointless |

Unknown tools and MCP tools count as `exec` risk, so `readonly` denies them and `trusted`
auto-approves them.

### Precedence: danger classification comes first

The mode never relaxes a dangerous shell command. Danger classification is evaluated **before** the
mode, in every mode:

| Situation | Result in `standard`, `readonly` and `trusted` |
| --- | --- |
| Interactive, `TOOL_CONFIRM=true` | Explicit confirmation prompt — only `y` runs it |
| Interactive, `TOOL_CONFIRM=false` | Denied (there is no prompt to confirm with) |
| Non-interactive (pipe/CI) | Denied |

So `readonly` does not turn `rm -r -f …` into an auto-deny with a different reason: an interactive
confirmation can still run it, exactly as in `standard`. Conversely, `trusted` never runs a
dangerous command silently.

### Setting the mode

```ini
# config.ini
[core]
TOOL_POLICY=readonly
```

```bash
# Environment variable (wins over config.ini)
export YAI_TOOL_POLICY=readonly
ai "read the test failures and explain them"

# One-off for a single command
YAI_TOOL_POLICY=trusted ai -p "update the changelog from the git log"
```

`ai --template` prints the current template, which includes `TOOL_POLICY=standard` (the default).
An existing `config.ini` that predates v0.21 does **not** need editing: a missing `TOOL_POLICY`
means `standard` (the previous behaviour) and the line is not materialised into existing files —
add it only when you want a different mode.

An invalid value falls back to `standard` with one warning on stderr (once per session, not per
tool call). The effective mode is shown by `ai --verbose` and recorded in every audit-log line.

### How the modes interact with approvals

- `standard` keeps the v0.19/v0.20 flow: persistent rules and session approvals skip the prompt,
  `--allowed-tools` grants a tool for the run, `--yes` auto-approves `read`-risk tools only, and
  non-interactive runs deny whatever is not granted.
- `readonly` is a hard ceiling: a persisted rule, an `A` (always allow) answer,
  `--allowed-tools`, `--yes` or `TOOL_CONFIRM=false` cannot make a `write`/`exec` call run. The
  model receives an actionable denial that names `TOOL_POLICY=readonly` and says to switch to
  `standard`.
- `trusted` is a floor: prompting is skipped for every non-dangerous tool, so approval rules are
  simply unnecessary. It does not bypass the workspace write guard — files are still confined and
  backed up (see [Workspace Safety](workspace-safety.md)).

Denied calls return a structured `{"error": "tool_denied", "reason": ...}` result to the model and
are recorded in the audit log with `source: "policy"`.

## Danger classification for shell commands

Shell commands are analysed with `shlex` (argv- and flag-based, not string matching) and can be
flagged as dangerous: recursive/forced deletion, filesystem formatting, raw device writes,
shutdown/reboot, recursive permission changes on `/`, `find … -delete`, piping a download straight
into a shell, fork bombs, and similar. Safe commands such as `git add`, `git status`, `ls -la` are
not flagged.

- Interactively, a dangerous command needs an explicit confirmation even if the tool or a rule
  already allows `execute_shell_command`, and even in `TOOL_POLICY=trusted`.
- Non-interactively, a dangerous command is always denied, even with `--yes`, a matching rule or
  `TOOL_POLICY=trusted`.
- With `TOOL_CONFIRM=false` there is no prompt to confirm with, so a dangerous command is denied
  as well (in every mode).

Additional shell guardrails apply automatically: a timeout (`TOOL_TIMEOUT`, default 120 s), process
group kill on timeout/interrupt, a filtered environment (`YAI_API_KEY` and other secrets are not
passed to commands; restore the old behaviour with `TOOL_ENV_INHERIT=true`), and a bounded working
directory (`WORKSPACE_ROOT` / `--cwd`).

## Persistent allowlist: `tool_permissions.json`

`A` (always allow) writes the permissions file in the config directory
(`~/.config/yaicli/tool_permissions.json` by default). `--allowed-tools` is a per-run policy and is
never written to it. The v2 format is:

```json
{
  "version": 2,
  "always_allow": ["fs_read_file", "web_search"],
  "rules": [
    {"tool": "execute_shell_command", "argv_prefix": ["git", "status"]},
    {"tool": "execute_shell_command", "argv_prefix": ["pytest"]},
    {"tool": "fs_write_file", "path_glob": "src/**"}
  ]
}
```

| Entry | Meaning |
| --- | --- |
| string in `always_allow` | Allow that tool for every call (danger classification still applies) |
| `{"tool": ..., "argv_prefix": [...]}` | For shell commands: allow when the parsed argv starts with the given prefix |
| `{"tool": ..., "path_glob": ...}` | For file writes: allow when every path-like argument of the call (`file_path`, `path`, `destination`, ...) matches the glob (`fnmatch`-style, relative to the workspace) |

The file is backward compatible: an old-style `{"always_allow": ["execute_shell_command"]}` keeps
working. Rules are additive; a call is allowed when the tool is listed, or any rule for that tool
matches the arguments. An `argv_prefix` rule only covers a single simple command (a pipeline,
redirect or `;`/`&&` chain still asks), and a `path_glob` rule only applies when every path
argument of the call matches. A denied call returns a structured result to the model
(`{"error": "tool_denied", "reason": ...}`) so it can choose another approach.

You can edit the file by hand; YAICLI reads it on the next run. The file is created with mode
`0600` and lives next to the config file, which is created `0600` as well.

### Managing rules from the REPL

| Command | Description |
| --- | --- |
| `/permissions` | List session approvals, the persistent allowlist and the numbered rules |
| `/permissions revoke <tool-or-index>` | Remove a persistent permission (the tool then asks again) |

The index is the rule number printed by `/permissions`; a tool name removes its `always_allow`
entry, every rule for that tool, and its session approval. `remove` is accepted as an alias of
`revoke`. Note that session approvals (`a`) are kept in memory and disappear when YAICLI exits;
only `A` results persist.

## Audit log

With `TOOL_AUDIT=true` (default), every tool decision is appended as one JSON line to
`tool_audit.jsonl` in the config directory:

```json
{"ts": "2026-11-07T14:34:56Z", "tool": "execute_shell_command", "risk": "exec", "policy": "standard", "decision": "denied", "source": "non_interactive", "args_summary": "du -sh .", "duration_ms": 0, "reason": "Dangerous shell command refused in a non-interactive session; ..."}
```

| Field | Meaning |
| --- | --- |
| `ts` | UTC timestamp |
| `tool` | Tool name |
| `risk` | Risk class of the tool |
| `policy` | Effective `TOOL_POLICY` mode (`readonly` / `standard` / `trusted`) for that decision |
| `decision` | `allowed` / `denied` / `error` |
| `source` | Why: `prompt` (you confirmed), `session`, `persist`, `rule`, `allowlist` (`--allowed-tools`), `yes`, `disabled` (`TOOL_CONFIRM=false`), `non_interactive`, or `policy` (decided by `TOOL_POLICY`) |
| `args_summary` | Sanitized, truncated argument summary (shell commands are shown decoded; secrets such as API keys are redacted) |
| `duration_ms` | Tool execution time (`0` for a denied call) |
| `reason` | Present for denials/errors: why the call was refused or failed (redacted and truncated to 300 characters) |

Set `TOOL_AUDIT=false` to disable, or point the log elsewhere by changing the config directory.
The audit log records decisions, not full command output.

## Headless / non-interactive runs

When there is no TTY (piped stdin/stdout, CI), YAICLI cannot ask, so unapproved tools are denied by
default. The flags that change this are:

| Flag | Effect |
| --- | --- |
| `--yes` | Auto-approve `read`-level tools only. With `--shell` in a non-interactive run it also means "execute the generated command" |
| `--allowed-tools "fs_*,execute_shell_command"` | Per-run allowlist by name or glob (`*` wildcards allowed), for this run only (not persisted) |
| `--fail-on-tool-denied` | Exit `3` when a tool was denied, instead of letting the model continue |
| `TOOL_CONFIRM=false` | Disable confirmation entirely; danger-classified shell commands are still refused |

See [Headless & Scripting](headless.md) for the full scripting contract.

> **`TOOL_POLICY=readonly` is the safe default for read-only automation.** It auto-allows
> read/network tools (including `fs_read_file`, `web_search`) and denies write/exec calls even if a
> flag or rule would otherwise grant them — no per-tool grants needed. Set it through
> `YAI_TOOL_POLICY=readonly` in the environment or `TOOL_POLICY=readonly` in `config.ini`.
> Tool calls that a mode does allow are still confined to the workspace and backed up before they
> change files (see [Workspace Safety](workspace-safety.md)).

> **Prefer narrow grants.** Granting `execute_shell_command` does not make every command safe:
> individual commands are still danger-classified, but a non-malicious-looking command can still do
> damage. Rules with an `argv_prefix` are safer than a bare tool name.

## Security notes

- **API keys**: `config.ini` may contain `API_KEY` in plaintext. The file is created with mode
  `0600`; prefer `YAI_API_KEY` (environment) on shared machines.
- **Workspace**: built-in filesystem writes and shell `cwd` are confined to `WORKSPACE_ROOT`
  (default: the directory `ai` was started in; `--cwd` overrides it). Before a write tool changes
  an existing file it is backed up to `.yaicli-backups/`, and protected paths such as `.git/` and
  `.env*` are refused. See [Workspace Safety](workspace-safety.md) for the write guard, backups
  and recovery.
- **Environment**: shell commands receive a filtered environment by default. `TOOL_ENV_INHERIT=true`
  restores the old behaviour — only do that if you trust every command the model may run.
- **Read-only / container environments**: state writes are best-effort, so read-only commands such
  as `--version` and `--help` work without a writable HOME.

## See Also

- [Workspace Safety](workspace-safety.md)
- [Headless & Scripting](headless.md)
- [Context & Limits](context-limits.md)
- [Command Reference](commands.md)
- [Configuration](configuration.md)
