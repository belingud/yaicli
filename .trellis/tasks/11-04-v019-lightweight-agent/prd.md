# PRD — v0.19.0「可用的轻量 agent」

## Source

- Requirements and gap evidence: `var/lightweight-audit/09-roadmap.md` (§2 P0 table, §3 version table, §4 detailed design, §7.3 test list).
- Baseline: master `84d9a13` (v0.18.0), audit date 2026-11-02. Branch: `release/v0.19.0`.
- Positioning decision (roadmap §8): **agent-first, lightweight-first** — "A lightweight agent in your terminal".

## Problem

YAICLI today is "a lightweight CLI assistant with function calling", not a usable lightweight agent:

1. **Not capable enough**: tool output enters context verbatim (8 MB file → ≈2.1M-token tool result); history is cut by message count and severs `tool_call`↔`tool` pairs (56 % of tool-heavy sessions get orphan `role=tool` and permanent 400); depth exhaustion stops silently with exit 0.
2. **Not lightweight enough** (v0.19 keeps the *promise honest*, footprint work is v0.20): no built-in tools out of the box (`--install-functions` hidden step).
3. **Not scriptable/safe**: `Assistant:` labels and Rich boxes in non-TTY, stdout polluted by errors/warnings, no `--json/-q/-p`, `--help | head` exits 1, SIGINT semantics inconsistent, no timeout/env/workspace guardrails on shell, approval only at tool-name granularity with unfaithful prompt.

## Goal (v0.19.0)

Turn the chat-with-tools CLI into a **safe, scriptable, context-bounded, out-of-the-box agent** without new dependencies and without breaking the 30+ provider compatibility layer.

## In scope (roadmap P0)

| ID | Deliverable |
| --- | --- |
| K01 | Builtin functions are loaded directly from the package (12 tools available on first run, 0 manual steps); user copies under `FUNCTIONS_DIR` override builtins; `--install-functions` becomes "export editable copy"; `--list-functions` shows source; manifest with version+sha256 warns about stale copies. |
| K15 | One broken function file can not brick all tools (per-file try/except + warning). |
| K02 | Context economy: per-tool output truncation (head/tail + marker, full text spilled to disk), token estimation + budget, group-aligned history trimming (assistant tool_calls and its tool results stay together), context-length 400 self-heal (trim + retry once), `/context` and `/compact` REPL commands. |
| K03 | Shell guardrails: `timeout` (default 120 s, clamp), bounded `cwd`, process-group kill on timeout/interrupt, filtered env (`TOOL_ENV_INHERIT` opt-in), output cap, shlex-based danger classification (replaces 3-substring blacklist so `git add` works). |
| K04 | Headless/scripting contract: `-p/--print`, `--output-format {text,json,stream-json}`, `--quiet`, `--max-turns`, `--yes`, `--allowed-tools`, `--cwd`, `--fail-on-tool-denied`; stdout = result/events only, decorations/errors → stderr; non-TTY disables Live/banner; JSON/NDJSON schema; EPIPE neutralized (`--help \| head` not exit 1); SIGINT = 130 for one-shot, REPL prompt Ctrl-C clears line and does not exit; `--shell` non-TTY prints command without executing; exit codes 0/1/2/3/130/141. |
| K05 | Errors/reliability: `yaicli/errors.py` classification (auth/rate_limit/context_length/network/timeout/provider/tool), `ProviderError(kind=...)`, bounded retry with backoff only for retryable failures (429/5xx/connection/timeout, honors Retry-After), no retry on 4xx auth/bad-request, uniform `TIMEOUT`, stream breakage reported clearly, depth exhaustion → `finish_reason=depth_limit` + message + non-zero one-shot exit, cohere/ollama no longer swallow API errors as assistant text. |
| K06 | Permissions MVP: risk class per tool (read/write/network/exec), faithful approval prompt (normalized/parsed arguments, decoded shell command + dangerous-flag summary, fs diff/overwrite summary), `tool_permissions.json` v2 (backward compatible rules: `{tool, argv_prefix}` for shell, `{tool, path_glob}` for writes), headless `--yes` read-only auto-approve, `--allowed-tools`, structured deny result, `tool_audit.jsonl`, `/permissions` list/revoke. |
| K07 | Docs & positioning: first line "A lightweight agent in your terminal" (README / docs index / PyPI description), 3-step quick start, new pages Headless & scripting / Permissions / Context & limits / Upgrade, quantified lightweight table (from audit §04 with measurement caveat), providers moved to Compatibility section, `mkdocs build --strict` passes. |
| K21 | Runtime robustness: `--version` fast path (new `_faststart.py`, zero imports of config/role → zero writes; measured ~38 ms prototype), lazy/low-side-effect imports for `--help/--template`, OSError-tolerant config/role/chat state (read-only HOME runs instead of traceback), config dir resolution `YAI_CONFIG_DIR` > `XDG_CONFIG_HOME/yaicli` > `%APPDATA%/yaicli` > `~/.config/yaicli`, `HOME=""` no `/.config`, config.ini 0600 + dir 0700, `python -m yaicli` works. |

## Out of scope (v0.20/v0.21)

- K08 full startup work (one-shot ≤1.2 s target, plain-click rewrite, lite transport), K09 dependency/extras slimming, K10 full policy v2, K11 workspace/backup/undo for writes, K12 AGENTS.md auto-load, K13 session isolation, K14 multi-provider tool-call parity, K16–K20 (MCP hardening, usage/cost, REPL polish, schema narrowing, secret redaction).
- No new runtime dependencies. New helpers stay stdlib. Provider compatibility must not regress.
- Do not publish/tag PyPI; do not hand-edit generated CHANGELOG sections.

## Acceptance criteria (v0.19)

1. Fresh HOME (no `functions/` dir) → tool call available and executed with 0 manual steps; `--list-functions` shows 12 builtin tools; no `--install-functions` needed.
2. 8 MB tool output truncated to ≤32 KB before entering messages; next request payload keeps under budget; 500 simulated tool-heavy sessions → 0 orphan `role=tool` messages after trimming; simulated context-length 400 self-heals and retries successfully.
3. Shell: `sleep 10` killed on timeout incl. children; env exposes no `YAI_API_KEY`; 1 MB output capped; dangerous `rm -r -f /tmp/x` requires second confirmation / denied non-interactively; `git add` not falsely blocked.
4. `ai -p "..." --output-format json | jq .content` works; stdout contains no `Assistant:`/box drawing/warnings; `ai --help | head -1` exits 0/141; SIGINT during one-shot exits 130; `--shell` non-TTY prints command and does not execute; REPL prompt Ctrl-C does not exit.
5. Error handling: mock 429 → retried then success; mock 401 → no retry, actionable message, exit 1; depth exhaustion → one-shot exit ≠ 0 with message; cohere/ollama API error surfaces as error, not assistant text.
6. Permissions: approving `execute_shell_command` does not let a rule-violating `rm -x` through; `--yes` headless auto-runs read tools, still denies write/exec; audit log records decisions; prompt shows the same normalized arguments that are executed (including `\u003b`/duplicate-key cases).
7. Docs: `mkdocs build --strict` passes; README/docs index first screen is agent + 3-step quick start; new Headless/Permissions/Context/Upgrade pages exist and are in `mkdocs.yml` nav.
8. Runtime: read-only HOME runs (no raw traceback) for `--version` and `--help`; cold HOME `--version` performs zero writes; XDG config dir works; new config.ini 0600; `python -m yaicli --version` works.
9. Quality gate: existing 1195 tests stay green (the one baseline exception is the sandbox-only `~/.yaicli_history` write in `tests/test_run_smoke.py`, which must become environment-safe); new tests from roadmap §7.3 added; `ruff check yaicli tests` clean; `mkdocs build --strict` clean.

## Constraints

- Python 3.10+; line length 120; F-only ruff rules; isort/black profile.
- New state files respect `YAI_CONFIG_DIR`/XDG; writes best-effort and mode 0600/0700 where secrets are involved.
- Builtin function templates remain standalone modules (stdlib/pydantic/`yaicli.function_schema` imports only); the v0.19 danger classification lives in `yaicli/tools/risk.py` and is enforced by the approval gate, not inside the standalone function file.
- Provider wire formats unchanged; tool messages must stay pairwise valid for OpenAI/Anthropic/Gemini/Ollama.
