# YAICLI Python Package — Development Guidelines

`yaicli/` is the whole product: a Typer-based CLI plus the provider, function-calling and rendering
stack behind it. This index covers code under `yaicli/`. Repository-wide rules (commits, docs,
release) live in [../repo/index.md](../repo/index.md).

## Pre-Development Checklist

1. Read this file, then the layer doc that matches the code you are about to touch:

   | Area you are changing | Read |
   | --- | --- |
   | Provider, streaming, message conversion, LLM client loop | [provider-guidelines.md](./provider-guidelines.md) |
   | Function calling, builtin functions, tool approval, MCP | [function-tool-guidelines.md](./function-tool-guidelines.md) |
   | CLI modes, REPL, slash commands, rendering, images | [cli-and-rendering.md](./cli-and-rendering.md) |
   | Config layering, roles, history, `@path` context | [config-and-context.md](./config-and-context.md) |
   | Tests, lint, formatting, verification commands | [quality-guidelines.md](./quality-guidelines.md) |

2. Skim the shared thinking guides: [../guides/index.md](../guides/index.md).
3. Decide whether the change is user-visible. If it is, plan the docs update in the same change
   (`README.md` and the matching `docs/` page, plus `mkdocs.yml` nav for a new page).
4. Run the quality gate at the end (below). Never claim "done" without the relevant tests and
   `ruff check yaicli tests`.

## Architecture

Entry flow (verified against imports in the tree):

```
entry.py (Typer app)  ->  cli.py (CLI: mode dispatch, REPL)
                          -> llms/client.py (LLMClient: stream + tool loop)
                          -> llms/provider.py (ProviderFactory -> Provider)
                          -> tools/__init__.py (schemas + execute_tool_call)
                                 -> tools/function.py  (builtin functions)
                                 -> tools/mcp.py       (MCP tools, lazy fastmcp)
                          -> printer.py / render.py   (streaming + Rich output)
```

Module map:

| Module | Owns |
| --- | --- |
| `yaicli/entry.py` | Typer app, CLI options, `--list-*`/`--install-functions` callbacks, top-level error handling. Imports `CLI` lazily inside `main()` (line ~409) so `--help` and simple flags stay fast. |
| `yaicli/cli.py` | `CLI` orchestrator: runtime mode dispatch (`TEMP_MODE`/`CHAT_MODE`/`EXEC_MODE`; `--code` is the CODER role + plaintext printer, not a runtime mode), REPL loop, role/session/history wiring, tool-call confirmation `generator.send()` plumbing. |
| `yaicli/chat.py` | `Chat` message model + `FileChatManager` (save/load/list/delete chat files). |
| `yaicli/cmd_handler.py` | `CmdHandler` for slash commands (`/clear`, `/mode`, `/add`, `/context`, `/save`, ...). |
| `yaicli/completer.py` | prompt_toolkit completer for `/` commands and `@` paths. |
| `yaicli/config.py` | `Config(dict)` singleton `cfg`: env `YAI_*` > `~/.config/yaicli/config.ini` > `const.DEFAULT_CONFIG_MAP`. |
| `yaicli/const.py` | Paths (`CONFIG_PATH`, `FUNCTIONS_DIR`, `HISTORY_FILE`, ...), mode/command constants, `DEFAULT_CONFIG_MAP`. |
| `yaicli/console.py` | `get_console()` singleton `YaiConsole` (Rich) with justified-print defaults. |
| `yaicli/context.py` | `ContextManager` for `@path` references and `/add` persistent context (recursive dirs, size/binary guards). |
| `yaicli/history.py` | `LimitedFileHistory` (prompt_toolkit history trimming). |
| `yaicli/role.py` | `Role`/`RoleManager` for `~/.config/yaicli/roles/`. |
| `yaicli/schemas.py` | Shared dataclasses: `ChatMessage`, `LLMResponse`, `ToolCall`, `ToolPolicy`, `RefreshLive`, `ConfirmToolCall`, `ToolConfirmDecision`. |
| `yaicli/printer.py` / `yaicli/render.py` | Streaming display, Live region, reasoning/think rendering, tool confirmation prompt, markdown rendering. |
| `yaicli/image.py` | `--image/-i` input (local files and URLs, base64/validation). |
| `yaicli/function_schema.py` | Lightweight `OpenAISchema` replacing `instructor.OpenAISchema`. |
| `yaicli/functions/` | Builtin function templates (`buildin/`) + install/reinstall/list callbacks. |
| `yaicli/llms/` | `LLMClient`, `Provider` ABC/`ProviderFactory`, and one module per provider in `providers/`. |
| `yaicli/tools/` | Function schema aggregation/caching, builtin function loading, MCP integration, approval store. |
| `yaicli/utils.py` | Shell/OS detection, `str2bool`, result-option callbacks, event-loop helper. |

`yaicli/__init__.py` is intentionally empty; the version comes from `importlib.metadata`
(`entry.py` uses `pkg_version("yaicli")`), not a module-level constant.

## Dependency Rules

- `entry.py` is the only module that builds the Typer app. Keep heavy imports (`CLI`, provider SDKs)
  inside command functions, not at module top — startup time matters for a CLI.
- `cli.py` may import any top-level subsystem. Subsystems must not import `cli.py`/`entry.py`
  (no cycles back into the orchestrator).
- `llms/client.py` may import `tools/` (it executes tool calls); `tools/` must not import
  `llms.providers` or the CLI.
- Provider modules (`llms/providers/*.py`) may import `..schemas`, `..config`, `..console`,
  `..utils`, and the tool-schema helpers in `...tools`. They are imported on demand by
  `ProviderFactory.providers_map` (in `llms/provider.py`) via `importlib`, so a top-level
  `import google.genai`/`import ollama` inside a provider file is intentional.
- Shared heavy/optional imports outside providers stay lazy: `tools/mcp.py` imports `fastmcp` inside
  `_import_fastmcp()` "to improve startup time", and `tools/function.py` imports function files with
  `importlib.util.spec_from_file_location`.
- Builtin function templates in `yaicli/functions/buildin/*.py` are **standalone**: they may import
  stdlib, third-party libs declared in `pyproject.toml`, `pydantic`, and `yaicli.function_schema` —
  never other `yaicli` internals. At runtime they are copied to `~/.config/yaicli/functions/` and
  executed as separate modules, so package-relative imports will break.
- Use `get_console()` from `yaicli/console.py` for output; use `Printer`/`render.py` for streaming
  and Live output. Do not create bare `rich.console.Console()` instances in new code.
- Tool results are JSON strings (in-band errors) under `yaicli/functions/buildin/`; the executor in
  `tools/__init__.py` is the single place that parses arguments and surfaces failures.

## Where New Code Goes

| Change | Files |
| --- | --- |
| New CLI flag / option | `yaicli/entry.py` (Typer option) -> `yaicli/cli.py`; config key -> `const.DEFAULT_CONFIG_MAP` + `docs/usage/configuration.md` |
| New slash command | `const.CMD_*` -> `cmd_handler.py` dispatch -> docs `usage/commands.md` |
| New provider | `llms/providers/<name>_provider.py` -> `ProviderFactory.providers_map` -> `tests/llms/` -> `docs/providers/` -> optional extra in `pyproject.toml` |
| New builtin function | `functions/buildin/<name>.py` -> `tests/tools/test_<name>.py` -> mention in README/docs |
| Provider-agnostic tool policy / approval change | `tools/approval.py` + `llms/client.py` gate; update `openspec/specs/` when behavior is specified |
| New rendering/streaming behavior | `printer.py` / `render.py` -> `tests/test_printer.py` / `tests/test_render.py` |
| New config value | `const.DEFAULT_CONFIG_MAP` (env key + type) -> `config.py` wiring -> docs `usage/configuration.md` |

## Quality Gate

```bash
uv sync --all-groups --all-extras     # install all extras (providers + docs + dev)
uv run pytest                         # full suite (or the changed test files)
uv run ruff check yaicli tests        # F rules; also run `just format` for format/isort
tox                                   # optional full matrix (py310-py313)
```

See [quality-guidelines.md](./quality-guidelines.md) for fixtures, mocking rules and known pitfalls.

## Known Discrepancies / Debt (document reality)

- `CLAUDE.md` still says "add to provider imports in `yaicli/llms/providers/__init__.py`". That file
  is empty; the real registration point is `ProviderFactory.providers_map` in
  `yaicli/llms/provider.py`. Follow the code, and fix `CLAUDE.md` when you touch provider
  registration.
- Runtime loads builtin functions from `~/.config/yaicli/functions/`; updating
  `yaicli/functions/buildin/` in the source tree only reaches an existing install after
  `ai --reinstall-functions`. Keep this in mind when a "function schema change" looks ignored.
- `buildin` (not `builtin`) is the historical directory name. Do not rename it casually — docs,
  paths and the installer reference it.
