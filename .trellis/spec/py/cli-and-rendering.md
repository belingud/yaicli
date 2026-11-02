# CLI & Rendering Guidelines

> Scope: before touching `yaicli/entry.py`, `cli.py`, `chat.py`, `cmd_handler.py`, `completer.py`,
> `printer.py`, `render.py`, `image.py`, `exceptions.py`, or their tests. Config/context internals:
> [config-and-context.md](./config-and-context.md). Cross-layer data flow: [cross-layer guide](../guides/cross-layer-thinking-guide.md).

`entry.py` (Typer surface) → `cli.py` (orchestrator) → `cmd_handler.py` / `chat.py` / `context.py`
(session services) → `printer.py` (display) → `llms/client.py` (generator). Only `entry.py` parses
arguments and only `printer.py` renders output; `entry.py` stays thin: normalize input → build `CLI` →
`cli.run(...)` → map exceptions to messages.

## Typer Entry (`entry.py`)

- Single command `main()`; options are class attributes (`LLMOptions`, `RoleOptions`, `ChatOptions`,
  `ShellOptions`, `CodeOptions`, `OtherOptions`, `MCPOptions`, `ImageOptions`, `FunctionOptions`) bound in
  the signature (`model: str = LLMOptions.model`). Add a flag to the class **and** `main()`.
- Config-overriding flags use `override_config` (`entry.py:30`): writes `cfg[param.name.upper()] = value`
  only when `value != param.default`, so untouched flags never clobber config. Hence defaults come from
  `cfg[...]` at import time, and booleans use `--x/--no-x` with `show_default=False` plus help text showing
  the effective default.
- Print-and-exit flags (`--version`, `--list-roles`, `--list-chats`, ...) use `@option_callback`
  (`yaicli/utils.py`), which runs the callback then raises `typer.Exit`; never construct `CLI` for them.
- `main()` input order: `--template` prints `DEFAULT_CONFIG_INI`; non-TTY stdin is read and prepended
  (`f"{stdin}\n\n{prompt}"`) and forces `--chat=False` with a warning; empty prompt + no chat + no
  `--image` prints `ctx.get_help()`; `--image` sources go through `process_image_source`
  (`typer.BadParameter` → exit 1) and an image-only invocation gets a minimal prompt
  (`Describe the image.` / `Describe these images.` for several); `--role` is ignored with a warning for
  `--shell`/`--code`.
- Only here are exceptions turned into user text: `YaicliError` → `YAICLI Error: ...`,
  `typer.Abort`/`typer.Exit` swallowed, other `Exception` → `Unknown error: ...`; `tests/test_entry.py`
  drives it with `typer.testing.CliRunner` + `patch("yaicli.cli.CLI", ...)`.

## Runtime Modes & Dispatch (`cli.py`)

- Runtime modes are three strings: `TEMP_MODE` (default single-shot), `CHAT_MODE` (REPL), `EXEC_MODE`
  (generate-then-confirm shell command). There is no code runtime mode: `--code` selects the `CODER` role
  plus `Printer(content_markdown=False)` through `evaluate_role_name`, not a `current_mode`. A fourth mode
  requires updating `get_prompt_tokens()`, `_get_tool_policy()`, `CmdHandler` and prompt-session setup.
- `CLI.evaluate_role_name(code, shell, role)` (`cli.py:154`) is the only precedence rule: `code` > `shell`
  > explicit `role` > `DEFAULT`. `set_role()` applies side effects: `CODER` → plaintext `Printer`, `SHELL`
  → `current_mode = EXEC_MODE`.
- `CLI.run()`: `chat=True` loads a session by `user_input` title then calls `_run_repl()`; otherwise
  `_run_once()` = `set_role(...)` + `_process_user_input()`. Empty `user_input` with `chat=False` raises
  `typer.Abort`; `entry.main` makes sure image-only calls pass a non-empty prompt, so this only fires for
  direct `CLI.run` callers.
- DI seam: `CLI(verbose, role, chat_manager, role_manager, context_manager, client)`, defaulting to the
  singletons `chat_mgr`/`role_mgr`/`ctx_mgr`; tests pass `MagicMock`s and overwrite `cli.console`/`cli.session`.
  `__init__` resolves "auto" `OS_NAME`/`SHELL_NAME` via `detect_os`/`detect_shell`; `--verbose` masks `API_KEY`.

## Message Assembly & Tool Policy

- `_build_messages()` is the single request assembler, in order: role system prompt → persistent context
  (`ContextManager.get_context_messages()`) → temporary `@` refs as a system message → `chat.history` →
  user message with `images + at_images`. The `NO_VISION_PROVIDERS` (`const.py`) guard drops images here.
- Images: repeatable `--image/-i` is processed in `entry.main` by `process_image_source()` (http(s) URL →
  `ImageData(is_url=True)`; local path → `validate_local_image()` then base64, `typer.BadParameter` → exit
  1). `@image.png` becomes `ImageData` via `ContextManager.parse_at_references()` instead of text.
  Image-only invocations are handled in `entry.main`, which substitutes `Describe the image.` /
  `Describe these images.` so `CLI.run()` never receives an empty prompt.
- `_get_tool_policy()` (`cli.py:308`) is the single `ToolPolicy` source: `EXEC_MODE` disables functions
  **and** MCP; else pass `cfg["ENABLE_FUNCTIONS"]`/`cfg["ENABLE_MCP"]`. The client intersects it with the
  provider default (`Provider.resolve_tool_policy`), so disable tools here, never ad hoc.
- After each turn `_process_user_input()` rebuilds `chat.history` from the client-returned messages
  **filtering out every `role == "system"`**, then `_check_history_len()` trims to `INTERACTIVE_ROUND * 2`
  messages. `INTERACTIVE_ROUND` is the in-conversation budget only; the prompt-history file is bounded by
  `MAX_HISTORY` (below). `tests/test_cli.py::TestMessageFiltering` locks the filtering in.
- `_confirm_and_execute()` is the only exec-mode execution path: `filter_command()` strips markdown fences,
  a `Panel` titled "Suggest Command" is shown, `Prompt.ask` offers `y/n/e`, `e` edits via
  `prompt_toolkit.prompt` (EOF cancels), and only then `subprocess.call(cmd, shell=True)`.

## REPL & Interaction

- `prepare_chat_loop()` sets `CHAT_MODE`, installs Shift+Tab (`s-tab`) chat/exec toggling in
  `_setup_key_bindings()`, touches `HISTORY_FILE`, then builds `PromptSession` with
  `LimitedFileHistory(HISTORY_FILE, max_entries=cfg["MAX_HISTORY"])` (a non-positive `MAX_HISTORY`
  disables history saving), `AutoSuggestFromHistory()` when `cfg["AUTO_SUGGEST"]`, `AtPathCompleter()`,
  `complete_while_typing=True`; on failure it falls back to `PromptSession(key_bindings=...)` and prints
  `Error initializing prompt session history: {e}`. `INTERACTIVE_ROUND` is unrelated: it only bounds the
  chat messages kept by `_check_history_len()` (`* 2`).
- `_run_repl()` loop: separator → `session.prompt(self.get_prompt_tokens)` → strip → skip blank →
  `_handle_special_commands()` (tri-state `False`=exit, `True`=handled, `str`=prompt) →
  `_process_user_input()`. `KeyboardInterrupt` during a turn is printed and continues; at the prompt it
  exits. Autosave on exit only when `not is_temp_session and chat.history`.
- `sys.stdin.isatty()` appears exactly three times: `entry.main` (stdin merge, `--chat` warning), `CLI.__init__`
  (swap `sys.stderr` to `devnull` around the first `PromptSession`), and `_create_client(interactive=...)`
  (non-TTY tool confirmation denies instead of blocking).

## Tool Confirmation Protocol (generator + `send()`)

`Printer.display_stream()` drives the generator manually: `next()` normally, `generator.send(...)` after a
confirmation. Contract defined by `LLMClient.completion_with_tools()` and `schemas.py`:

1. `LLMResponse` chunks are rendered in the `Live` region.
2. `ConfirmToolCall` arrives → stop the live, `_confirm_tool_call()` (`Panel` + `Prompt.ask` with
   `y`/`a`/`A`/`n`), then `generator.send(ToolConfirmDecision)` and start a fresh live.
3. `ONCE`; `SESSION` → `approval.allow_session`; `PERSIST` → `allow_persist` (fallback to session on
   `OSError`); `DENY` → client appends a matching tool-result message so the next request stays valid.
   `RefreshLive` starts a new tool round (flush reasoning, reset accumulators, restart live); `StopLive` is
   declared but unused. Never materialize this generator or call `next()` outside `Printer`.

## Slash Commands & Completion

- `CmdHandler.commands` maps `const.CMD_*` constants to handlers; exact matches first, then prefix match for
  argument-taking commands (`/save`, `/load`, `/del`, `/mode`, `/add`, `/context`). Aliases: `/ctx`,
  `/chats`, `?`, and `!`/`！` → `subprocess.call(shell=True)`. `handle_command()` returns `True` (continue),
  `False` (exit) or the original input; handlers return `bool` and print via `self.cli.console`.
- `/add`, `/context` use `shlex.split` (quoted paths work) and strip one leading `@`; bad quoting prints
  `Error parsing command`. `/context` handles `list|clear|add <path>|remove <path>` (`rm|delete|del`
  aliases), listing by default.
- New command checklist: constant in `const.py` → register in `CmdHandler.commands` → usage line in
  `cli.print_help()` → path prefix in `completer.py` (`_is_context_command`, lines 27-29) if it takes
  a path (`tests/test_command_handler.py` covers shlex errors, missing args, aliases, tri-state return).
- `AtPathCompleter(base_dir=Path.cwd())` fires only on `@` in `document.text_before_cursor` or the `/add`,
  `/context add`, `/context remove` prefixes. Completions are relative to `base_dir`, directories get `/`,
  spaces are quoted, hidden files are listed, `display_meta` is `[DIR]` or the suffix, and
  `OSError`/`PermissionError` are swallowed. Keep the `base_dir` parameter (`tests/test_completer.py`).

## Rendering (`printer.py`, `render.py`)

- `Printer` dataclass (`console`, `config`, `content_markdown=True`): `__post_init__` caches
  `code_theme`/`show_reasoning` and chooses `content_formatter` = `Markdown` or `plain_formatter`;
  `Printer(content_markdown=False)` is the code-mode renderer.
- Reasoning is append-only console output, not live-rendered: `_emit_reasoning()` emits whole lines only
  (`> ` prefix, `style="dim", markup=False, highlight=False` — model text is not Rich markup), buffers a
  partial trailing line, and flushes on content start, `RefreshLive` and `finally`.
- Content renders in `Live(console=self.console, auto_refresh=False)` with explicit
  `live.update(..., refresh=True)`; auto-refresh is deliberately off (no refresh thread racing tool-output
  `console.print`). Keep `_safe_stop_live` + `finally`: errors must stop the live and re-raise.
- `<think>` tags inside content are split into reasoning by `_check_and_update_think_tags()`
  (`in_reasoning` state); native reasoning arrives via `LLMResponse.reasoning`. `SHOW_REASONING=false`
  suppresses both header and body.
- `render.py`: `JustifyMarkdown` defaults `justify` to `cfg["JUSTIFY"]` (explicit argument wins),
  `plain_formatter` is identity, and `printer.py` imports `Markdown` **from `render.py`** (relying on its
  module-level re-export) — keep that import when refactoring.
- Render tests build `Printer(console=Console(file=StringIO(), width=80))` for real output, replace
  `printer.console`/`printer.config` with `MagicMock`s, or `patch("yaicli.printer.Live")`.

## Errors, Console & Output

`yaicli/exceptions.py` is the taxonomy: `YaicliError` base + `ConfigError`, `ConfigMissingError`, `ProviderError`,
`ChatSaveError`, `ChatLoadError`, `ChatDeleteError`, `MCPToolsError`; raise the specific subclass in the failing
layer and catch `YaicliError` only at `entry.py` or a REPL boundary that keeps looping. Output goes through
`get_console()` (`yaicli/console.py`, a `YaiConsole` singleton defaulting `justify` to `cfg["JUSTIFY"]`) or
`typer.echo` in `entry.py`: no bare `rich.console.Console()` in feature code and no `print()` in `CLI`/`CmdHandler`/
`Printer` (existing: `entry.py`, the `@Function call`/`@MCP call` debug lines, `ProviderFactory.list_providers`). Tests
inject `mock_console`.

Untrusted text (model output, tool arguments/results, file names, chat titles, provider error
bodies) must never be interpolated into a Rich markup string: use `safe_text()`/`untrusted_text()`/
`print_untrusted()` from `yaicli/console.py` (helpers also strip C0/C1 control characters to prevent
ANSI/OSC terminal injection; `tests/test_markup_safety.py` covers the sink list). A single bad
turn must not kill the REPL: `_run_repl()` catches unexpected exceptions per turn and keeps
looping (KeyboardInterrupt/EOF keep their original semantics). Handled failures set
`CLI.had_error`; `entry.main()` maps that to `typer.Exit(1)` in single-shot mode, and `ConfigError`
exits `1` at import time (S5 contract).

## Verification

```bash
uv run pytest tests/test_entry.py tests/test_cli.py tests/test_printer.py tests/test_render.py \
  tests/test_completer.py tests/test_command_handler.py tests/test_event_loop.py -q
```

Fixtures live in `tests/conftest.py` (`patched_config_path`, `setup_test_environment`, `cli`, `mock_console`);
`tests/test_cli.py` adds `mock_api_client` / `mock_printer` / `mock_chat_manager` / `cli_with_mocks`.
Never call a real API: mock `client.completion_with_tools` and `Printer.display_stream` when not testing
rendering.
