# Upgrade Notes

This page explains what changes when you upgrade to **v0.24** and what (if anything) you must do.
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

## What changed in v0.24

- **`openai` and `openai-compatible` use a built-in HTTP transport by default.** Chat Completions
  requests for these two providers now go through a small httpx client instead of importing the
  `openai` Python SDK. For one-shot runs this removes the SDK import (≈0.6 s in the benchmark
  sandbox) from the startup path, so they start sooner.
  The request URL/headers/body, streaming output, tool calls, usage and error classification are
  unchanged — only the HTTP client that performs the request differs.
- **Other providers are untouched.** Every other provider keeps using its own SDK, and
  `openai-azure` plus custom provider subclasses always use the `openai` SDK even with the default
  setting.
- **`--verbose` names the active transport.** It prints `Transport: lite (httpx)` or
  `Transport: openai SDK` when the provider is constructed (in `-p`/`--json` mode the line goes to
  stderr, so stdout stays machine-readable).
- **No data or format changes.** Sessions, config files, JSON/NDJSON output and exit codes are
  unchanged; there is no migration step.

### Rolling back the transport (one line)

Output and tool behaviour are identical on both paths; only the initialisation is slower with the
SDK (≈0.6 s in the benchmark sandbox). To restore it, add one line to `config.ini` and restart `ai`:

```ini
LITE_TRANSPORT=false
```

`YAI_LITE_TRANSPORT=false` does the same for a single shell/run. See
[Transport Selection](../usage/configuration.md#transport-selection) for the exact scope and
troubleshooting.

No action is normally needed.

### New configuration keys (v0.24)

| Key | Default | Purpose |
| --- | --- | --- |
| `LITE_TRANSPORT` | `true` | `openai`/`openai-compatible`: use the built-in httpx transport (`false` = `openai` SDK); see [Transport Selection](../usage/configuration.md#transport-selection) |

## What changed in v0.23

- **Model context windows are resolved instead of guessed.** The window now comes from, highest
  priority first: your `MODEL_CONTEXT_WINDOWS` config → a limit learned from a provider "too long"
  error → provider metadata (OpenRouter `/models`, Gemini `models.get`, Ollama `/api/show`; lazy,
  2-second timeout, silent fallback) → the bundled catalog → family heuristics → an explicit 128k
  assumption with a one-time stderr warning. The old "first substring match" table is gone, so
  `gpt-4-32k`, `o1-mini` and local Ollama models get the right window.
- **The request budget no longer wastes 30% of the window.** It is now
  `min(window, max_input) - MAX_TOKENS - CONTEXT_SAFETY_TOKENS`; `CONTEXT_BUDGET_TOKENS > 0` still
  overrides it verbatim. Example: `gpt-4o` gets 125,952 input tokens instead of 89,600.
- **`/context` shows where the window came from** (`source: user|learned|metadata|catalog|heuristic|default`),
  plus the output/safety reserve, role prompt, project instructions, persistent `/add` context and the
  fixed request-overhead bucket (shown so the rows add up to the reported total). Bare `/context` no
  longer repeats the subcommand list.
- **Context-length errors are learned.** When the provider reports the real limit
  (`maximum context length is N tokens`, ...), YAICLI records it (memory + cache keyed by
  provider/base URL/model), recomputes the budget and retries once — later requests use the learned value.
- **Unknown models are no longer silent**: the first request prints one stderr notice with a
  copy-pasteable override example; `heuristic`/`catalog` values do not count as unknown.

No action is normally needed. If a model reports an unexpected window, set `MODEL_CONTEXT_WINDOWS`
(see [Configuration](../usage/configuration.md#configuration-options-reference)).

### New configuration keys (v0.23)

| Key | Default | Purpose |
| --- | --- | --- |
| `MODEL_CONTEXT_WINDOWS` | *empty* (auto) | JSON map of `model` / `provider:model` / `provider/model` → window or `{"window": N, "max_output": M}`; highest-priority override |
| `ENABLE_MODEL_METADATA` | `true` | Probe OpenRouter / Gemini / Ollama metadata for the window (lazy, silent fallback) |
| `CONTEXT_SAFETY_TOKENS` | `1024` | Headroom kept below `window - MAX_TOKENS` when deriving the request budget |
| `ENABLE_MODEL_LIMITS_CACHE` | `true` | Cache resolved windows under `<config-dir>/cache/model_limits.json` (metadata 7d, learned 30d) |

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
- **Project context on by default** — YAICLI reads `.yaicli.md` / `AGENTS.md` / `CLAUDE.md` from the
  working directory up to the nearest git root and appends them to the system prompt. Discovery and
  content are bounded (`PROJECT_CONTEXT_MAX_CHARS`, default 20000) and a truncated block prints one
  stderr warning. Disable with `ENABLE_PROJECT_CONTEXT=false` (no file reads at all). Loading is
  once per run, so restart `ai` to pick up edits. Project files are untrusted input — review them
  before running the agent in a repository. See [Project Context](../usage/project-context.md).
- **Per-project sessions + `--resume` (behaviour change)** — saved chat sessions moved from the old
  shared temp directory to `~/.yaicli/sessions/<sha256(resolved cwd)[:16]>/` (directories `0700`,
  files `0600`). Each session records `model`/`provider`/`role`/`cwd`/`created_at`/`updated_at`;
  resumed sessions print a one-line notice with that metadata. New `--resume` continues the newest
  session of the current project. `ai --chat "<title>"` now prints an explicit notice when the title
  does not exist instead of silently starting a new session. An explicit `CHAT_HISTORY_DIR` /
  `YAI_CHAT_HISTORY_DIR` override keeps the old flat layout. Existing `config.ini` files contain a
  materialised `CHAT_HISTORY_DIR=<temp path>` line: when it matches the built-in default it counts
  as unset (per-project store); if the temp path changed it keeps that flat directory — delete or
  comment the line to opt into per-project sessions. **Old sessions in the temp directory are left
  in place — there is no automatic migration**; see
  [Chat Sessions & Resume](../usage/sessions.md#migrating-from-old-sessions). The REPL history file
  is now created `0600` (legacy `0644` files are repaired on the next append/trim).
- **Parallel tool calls are kept** — providers that return several tool calls in one response are no
  longer reduced to the first one: parallel calls from Anthropic, Gemini and Ollama, and the
  single-slot streaming providers, are all executed and their results appended (the streaming
  providers also stop surfacing partial function-call arguments mid-stream). No configuration
  change.

No action is normally needed. If you script permissions, see
[Permissions & Safety](../usage/permissions.md#permission-modes-tool_policy); if the agent writes
files for you, see [Workspace Safety](../usage/workspace-safety.md); for project instructions and
sessions see [Project Context](../usage/project-context.md) and
[Chat Sessions & Resume](../usage/sessions.md).

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
| `ENABLE_PROJECT_CONTEXT` | `true` | Auto-load project instruction files into the system prompt (`false` = no project-file reads); see [Project Context](../usage/project-context.md) |
| `PROJECT_CONTEXT_MAX_CHARS` | `20000` | Max characters of project context added to the system prompt (`0` = no cap) |
| `TOOL_OUTPUT_MAX_CHARS` | `32000` | Per-tool-result character cap (`0` = unlimited) |
| `TOOL_OUTPUT_DIR` | `<tempdir>/yaicli/chats/tool-outputs` | Where full tool outputs are stored (independent of the per-project session store) |
| `CONTEXT_BUDGET_TOKENS` | `0` (derived from the model window) | Per-request input-token budget override |
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

Outside the config directory:

- `~/.yaicli/sessions/<hash>/` — saved chat sessions per project (dirs `0700`, files `0600`);
  an explicit `CHAT_HISTORY_DIR` / `YAI_CHAT_HISTORY_DIR` override keeps the old flat directory
  (see [Chat Sessions & Resume](../usage/sessions.md)).
- `<tempdir>/yaicli/chats/tool-outputs/` — spilled full tool outputs (legacy scratch dir;
  `TOOL_OUTPUT_DIR` overrides; independent of the per-project session store).
- `$XDG_STATE_HOME/yaicli/history` or `~/.yaicli_history` — REPL prompt history (mode `0600` since
  v0.21; bounded by `MAX_HISTORY`).

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
6. If old chats or `--resume` do not find a session, you are probably in a different working
   directory than the session's project store (sessions are per directory) — see
   [Chat Sessions & Resume](../usage/sessions.md#migrating-from-old-sessions).

## Rollback

To go back to the previous release:

```bash
pip install 'yaicli==0.20.0'
```

Your `config.ini` and permissions file remain readable by the old version (unknown keys are
ignored); `tool_permissions.json` stays backward compatible because v2 only adds keys. Remove
`tool_audit.jsonl` / `tool-outputs/` if you no longer need them, and note that v0.21 may have
created a `.yaicli-backups/` directory in your workspace — keep it if you want the stored backups,
delete it otherwise. Sessions saved by v0.21 in `~/.yaicli/sessions/` are not visible to v0.20 (which
uses the old flat directory); copy them if you plan to roll back permanently.

## See Also

- [Permissions & Safety](../usage/permissions.md)
- [Workspace Safety](../usage/workspace-safety.md)
- [Project Context](../usage/project-context.md)
- [Chat Sessions & Resume](../usage/sessions.md)
- [Headless & Scripting](../usage/headless.md)
- [Context & Limits](../usage/context-limits.md)
- [Configuration](../usage/configuration.md)
- [Changelog](../changelog.md)
