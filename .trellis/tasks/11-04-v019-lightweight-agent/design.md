# Design — v0.19.0「可用的轻量 agent」

## 1. Module map (new / changed)

### New modules (single responsibility, stdlib only)

| Module | Responsibility | Owner |
| --- | --- | --- |
| `yaicli/errors.py` | `ErrorKind` (StrEnum incl. auth/rate_limit/context_length/network/timeout/provider/tool/bad_request/depth_limit/interrupted), `AgentError(YaicliError)` with `kind`, `status_code`, `retryable`, `user_message`, `classify_exception(exc) -> AgentError`, `is_retryable(err)`, `retry_after_seconds(err)`, `backoff_delay(attempt, base, retry_after)`, exit-code constants `EXIT_OK=0, EXIT_ERROR=1, EXIT_USAGE=2, EXIT_TOOL_DENIED=3, EXIT_SIGINT=130, EXIT_EPIPE=141`. | Lead (skeleton) → `error-surfaces` |
| `yaicli/tokens.py` | Heuristic token estimator (`estimate_tokens`, `estimate_message_tokens`, `estimate_messages_tokens`), model context-window table + `resolve_context_budget(config, model)`, turn-group splitter + `trim_messages_to_budget(messages, budget) -> TrimResult(removed, tokens_before, tokens_after)`. | `agent-loop` |
| `yaicli/tools/risk.py` | `RiskLevel` (read/write/network/exec), builtin tool→risk map, `get_tool_risk(name)`, `classify_shell_command(command) -> ShellRisk(level, dangerous, reasons)`, `is_dangerous_shell(command) -> (bool, reasons)`. shlex/argv based (no substring blacklist), `git add` must pass. | `shell-guard` |
| `yaicli/tools/limits.py` | `truncate_tool_output(text, tool_name, max_chars=None) -> str` head/tail + marker, full text spill to `TOOL_OUTPUT_DIR`, per-tool cap map. Used by `execute_tool_call` and shell tool. | `agent-loop` |
| `yaicli/_faststart.py` | Ultra-thin console entry: version fast path (`-v/--version` → `importlib.metadata.version("yaicli")`, no config/role import, zero writes), `python -m yaicli` dispatch, BrokenPipeError → quiet exit. | `runtime` |
| `yaicli/__main__.py` | `from ._faststart import main; main()`. | `runtime` |
| `yaicli/output.py` | Headless emitters: `OutputFormat` enum, `build_result_payload(...)`, `write_json`, `EventEmitter` (NDJSON: turn_start/text_delta/tool_call/tool_result/usage/done), final newline discipline. stdout = result/events only. | `headless` (may live in cli.py if smaller) |

### Changed modules

| Module | Change | Owner |
| --- | --- | --- |
| `yaicli/const.py` | Config/state dir resolution (`YAI_CONFIG_DIR` > `XDG_CONFIG_HOME/yaicli` > `%APPDATA%/yaicli` > `~/.config/yaicli`; empty/absent HOME fallback to temp), `HOME=""` never yields `/.config`; `TOOL_OUTPUT_DIR`, `TOOL_AUDIT_PATH`; all new config keys + `DEFAULT_CONFIG_INI`. | Lead (pre-wave) |
| `yaicli/console.py` | `get_error_console()` stderr console; `YaiConsole.on_broken_pipe` neutralized (no exit-1 on EPIPE); keep `safe_text`/`untrusted_text`. | Lead (pre-wave) |
| `yaicli/exceptions.py` | `ProviderError(message, kind=None, status_code=None, retryable=None)`; keep subclasses. | Lead (pre-wave) |
| `yaicli/config.py` | No import-time mkdir/write when file absent (parse template in memory); on-demand `ensure_config_file()`; all writes OSError-tolerant (warn once to stderr, continue with defaults); new config.ini mode 0600, dir 0700. | `runtime` |
| `yaicli/role.py` | No import-time role-file writes (defaults in memory); lazy/best-effort persist on create/delete; OSError tolerated; `role_mgr` import safe on read-only HOME. | `runtime` |
| `yaicli/chat.py` | `FileChatManager` creates dir lazily/best-effort; import-time `chat_mgr` safe. | `runtime` |
| `yaicli/utils.py` | Keep helpers; no behavior change required except if lazy import helps K21 (optional). | `runtime` |
| `pyproject.toml` | Console scripts → `yaicli._faststart:main`; version bump at release step (not before). | Lead + `runtime` |
| `yaicli/tools/function.py` | Builtin direct-load precedence: package `yaicli/functions/buildin/*.py` first, then `FUNCTIONS_DIR/*.py` override by function name; per-file try/except (K15); stale-copy manifest check (warn only); `Function.risk` attribute via `tools.risk`. | `fn-loader` |
| `yaicli/functions/__init__.py` | `--install-functions` = export editable copies (manifest version+sha256), `--reinstall-functions` = overwrite stale copies, `--list-functions` shows source (builtin/user) + stale warning. | `fn-loader` |
| `yaicli/functions/buildin/execute_shell_command.py` | timeout/cwd/env filtering/output cap/process-group kill; no substring blacklist (risk gate handles danger). | `shell-guard` |
| `yaicli/entry.py` | New headless options (`-p/--print`, `--output-format`, `-q/--quiet`, `--max-turns`, `-y/--yes`, `--allowed-tools`, `--cwd`, `--fail-on-tool-denied`); stdout/stderr split; non-TTY disables banner/Live; error/exit-code mapping via `CLI.exit_code`; SIGINT 130; `--shell` non-TTY behavior. | `headless` |
| `yaicli/cli.py` | `interactive` flag (skip PromptSession/banner when non-TTY or -p); headless output wiring; `exit_code`/`interrupted`/`depth_limit_reached`/`tool_denied` state; REPL Ctrl-C semantics; context budget + trim hookup; `/context` `/compact` `/permissions` route. | `headless` then `agent-loop`/`permissions` |
| `yaicli/printer.py` | Faithful confirmation preview (normalized JSON / decoded shell / fs diff / write summary), non-TTY: no Live, plain text; tool result rendering respects truncation; headless quiet mode. | `headless` then `permissions` |
| `yaicli/llms/client.py` | Budget enforcement before provider call, context-length self-heal, retry wrapper (retryable kinds only), depth-limit finish + flag, tool gate hook (risk/allowlist/danger), structured deny results, tool result truncation already applied in `execute_tool_call`. | `agent-loop` then `permissions` gate |
| `yaicli/llms/providers/*.py` | `ProviderError(kind=...)` / `classify_exception` wrapping where missing; cohere/ollama stop swallowing API errors as assistant text; ChatGLM honors `TIMEOUT`; stream breakage explicit. | `error-surfaces` |
| `yaicli/cmd_handler.py` | `/context`, `/compact [keep_rounds]`, `/permissions [list|revoke ...]` registration + help text. | `agent-loop` (`/context`, `/compact`), `permissions` (`/permissions`) |
| `tests/*` | New suites: `test_context_budget.py`, `test_shell_tool.py`, `test_headless_contract.py`, `test_errors.py`, `test_permissions.py`, `test_runtime_bootstrap.py`, `test_function_loading.py` (extend), docs checks; update existing tests only where behavior intentionally changed. | each owner |

## 2. Key contracts

### 2.1 Exit codes (single source of truth: `errors.py`)

`0` success · `1` handled error · `2` usage/argument error · `3` tool denied with `--fail-on-tool-denied` · `130` SIGINT · `141` EPIPE (also acceptable: quiet `0` for `| head`). `CLI.exit_code` is set by CLI/client; `entry.py` raises `typer.Exit(code=cli.exit_code)` after a non-chat run.

### 2.2 Headless JSON

```json
{"content": "...", "tool_calls": [{"name": "...", "arguments": {...}, "result": "..."}],
 "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "model": "...", "provider": "...",
 "error": null, "exit_code": 0}
```
`stream-json` = one JSON object per line, kinds: `turn_start`, `text_delta`, `tool_call`, `tool_result`, `usage`, `done`. Only these go to stdout; all progress/warnings/errors go to stderr.

### 2.3 Tool output truncation

`execute_tool_call` returns model-facing text truncated per tool (shell 32 KB, `fs_read_file` 64 KB, search/list 48 KB, fetch 100 KB, MCP/default 32 KB) with head+tail and marker: `...[truncated N chars; full output saved to <path>; use fs_read_file with offset/limit to read more]...`. Full text is spilled to `TOOL_OUTPUT_DIR`; spill failure degrades to plain truncation.

### 2.4 History trimming (invariant)

A **turn group** = one `user` message + following `assistant`/`tool` messages until the next `user` message. Trimming only drops whole groups; an `assistant` message carrying `tool_calls` is never separated from its `tool` results (0 orphan `role=tool`). Leading system/context messages are preserved. Budget = `CONTEXT_BUDGET_TOKENS` if > 0, else 70 % of the model window (table in `tokens.py`, default 128 k). Trim emits one stderr notice. Context-length 400 → drop one extra group and retry once → still failing = actionable error suggesting `/clear`.

### 2.5 Permissions v2 file

```json
{"version": 2,
 "always_allow": ["fs_read_file"],
 "rules": [{"tool": "execute_shell_command", "argv_prefix": ["git", "status"]},
           {"tool": "fs_write_file", "path_glob": "src/**"}]}
```
Backward compatible: bare strings in `always_allow` keep old semantics; `is_allowed(name, arguments)` checks session allow + plain names + matching rules. Audit `tool_audit.jsonl`: `{ts, tool, risk, decision, args_summary, duration_ms}` (args sanitized/truncated). Dangerous shell command always requires explicit confirmation even if tool/rule allowed; non-interactive = deny unless `--yes` (read-only) or `--allowed-tools` matches, danger still denied when non-interactive.

### 2.6 Builtin function loading precedence

1. Load `yaicli/functions/buildin/*.py` (importlib, unique module names).
2. Load `FUNCTIONS_DIR/*.py`; a user function whose schema name equals a builtin replaces it.
3. Broken file → warning to stderr, skip (other tools keep working).
4. `functions_manifest.json` (in config dir) stores version + sha256 per builtin; if a user copy exists and differs → one-line "stale copy" warning (`--reinstall-functions`).

### 2.7 Startup / writes

`--version` path: `_faststart.main` prints `yaicli <version>` from `importlib.metadata`; never imports `yaicli.config`/`yaicli.role`/`yaicli.cli`; zero filesystem writes. Config file creation moves from import time to first run needing persistence (`cfg.ensure_config_file()`), all state writes are best-effort with OSError → single warning + defaults.

## 3. Ownership / write scopes (advisory, shared worktree)

| Wave | Package | Files (write scope) |
| --- | --- | --- |
| W0 Lead | foundation | `yaicli/const.py`, `yaicli/errors.py`, `yaicli/console.py`, `yaicli/exceptions.py`, `pyproject.toml` (only if needed), task artifacts |
| W1 | K01+K15 `fn-loader` | `yaicli/tools/function.py`, `yaicli/functions/__init__.py`, `tests/tools/test_function_loading.py`, `tests/test_functions_init.py` |
| W1 | K03 `shell-guard` | `yaicli/functions/buildin/execute_shell_command.py`, `yaicli/tools/risk.py`, `tests/test_shell_tool.py` |
| W1 | K04 `headless` | `yaicli/entry.py`, `yaicli/cli.py`, `yaicli/printer.py`, (`yaicli/output.py`), `tests/test_headless_contract.py` + existing CLI/entry/printer tests as needed |
| W1 | K21 `runtime` | `yaicli/_faststart.py`, `yaicli/__main__.py`, `yaicli/config.py`, `yaicli/role.py`, `yaicli/chat.py`, `pyproject.toml`, `tests/test_runtime_bootstrap.py`, `tests/test_config.py`/`test_role.py`/`test_chat_manage.py` as needed |
| W1 | K07 `docs` | `README.md`, `docs/**`, `mkdocs.yml` |
| W2 | K02 `agent-loop` | `yaicli/tokens.py`, `yaicli/tools/limits.py`, `yaicli/tools/__init__.py`, `yaicli/llms/client.py`, `yaicli/cli.py` (context portions), `yaicli/cmd_handler.py` (context portions), `tests/test_context_budget.py` |
| W2 | K05 `error-surfaces` | `yaicli/errors.py`, `yaicli/llms/providers/**`, `yaicli/entry.py` (error rendering only), `tests/test_errors.py`, provider tests |
| W3 | K06 `permissions` | `yaicli/tools/approval.py`, `yaicli/printer.py` (preview), `yaicli/llms/client.py` (gate), `yaicli/entry.py` (flags), `yaicli/cmd_handler.py` (`/permissions`), `tests/test_permissions.py` |
| W4 | integration | Lead: full suite, ruff, mkdocs strict, acceptance checks, CHANGELOG/version bump, final diff review |

No teammate edits `.git`, does not run `git commit`, and does not touch files outside its scope without messaging the Lead. Conflicting need → Lead reassigns or serializes.

## 4. Compatibility & rollback

- All new behavior is opt-in by flag or config except: builtin tools now load by default (intended), tool-output truncation (intended, configurable via `TOOL_OUTPUT_MAX_CHARS`, `0` = unlimited), env filtering for shell (restore with `TOOL_ENV_INHERIT=true`), headless stdout/stderr split (TTY behavior unchanged).
- New config keys are added to `DEFAULT_CONFIG_MAP` + `DEFAULT_CONFIG_INI` with safe defaults; old config.ini files keep working (missing keys fall back to defaults).
- Old `tool_permissions.json` with bare-string allowlist stays valid.
- Rollback: branch `release/v0.19.0` is isolated; commits grouped per package so a single `git revert` of a package commit restores v0.18 behavior.
