# Journal - belingud (Part 1)

> AI development session journal
> Started: 2026-11-01

---



## Session 1: Bootstrap Trellis project spec
<!-- trellis-session: v=2 fp=33a64bd369a97188 -->

**Date**: 2026-11-01
**Task**: Bootstrap Trellis project spec
**Branch**: `master`

### Summary

Installed Trellis 0.6.17 for Claude Code and DeepSeek Harness (dsh), then completed 00-bootstrap-guidelines by reshaping the generated backend scaffold into py/ and repo/ spec layers grounded in the real codebase.

### Main Changes

- Installed .trellis/ workflow+scripts, .agents/skills, .dsh/ entry skills and the Claude Code surface (.claude/ hooks, agents, commands, skills, settings.json); added the managed Trellis block to CLAUDE.md.
- Reshaped .trellis/spec: deleted backend/ template, added py/ (architecture, providers, function-calling/tools, CLI/rendering, config/context, quality) and repo/ (conventions, build/CI/release).
- Recorded current defects found during spec writing (first-run PROVIDER KeyError, unused CODE_MODE, dead MAX_HISTORY/ROLE_MODIFY_WARNING, --image-only abort, context '[' sentinel, role.print_roles, fs_read_image Union debt).

### Git Commits

| Hash | Message |
|------|---------|
| `cb6abd8` | chore(trellis): install Trellis workflow and bootstrap project spec |

### Testing

- [OK] placeholder scan clean; index<->file coverage complete; relative links resolve; get_context.py --mode packages -> py, repo; independent read-only verifier PASS.

### Status

[OK] **Completed**

### Next Steps

- Commit/verify the archive+journal commits and push master when ready.


## Session 2: Fix bootstrap-known defects
<!-- trellis-session: v=2 fp=c0b9be5da42d7b20 -->

**Date**: 2026-11-01
**Task**: Fix bootstrap-known defects
**Branch**: `master`

### Summary

Fixed the seven defects recorded during the Trellis spec bootstrap: first-run config parse + YAI_PROVIDER (097b6b4), MAX_HISTORY/ROLE_MODIFY_WARNING wiring + dead print_roles removal (defdf80), structured FileReadResult context reads (8703514), image-only minimal prompt (c6df177), array-first fs_read_image schema (92a4d05), docs (37d46a7). Full suite 1055 passed + 1 environmental sandbox failure; independent verifier PASS on D1-D7. Commits 097b6b4..2011b37.

### Git Commits

| Hash | Message |
|------|---------|
| `2011b37` | chore(trellis): record fixed bootstrap defects in spec and task |

### Status

[OK] **Completed**


## Session 3: v0.19.0 lightweight agent implementation
<!-- trellis-session: v=2 fp=90f68b5a72b8c1ec -->

**Date**: 2026-11-04
**Task**: v0.19.0 lightweight agent implementation
**Branch**: `release/v0.19.0`

### Summary

Implemented all v0.19 P0 items from var/lightweight-audit/09-roadmap.md (K01, K02, K03, K04, K05, K06, K07, K21) on release/v0.19.0 with tests, docs and release-prep commits.

### Main Changes

- K01/K15: built-in tools load from the installed package out of the box (user copies override), functions_manifest.json stale-copy warning, per-file robustness, shell install/reinstall/list lifecycle
- K03: shell tool timeout/cwd/env-allowlist/output-cap/process-group-kill; tools/risk.py shlex argv danger classification replaces the substring blacklist
- K04: headless contract (-p/--print, --output-format text|json|stream-json, --json, -q, --max-turns, -y, --allowed-tools, --cwd, --fail-on-tool-denied), clean stdout/stderr split, exit codes 0/1/2/3/130/141, EPIPE/SIGINT handling, REPL Ctrl-C semantics
- K21: _faststart --version fast path (static version, zero writes, ~45ms vs ~500ms), python -m yaicli, write-free imports, ensure_config_file (0600/0700, lazy), YAI_CONFIG_DIR/XDG resolution, read-only HOME tolerance
- K02: tool-output truncation+spill, token estimator/budget, turn-group-aligned trimming (no orphan tool messages), context-length self-heal, /context and /compact, depth-limit flag
- K05: yaicli/errors.py taxonomy + retry/backoff; all 39 provider registry keys raise classified AgentError instead of swallowing API errors or returning them as assistant content
- K06: risk-aware approval gate (danger double-confirm, --yes read-only, --allowed-tools), tool_permissions.json v2 rules, faithful prompt previews, structured deny results, audit JSONL, /permissions
- K07: agent-first positioning, 3-step quick start, footprint table with caveat, new headless/permissions/context-limits/upgrade pages, mkdocs nav sync

### Git Commits

| Hash | Message |
|------|---------|
| `dbd0a0b` | docs: reposition YAICLI as a lightweight agent and document v0.19 |
| `77bd086` | feat(functions): load built-in tools out of the box and harden shell execution |
| `978eec5` | feat(cli): headless scripting contract and side-effect-free startup |
| `3b8e27d` | feat(agent): context economy, retries and classified provider errors |
| `c83c87c` | feat(permissions): risk-aware confirmation, rule-based allowlist and audit log |
| `e9eb123` | chore(release): v0.19.0 |
| `b928de8` | chore(trellis): record v0.19 lightweight-agent task and refresh specs |
| `a5b7d84` | chore(task): archive 11-04-v019-lightweight-agent |

### Testing

- [OK] full suite: 1729 passed (baseline 1195)
- [OK] new suites: test_context_budget 51, test_errors 210, test_headless_contract 36, test_permissions 53, test_runtime_bootstrap 20, test_shell_tool 94
- [OK] ruff check yaicli tests clean; mkdocs build --strict passes
- [OK] Lead acceptance probe matrix: 28/28 checks (fast version zero writes, list-functions 12 builtins, JSON headless contract, read-only HOME, config 0600/0700, shell guardrails, 8MB truncation+spill, permissions v1/v2)

### Status

[OK] **Completed**

### Next Steps

- v0.20: startup/footprint work K08-K15 (one-shot <=1.2s, dependency extras split, permission policy v2, workspace writes/undo, AGENTS.md, session isolation), then publish/tag v0.19.0 via the existing release flow


## Session 4: v0.19 independent verification fixes
<!-- trellis-session: v=2 fp=e6c100cfd14918b0 -->

**Date**: 2026-11-04
**Task**: v0.19 independent verification fixes
**Branch**: `release/v0.19.0`

### Summary

Fixed all defects found by the independent v0.19 verification: headless stdout pollution, permission-rule bypasses, false fs_read_file paging claim, import-time config write, debug prints, and environment-dependent test isolation. Re-verified with clean-HOME full suite and dedicated regression probes.

### Main Changes

- D1/D2/D3/D8: provider/client consoles re-pointed to stderr in machine mode, headless intent passed to CLI constructor before PromptSession/console creation, debug ANSI prints moved to stderr
- D4/D5: path_glob candidates normalized (no .. traversal/absolute escape), argv_prefix rules reject shell control/expansion syntax; 17 new tests
- D6: fs_read_file offset/limit paging implemented (marker/docs truthful) + spill files 0600 + --cwd wins over stale exported YAI_WORKSPACE_ROOT
- D7/T1: legacy config key migration deferred to ensure_config_file (deduped per path), test credentials set before any yaicli import, _faststart ignores version flags after --

### Git Commits

| Hash | Message |
|------|---------|
| `5fd62bc` | fix(cli): keep machine-readable stdout clean in headless modes |
| `4735f3d` | fix(permissions): block path-glob traversal and shell-syntax rule bypasses |
| `f19cac6` | fix(agent): implement tool-output paging and harden shell env/spill handling |
| `bf39624` | fix(runtime): keep config imports write-free and make tests environment-safe |
| `1868067` | docs(changelog,spec): record v0.19 verification fixes |

### Testing

- [OK] full suite: 1775 passed (ambient env and fresh-HOME clean env)
- [OK] regression probes: 20/20 (json/stream-json stdout purity incl. verbose, path traversal, substitution/pipe rules, paging, deferred migration, debug prints, -- parsing)
- [OK] ruff check yaicli tests clean; mkdocs build --strict passes

### Status

[OK] **Completed**

### Next Steps

- v0.20: K08-K15 startup/footprint work; publish/tag v0.19.0 via the existing release flow


## Session 5: v0.19.0 release and double Ctrl-C REPL exit
<!-- trellis-session: v=2 fp=ab3f141e9c76388c -->

**Date**: 2026-11-04
**Task**: v0.19.0 release and double Ctrl-C REPL exit
**Branch**: `master`

### Summary

Adds a second-Ctrl-C REPL exit, syncs the docs changelog page, and ships v0.19.0 to PyPI and the docs site.

### Main Changes

- REPL now exits on a second Ctrl-C within ~2s (single press still clears input/cancels the turn; a completed prompt read resets the window)
- README/docs/commands/headless/upgrade pages and the cli-and-rendering spec document the new Ctrl-C semantics

### Git Commits

| Hash | Message |
|------|---------|
| `3c401ae` | feat(cli): exit the REPL on a double Ctrl-C |
| `295dfd5` | docs(changelog): include the double Ctrl-C REPL exit in v0.19.0 notes |
| `42fca6d` | docs(changelog): sync docs changelog page for v0.19.0 |

### Testing

- [OK] pytest: 1778 passed; ruff check clean; mkdocs build --strict ok
- [OK] hatchling wheel/sdist for 0.19.0 built and console scripts smoke-tested

### Status

[OK] **Completed**

### Next Steps

- Watch user feedback on the new Ctrl-C hint and the double-press window


## Session 6: v0.19.1 tool-output viewer release
<!-- trellis-session: v=2 fp=4b6eaa52dabc94d6 -->

**Date**: 2026-11-05
**Task**: v0.19.1 tool-output viewer release
**Branch**: `master`

### Summary

Ships the full-screen Ctrl+O tool-output viewer, compact head-only tool previews and background generation to PyPI and the docs site as v0.19.1.

### Main Changes

- Ctrl+O // /show-output opens a two-pane alternate-screen viewer listing every tool result of the turn; the REPL keeps a 15-line head-only preview (… +N lines · Ctrl+O to expand)
- Generation runs on a worker thread through ThreadedStream; Ctrl+O works while the model streams, closing the viewer redraws accumulated content, and abort never corrupts the message list
- Viewer chrome uses compact tool labels (shell/read/write/…) and one-line call captions instead of the raw execute_shell_command name; body pane keeps full name, args, spilled full output on f (1 MB cap)
- macOS VDISCARD/IXON were swallowing Ctrl+O during generation (missing TUI lines); watcher now disables output control keys and restores termios; execute_shell_command argument renamed shell_command -> command

### Git Commits

| Hash | Message |
|------|---------|
| `a0db5eb` | feat(tools): render tool results as a compact head-only preview |
| `d77e190` | feat(tools): add full-screen Ctrl+O tool-output viewer |
| `7fcea5f` | feat(cli): toggle the tool-output viewer during generation |
| `b6709cf` | feat(stream): add threaded stream bridge for background generation |
| `c0874a8` | feat(stream): route worker-thread console output through the bridge |
| `b9337bd` | feat(cli): run interactive generation on a worker thread |
| `d598955` | fix(stream): keep aborting/lingering workers from corrupting state |
| `f437f7e` | docs(tools): document background generation Ctrl+O behavior |
| `2eaaadf` | refactor(tools)!: rename execute_shell_command argument to command |
| `cba65ee` | fix(cli): service Ctrl+O between background stream chunks |
| `28f29f7` | fix(keys): stop macOS VDISCARD from swallowing Ctrl+O during generation |
| `573f6d8` | feat(viewer): show tool-call captions in the output list |
| `2f026ca` | feat(viewer): use compact tool labels in the output list |
| `0b5a95a` | Bump version: 0.19.0 → 0.19.1 |
| `fc8b98c` | docs(changelog): update changelog for v0.19.1 release |

### Testing

- [OK] pytest: 1909 passed; ruff check clean; mkdocs build --strict ok
- [OK] GitHub publish.yml + deploy-docs.yml success; PyPI 0.19.1 wheel/sdist live; docs changelog shows 0.19.1

### Status

[OK] **Completed**

### Next Steps

- Collect UX feedback on the viewer list (compact labels, caption width) and the generation-time Ctrl+O flow
- v0.20: startup/footprint K08-K15, permission policy v2, workspace writes/undo, session isolation


## Session 7: v0.20.0 startup, packaging and viewer release
<!-- trellis-session: v=2 fp=0dbc1e0572506e7c -->

**Date**: 2026-11-07
**Task**: v0.20.0 startup, packaging and viewer release
**Branch**: `master`

### Summary

Ships K08 startup latency, K09 tools-complete packaging and the Ctrl+O full-tool-name fix as v0.20.0 (PyPI + docs).

### Main Changes

- K08: entry/cli heavy imports are lazy and the LLM client is constructed on first use; REPL first prompt proxy ~1.55s -> ~0.55s, --help no longer imports the CLI stack; new scripts/bench.py + bench.yml cold-start gate
- K09: base install stays tools-complete (ddgs/trafilatura/fastmcp kept), anthropic[bedrock,vertex] split into [bedrock]/[vertex], [all] complete, missing-SDK AgentError hint, Bedrock/Vertex api_key fix, packaging policy tests + docs
- Viewer: Ctrl+O list/header show full tool names again (execute_shell_command, _mcp__<tool>, ...) with caption/size unchanged; spec locks the rule and tests

### Git Commits

| Hash | Message |
|------|---------|
| `3d33651` | perf(startup): defer heavy imports and build the LLM client lazily (K08) |
| `d874b09` | build(deps): keep tools complete in base and split Anthropic cloud extras (K09) |
| `641d7cf` | fix(viewer): show full tool names in the output list |
| `9be64e2` | docs(spec): require raw tool names in the Ctrl+O viewer chrome |
| `a9f347d` | docs: refresh lightweight claims and v0.20 upgrade notes |
| `390e045` | ci(bench): widen the one-shot local-overhead gate to 2200 ms for shared runners |
| `8aa1cb2` | Bump version: 0.19.1 → 0.20.0 |
| `5e69202` | docs(changelog): update changelog for v0.20.0 release |

### Testing

- [OK] pytest: 1922 passed; ruff clean; mkdocs build --strict ok; scripts/bench.py --gate ok (CI Startup benchmark workflow success)
- [OK] GitHub publish.yml + deploy-docs.yml success; PyPI 0.20.0 wheel/sdist live; published wheel smoke: ai --version 0.20.0, 12 builtin functions; docs changelog shows 0.20.0

### Status

[OK] **Completed**

### Next Steps

- Start v0.21 safety foundation (task 11-07-v021-safety-foundation): K10 policy modes, K11 workspace write safety + /undo, K12 AGENTS.md, K13 session isolation, K14 provider tool-call consistency


## Session 8: v0.21.0 safety foundation release (K10-K14)
<!-- trellis-session: v=2 fp=0e2bf2a84e624394 -->

**Date**: 2026-11-07
**Task**: v0.21.0 safety foundation release (K10-K14)
**Branch**: `master`

### Summary

Shipped K10 permission policy modes, K11 workspace write safety + /undo, K12 project context, K13 per-project sessions + --resume, K14 multi-provider tool-call consistency; released v0.21.0 to PyPI/docs with specs, openspec and changelog.

### Main Changes

# v0.21.0 — safety foundation (K10–K14)

## Shipped

- **K10 permission policy modes** (`09a41ad`): `TOOL_POLICY` (`YAI_TOOL_POLICY`) with
  `readonly`/`standard`/`trusted`, enforced as a hard ceiling/floor in the tool gate; readonly auto-allows
  read/network and hard-denies write/exec even when pre-approved; trusted auto-allows non-dangerous tools;
  danger-classified shell keeps its precedence in every mode; audit JSONL gained a `policy` field; invalid
  values fall back to standard with one warning.
- **K11 workspace write safety + /undo** (`d305e92`): new stdlib `tools/workspace.py` guard called from
  `execute_tool_call` for `fs_write_file`/`fs_edit_file`/`fs_file_operations`: confinement to
  `WORKSPACE_ROOT` (default cwd), symlink/`..` escape refusal, protected paths (`.git/.ssh/.aws/.gnupg`,
  `.env*`, `*.pem`, `*.key`), backups under `<workspace>/.yaicli-backups/` (0600/0700, fail closed), and
  in-memory bounded undo + `/undo` REPL command. Denials are in-band JSON with actionable reasons.
- **K12 project context** (`001258f`): stdlib `project_context.py` auto-loads `AGENTS.md`/`CLAUDE.md`/
  `.yaicli.md` from cwd to the git root into the role system message; bounded by
  `PROJECT_CONTEXT_MAX_CHARS` (20000), one stderr truncation notice, `ENABLE_PROJECT_CONTEXT` disable,
  byte-identical payload when no files exist.
- **K13 session isolation + resume** (`7def9ad`): sessions under
  `~/.yaicli/sessions/<sha256(cwd)[:16]>/` (0700/0600, atomic) with model/provider/role/cwd/timestamps
  metadata; explicit `CHAT_HISTORY_DIR` keeps the flat dir; `--resume` continues the newest project
  session with a notice (explicit new-session notice when none); missed `--chat <title>` is announced, not
  silent; prompt history created 0600. Old temp-dir sessions left in place (no auto-migration).
- **K14 multi-provider tool-call consistency** (`7d5fa88`): shared stdlib `llms/tool_calls.py` accumulator
  and plural `LLMResponse.tool_calls` (legacy `tool_call` mirrored); client collects/executes every call;
  fixed Anthropic parallel `tool_use` (non-stream+stream), Gemini streamed same-name calls, Ollama multiple
  calls, chatglm/huggingface, minimax, ai21, mistral and openai-compatible (no partial-args streaming).
- **Docs/spec/openspec**: permissions modes, workspace-safety, project-context and session pages; upgrade
  v0.21 section; README/index; specs for tool policy/workspace/context/session/provider contracts; new
  openspec specs `workspace-write-safety`, `project-context`, `session-isolation` and the tool-policy
  requirements added to `tool-execution-confirmation`.

## Verification

- Full suite: **2136 passed**; `ruff check yaicli tests` clean; `mkdocs build --strict` passes.
- `scripts/bench.py --gate`: version 74.8/250ms, help 516/900, template 480/900, entry_import 429/900,
  repl_ready 600/1800, oneshot_local 1624/2200 — all ok.
- Release: tag `v0.21.0` (`cec4ae1`), changelog `dc52fa1`; PyPI wheel (283,442 B) + sdist live; GitHub
  workflows Publish-to-PyPI, Deploy-MkDocs and Startup-benchmark all success; docs changelog shows 0.21.0.
- Released-wheel smoke in a clean venv: `ai --version` → 0.21.0, `--help` lists `--resume`, `--template`
  contains `TOOL_POLICY`/`ENABLE_PROJECT_CONTEXT`/`PROJECT_CONTEXT_MAX_CHARS`, new modules import, builtin
  functions load.

## Next

v0.22.0 «ecosystem & observability» = K16 MCP hardening + K20 secret redaction first, then K17 usage/cost,
K18 REPL experience, K19 on-demand tool schemas.


### Git Commits

| Hash | Message |
|------|---------|
| `09a41ad` | feat(permissions): add TOOL_POLICY readonly/standard/trusted modes (K10) |
| `d305e92` | feat(tools): confine writes to the workspace, back up mutations and add /undo (K11) |
| `001258f` | feat(context): auto-load project AGENTS.md context into the system prompt (K12) |
| `7def9ad` | feat(chat): isolate sessions per project, stamp metadata and add --resume (K13) |
| `7d5fa88` | fix(providers): keep every tool call in multi-call turns (K14) |
| `cec4ae1` | Bump version: 0.20.0 → 0.21.0 |
| `dc52fa1` | docs(changelog): update changelog for v0.21.0 release |

### Status

[OK] **Completed**


## Session 9: v0.22.0 ecosystem & observability (K16–K20)
<!-- trellis-session: v=2 fp=b1f5b58b8a4725ee -->

**Date**: 2026-11-08
**Task**: v0.22.0 ecosystem & observability (K16–K20)
**Branch**: `master`

### Summary

Shipped v0.22.0: MCP hardening, real usage/cost observability, secret redaction on disk, tool-schema narrowing and the REPL agent UX (prompt model/role/context, slash completion, /model /role /retry, multi-line).

### Main Changes

- K17 usage observability: new stdlib usage.py (Usage/UsageTracker/estimate_cost + provider converters), LLMResponse.usage, real JSON/stream-json usage + finish_reason, MAX_TOKENS warning, SHOW_USAGE per-turn line, /cost command; OpenAI stream_options include_usage with 400 fallback, Anthropic/Gemini/Mistral/Ollama capture, estimation fallback.
- K16 MCP hardening: broken mcp.json/missing fastmcp degrade to [] with one actionable stderr warning; MCP_TIMEOUT bounds list/call; MCP_MAX_TOOLS caps injected tools; descriptions sanitized/ANSI-stripped/capped/source-labelled; results join all blocks and mark is_error.
- K20 secret redaction: new redaction.py (provider keys, AWS/GitHub/Slack/Google tokens, Bearer, PEM blocks, env assignments, URL userinfo, JWTs; control chars) applied to tool-output spill files and saved/auto-saved sessions, configurable via REDACT_SECRETS; audit redaction reuses the same implementation.
- K19 schema narrowing: ENABLED_TOOLS config + --tools flag (fnmatch globs, builtin and _mcp__ names), per-pattern caching, unknown-name warning, and an in-band tool_disabled refusal for non-offered calls.
- K18 REPL UX: prompt shows model/role/context %, slash-command completion from a single CommandInfo metadata source, /model /role /retry commands, Alt+Enter/Ctrl+J multi-line input; /model vs /mode prefix ambiguity fixed.
- Config/docs: six new keys (MCP_TIMEOUT, MCP_MAX_TOOLS, SHOW_USAGE, MODEL_PRICING, ENABLED_TOOLS, REDACT_SECRETS) wired through const.py template, README and configuration.md drift guard; README/feature pages and CLI reference snapshot updated.

### Git Commits

| Hash | Message |
|------|---------|
| `cf823fb` | feat(config): add v0.22 keys for MCP hardening, usage and redaction |
| `f61da5d` | feat(mcp): harden MCP config, timeouts, tool caps and result handling |
| `1ff622d` | feat(security): redact secrets before tool output and sessions hit disk |
| `cdb8158` | feat(usage): surface provider token usage, cost and finish reasons |
| `101b097` | feat(tools): narrow offered tool schemas with ENABLED_TOOLS/--tools |
| `631f305` | feat(repl): show model/role/context in the prompt, add /model /role /retry and slash completion |
| `64f2e40` | docs: document the v0.22 observability, MCP, redaction and REPL features |
| `75bc821` | Bump version: 0.21.2 → 0.22.0 |
| `94cf58b` | docs(changelog): update changelog for v0.22.0 release |

### Testing

- [OK] Full suite 2435 passed; ruff check clean; mkdocs build --strict pass; scripts/bench.py --gate ok on an idle machine (version 71/250, help 554/900, template 555/900, entry_import 442/900, repl_ready 668/1800, oneshot_local 1873/2200).
- [OK] Released-wheel smoke in a clean venv: ai --version 0.22.0; template lists all six keys; non-stream and streaming mock-provider runs report real usage (123/45 and 77/11), cost and finish_reason in JSON.
- [OK] Local ~/.config/yaicli/config.ini gained the v0.22 keys and parses with correct types (int/bool/dict/str).

### Status

[OK] **Completed**

### Next Steps

- Installed ai tool still reports 0.21.0 (uv tool install; PyPI mirror lag) — upgrade later with the usual uv tool upgrade, no forced reinstall.
- Optional cleanup: strip remaining milestone-ID labels (K16/K17/K19/K20) from code comments if the K18-style clean-up should apply repo-wide.


## Session 10: Add CI test workflow and release wrap-up
<!-- trellis-session: v=2 fp=58aab77e87b4682f -->

**Date**: 2026-11-09
**Task**: Add CI test workflow and release wrap-up
**Branch**: `master`

### Summary

Filled the missing test/lint CI gap and did the v0.22.0 post-release wrap-up (spec drift, roadmap status, stale branches).

### Main Changes

- Added .github/workflows/test.yml: lint+docs job (ruff check --no-fix because [tool.ruff] fix=true would auto-repair and exit 0; mkdocs build --strict) and a pytest matrix on Python 3.10/3.12/3.13, on push/PR to master plus workflow_dispatch, with concurrency cancellation.
- Corrected .trellis/spec/repo/build-and-release.md: version now lives in both pyproject.toml and yaicli/__init__.py __version__ (bump2version updates both; --version fast path reads the constant), and documented test.yml/bench.yml/publish.yml plus the CI gate in the release checklist.
- Local-only roadmap (var/, gitignored) updated: v0.21.x and v0.22.0 marked released, stretch openai-compatible lite transport singled out as the v0.23 candidate.
- Branch cleanup: deleted 18 merged local branches and 2 merged remote feature branches, pruned remote-tracking refs (kept master/docs/develop/gh-pages and the unmerged feat/cli-list-mcp-details-optional-filter).

### Git Commits

| Hash | Message |
|------|---------|
| `8d01291` | docs(spec): correct version mechanism and CI workflow description |

### Testing

- [OK] Full suite green on Python 3.12 (2435 passed) and on the previously untested 3.10 (2434 passed, 1 skipped) and 3.13 (2435 passed) using isolated /tmp venvs.
- [OK] ruff check --no-fix yaicli tests clean; mkdocs build --strict passed; workflow YAML parsed correctly.

### Status

[OK] **Completed**

### Next Steps

- First GitHub Actions run of test.yml on master: watch it green (bench.yml also re-runs); fix forward if the 3.10/3.13 matrix surfaces anything.
- v0.23 candidate remains the openai-compatible lite transport (roadmap P1-c) with tightened bench gates.


## Session 11: Fix CI-surfaced environment-dependent tests
<!-- trellis-session: v=2 fp=7a1eee614d2451b7 -->

**Date**: 2026-11-09
**Task**: Fix CI-surfaced environment-dependent tests
**Branch**: `master`

### Summary

The newly added CI matrix failed on its first run; fixed the five environment-dependent assertions it exposed (macOS passed locally, Linux CI failed).

### Main Changes

- Added a strip_ansi fixture in tests/conftest.py: Typer renders --help via Rich, and with TERM unset (CI runner default) Rich emits ANSI style codes that split 'Usage: main' / '--resume' / '--tools' so plain substring assertions failed; the fixture strips SGR sequences first.
- tests/test_entry.py, tests/test_session_isolation.py, tests/test_tool_schema_filter.py now use the fixture for --help assertions.
- tests/tools/test_fs_write_file.py: /etc resolves to /private/etc on macOS (open -> PermissionError) but stays /etc on Linux (system-dir blacklist -> 'Cannot write to system directory'); both system-directory tests now accept either blocked outcome.

### Git Commits

| Hash | Message |
|------|---------|
| `174744c` | test: make help-output and system-directory assertions platform-agnostic |

### Testing

- [OK] Full suite green under a CI-like environment (TERM/COLUMNS unset, CI=true): 2435 passed on Python 3.12; ruff check --no-fix clean; the 34 affected tests pass in the normal env too.
- [OK] Added test.yml itself: lint+docs job (ruff --no-fix because [tool.ruff] fix=true would auto-repair, mkdocs build --strict) plus pytest matrix 3.10/3.12/3.13 on push/PR to master.

### Status

[OK] **Completed**

### Next Steps

- Watch the re-run of CI on master go green across all three Python versions; bench gate already passed.
- v0.23 candidate remains the openai-compatible lite transport (roadmap P1-c).


## Session 12: K22 context-window resolution + /context polish (v0.23.0)
<!-- trellis-session: v=2 fp=941c0a00061f8f5f -->

**Date**: 2026-11-11
**Task**: K22 context-window resolution + /context polish (v0.23.0)
**Branch**: `master`

### Summary

Implemented the six-layer model context-window resolver (model_limits.py): user > learned > provider metadata > catalog > heuristic > default; budget = window - MAX_TOKENS - safety (70% ratio removed); OpenRouter/Gemini/Ollama metadata hooks; 400-error limit learning; disk cache with TTLs; /context now shows window source, buckets, overhead and reserve, and no longer repeats the subcommand hint. Binding rules in .trellis/spec/py/context-window-limits.md, docs completed with normalization/heuristic/catalog rules. Full pytest (2542) + ruff + mkdocs --strict green. Released as v0.23.0.

### Git Commits

| Hash | Message |
|------|---------|
| `901c59a` | feat(context): resolve model context windows through six layers (K22) |
| `32ff2da` | docs(context): document six-layer window resolution and /context output |
| `864136e` | docs(spec): make context-window and budget rules binding (K22) |

### Status

[OK] **Completed**
