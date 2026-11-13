# CLAUDE.md

This file provides guidance when working with code in this repository.

## Project Overview

YAICLI is a CLI tool for interacting with LLMs from the terminal. It supports 30+ providers (OpenAI, Anthropic, Gemini, Ollama, etc.), multiple interaction modes (chat, shell command execution, quick query), function calling, and MCP integration.

## Common Commands

```bash
# Install dependencies (all extras for development)
uv sync --all-groups --all-extras

# Run tests
uv run pytest                      # all tests
uv run pytest tests/test_cli.py    # single file
uv run pytest -k "test_name"       # single test by name
uv run pytest --cov=yaicli         # with coverage

# Multi-version testing
tox                                # all Python versions (3.10-3.13)
tox -e py312                       # specific version
tox -e lint                        # lint only

# Linting and formatting
just format                        # format with ruff + isort
ruff check yaicli tests            # check only
ruff check --fix yaicli tests      # check and fix

# Build
uv build

# Version bump (uses bump2version)
uv run bump2version patch|minor|major
```

## Architecture

### Core Flow
```
entry.py (Typer app) → cli.py (CLI orchestrator) → llms/client.py (LLMClient)
                                                  → llms/provider.py (ProviderFactory → Provider)
```

### Key Modules

- **`yaicli/cli.py`**: Main orchestrator handling chat, exec, and temp modes. Manages roles, sessions, keybindings, and history.
- **`yaicli/llms/client.py`**: `LLMClient` coordinates provider calls, tool execution (recursive with depth limit), and streaming.
- **`yaicli/llms/provider.py`**: `Provider` ABC + `ProviderFactory`. Each provider in `providers/` extends this.
- **`yaicli/config.py`**: Layered config (env vars `YAI_*` > config file `~/.config/yaicli/config.ini` > defaults).
- **`yaicli/tools/function.py`**: Function calling schema generation and execution.
- **`yaicli/tools/mcp.py`**: MCP protocol integration (lazy-loaded).
- **`yaicli/printer.py`**: Rich text rendering for streaming responses.

### Adding a New Provider

1. Create `yaicli/llms/providers/your_provider.py`
2. Extend the narrowest base (`Provider` ABC, `OpenAIProvider`, `AnthropicProvider`, ...); implement
   `completion()` and `detect_tool_role()`; override `_convert_messages()` only when the wire format differs
3. Register the key in `ProviderFactory.providers_map` in `yaicli/llms/provider.py` (the
   `yaicli/llms/providers/__init__.py` file is empty)
4. Add tests under `tests/llms/` and docs under `docs/providers/` (+ `mkdocs.yml` nav)
5. Declare the SDK extra in `pyproject.toml` if it is optional

See `docs/dev/add-provider.md` for the step-by-step guide.

### Configuration Priority

Environment variables (`YAI_*`) > Config file (`~/.config/yaicli/config.ini`) > Default values in `yaicli/const.py`

## Testing Patterns

- **Fixtures** in `tests/conftest.py`: `patched_config_path` (session-scoped), `setup_test_environment`, `cli()`, `mock_console()`
- **Mock external APIs**: Never make real API calls in tests
- **Provider tests**: Located in `tests/llms/`
- **Tool tests**: Located in `tests/tools/`

## Code Style

- Line length: 120 characters
- Import sorting: `isort` with black profile
- Linting: `ruff` with F (pyflakes) rules only
- Type hints used throughout
- Lazy imports for heavy libraries (e.g., `fastmcp`) to reduce startup time

## Git Workflow (branch + PR)

Never change code directly on `master` and never push to `master` yourself — every change goes through
a branch and a pull request:

```bash
# 1. branch from the latest master
git switch master && git pull --ff-only
git switch -c feat/<slug>        # prefixes: feat/ fix/ chore/ (see the docs note below)

# 2. implement, run the gates, commit on the branch
uv run pytest
ruff check --no-fix yaicli tests
uv run mkdocs build --strict     # when docs changed

# 3. push the branch and open a PR against master
git push -u origin feat/<slug>
gh pr create --base master --title "<conventional title>" --body "<what/why + test evidence>"

# 4. wait for CI, then ASK THE USER whether to merge — never merge on your own
gh pr checks <number>            # must be green before asking
# only after an explicit "yes" from the user:
gh pr merge <number> --merge --delete-branch

# 5. sync local master after the merge
git switch master && git pull --ff-only
```

- The long-lived `docs` branch (docs-site deploy) occupies the `docs/` ref namespace, so a
  `docs/<slug>` branch cannot be created — use `chore/docs-<slug>` for documentation-only changes.
- `gh` is installed and authenticated (`pr create/view/checks/merge` all work). **Merging always needs
  the user's explicit confirmation** — report the PR number and check status, ask, then wait. Never
  merge or auto-merge on your own.
- Prefer `gh pr merge --merge` (merge commit) to match the repository's PR history; use `--squash` only
  when the user asks for it.
- Trellis tasks must record the branch and PR target: `task.py set-branch <task> feat/<slug>` and
  `set-base-branch <task> master` (`task.py create-pr` is not available in this checkout — use `gh`).
  `task.py archive` rejects a task whose branch and base branch are both `master`.
- Trellis bookkeeping commits (task archive / session journal) are the only direct `master` changes:
  they land after the PR merge and may be pushed as a follow-up.
- Releases (tag/bump/changelog) are cut from `master` after the PR is merged
  (see `.trellis/spec/repo/build-and-release.md`).

## Feature Specs

Every PRD, OpenSpec proposal/spec delta or plan that introduces user-visible behavior must include a
`## Feature examples` section: the concrete UI (verbatim terminal/output block), the presentation
form (stdout vs stderr, formatting, TTY vs non-TTY, machine modes) and the logic (triggers,
precedence, state, edge cases, exact user-facing messages and exit codes). A prose-only requirement
list is not a spec. Full convention: `.trellis/spec/repo/feature-spec-writing.md`.

<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->
