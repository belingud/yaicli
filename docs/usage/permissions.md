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

Every tool has a risk class. The class decides what `--yes` and rules may auto-approve.

| Risk | Built-in tools | Notes |
| --- | --- | --- |
| `read` | `fs_get_filesystem_info`, `fs_list_directory`, `fs_read_file`, `fs_read_image`, `fs_search_files` | Read-only local access; the only class auto-approved by `--yes` |
| `write` | `fs_write_file`, `fs_edit_file`, `fs_file_operations` | Change files on disk |
| `network` | `fetch_webpage`, `web_search`, `get_weather` | Outbound requests |
| `exec` | `execute_shell_command` | Runs arbitrary shell commands |

MCP and custom tools default to `exec` because YAICLI cannot inspect what they do.

## Danger classification for shell commands

Shell commands are analysed with `shlex` (argv- and flag-based, not string matching) and can be
flagged as dangerous: recursive/forced deletion, filesystem formatting, raw device writes,
shutdown/reboot, recursive permission changes on `/`, `find … -delete`, piping a download straight
into a shell, fork bombs, and similar. Safe commands such as `git add`, `git status`, `ls -la` are
not flagged.

- Interactively, a dangerous command needs an explicit confirmation even if the tool or a rule
  already allows `execute_shell_command`.
- Non-interactively, a dangerous command is always denied, even with `--yes` or a matching rule.
- With `TOOL_CONFIRM=false` there is no prompt to confirm with, so a dangerous command is denied
  as well.

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
{"ts": "2026-11-04T12:34:56Z", "tool": "execute_shell_command", "risk": "exec", "decision": "denied", "source": "non_interactive", "args_summary": "du -sh .", "duration_ms": 0, "reason": "Dangerous shell command refused in a non-interactive session; ..."}
```

| Field | Meaning |
| --- | --- |
| `ts` | UTC timestamp |
| `tool` | Tool name |
| `risk` | Risk class of the tool |
| `decision` | `allowed` / `denied` / `error` |
| `source` | Why: `prompt` (you confirmed), `session`, `persist`, `rule`, `allowlist` (`--allowed-tools`), `yes`, `disabled` (`TOOL_CONFIRM=false`) or `non_interactive` |
| `args_summary` | Sanitized, truncated argument summary (shell commands are shown decoded; secrets such as API keys are redacted) |
| `duration_ms` | Tool execution time (`0` for a denied call) |
| `reason` | Present for denials/errors: why the call was refused or failed |

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

> **Prefer narrow grants.** Granting `execute_shell_command` does not make every command safe:
> individual commands are still danger-classified, but a non-malicious-looking command can still do
> damage. Rules with an `argv_prefix` are safer than a bare tool name.

## Security notes

- **API keys**: `config.ini` may contain `API_KEY` in plaintext. The file is created with mode
  `0600`; prefer `YAI_API_KEY` (environment) on shared machines.
- **Workspace**: shell tools run inside `WORKSPACE_ROOT` (or `--cwd`); a `cwd` outside it is
  rejected.
- **Environment**: shell commands receive a filtered environment by default. `TOOL_ENV_INHERIT=true`
  restores the old behaviour — only do that if you trust every command the model may run.
- **Read-only / container environments**: state writes are best-effort, so read-only commands such
  as `--version` and `--help` work without a writable HOME.

## See Also

- [Headless & Scripting](headless.md)
- [Context & Limits](context-limits.md)
- [Command Reference](commands.md)
- [Configuration](configuration.md)
