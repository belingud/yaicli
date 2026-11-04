# Python Quality Guidelines

Applies to changes under `yaicli/` and `tests/`. The bar is modest: `ruff check` clean, `just format`
applied, relevant pytest files green. Ruff runs only pyflakes (`F`); there is no mypy/pyright, no
coverage threshold, and no test job in CI — the remaining rules here are conventions, not lint failures.

## Toolchain and Commands

| Need | Command | Notes |
| --- | --- | --- |
| Dev install | `uv sync --all-groups --all-extras` | `--all-extras` required: provider test modules import optional SDKs at import time |
| Format | `just format` | `ruff format` + `ruff check --fix` on `yaicli` and `tests`, then `isort yaicli yaicli` / `isort yaicli tests` (`Justfile`) |
| Lint | `ruff check --no-fix yaicli tests` | plain `ruff check yaicli tests` applies fixes because `fix = true`; only `F401` is fixable |
| One file / subset | `uv run pytest tests/tools/test_fs_read_file.py -q`, `uv run pytest -k "streaming"` | |
| Full suite | `uv run pytest` | 60 `test_*.py` files; `testpaths = ["tests"]` |
| Coverage (opt-in) | `uv run pytest --cov=yaicli` | `pytest-cov` is in the `dev` dependency-group; no addopts, no threshold |
| Multi-version | `tox`, `tox -e py312`, `tox -e lint` | `tox.ini`: `env_list = py310, py311, py312, py313`, testenv `extras = all` |
| Build | `uv build` | hatchling |

`Justfile` recipes are `sync`, `format`, `test`, `build`, `publish`, `clean`, `install`, `changelog` —
there is no `just check`; lint is bare `ruff check` or `tox -e lint`. `CLAUDE.md` documents the same commands.

## Ruff, isort, and Style Reality

- `pyproject.toml`: `[tool.ruff] line-length = 120`, `fix = true`; `[tool.ruff.lint] select = ["F"]`,
  `fixable = ["F401"]` (undefined names, unused imports/variables, f-string mistakes only — no `E`/`W`,
  no `I`). Import order is enforced solely by `isort` with `profile = "black"`; `ruff format` does not
  sort imports. `requires-python = ">=3.10"`, tox covers 3.10–3.13, so avoid 3.11+-only syntax.
- Because `fix = true`, `ruff check` silently deletes unused imports: review `git diff` after linting.
  Non-`F` style issues pass lint, so follow the visible code pattern: 120 columns, double quotes, type
  annotations on public functions, docstrings, and generator-based `completion()` yielding `LLMResponse`.
- No mypy/pyright config and no coverage gate. Do not add type-checker config, new lint selectors, or
  `# noqa` sprawl unless the task explicitly asks for it.

## Lazy Imports and Optional Dependencies

- Provider SDKs are optional extras in `pyproject.toml` (`gemini` → `google-genai`, `ollama`, `cohere`,
  `mistral`, `doubao` → `volcengine-python-sdk`, ...; the `all` extra aggregates them).
  `ProviderFactory.providers_map` / `create_provider()` in `yaicli/llms/provider.py` load provider modules
  with `importlib.import_module`, so an SDK imports only when that provider is used; provider modules may
  import their SDK at top level. Register new providers in that map — `yaicli/llms/providers/__init__.py`
  is empty, despite older docs/`CLAUDE.md` pointing there.
- `yaicli/tools/mcp.py` keeps `fastmcp` out of startup via `TYPE_CHECKING` imports (`# noqa: F401`) and a
  local `_import_fastmcp()`; `yaicli/tools/__init__.py` wraps `get_mcp_manager`/`get_mcp` in lazy imports.
- `yaicli/functions/buildin/web_search.py` imports `ddgs` inside `execute()` and returns a JSON error with
  an install hint on `ImportError`. Follow that pattern for optional runtime dependencies; never add a
  heavy import to the `yaicli` package import path.

## Test Layout and Shared Fixtures

- Layout: `tests/llms/` (provider/client modules), `tests/tools/` (functions, MCP, approval, schemas),
  and flat modules for CLI/config/roles/printer/history. Both subdirectories are packages; `tests/` is not.
- `tests/conftest.py` provides `patched_config_path` (session-scoped `autouse`; patches
  `yaicli.config.CONFIG_PATH` to a session temp `.config/yaicli/config.ini`), `patched_history_file`
  (session-scoped `autouse`; points `yaicli.cli.HISTORY_FILE`/`const.HISTORY_FILE` at a temp file so
  REPL tests never write the real `~/.yaicli_history` in read-only HOME/CI),
  `setup_test_environment` (session-scoped `autouse`; sets `YAI_PROVIDER=openai`,
  `YAI_API_KEY=test_api_key`, `YAI_MODEL=gpt-3.5-turbo`, mock AWS credentials/region and
  `FIREWORKS_API_KEY`, restored at teardown — mutations leak for the whole session),
  `cli()` (function-scoped `CLI()` on the patched config path, as used by `tests/test_image.py`), and
  `mock_console()` (function-scoped `MagicMock`).
- Test credentials must be in the environment **before** any `yaicli` import: `tests/conftest.py`
  installs `YAI_PROVIDER`/`YAI_API_KEY`/`YAI_MODEL`/AWS/Fireworks values at module import (before
  importing `yaicli.config`/`CLI`, which are now imported inside fixtures) and restores the original
  values at session teardown. A session-scoped fixture is too late — the config singleton is created at
  import, and a fresh HOME would then fail real-provider tests with "API_KEY is required".
- Process-level tests (headless contract, faststart, config-dir resolution) run `sys.executable`
  subprocesses with a private `HOME` + `YAI_CONFIG_DIR` under `tmp_path`, `stdin=DEVNULL`, and the
  inherited `YAI_*`/`XDG_*` variables stripped (`tests/test_runtime_bootstrap.py`,
  `tests/test_headless_contract.py`). Copy that harness instead of touching the real environment.
- Pytest config: `python_files = ["test_*.py"]`; `filterwarnings` ignores `DeprecationWarning`,
  `PendingDeprecationWarning`, `UserWarning`, and pydantic deprecations. Warnings never fail a test —
  assert behavior directly.
- Path-isolation pitfall: patching `yaicli.config.CONFIG_PATH` does not redirect `FUNCTIONS_DIR`,
  `ROLES_DIR`, `MCP_JSON_PATH`, `TOOL_PERMISSIONS_PATH`, `TOOL_AUDIT_PATH`, `TOOL_OUTPUT_DIR` or
  `HISTORY_FILE`; `yaicli/const.py` resolves them once at import from `YAI_CONFIG_DIR`/XDG/`~/.config`.
  Patch the consuming module or pass an explicit path:
  `patch.object(yaicli.tools.function, "FUNCTIONS_DIR", tmp)` (`tests/tools/test_function_loading.py`),
  `patch("yaicli.role.ROLES_DIR")` (`tests/test_role.py`),
  `ToolApprovalManager(permissions_path=tmp_path / "tool_permissions.json")` (`tests/tools/test_approval.py`),
  or patch `yaicli.tools.cfg["TOOL_AUDIT"]`/`const.TOOL_AUDIT_PATH` for permission tests
  (`tests/test_permissions.py`). For a truly fresh config dir, set `YAI_CONFIG_DIR` in a subprocess.

## Test Patterns to Copy

**Providers** (`tests/llms/test_openai_provider.py`, `tests/llms/test_streaming.py`):

- Each test class has a `mock_config` fixture dict with the full key set (`API_KEY`, `BASE_URL`, `MODEL`,
  `TEMPERATURE`, `TOP_P`, `MAX_TOKENS`, `TIMEOUT`, `ENABLE_FUNCTIONS`, `ENABLE_MCP`, ...).
- Mock the SDK client by patching the name the provider module binds at import:
  `patch.object(SomeProvider, "CLIENT_CLS")`, then overwrite `provider.client = MagicMock()` after
  construction — never use a real client. `patch("openai.OpenAI")` does **not** intercept construction
  because `CLIENT_CLS` is bound at import time.
- Build responses as `MagicMock` with explicit fields (`message.content`, `message.reasoning_content =
  None`, `message.model_extra`, `choices`, `finish_reason`); assert yielded `LLMResponse` values and
  `client.chat.completions.create.call_args.kwargs`. Patch schema helpers on the **provider module**,
  not on `yaicli.tools`: OpenAI-family providers do `from ...tools import get_openai_schemas` at import,
  so `@patch("yaicli.tools.get_openai_schemas")` is a no-op. Use
  `@patch("yaicli.llms.providers.openai_provider.get_openai_schemas", return_value=[])`. Exception:
  `anthropic_provider.py` imports `get_anthropic_schemas` lazily inside `completion()`, so its tests
  correctly patch `yaicli.tools.get_anthropic_schemas`; check the import site before choosing a target.
  Many existing test files (7 as of this writing) still carry the no-op decorator — their assertions do
  not depend on the patched value, but the real `FUNCTIONS_DIR` may still be read; do not copy it.
  For streaming, return a list of chunk mocks with `.choices[0].delta`.
- `tests/llms/test_simple_providers.py` is the compact variant for OpenAI-compatible providers; legacy
  `unittest.TestCase` style survives in `tests/test_run_smoke.py` — new tests use pytest classes/functions.

**Tools** (`tests/tools/test_fs_read_file.py`, `tests/tools/test_tools_init.py`):

- Exercise `Function.execute(...)` directly and `json.loads` the result; assert the payload contract
  (`success`, `error`, `size`, multi-file aggregates), not console text.
- Add schema-contract tests against `Function.openai_schema["parameters"]` and
  `Function.anthropic_schema["input_schema"]` (types, `required`, absence of `anyOf`).
- Cover the runtime path with `execute_tool_call(ToolCall(...))` under
  `patch("yaicli.tools.cfg", FAKE_CFG)`, `patch("yaicli.tools.get_function", ...)`, and
  `patch("yaicli.tools.console", ...)`.
- Guard optional-dependency checks with `pytest.importorskip("google.genai")` inside a fixture (only
  `TestFSReadFileGeminiSchema` does this today); use `tmp_path` for all filesystem work. For MCP/lazy
  behavior, patch the package boundary (`patch("yaicli.tools.mcp.get_mcp_manager")`) and assert
  delegation or `MCPToolsError` wrapping — never start a real MCP server.

**CLI**: `tests/test_entry.py` uses `typer.testing.CliRunner().invoke(app, ["--help"])` and patches
`yaicli.cli.CLI`; `tests/test_cli.py` patches `yaicli.cli.get_console`, `Printer`, `FileChatManager`,
`PromptSession`, `pathlib.Path.mkdir` and injects mocks; `tests/test_run_smoke.py` uses `CLI(client=...)`.
`tests/test_headless_contract.py` covers the v0.19 stdout/stderr split, JSON/NDJSON payloads, exit codes
and `--shell` non-TTY behaviour; keep stdout assertions exact (progress/errors must go to stderr).

**Agent loop / context**: `tests/test_context_budget.py` (estimator, 8MB truncation + spill, 500-session
turn-group invariant simulation, context-length self-heal, retry rules, `/context` + `/compact`),
`tests/test_errors.py` (39-provider classification/no-swallow matrix), `tests/test_shell_tool.py`
(timeout/process-group/env/output/danger), `tests/test_permissions.py` (risk gate, rules v2, audit,
prompt/exec argument equality). Use `TemporaryDirectory`/`tmp_path` for spill/output paths.

## Hard Rules

- Mock every external boundary: provider SDKs/HTTP clients, MCP servers, `httpx.Client`
  (`tests/tools/test_fetch_webpage.py`), `ddgs`/web search, and shell execution. Never make real
  network/API calls; a test that reaches the network hangs until the configured `TIMEOUT`.
- Never read or write the developer's real `~/.config/yaicli` (`config.ini`, `functions/`, `roles/`,
  `mcp.json`, `tool_permissions.json`) or the repo working tree. Use `tmp_path`, explicit constructor
  paths, or patch the consuming module (see the path-isolation pitfall above).
- Keep tests deterministic. `tests/test_chat_manage.py` uses `time.sleep(0.1)` to force distinct chat
  timestamps — do not copy that; inject timestamps and avoid sleeps, randomness, and ordering assumptions.
- Do not add huge fixtures casually: `tests/tools/test_fs_read_file.py` writes 11 MB and 2×30 MB temp
  files and takes ~17s locally.
- Optional SDK coverage stays enabled via `uv sync --all-groups --all-extras`; `pytest.importorskip` is
  for the specific optional-SDK assertion, not a way to skip core coverage.

## Verification Gate

Before reporting a Python change complete:

- [ ] `just format` applied; `git diff` reviewed (auto-fix may have removed imports).
- [ ] `ruff check --no-fix yaicli tests` clean.
- [ ] Relevant tests green: tool change → `uv run pytest tests/tools/test_<name>.py` plus
      `tests/tools/test_tools_init.py`; provider change → `tests/llms/test_<provider>_provider.py` plus
      `tests/llms/test_streaming.py` and `tests/test_errors.py`; CLI/config → `tests/test_cli.py
      tests/test_config.py tests/test_entry.py tests/test_headless_contract.py`; context/client →
      `tests/test_context_budget.py tests/llms/test_client.py`; permissions → `tests/test_permissions.py
      tests/llms/test_tool_confirmation.py tests/tools/test_approval.py`.
- [ ] Full suite `uv run pytest` green before finishing cross-cutting changes (client, config, function
      registry, schemas), and at least once with a **fresh HOME and no ambient `YAI_*`/`XDG_*`**
      (`env -u YAI_API_KEY -u YAI_PROVIDER ... HOME=$(mktemp -d) uv run pytest`) so the suite is
      environment-safe (the five `test_image.py` errors found by v0.19 verification came from test
      credentials being set too late).
- [ ] New built-in function in `yaicli/functions/buildin/` has `tests/tools/test_<name>.py` covering
      execute + schema contract, and user-facing docs are updated where behavior is visible:
      `README.md` "Function Call" and `docs/usage/advanced.md` (as done for `fs_read_file`).
- [ ] New provider has a test in `tests/llms/`, is registered in `ProviderFactory.providers_map`, and its
      SDK is declared under `[project.optional-dependencies]` (including `all`) in `pyproject.toml`.
- [ ] `tox -e lint` (or full `tox`) when touching packaging or when CI-parity is requested.

## CI Reality

`.github/workflows/` contains only `publish.yml` (on `v*` tags: hatchling build + PyPI publish) and
`deploy-docs.yml` (on branch `docs`: `mkdocs gh-deploy`). No workflow runs pytest, ruff, or tox, so the
checks above are the only gate. See [guides/index.md](../guides/index.md) for the project thinking guides.
