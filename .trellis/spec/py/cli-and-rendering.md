# CLI & Rendering Guidelines

> Scope: before touching `yaicli/entry.py`, `cli.py`, `chat.py`, `cmd_handler.py`, `completer.py`,
> `printer.py`, `render.py`, `image.py`, `exceptions.py`, or their tests. Config/context internals:
> [config-and-context.md](./config-and-context.md). Cross-layer data flow: [cross-layer guide](../guides/cross-layer-thinking-guide.md).

`entry.py` (Typer surface) → `cli.py` (orchestrator) → `cmd_handler.py` / `chat.py` / `context.py`
(session services) → `printer.py` (display) → `llms/client.py` (generator). Only `entry.py` parses
arguments and only `printer.py` renders output; `entry.py` stays thin: normalize input → build `CLI` →
`cli.run(...)` → map exceptions to messages.

## Entry Points & Typer Surface

- Console scripts (`ai`/`yaicli`) point at `yaicli/_faststart.py:main`. It answers `-v/--version`
  with only `sys` + the static `yaicli.__version__` (no config/role/CLI import, zero writes), catches
  `BrokenPipeError` quietly, and otherwise delegates to `yaicli.entry.app`. `python -m yaicli` uses
  the same path (`__main__.py`). Keep this file tiny: it is the startup budget.
- `YaiApp(typer.Typer)` restores the POSIX default `SIGPIPE` disposition before running a command,
  so `ai --help | head -1` exits 141 quietly instead of 1 with a traceback. `YaiConsole.on_broken_pipe`
  additionally exits 0 for Rich-driven writes.
- Single command `main()`; options are class attributes (`LLMOptions`, `RoleOptions`, `ChatOptions`,
  `ShellOptions`, `CodeOptions`, `OtherOptions`, `MCPOptions`, `ImageOptions`, `FunctionOptions`,
  `HeadlessOptions`) bound in the signature. Add a flag to the class **and** `main()`.
- Config-overriding flags use `override_config`: writes `cfg[param.name.upper()] = value` only when
  `value != param.default`, so untouched flags never clobber config. Booleans use `--x/--no-x` with
  `show_default=False` plus help text showing the effective default.
- Print-and-exit flags (`--version`, `--list-roles`, `--list-chats`, ...) use `@option_callback`
  (`yaicli/utils.py`), which runs the callback then raises `typer.Exit`; never construct `CLI` for
  them, and keep `--version/--help/--template/--list-*` free of config-file creation (K21 contract).
- `main()` input order: `--template` prints `DEFAULT_CONFIG_INI`; `--cwd` is validated/chdir'd before
  relative prompt/image paths resolve; `--max-turns` writes `cfg["MAX_TOOL_CALL_DEPTH"]`; non-TTY stdin
  is read and prepended (`f"{stdin}\n\n{prompt}"`) and forces `--chat=False` with a warning; empty
  prompt + no chat + no `--image` prints `ctx.get_help()` (or exits 2 when a structured output format
  was requested); `--image` sources go through `process_image_source` and an image-only invocation
  gets a minimal prompt; `--role` is ignored with a warning for `--shell`/`--code`.
- Headless flags (`HeadlessOptions`): `-p/--print`, `--output-format {text,json,stream-json}`,
  `--json` (shorthand for json), `-q/--quiet`, `--max-turns`, `-y/--yes`, `--allowed-tools`
  (comma+glob), `--cwd`, `--fail-on-tool-denied`. Non-text formats and `-p` force a one-shot run
  (`--chat` is ignored with a stderr warning). `entry.main` validates the values, calls
  `cfg.ensure_config_file()` only on real-run paths, builds `CLI`, calls
  `cli.configure_headless(...)`, then `_apply_run_tool_policy(...)` to hand `--yes`/`--allowed-tools`
  to the approval manager.
- Only here are exceptions turned into user text: `typer.Exit`/`typer.BadParameter` keep their
  codes; `BrokenPipeError` → 141 quiet; `KeyboardInterrupt` → one stderr line + 130;
  `YaicliError` → `YAICLI Error: <user_message>` on stderr + 1; other `Exception` → `Unknown error`
  on stderr (+ traceback only with `--verbose`) + 1. After a non-chat run the process exits with
  `CLI.exit_code` (`_resolve_exit_code` reads the public attributes, with legacy fallbacks for mocks).

## Runtime Modes & Dispatch (`cli.py`)

- Runtime modes are three strings: `TEMP_MODE` (default single-shot), `CHAT_MODE` (REPL), `EXEC_MODE`
  (generate-then-confirm shell command). There is no code runtime mode: `--code` selects the `CODER` role
  plus `Printer(content_markdown=False)` through `evaluate_role_name`, not a `current_mode`. A fourth mode
  requires updating `get_prompt_tokens()`, `_get_tool_policy()`, `CmdHandler` and prompt-session setup.
- `CLI.evaluate_role_name(code, shell, role)` is the only precedence rule: `code` > `shell`
  > explicit `role` > `DEFAULT`. `set_role()` applies side effects: `CODER` → plaintext `Printer`, `SHELL`
  → `current_mode = EXEC_MODE`.
- `CLI.__init__` derives `interactive` from stdin+stdout TTY and skips `PromptSession` creation and the
  welcome banner when not interactive (headless runs stay cheap and quiet; the REPL builds its own
  session in `prepare_chat_loop()`). It accepts defaulted `print_mode`/`output_format`/`quiet` kwargs so
  ``entry.main`` can pass the headless intent *before* any console/printer/client/prompt-toolkit object
  is built (D3: `-p --json` on a TTY must not create a PromptSession or print to stdout).
  `configure_headless(...)` then applies the remaining flags (yes/allowed-tools/fail-on-denied/
  max-turns/cwd) and is idempotent. `_sync_client_console()` re-points both `client.console` and
  `client.provider.console` at the stderr console in machine mode (D1/D2) — provider verbose dumps and
  error bodies must never reach structured stdout.
- Public state contract consumed by `entry.py` (keep these names): `interactive`, `exit_code`,
  `had_error`, `interrupted`, `depth_limit_reached`, `tool_denied`, plus `yes`, `allowed_tools`,
  `fail_on_tool_denied`, `output_format`, `quiet`, `machine_output`. `_finalize_exit_code()` maps them:
  interrupted → 130, denied + `--fail-on-tool-denied` → 3, handled error / depth limit (when
  `EXIT_ON_DEPTH_LIMIT`) → 1, else 0. The client reports depth/denial via its own flags; the CLI
  mirrors them after each turn.
- `CLI.run()`: `chat=True` loads a session by `user_input` title then calls `_run_repl()`; otherwise
  `_run_once()` = `set_role(...)` + `_process_user_input()`. Empty `user_input` with `chat=False` raises
  `typer.Abort`; `entry.main` makes sure image-only calls pass a non-empty prompt.
- DI seam: `CLI(verbose, role, chat_manager, role_manager, context_manager, client)`, defaulting to the
  singletons `chat_mgr`/`role_mgr`/`ctx_mgr`; tests pass `MagicMock`s and overwrite `cli.console`/`cli.session`.
  `__init__` resolves "auto" `OS_NAME`/`SHELL_NAME` via `detect_os`/`detect_shell`; `--verbose` masks `API_KEY`
  and in machine mode writes to stderr.

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
  **filtering out every `role == "system"`**. Context economy (v0.19): `LLMClient` enforces the token
  budget before each request using `yaicli/tokens.py` (turn-group trimming: a `user` message group with
  its assistant/tool messages moves in and out together; leading system/context messages preserved;
  never an orphan `role=tool` or an unanswered `assistant(tool_calls)`), prints one stderr notice, and
  recovers from a context-length 400 by trimming one group and retrying once. `CLI._check_history_len()`
  keeps `INTERACTIVE_ROUND * 2` only as a group-aligned max-message cap; real retention is
  `CONTEXT_BUDGET_TOKENS` (0 = 70% of the model window). `/context` shows the estimate and
  `/compact [keep_rounds]` trims whole turn groups. Do not reintroduce count-only slicing of
  `chat.history`.
- Headless output: stdout carries only the result (`content`), one JSON object, or NDJSON events;
  labels/banners/progress/errors go to `get_error_console()`. `Printer(machine=True)` renders plain
  text/events with no Live/Markdown, and auto-denies interactive confirmations. JSON keys are exactly
  `{content, tool_calls, usage, model, provider, error, exit_code}` (`usage` zeroed until token
  accounting lands); stream-json events are `turn_start/text_delta/tool_call/tool_result/usage/done`.
  Text mode ends with exactly one newline; `--quiet` prints the answer only.
- `_confirm_and_execute()` is the only exec-mode execution path: `filter_command()` strips markdown fences,
  a `Panel` titled "Suggest Command" is shown, `Prompt.ask` offers `y/n/e`, `e` edits via
  `prompt_toolkit.prompt` (EOF cancels), and only then `subprocess.call(cmd, shell=True)`.

## REPL & Interaction

- `prepare_chat_loop()` sets `CHAT_MODE`, installs Shift+Tab (`s-tab`) chat/exec toggling in
  `_setup_key_bindings()`, makes the `HISTORY_FILE` setup OSError-tolerant (read-only HOME / container:
  warn once, continue without history; never crash), then builds `PromptSession` with
  `LimitedFileHistory(HISTORY_FILE, max_entries=cfg["MAX_HISTORY"])` (a non-positive `MAX_HISTORY`
  disables history saving), `AutoSuggestFromHistory()` when `cfg["AUTO_SUGGEST"]`, `AtPathCompleter()`,
  `complete_while_typing=True`; on failure it falls back to `PromptSession(key_bindings=...)` and prints
  `Error initializing prompt session history: {e}`. `_setup_key_bindings()` also binds `c-o`:
  the handler calls `event.app.exit(exception=ToolOutputViewerRequested())` (never `raise` inside the
  handler; that hangs the prompt event loop), and `_run_repl()` catches the signal, runs
  `CLI._open_tool_output_viewer()` (a synchronous alt-screen `prompt_toolkit.Application`) and
  continues. `/show-output` (`CmdHandler.handle_show_output`) opens the same viewer.
- `_run_repl()` loop: separator → `session.prompt(self.get_prompt_tokens)` → strip → skip blank →
  `_handle_special_commands()` (tri-state `False`=exit, `True`=handled, `str`=prompt) →
  `_process_user_input()`. SIGINT semantics (v0.19, consistent with the headless contract): a single
  Ctrl-C at the prompt clears the current input and keeps the REPL alive; a second Ctrl-C within
  `DOUBLE_CTRL_C_WINDOW_SECONDS` (~2s) exits the REPL (a prompt read resets the window); Ctrl-D exits
  0; Ctrl-C during a turn cancels that turn and keeps the REPL alive, with the next Ctrl-C at the
  prompt exiting. One-shot runs exit 130 on SIGINT.
  Autosave on exit only when `not is_temp_session and chat.history`.
- `sys.stdin.isatty()` appears exactly three times: `entry.main` (stdin merge, `--chat` warning), `CLI.__init__`
  (skip the first `PromptSession` when not interactive), and `_create_client(interactive=...)`
  (non-TTY tool confirmation denies instead of blocking — the K06 gate additionally applies
  `--yes`/`--allowed-tools`).

## Tool Confirmation Protocol (generator + `send()`)

`Printer.display_stream()` drives the generator manually: `next()` normally, `generator.send(...)` after a
confirmation. Contract defined by `LLMClient.completion_with_tools()` and `schemas.py`:

1. `LLMResponse` chunks are rendered in the `Live` region.
2. `ConfirmToolCall` arrives → stop the live, `_confirm_tool_call()` (`Panel` + `Prompt.ask` with
   `y`/`a`/`A`/`n`), then `generator.send(ToolConfirmDecision)` and start a fresh live. The panel must
   show the *canonical* arguments (same repaired dict that executes), with specialized previews for
   shell commands / `fs_write_file` / `fs_edit_file` (diff head 40) and the shell danger reasons.
3. `ONCE`; `SESSION` → `approval.allow_session`; `PERSIST` → `allow_persist` (fallback to session on
   `OSError`); `DENY` → client appends a matching tool-result message: structured JSON
   `{"error": "tool_denied", "reason": "..."}` with the same `tool_call_id`, and sets
   `LLMClient.tool_denied`. Gate details (risk classes, rules v2, `--yes` read-only, danger
   double-confirm, audit) are in [function-tool-guidelines.md](./function-tool-guidelines.md).
   `RefreshLive` starts a new tool round (flush reasoning, reset accumulators, restart live); `StopLive` is
   declared but unused. Never materialize this generator or call `next()` outside `Printer`.

## Slash Commands & Completion

- `CmdHandler.commands` maps `const.CMD_*` constants to handlers; exact matches first, then prefix match for
  argument-taking commands (`/save`, `/load`, `/del`, `/mode`, `/add`, `/context`, `/compact`,
  `/permissions`). Aliases: `/ctx`, `/chats`, `?`, and `!`/`！` → `subprocess.call(shell=True)`.
  `handle_command()` returns `True` (continue), `False` (exit) or the original input; handlers return
  `bool` and print via `self.cli.console`.
- `/add`, `/context` use `shlex.split` (quoted paths work) and strip one leading `@`; bad quoting prints
  `Error parsing command`. Bare `/context` prints the estimated token usage block **and** the legacy
  file-context list; subcommands `list|clear|add <path>|remove <path>` are unchanged, and
  `budget|stats|usage` prints only the usage block.
- `/compact [keep_rounds]` (default 5) trims the conversation to whole turn groups and reports
  before→after estimated tokens; it must never split tool pairs. `/permissions [revoke <tool-or-index>]`
  lists session/persisted/rules and revokes persisted entries.
- New command checklist: constant in `const.py` (or cmd_handler-local like `CMD_COMPACT`) → register in
  `CmdHandler.commands` → usage line in `cli.print_help()` → path prefix in `completer.py`
  (`_is_context_command`) if it takes a path (`tests/test_command_handler.py` covers shlex errors,
  missing args, aliases, tri-state return).
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

`yaicli/exceptions.py` is the base taxonomy (`YaicliError` + `ConfigError`, `ProviderError`,
`ChatSaveError`, `ChatLoadError`, `ChatDeleteError`, `MCPToolsError`). Since v0.19 failures are
classified: `yaicli/errors.py` defines `ErrorKind`, `AgentError(ProviderError)` (kind/status/retryable/
`user_message`/`hint`), `classify_exception()` (duck-typed HTTP status, SDK exception class names,
message patterns), `is_retryable()`, `retry_after_seconds()`, `backoff_delay()`, provider wrappers and
the `EXIT_*` codes. Providers raise classified errors; `LLMClient` retries retryable failures before
any content was streamed and self-heals context-length errors; `entry.py`/`cli.py` render
`user_message` (kind + HTTP status + Hint) to stderr and map the process exit code.

Output goes through `get_console()` (`yaicli/console.py`, a `YaiConsole` singleton defaulting `justify`
to `cfg["JUSTIFY"]`) or, for anything that must not pollute scripted stdout (warnings/errors/progress
in machine mode), `get_error_console()` (stderr twin). No bare `rich.console.Console()` in feature code.
No `print()` in `CLI`/`CmdHandler`/`Printer`: the existing exceptions are `entry.py` meta-flag output,
the `@Function call`/`@MCP call` debug lines (routed to the TTY-aware tool console), and
`ProviderFactory.list_providers`. Tests inject `mock_console`.

Untrusted text (model output, tool arguments/results, file names, chat titles, provider error
bodies) must never be interpolated into a Rich markup string: use `safe_text()`/`untrusted_text()`/
`print_untrusted()` from `yaicli/console.py` (helpers also strip C0/C1 control characters to prevent
ANSI/OSC terminal injection; `tests/test_markup_safety.py` covers the sink list). A single bad
turn must not kill the REPL: `_run_repl()` catches unexpected exceptions per turn and keeps
looping. Handled failures set `CLI.had_error`/`error_kind`; `entry.main()` maps the CLI state to the
exit-code contract (0/1/2/3/130/141). `ConfigError` exits 1 at import time (S5 contract).

## Verification

```bash
uv run pytest tests/test_entry.py tests/test_cli.py tests/test_printer.py tests/test_render.py \
  tests/test_completer.py tests/test_command_handler.py tests/test_event_loop.py \
  tests/test_headless_contract.py tests/test_permissions.py -q
```

Fixtures live in `tests/conftest.py` (`patched_config_path`, `patched_history_file`,
`setup_test_environment`, `cli`, `mock_console`); `tests/test_cli.py` adds `mock_api_client` /
`mock_printer` / `mock_chat_manager` / `cli_with_mocks`. Never call a real API: mock
`client.completion_with_tools` and `Printer.display_stream` when not testing rendering. Headless tests
drive `CliRunner`/subprocesses with a private `HOME`/`YAI_CONFIG_DIR` and assert stdout purity and exit
codes (`tests/test_headless_contract.py`).
