# Build, CI & Release

Everything here is verified against the current tree (`Justfile`, `pyproject.toml`, `tox.ini`,
`.github/workflows/`, `.bumpversion.cfg`, `cliff.toml`). If you change one of them, update this file.

## Local Development Setup

```bash
uv sync --all-groups --all-extras     # dev + docs + every provider extra
uv run pytest                         # full test suite
uv run ruff check yaicli tests        # lint (F rules only)
just format                           # ruff format + ruff check --fix + isort
```

`uv` is the only supported dependency manager (`uv.lock` is committed). `tox` is the multi-Python
matrix runner, not the everyday command.

## Task Runner (`Justfile`)

| Recipe | Runs |
| --- | --- |
| `just help` | `just -l` (default goal) |
| `just sync` / `just install` | `uv sync --all-groups --all-extras` |
| `just format` | `ruff format` + `ruff check --fix` on `yaicli` and `tests`, then `isort` |
| `just test` | `uv run pytest` |
| `just build` | `rm -rf dist/` + `uv build` |
| `just publish` | `build` then `uv-publish` (external tool on the maintainer machine) |
| `just changelog` | `uv lock` + `git cliff -l --prepend CHANGELOG.md` |
| `just clean` | removes `build/`, `dist/`, `*.egg-info/`, `__pycache__/`, `.pytest_cache/`, `.pdm_build/`, `.ruff_cache/` |

Quirks to preserve when editing the Justfile: the `format` recipe calls `isort yaicli yaicli`
(duplicate arg) and CI never runs `just`, so the individual commands must stay directly runnable.

## Packaging (`pyproject.toml`)

- **Build backend**: `hatchling>=1.18`. `[tool.hatch.build]` includes `yaicli` + `pyproject.toml`
  and excludes `test_*.py`, `tests/*`, `.gitignore` — the wheel ships the package and README only.
- **Console scripts**: `ai = "yaicli._faststart:main"` and `yaicli = "yaicli._faststart:main"` (both
  names are supported; `ai` is the documented one). `--version` is answered before importing the CLI
  stack; only other invocations reach `entry.py`.
- **Python**: `requires-python = ">=3.10"`; tox covers 3.10-3.13.
- **Runtime dependencies (tools-complete base, K09)**: `typer`, `click`, `rich`, `openai`,
  `anthropic` (plain API), `httpx`, `prompt-toolkit`, `json-repair`, `docstring-parser`, `trafilatura`,
  `fastmcp`, `ddgs`, `distro`, `socksio`. `ddgs` (web_search), `trafilatura` (fetch_webpage
  extraction) and `fastmcp` (MCP) intentionally stay in base: a plain `pip install yaicli` must never
  leave a builtin tool broken. Do not move them to extras without a product decision.
- **Optional extras** keep cloud/long-tail provider SDKs out of the core install: `all`, `bedrock`,
  `vertex`, `doubao`, `ollama`, `cohere`, `gemini`, `huggingface`, `mistral`, `cerebras`,
  `fireworks`. `bedrock`/`vertex` wrap `anthropic[bedrock]`/`anthropic[vertex]`; `all` stays complete
  (it includes `anthropic[bedrock,vertex]`). A new provider that needs an SDK must add its extra here,
  add a key to `ProviderFactory`'s `_OPTIONAL_PROVIDER_EXTRAS`, and import the SDK lazily from the
  provider module (see [../py/index.md](../py/index.md) dependency rules) so a missing SDK raises the
  classified `AgentError` with `pip install "yaicli[<extra>]"`.
- **Packaging policy tests**: `tests/test_packaging.py` parses `pyproject.toml` (Python 3.10-compatible,
  no tomllib requirement) and locks the tools-complete base / cloud-extras split. Update it with any
  intentional extras change.

```bash
uv build           # sdist + wheel into dist/ (equivalent to `just build`)
```

## Versioning

`.bumpversion.cfg` is the single source of the version bump; it updates **two** files:

```ini
[bumpversion]
current_version = 0.22.0
commit = True
tag = True
[bumpversion:file:pyproject.toml]     # project.version
[bumpversion:file:yaicli/__init__.py] # __version__ static constant
```

`yaicli/__init__.py` carries a static `__version__` constant on purpose: `ai --version` is answered
by `yaicli/_faststart.py` before the CLI stack is imported and reads that constant (falling back to
`importlib.metadata.version("yaicli")` only when the constant is empty), which avoids the
~100 ms+ distribution-metadata scan. Because `commit = True` and `tag = True`, a plain
`bump2version patch|minor|major` also commits and tags `vX.Y.Z` — expect that before running it.

## Changelog (`cliff.toml` + `git cliff`)

- `CHANGELOG.md` is generated from Conventional Commits by `git cliff`, configured in `cliff.toml`
  (groups like Features / Bug Fixes / Refactor / Documentation; `filter_unconventional = true`).
- Regenerate with `just changelog` (`uv lock` first, then `git cliff -l --prepend CHANGELOG.md`).
  Never hand-edit released sections.
- Observed release order in history: `Bump version: 0.16.0 → 0.17.0` (the tagged commit) →
  `docs: update CHANGELOG for v0.17.0 release` → docs commit(s). The tag therefore points at the
  bump commit, not at the changelog commit.
- `docs/changelog.md` is synced from `CHANGELOG.md` at release time (`cp CHANGELOG.md docs/changelog.md`);
  `CHANGELOG.md` remains the source of truth. Keep the two in sync whenever you regenerate the changelog.
  (v0.18.0 release: synced after `git cliff -l --prepend CHANGELOG.md`.)

## CI (`.github/workflows/`)

**`test.yml`** — runs on push/PR to `master` plus manual `workflow_dispatch`; two jobs:

1. `lint` — Python 3.12: `uv sync --all-groups --all-extras`, `uv run ruff check --no-fix yaicli tests`
   (`--no-fix` matters: `pyproject.toml` sets `[tool.ruff] fix = true`, so a bare `ruff check` would
   auto-repair violations and still exit 0), then `uv run mkdocs build --strict`.
2. `test` — matrix Python `3.10 / 3.12 / 3.13`: `uv sync --all-groups --all-extras`, `uv run pytest -q`.

**`bench.yml`** — runs on push/PR to `master`; cold-start gate `uv run python scripts/bench.py --gate -n 3`
(P50 limits live in `scripts/bench.py`: `GATE_LIMITS`).

**`publish.yml`** — runs on tags matching `v*`:

1. checkout, Python 3.11, `pip install hatchling`
2. `python -m hatchling build` (`hatchling` >= 1.19 ships `__main__.py`; v0.18.0 publish run succeeded)
3. `pypa/gh-action-pypi-publish@release/v1` with `secrets.PYPI_API_TOKEN` (token-based publishing,
   not PyPI trusted publishing)

So publishing a release means pushing the `vX.Y.Z` tag created by `bump2version`.

**`deploy-docs.yml`** — runs on push to the `docs` branch (not `master`):

1. checkout with `fetch-depth: 0`, Python 3.10, `pip install uv`
2. `uv sync --all-groups`
3. `uv run mkdocs gh-deploy --force --clean` with `GITHUB_TOKEN`

Consequence: docs never deploy from a feature branch; merge/copy the docs commit onto `docs` and push.
If the remote `docs` branch diverged (it accumulates deploy/merge commits), fast-forward it by
force-with-lease after a fetch: `git push --force-with-lease origin master:docs` (v0.18.0 used this).

## Docs Site (`mkdocs.yml` + `docs/`)

- Config is `mkdocs.yml` (Material theme); navigation is the `nav:` list — a new page that is not
  added there is unreachable.
- Docs tooling is the `docs` dependency-group (`mkdocs`, `mkdocs-material`, `mkdocstrings`):
  `uv sync --all-groups` then `uv run mkdocs serve` / `uv run mkdocs build`.
- `docs/dev/` contains the contributor guides (`architecture.md`, `add-provider.md`, `debug-cli.md`);
  `.trellis/spec/py/index.md` remains the layer-level reference and `CLAUDE.md` the agent entry point.

## Test Matrix (`tox.ini`)

```ini
env_list = py310, py311, py312, py313
[testenv]            deps = pytest, pytest-cov ; extras = all ; commands = pytest {posargs:tests}
[testenv:lint]       deps = ruff ; commands = ruff check {posargs:yaicli tests}
```

CI (`test.yml`) runs the same suite on Python 3.10 / 3.12 / 3.13 with `uv`; `tox` additionally covers
3.11 locally. Both are optional for everyday work (`uv run pytest`), but the CI matrix is the gate a
release must pass.

## Branch Workflow (branch + PR)

`master` is the release branch; feature/fix/docs work is never committed or pushed to it directly.
Every change goes through a branch cut from `master` and a pull request.

```bash
git switch master && git pull --ff-only
git switch -c feat/<slug>          # prefixes: feat/ fix/ chore/
# ... implement + gates + commit on the branch ...
git push -u origin feat/<slug>
gh pr create --base master --title "<conventional title>" --body "<what/why + test evidence>"
gh pr checks <number>              # wait for CI to be green
# ASK THE USER before merging; only after an explicit yes:
gh pr merge <number> --merge --delete-branch
git switch master && git pull --ff-only
```

- **Merging always needs the user's explicit confirmation**, even though `gh` is installed and
  authenticated. Report the PR number + check status, ask, and wait for the answer.
- Use `gh pr merge --merge` (merge commit) to match the repository's existing PR history; `--squash`
  only when the user asks for it.
- The long-lived `docs` branch (docs-site deploy) occupies the `docs/` ref namespace — a `docs/<slug>`
  branch cannot be created. Use `chore/docs-<slug>` for documentation-only changes.
- **Trellis metadata**: `python3 ./.trellis/scripts/task.py set-branch <task> feat/<slug>` and
  `set-base-branch <task> master`. `task.py create-pr` is not available in this checkout — create PRs
  with `gh`. `task.py archive` refuses a task whose `branch` and `base_branch` are both `master`
  (`--skip-branch-validation` is only for tasks that never had a branch at all).
- **Trellis bookkeeping commits** (task archive / session journal auto-commits) are made after the PR
  is merged; they are the only direct `master` commits and may be pushed as a follow-up.
- **Releases are cut from `master`** after the PR is merged: `bump2version`, changelog and the tag are
  made on `master`, not on the feature branch.

## Release Checklist

0. Merge the release PR (after the user confirms) and sync master
   (`git switch master && git pull --ff-only`) — releases are cut from `master`.
1. `uv run pytest` and `uv run ruff check yaicli tests` are green (full suite; see
   [../py/quality-guidelines.md](../py/quality-guidelines.md)).
2. Update user docs for the release (README / docs pages / `mkdocs.yml` nav as needed).
3. `uv run bump2version patch|minor|major` — commits `Bump version: X.Y.Z → A.B.C` and tags `vA.B.C`.
4. `just changelog` and commit the regenerated `CHANGELOG.md` as `docs: update CHANGELOG for vA.B.C release`.
5. Push `master` **and** the tag: `git push origin master --tags` — the tag push triggers `publish.yml`
   and the `master` push triggers `test.yml` + `bench.yml`; all must end green before announcing.
6. If docs changed, push the docs branch to trigger `deploy-docs.yml`: `git push origin master:docs`
   (or `git push --force-with-lease origin master:docs` when the remote `docs` branch has diverged).
7. Sync the docs changelog page before pushing docs: `cp CHANGELOG.md docs/changelog.md`.
