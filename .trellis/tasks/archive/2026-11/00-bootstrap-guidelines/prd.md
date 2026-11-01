# Bootstrap Task: Fill Project Development Guidelines

**You (the AI) are running this task. The developer does not read this file.**

The developer just ran `trellis init` on this project for the first time.
`.trellis/` now exists with empty spec scaffolding, and this bootstrap task
exists under `.trellis/tasks/`. When they want to work on it, they should start
this task from a session that provides Trellis session identity.

**Your job**: help them populate `.trellis/spec/` with the team's real
coding conventions. Every future AI session — this project's
`trellis-implement` and `trellis-check` sub-agents — auto-loads spec files
listed in per-task jsonl manifests. Empty spec = sub-agents write generic
code. Real spec = sub-agents match the team's actual patterns.

---

## Status — DONE (2026-11-01)

- [x] Reshape the generated template to the repository's real layers
- [x] Fill Python package guidelines (`py/`)
- [x] Fill repository-level guidelines (`repo/`)
- [x] Back every rule with real file paths, tests, or commits
- [x] Remove non-applicable template scaffolding (`backend/`)
- [x] Verify: no placeholders, index ↔ files consistent, layers discovered

The scaffold assumed a backend web app (`routes`, `ORM`, `database migrations`).
This repository is a Python CLI + LLM provider/function-calling library, so the
layer set was **reshaped**, not filled:

- deleted `.trellis/spec/backend/{directory-structure,database-guidelines,error-handling,logging-guidelines,quality-guidelines,index}.md`
  — the project has no routes, ORM, or database;
- created two layers that match the real tree: `py/` (the `yaicli/` package) and
  `repo/` (build, CI, release, docs, commits);
- kept `.trellis/spec/guides/` unchanged (generic thinking guides, still valid).

---

## Delivered spec set

### `py/` — the `yaicli/` Python package

| File | Documents |
|------|-----------|
| `py/index.md` | Scope, pre-development checklist, verified architecture map (entry → CLI → client → providers → tools → printer), module ownership table, import/dependency rules, where-new-code-goes table, quality gate, known discrepancies |
| `py/provider-guidelines.md` | `Provider` ABC contract, `ProviderFactory.providers_map` registration (and that `providers/__init__.py` is empty), provider inheritance families, streaming/tool-call accumulation, reasoning normalization, `COMPLETION_PARAMS_KEYS`/`EXCLUDE_PARAMS`, 8-step add-a-provider checklist, testing rules, anti-patterns |
| `py/function-tool-guidelines.md` | `OpenAISchema`/`function_schema.py` generation, "one exact JSON type" schema rule (fs_read_file `0d2d943` case), builtin-function contract (`functions/buildin/`), install/reinstall lifecycle from `FUNCTIONS_DIR`, `execute_tool_call` path, `ToolPolicy` + four-state confirmation gate, MCP boundary, tests, anti-patterns |
| `py/cli-and-rendering.md` | Typer entry and overrides, three real runtime modes (`TEMP`/`CHAT`/`EXEC`; `CODE_MODE` unused), REPL lifecycle, generator + `send()` tool-confirmation handshake, slash commands/completion, `Printer` incremental rendering/Live/Think, `--image`, exceptions/console conventions, test patterns |
| `py/config-and-context.md` | Three-layer config (`YAI_*` env > `config.ini` > `DEFAULT_CONFIG_MAP`), `cfg` singleton, type conversion, `EXTRA_HEADERS/BODY`, adding a config key, `const.py` paths, role system, `@path` vs `/add` context mechanisms and limits, prompt history, `schemas.py` cross-layer contract, test caveats |
| `py/quality-guidelines.md` | Real toolchain commands, ruff/isort/style reality (F-only, 120 cols, no mypy), lazy imports/optional extras, test layout and `conftest.py` fixtures, provider/tool/CLI test patterns, hard rules, verification gate, CI reality |

### `repo/` — cross-cutting rules

| File | Documents |
|------|-----------|
| `repo/index.md` | Conventional Commits requirement (git-cliff grouping), docs-with-change rule + documentation map, `AGENTS.md` symlink rule, Trellis files-in-git rule, task/openspec/plans workflow, repository layout, task runner, Trellis workflow commands |
| `repo/build-and-release.md` | Local setup, `Justfile` recipes, hatchling packaging and optional extras, `bump2version` version flow, git-cliff changelog flow (tag points at the bump commit; `docs/changelog.md` is stale), GitHub Actions publish/deploy-docs flows, tox matrix, docs-site nav requirements, release checklist |

### Thinking guides (unchanged)

`.trellis/spec/guides/` — code-reuse and cross-layer thinking guides, pre-filled by Trellis and still applicable.

---

## Known defects documented by bootstrap — FIXED (2026-11-01)

These were found while writing the specs and recorded as "current state". All seven were fixed by
the follow-up task `.trellis/tasks/archive/2026-11/11-01-fix-bootstrap-known-defects/`:

- First run with an empty config directory crashed: `PROVIDER` was not in `DEFAULT_CONFIG_MAP`,
  `Config._load_from_file()` wrote the default ini and returned without parsing it, so `CLI()`
  raised `KeyError: 'PROVIDER'`; `YAI_PROVIDER` was likewise never read. **Fixed in `097b6b4`**
  (PROVIDER in the map, created template parsed, empty values fall back to typed defaults).
- `const.CODE_MODE` was defined but never dispatched; "code mode" is the CODER role.
  **Removed in `097b6b4`.**
- `MAX_HISTORY` and `ROLE_MODIFY_WARNING` were declared in `DEFAULT_CONFIG_MAP`/the default ini
  but no code read them. **Wired in `defdf80`.**
- An `--image`-only invocation built an empty user prompt and aborted in `CLI.run()`.
  **Fixed in `c6df177`** (entry sends a minimal prompt).
- `ContextManager` used a `"[...]"`-prefixed string as its "unavailable" sentinel, so real text
  files whose path/content starts with `[` could be silently dropped. **Replaced by the
  structured `FileReadResult` in `8703514`.**
- `RoleManager.print_roles()` was unwired/broken code (attribute access on a dict).
  **Removed in `defdf80`.**
- `functions/buildin/fs_read_image.py` used `Union[str, List[str]]` for `image_paths` — the same
  schema shape fixed for `fs_read_file` in `0d2d943`. **Migrated to the array-first contract in
  `92a4d05`.**

The follow-up task's PRD records the acceptance tests and verification evidence; the specs under
`.trellis/spec/py/` were updated to the fixed behaviour.

---

## Evidence & Verification (2026-11-01)

Every rule traces back to sources in the repository:

- `CLAUDE.md` / `AGENTS.md` (architecture, commands, conventions)
- `Justfile`, `pyproject.toml`, `tox.ini`, `.bumpversion.cfg`, `cliff.toml`,
  `.github/workflows/{publish,deploy-docs}.yml`, `mkdocs.yml`, `openspec/`, `plans/`
- `yaicli/` package: `entry.py`, `cli.py`, `chat.py`, `cmd_handler.py`, `completer.py`,
  `config.py`, `const.py`, `console.py`, `context.py`, `exceptions.py`,
  `function_schema.py`, `history.py`, `image.py`, `printer.py`, `render.py`,
  `role.py`, `schemas.py`, `utils.py`, `llms/`, `tools/`, `functions/`
- `tests/` suite: `conftest.py`, `tests/llms/`, `tests/tools/`, flat `test_*.py`
  (provider/tool/CLI test patterns cited per spec file)
- Git history: `0d2d943` (function schema), `9b77aa1` (Cohere credentials),
  `7cc64f0` (tool confirmation), `2cf4636` (version bump) as cited examples

Verification performed:

- `find .trellis/spec -type f` → 11 files (6 `py/`, 2 `repo/`, 3 `guides/`);
  no `backend/` scaffolding remains.
- Placeholder scan (`TODO|To be filled|placeholder|Fill in each|backend/`) over
  `.trellis/spec` → clean.
- Index/link check → every relative Markdown link resolves; `py/index.md` and
  `repo/index.md` cover every file in their layer.
- `python3 .trellis/scripts/get_context.py --mode packages` → `Spec layers: py, repo`.
- `python3 .trellis/scripts/task.py validate 00-bootstrap-guidelines` → passed.
- Targeted test evidence while writing (no full-suite claim here):
  `tests/tools/test_fs_read_file.py` 43 passed (schema case + Gemini regression);
  cited provider/tool test files 63 passed; cited CLI/config/role/history test files
  272 passed; `ruff check yaicli tests` clean.

Execution note: this bootstrap was run by the DSH Agent Teams flow — one Lead
(research, install, `py/index.md`, `repo/`) plus four spec writers with disjoint
file scopes and one independent read-only verifier.

---

## Quick explainer of the runtime (share when they ask "why do we need spec at all")

- Every AI coding task spawns two sub-agents: `trellis-implement` (writes
  code) and `trellis-check` (verifies quality).
- Each task has `implement.jsonl` / `check.jsonl` manifests listing which
  spec files to load.
- The platform hook auto-injects those spec files + the task's `prd.md`
  into every sub-agent prompt, so the sub-agent codes/reviews per team
  conventions without anyone pasting them manually.
- Source of truth: `.trellis/spec/`. That's why filling it well now pays
  off forever.

---

## Completion

Completed on 2026-11-01. The work commit contains `.trellis/` (workflow, spec,
task, workspace), `.agents/`, `.dsh/`, the Claude Code surface in `.claude/`, and
the `CLAUDE.md` Trellis block. The task was then finished and archived so future
developers get a `00-join-<slug>` onboarding task instead of this bootstrap task.
