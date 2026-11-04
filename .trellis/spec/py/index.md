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
_faststart.py (console entry: --version fast path)  ->  entry.py (Typer app)
entry.py (Typer app)  ->  cli.py (CLI: mode dispatch, REPL, headless output)
                          -> llms/client.py (LLMClient: stream + tool loop, budget/retry/depth)
                          -> llms/provider.py (ProviderFactory -> Provider)
                          -> tools/__init__.py (schemas + execute_tool_call + truncation)
                                 -> tools/function.py  (builtin direct-load + user overrides)
                                 -> tools/risk.py      (risk classes / shell danger classification)
                                 -> tools/limits.py    (per-tool output caps + spill)
                                 -> tools/mcp.py       (MCP tools, lazy fastmcp)
                          -> tokens.py         (estimator / budget / turn-group trimming)
                          -> errors.py         (error taxonomy, retry policy, exit codes)
                          -> printer.py / render.py   (streaming + Rich output; machine mode)
```

Module map:

| Module | Owns |
| --- | --- |
| `yaicli/_faststart.py` | Console entry (`ai`/`yaicli`/`python -m yaicli`): answers `-v/--version` with only `sys` + the static `yaicli.__version__` (no config/role import, zero writes), then delegates to `entry.app`. Handles a closed stdout/pipe quietly. |
| `yaicli/entry.py` | Typer app (`YaiApp` restores POSIX SIGPIPE default), CLI options incl. headless (`-p`, `--output-format`, `--json`, `-q`, `--max-turns`, `-y`, `--allowed-tools`, `--cwd`, `--fail-on-tool-denied`), `--list-*`/`--install-functions` callbacks, exit-code mapping, top-level error→stderr rendering. Imports `CLI` lazily inside `main()`. |
| `yaicli/cli.py` | `CLI` orchestrator: runtime mode dispatch (`TEMP_MODE`/`CHAT_MODE`/`EXEC_MODE`), REPL loop, role/session/history wiring, tool-call confirmation `generator.send()` plumbing, headless/JSON/NDJSON output contract and CLI state (`interactive`, `exit_code`, `had_error`, `interrupted`, `depth_limit_reached`, `tool_denied`, `yes`, `allowed_tools`). |
| `yaicli/chat.py` | `Chat` message model + `FileChatManager` (save/load/list/delete chat files; dir created lazily on first save). |
| `yaicli/cmd_handler.py` | `CmdHandler` for slash commands (`/clear`, `/mode`, `/add`, `/context` (+`budget`), `/compact`, `/permissions`, `/save`, ...). |
| `yaicli/completer.py` | prompt_toolkit completer for `/` commands and `@` paths. |
| `yaicli/config.py` | `Config(dict)` singleton `cfg`: env `YAI_*` > config file > `const.DEFAULT_CONFIG_MAP`. Import is write-free; `ensure_config_file()` creates the file lazily (0600/dir 0700, OSError-tolerant). |
| `yaicli/const.py` | Config-dir/path resolution (`YAI_CONFIG_DIR`/XDG/APPDATA/`~/.config`, `get_config_dir()`, `get_history_file()`), `CONFIG_PATH`/`FUNCTIONS_DIR`/`FUNCTIONS_MANIFEST_PATH`/`TOOL_PERMISSIONS_PATH`/`TOOL_AUDIT_PATH`/`TOOL_OUTPUT_DIR`, mode/command constants, `DEFAULT_CONFIG_MAP` + `DEFAULT_CONFIG_INI`. |
| `yaicli/console.py` | `get_console()` singleton `YaiConsole` (Rich, justified-print defaults), `get_error_console()` (stderr twin for diagnostics/headless), `safe_text`/`untrusted_text`/`strip_control_chars`, EPIPE-safe `on_broken_pipe` (exit 0). |
| `yaicli/context.py` | `ContextManager` for `@path` references and `/add` persistent context (recursive dirs, size/binary guards). |
| `yaicli/errors.py` | `ErrorKind`, `AgentError` (kind/status/retryable/hint/user_message), `classify_exception`, `is_retryable`, `retry_after_seconds`, `backoff_delay`, `wrap_provider_exception`/`provider_response_error`, exit-code constants. |
| `yaicli/tokens.py` | Heuristic token estimator (chars/3.5 + CJK), model-window table, `resolve_context_budget()`, turn-group split/trim/repair (`trim_messages_to_budget`, `validate_tool_pairing`), `/context` usage estimate. |
| `yaicli/history.py` | `LimitedFileHistory` (prompt_toolkit history trimming). |
| `yaicli/role.py` | `Role`/`RoleManager`: built-in roles in memory, user JSON files under `ROLES_DIR`; import is write-free, writes only on create/delete (OSError-tolerant). |
| `yaicli/schemas.py` | Shared dataclasses: `ChatMessage`, `LLMResponse`, `ToolCall`, `ToolPolicy`, `RefreshLive`, `ConfirmToolCall`, `ToolConfirmDecision`. |
| `yaicli/output.py` (if present) | Headless result/event helpers; the current implementation keeps this logic in `cli.py` (`_write_text_result`, `_emit_event`, `_build_result`). |
| `yaicli/printer.py` / `yaicli/render.py` | Streaming display, Live region, reasoning/think rendering, faithful tool confirmation preview (parsed args, shell command, fs diff), markdown rendering; `Printer(machine=True)` is the headless plain-text/event renderer (no Live/markdown). |
| `yaicli/image.py` | `--image/-i` input (local files and URLs, base64/validation). |
| `yaicli/function_schema.py` | Lightweight `OpenAISchema` replacing `instructor.OpenAISchema`. |
| `yaicli/functions/` | Builtin function templates (`buildin/`) + install/reinstall/list callbacks and `functions_manifest.json` (version+sha256, stale-copy warning). |
| `yaicli/llms/` | `LLMClient` (tool loop, budget, retry, depth limit), `Provider` ABC/`ProviderFactory`, one module per provider in `providers/`. |
| `yaicli/tools/` | Function schema aggregation/caching, builtin function direct-loading + user overrides, MCP integration, approval store (rules v2 + audit), `risk.py`, `limits.py`, `execute_tool_call` (arg repair, truncation, stderr-aware console). |
| `yaicli/utils.py` | Shell/OS detection, `str2bool`, result-option callbacks, event-loop helper. |

`yaicli/__init__.py` holds the static `__version__` (kept in sync with `pyproject.toml` by
`.bumpversion.cfg`); `_faststart.py` uses it so `--version` avoids `importlib.metadata` (~100 ms+ on
some filesystems). `entry.version_callback` prints the same constant.

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
  never other `yaicli` internals. Since v0.19 they are loaded directly from the installed package as
  the default tool set; same-named user copies under `FUNCTIONS_DIR` override them (so package-relative
  imports would still be unsafe for user copies).
- Use `get_console()` from `yaicli/console.py` for normal output and `get_error_console()` (stderr) for
  warnings/errors/progress that must not pollute scripted stdout; use `Printer`/`render.py` for streaming
  and Live output. Do not create bare `rich.console.Console()` instances in new code.
- Tool results are JSON strings (in-band errors) under `yaicli/functions/buildin/`; the executor in
  `tools/__init__.py` is the single place that parses arguments, truncates output and surfaces failures.
- `errors.py`, `tokens.py`, `tools/risk.py` and `tools/limits.py` are stdlib-only leaf modules: they may
  be imported by `cli.py`, `llms/` and `tools/` without pulling a provider SDK or the Typer app.

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
| New headless flag / exit code | `entry.py` option + `CLI.configure_headless` contract -> `cli.py` output path -> `tests/test_headless_contract.py` -> docs `usage/headless.md` |
| New error kind / retry rule | `errors.py` (`ErrorKind`, classifier) -> client retry/self-heal -> `tests/test_errors.py` |
| New tool risk class / danger rule | `tools/risk.py` -> approval gate in `llms/client.py` -> `tests/test_shell_tool.py`/`tests/test_permissions.py` |
| New context-budget behavior | `tokens.py` -> `llms/client.py` enforcement -> `tests/test_context_budget.py` |

## Quality Gate

```bash
uv sync --all-groups --all-extras     # install all extras (providers + docs + dev)
uv run pytest                         # full suite (or the changed test files)
uv run ruff check yaicli tests        # F rules; also run `just format` for format/isort
tox                                   # optional full matrix (py310-py313)
```

See [quality-guidelines.md](./quality-guidelines.md) for fixtures, mocking rules and known pitfalls.

## Known Discrepancies / Debt (document reality)

- Builtin functions load from the installed package first; a same-named file in
  `~/.config/yaicli/functions/` (left by `--install-functions`) overrides it. That is the documented
  customization path, but an old installed copy silently wins over a newer builtin until
  `ai --reinstall-functions`. The `functions_manifest.json` sha256 check emits a one-line stale-copy
  warning (only once a v0.19 install/reinstall wrote a manifest); pre-v0.19 configs get no warning.
- `buildin` (not `builtin`) is the historical directory name. Do not rename it casually — docs,
  paths and the installer reference it.
- `_faststart.py` answers `-v/--version` before `entry.py`; `entry.version_callback` exists for direct
  `entry.app` invocations (tests, `CliRunner`) and prints the same static constant. Keep the two in sync.
- Headless JSON `usage` is zeroed: `LLMResponse` still has no usage field. Token/cost accounting is a
  later milestone; do not promise real usage numbers in docs yet.
- The `.venv` console scripts (`ai`, `yaicli`) are generated at install time; after changing
  `[project.scripts]` reinstall the package (editable install) before testing `ai` directly.
