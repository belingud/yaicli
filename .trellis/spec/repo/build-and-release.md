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

`.bumpversion.cfg` is the single source of the version bump:

```ini
[bumpversion]
current_version = 0.17.0
commit = True
tag = True
[bumpversion:file:pyproject.toml]   # only pyproject.toml carries the version
```

There is no version constant in the package (`yaicli/__init__.py` is empty); `--version` reads
`importlib.metadata.version("yaicli")`. Because `commit = True` and `tag = True`, a plain
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

`tox` / `tox -e py312` / `tox -e lint` mirror CI locally but are optional for everyday work.

## Release Checklist

1. `uv run pytest` and `uv run ruff check yaicli tests` are green (full suite; see
   [../py/quality-guidelines.md](../py/quality-guidelines.md)).
2. Update user docs for the release (README / docs pages / `mkdocs.yml` nav as needed).
3. `uv run bump2version patch|minor|major` — commits `Bump version: X.Y.Z → A.B.C` and tags `vA.B.C`.
4. `just changelog` and commit the regenerated `CHANGELOG.md` as `docs: update CHANGELOG for vA.B.C release`.
5. Push `master` **and** the tag: `git push origin master --tags` — the tag push triggers `publish.yml`.
6. If docs changed, push the docs branch to trigger `deploy-docs.yml`: `git push origin master:docs`
   (or `git push --force-with-lease origin master:docs` when the remote `docs` branch has diverged).
7. Sync the docs changelog page before pushing docs: `cp CHANGELOG.md docs/changelog.md`.
