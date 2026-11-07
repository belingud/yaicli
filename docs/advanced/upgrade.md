# Upgrade Notes

This page explains what changes when you upgrade to **v0.21** and what (if anything) you must do.
Old config files keep working: newly added keys simply fall back to their defaults.

## Upgrade the package

```bash
# pip
pip install -U yaicli

# pipx
pipx upgrade yaicli

# uv
uv tool upgrade yaicli
```

Then verify:

```bash
ai --version
ai --list-functions     # 12 builtin tools should be listed
ai --list-providers
```

## Do I need to reinstall functions?

**Usually no.** Since v0.19 the 12 built-in tool definitions load directly from the installed
package, so a fresh install (and a fresh `HOME`) can call tools on the first run. `ai
--install-functions` is no longer part of the setup.

You only need to refresh function files if you have **exported copies** in the functions directory
(`<config-dir>/functions/`, normally `~/.config/yaicli/functions/`), for example because you ran
`ai --install-functions` before, or you edited a built-in tool:

```bash
ai --reinstall-functions    # overwrite stale built-in copies (custom names are kept)
ai --list-functions         # shows builtin/user source and warns about stale copies
```

If a user file has the same tool name as a built-in, the user file wins. If you want the new
built-in version, delete the old copy (or run `--reinstall-functions`) and restart `ai`.
YAICLI only warns about stale copies; it never silently overwrites your customisations.

## What changed in v0.21

- **Permission modes (`TOOL_POLICY`)** — a session-wide mode: `readonly`, `standard` or `trusted`
  (`TOOL_POLICY` in `config.ini`, `YAI_TOOL_POLICY` in the environment). `standard` is the default
  and keeps the previous behaviour, so **existing config files need no edit**: a missing
  `TOOL_POLICY` means `standard` and the line is not written into existing files. `readonly`
  auto-allows read/network tools and hard-denies write/exec calls (approvals, `--yes`,
  `--allowed-tools` and `TOOL_CONFIRM=false` cannot override it); `trusted` auto-runs every
  non-dangerous tool. Danger-classified shell commands keep their confirmation/denial precedence in
  every mode. Audit lines now include the effective `policy` field.
- **Workspace-confined writes (on by default)** — `fs_write_file`, `fs_edit_file` and
  `fs_file_operations` now only modify files inside `WORKSPACE_ROOT` (default: the directory `ai`
  was started in; `--cwd` sets it). Absolute paths outside the workspace now fail with an in-band
  `outside_workspace` refusal where earlier versions wrote them. To keep writing elsewhere, start
  `ai` in that directory, set `WORKSPACE_ROOT`, or pass `--cwd`.
- **Protected paths** — the guarded filesystem tools refuse `.git`/`.ssh`/`.aws`/`.gnupg` path
  components and `.env`/`.env.*`/`*.pem`/`*.key` files even inside the workspace. Edit those
  yourself.
- **Backups before every mutation** — an existing file/directory is copied to
  `<workspace>/.yaicli-backups/<UTC stamp>/<path relative to the workspace root>` (files `0600`,
  directories `0700`) before it is overwritten, edited, appended to, deleted or moved. If the
  backup cannot be written, the change is refused (fail closed). Add `.yaicli-backups/` to your
  `.gitignore`; backups are not cleaned up automatically.
- **`/undo`** — in the REPL, reverts the last guarded file change: restores overwritten/edited/
  deleted/moved files from their backup and deletes files the agent created. The stack keeps the
  last 20 mutations and is process-local, so it disappears when `ai` exits; shell-command and MCP
  side effects are not undoable.

No action is normally needed. If you script permissions, see [Permissions & Safety](../usage/permissions.md#permission-modes-tool_policy);
if the agent writes files for you, see [Workspace Safety](../usage/workspace-safety.md).

## What changed in v0.20

- **Faster startup**: the REPL shows its first prompt before the provider SDK loads (≈0.55–0.65 s in
  the sandbox vs ≈1.55 s), and `--help`/one-shot runs no longer import prompt_toolkit. No action needed.
- **Ctrl+O viewer**: the output list and header show the full tool name (`execute_shell_command`,
  `fetch_webpage`, ...) so you can tell which tool ran. No action needed.
- **Cloud provider extras**: the base install stays tools-complete, but the Anthropic Bedrock/Vertex
  SDK closure moved out of it (see the extras below).

The base install is still **tools-complete** (builtin tools and MCP work out of the box), but the
Anthropic cloud SDK closure is no longer installed by default: `pip install yaicli` keeps the normal
Anthropic API, while **Bedrock** and **Vertex** users must add one extra:

```bash
pip install -U 'yaicli[bedrock]'   # AWS Bedrock
pip install -U 'yaicli[vertex]'    # Google Vertex AI
```

`pip install 'yaicli[all]'` still includes both. If you upgrade and see an actionable
`Provider 'anthropic-bedrock' requires an optional dependency` message, install the extra above.

## What changed in v0.19

| Area | Change | Action needed |
| --- | --- | --- |
| Built-in tools | Loaded directly from the package (12 tools out of the box); `--install-functions` = export editable copies; `--list-functions` shows `builtin`/`user` source | None, unless you keep exported copies — then run `--reinstall-functions` |
| Shell tool environment | Commands receive a filtered environment by default (`YAI_API_KEY` and other secrets are not passed) | Set `TOOL_ENV_INHERIT=true` to restore the old full-environment behaviour |
| Shell tool timeout | `TOOL_TIMEOUT` (default 120 s); timed-out commands are killed with their whole process group (exit code 124 in the tool result) | Check long-running commands; raise `TOOL_TIMEOUT` if needed |
| Shell danger checks | Replaced the old 3-substring blacklist with argv/flag analysis: dangerous commands need an extra confirmation, and `git add` is no longer blocked | None |
| Tool output size | Results are truncated (`TOOL_OUTPUT_MAX_CHARS`, default 32000 chars); the full output is spilled to `TOOL_OUTPUT_DIR` | Raise the cap or set `0` to disable; the model can page spilled files back with `fs_read_file` |
| Context window | Token budget (`CONTEXT_BUDGET_TOKENS`), turn-group trimming and context-length self-heal; `/context` and `/compact` added | None; tune the budget for small-window models |
| Permissions | Risk classes, `tool_permissions.json` v2 rules (`argv_prefix`, `path_glob`), audit log (`TOOL_AUDIT`), `/permissions` command | Old `always_allow` string list stays valid; add rules for finer control |
| Headless | New flags `-p/--print`, `--output-format`, `-q/--quiet`, `--max-turns`, `-y/--yes`, `--allowed-tools`, `--cwd`, `--fail-on-tool-denied`; clean stdout/stderr split; exit codes 0/1/2/3/130/141 | Update scripts that parsed decorated output; see [Headless & Scripting](../usage/headless.md) |
| One-shot exit codes | Handled errors now exit non-zero in one-shot mode (previously 0); depth-limit exhaustion exits non-zero (`EXIT_ON_DEPTH_LIMIT`) | Add error handling to scripts that relied on exit 0 |
| Interrupts | One-shot SIGINT exits 130; REPL prompt Ctrl+C clears the line (press twice quickly to exit); Ctrl+D exits | None |
| Startup | `--version` fast path: no config/role imports, zero filesystem writes, much faster; `--help`/`--template` no longer create state files | None |
| Config & state paths | `YAI_CONFIG_DIR` / `XDG_CONFIG_HOME` (and `%APPDATA%` on Windows) are honoured; config dir 0700 / `config.ini` 0600; new files are created on demand | Move config if you want XDG locations; existing `~/.config/yaicli` keeps working |
| History file | Uses `XDG_STATE_HOME/yaicli/history` when `XDG_STATE_HOME` is set, otherwise `~/.yaicli_history` | None |
| `python -m` | `python -m yaicli --version` now works | None |

## New configuration keys

Add these to `config.ini` only if you want non-default values (see
[Configuration](../usage/configuration.md)); `ai --template` prints the full template.

| Key | Default | Purpose |
| --- | --- | --- |
| `TOOL_POLICY` | `standard` | Session-wide permission mode (`readonly`/`standard`/`trusted`); see [Permissions & Safety](../usage/permissions.md#permission-modes-tool_policy) |
| `TOOL_OUTPUT_MAX_CHARS` | `32000` | Per-tool-result character cap (`0` = unlimited) |
| `TOOL_OUTPUT_DIR` | `<chat history>/tool-outputs` | Where full tool outputs are stored |
| `CONTEXT_BUDGET_TOKENS` | `0` (70% of model window) | Per-request token budget |
| `TOOL_TIMEOUT` | `120` | Shell command timeout in seconds |
| `TOOL_ENV_INHERIT` | `false` | Pass the full parent environment to shell tools |
| `WORKSPACE_ROOT` | *empty* (current dir) | Workspace root for the shell `cwd` and guarded filesystem writes |
| `RETRY_ENABLED` | `true` | Retry retryable API failures |
| `RETRY_MAX` | `2` | Maximum retry attempts |
| `RETRY_BASE_DELAY` | `1.0` | Base backoff delay (seconds) |
| `EXIT_ON_DEPTH_LIMIT` | `true` | One-shot exits non-zero when the tool-round limit is reached |
| `TOOL_AUDIT` | `true` | Append tool decisions to `tool_audit.jsonl` |

## Where state lives now

The config directory is resolved in this order:

1. `YAI_CONFIG_DIR` (explicit override)
2. `XDG_CONFIG_HOME/yaicli`
3. `%APPDATA%/yaicli` on Windows
4. `~/.config/yaicli`

Files in the config directory:

| File / directory | Purpose |
| --- | --- |
| `config.ini` | Main configuration (created `0600`; may contain an API key) |
| `roles/` | Role definitions |
| `functions/` | User/exported tool definitions (override built-ins by tool name) |
| `functions_manifest.json` | Package version + hashes used to detect stale exported copies |
| `mcp.json` | MCP server configuration |
| `tool_permissions.json` | Persistent tool allow rules (v2) |
| `tool_audit.jsonl` | Tool decision audit log |
| `tool-outputs/` | Spilled full tool outputs (by default under the chat history dir) |

`HISTORY_FILE` is separate: `$XDG_STATE_HOME/yaicli/history` when `XDG_STATE_HOME` is set, otherwise
`~/.yaicli_history`. Chat sessions live under `CHAT_HISTORY_DIR`.

## If something behaves unexpectedly

1. Run `ai --list-functions` — stale exported copies are flagged there. Refresh with
   `ai --reinstall-functions`.
2. Run `ai --verbose "..."` and check the effective config file path and provider/model.
3. Reproduce with a clean config dir: `YAI_CONFIG_DIR=$(mktemp -d) ai "hi"`.
4. Check the new defaults: environment filtering (`TOOL_ENV_INHERIT`), output truncation
   (`TOOL_OUTPUT_MAX_CHARS`), and shell timeout (`TOOL_TIMEOUT`) are the most likely reasons an old
   workflow behaves differently.
5. If a file write is refused, check `WORKSPACE_ROOT` (`ai --verbose` prints it) and the protected-
   path rules; the model-facing error names the reason (`outside_workspace`, `protected_path`, ...).
   See [Workspace Safety](../usage/workspace-safety.md) — and remember that pre-change backups are
   in `<workspace>/.yaicli-backups/` if you need to restore something by hand.

## Rollback

To go back to the previous release:

```bash
pip install 'yaicli==0.20.0'
```

Your `config.ini` and permissions file remain readable by the old version (unknown keys are
ignored); `tool_permissions.json` stays backward compatible because v2 only adds keys. Remove
`tool_audit.jsonl` / `tool-outputs/` if you no longer need them, and note that v0.21 may have
created a `.yaicli-backups/` directory in your workspace — keep it if you want the stored backups,
delete it otherwise.

## See Also

- [Permissions & Safety](../usage/permissions.md)
- [Workspace Safety](../usage/workspace-safety.md)
- [Headless & Scripting](../usage/headless.md)
- [Context & Limits](../usage/context-limits.md)
- [Configuration](../usage/configuration.md)
- [Changelog](../changelog.md)
