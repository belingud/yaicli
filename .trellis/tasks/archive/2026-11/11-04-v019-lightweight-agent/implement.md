# Implement — v0.19.0「可用的轻量 agent」

## Status legend

`[ ]` pending · `[~]` in progress · `[x]` done

## W0 — Foundation (Lead)

- [ ] Branch `release/v0.19.0`; Trellis task active; shared task board created.
- [ ] `yaicli/const.py`: config/state dir resolution (`YAI_CONFIG_DIR`, XDG, APPDATA, `~/.config`; empty HOME → temp), `HOME=""` never `/.config`; `TOOL_OUTPUT_DIR`, `TOOL_AUDIT_PATH`; new config keys: `TOOL_OUTPUT_MAX_CHARS`, `TOOL_OUTPUT_DIR`, `CONTEXT_BUDGET_TOKENS`, `TOOL_TIMEOUT`, `TOOL_ENV_INHERIT`, `WORKSPACE_ROOT`, `RETRY_ENABLED`, `RETRY_MAX`, `RETRY_BASE_DELAY`, `EXIT_ON_DEPTH_LIMIT`, `TOOL_AUDIT`; `DEFAULT_CONFIG_INI` sync.
- [ ] `yaicli/errors.py`: `ErrorKind`, `AgentError`, `classify_exception`, `is_retryable`, `retry_after_seconds`, `backoff_delay`, exit-code constants.
- [ ] `yaicli/console.py`: `get_error_console()` + EPIPE-safe `on_broken_pipe`.
- [ ] `yaicli/exceptions.py`: `ProviderError(kind, status_code, retryable)`.
- [ ] Foundation smoke: `.venv/bin/python -m pytest tests/test_config.py tests/test_entry.py -q`.

## W1 — Parallel (5 teammates, disjoint write scopes)

### K01+K15 `fn-loader`
- [ ] `tools/function.py`: builtin direct-load (package `functions/buildin/*.py`), user override, per-file try/except, `Function.risk`, manifest stale-copy check.
- [ ] `functions/__init__.py`: install=export copy, reinstall overwrite, list shows builtin/user source; manifest version+sha256.
- [ ] Tests: fresh-HOME 12 builtins, user override wins, broken file skipped, stale warning.
- [ ] Acceptance read-back: `--list-functions` on fresh HOME.

### K03 `shell-guard`
- [ ] `tools/risk.py`: risk levels + builtin map + shlex/argv danger classifier (`git add` passes; `rm -r -f`, `mkfs`, `dd of=/dev/*`, `shutdown/reboot`, `chmod -R /`, `find -delete`, `curl|sh` flagged).
- [ ] `functions/buildin/execute_shell_command.py`: timeout/cwd/env allowlist/output cap/process-group kill (exit 124).
- [ ] `tests/test_shell_tool.py`: timeout kills child, env leak blocked, 1 MB capped, cwd escape rejected.
- [ ] Interface to `permissions`: `get_tool_risk`, `classify_shell_command`.

### K04 `headless`
- [ ] `entry.py`: `-p/--print`, `--output-format {text,json,stream-json}`, `-q/--quiet`, `--max-turns`, `-y/--yes`, `--allowed-tools`, `--cwd`, `--fail-on-tool-denied`; stdout/stderr split; exit-code mapping via `CLI.exit_code`; SIGINT 130; `--shell` non-TTY print-only; EPIPE-safe.
- [ ] `cli.py`/`printer.py`: interactive flag (no PromptSession/banner when non-TTY/-p), quiet/plain mode, JSON/NDJSON emission (may add `output.py`), REPL Ctrl-C clears line / Ctrl-D exits 0.
- [ ] `tests/test_headless_contract.py`: JSON via runner+subprocess, stdout cleanliness, `--help | head`, SIGINT 130, `--shell` non-TTY not executed.
- [ ] Freeze contract for later waves: `CLI.exit_code`, `CLI.interrupted`, `CLI.depth_limit_reached`, `CLI.tool_denied`, `CLI.interactive`.

### K21 `runtime`
- [ ] `_faststart.py` + `__main__.py` + pyproject console scripts; `--version` zero writes/zero config imports (~<150 ms).
- [ ] `config.py`: no import-time write when file absent (parse template in memory), `ensure_config_file()` on demand, OSError-tolerant, dir 0700 / file 0600.
- [ ] `role.py`/`chat.py`: import-safe, lazy/best-effort writes, OSError tolerated.
- [ ] `tests/test_runtime_bootstrap.py`: read-only HOME no traceback, cold HOME `--version` zero writes, XDG config dir, config 0600, `python -m yaicli --version`.
- [ ] Keep `yaicli.config.CONFIG_PATH` patch point used by `tests/conftest.py`.

### K07 `docs`
- [ ] First line agent positioning: `README.md`, `docs/index.md`, `pyproject.toml` description.
- [ ] 3-step Quick Start (install → key → `ai "用工具完成 X"`), remove `--install-functions` from onboarding.
- [ ] New pages: `docs/usage/headless.md`, `docs/usage/permissions.md`, `docs/usage/context-limits.md`, `docs/advanced/upgrade.md`; `mkdocs.yml` nav updated.
- [ ] Quantified lightweight table from `var/lightweight-audit/04-footprint.md` with macOS/DSH measurement caveat; providers to a Compatibility section.
- [ ] `mkdocs build --strict` passes (run from `.venv`; install docs deps if already present).

## W2 — Parallel (2 teammates; depends on W1)

### K02 `agent-loop` (owns `llms/client.py`, `tokens.py`, `tools/limits.py`, `tools/__init__.py`)
- [ ] `tokens.py` estimator + budget + turn-group splitter + budget trim.
- [ ] `tools/limits.py` truncation/spill; wire into `execute_tool_call` + `SHOW_FUNCTION_OUTPUT`.
- [ ] `client.py`: budget enforcement at top-level call, trim notice on stderr, context-length self-heal (trim once + retry once → actionable error), depth limit `finish_reason=depth_limit` + `depth_limit_reached`.
- [ ] `cli.py` hookup: history uses budget/group trim; `/context` + `/compact [keep_rounds]` via `cmd_handler.py`; prompt hint.
- [ ] `tests/test_context_budget.py`: 8 MB → ≤32 KB & payload ≤ budget; 500-session simulation 0 orphans; 400 self-heal; `/context` output.
- [ ] Interface consumed from `errors.py` (`classify_exception`, `is_retryable`, `backoff_delay`) — implement retry loop here (W2 owns client retry).

### K05 `error-surfaces` (owns `errors.py` helpers, `llms/providers/*`, provider tests, entry error rendering)
- [ ] `errors.py`: full classification for openai/anthropic/httpx/generic; retry-after parsing; actionable messages.
- [ ] Providers: wrap errors with kind; stop swallow in cohere/ollama (no API error as assistant text); ChatGLM honors `TIMEOUT`; stream breakage explicit; `ImportError` → provider error (optional).
- [ ] `tests/test_errors.py`: 429 retried, 401 no-retry, 400 context_length classification, depth, no-swallow per provider.
- [ ] Coordinate with `agent-loop`: retry loop lives in `client.py`; no edits there from this teammate.

## W3 — `permissions` (K06; depends on K02 + K04 + K03)

- [ ] `tools/risk.py` consumer in client gate; risk class exposed on `Function`.
- [ ] `tools/approval.py`: rules v2 (backward compatible), `is_allowed(name, arguments)`, `--yes` read-only, `--allowed-tools`, audit jsonl, `/permissions` list/revoke.
- [ ] `printer.py` faithful preview: repaired/canonical arguments, decoded shell command + danger reasons, fs_edit diff head 40, fs_write target/overwrite preview; prompt must show exactly what executes (`\u003b`/duplicate-key case).
- [ ] `client.py` gate: risk/danger/rule decisions, structured deny `{"error":"tool_denied","reason":...}`, audit entries, `tool_denied` flag + exit code 3 with `--fail-on-tool-denied`.
- [ ] `tests/test_permissions.py`: rule precedence, danger double-confirm, headless `--yes` read-only, audit log, prompt/exec argument equality.

## W4 — Integration & release prep (Lead + verifier)

- [ ] Full `.venv/bin/python -m pytest -q` green; `ruff check yaicli tests` clean; `just format` diff clean; `mkdocs build --strict` clean.
- [ ] Acceptance script vs PRD §Acceptance (subprocess/mock, no paid API).
- [ ] Update `docs/changelog`? Only via `just changelog` (git-cliff) at release; bump version with `uv run bump2version minor` when green (v0.19.0) — run only after explicit release step.
- [ ] Review final `git diff --stat`; commit per package (conventional commits); no tag/publish without user confirmation.
- [ ] Trellis: spec update if conventions changed; archive task; journal entry.

## Validation commands (shared worktree)

```bash
.venv/bin/python -m pytest -q                       # full suite (baseline: 1195 passed, 1 sandbox-only failure)
.venv/bin/python -m pytest tests/<file> -q           # focused
.venv/bin/ruff check yaicli tests
.venv/bin/ruff format --check yaicli tests
.venv/bin/isort --check-only yaicli tests
shellcheck not used; zsh/bash: ai --help | head -1; echo $?
```

Notes: run `uv` only with `UV_CACHE_DIR="$PWD/var/uv-cache"` (sandbox); prefer `.venv/bin/python` so no package rebuild/network is needed. Never write outside the workspace (HOME writes are sandbox-denied) — use `tmp_path` in tests.
