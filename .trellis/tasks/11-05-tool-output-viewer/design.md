# Design — tool-output viewer (v0.19.1)

## Data model

`yaicli/tools/output_history.py` (module-level, process lifetime):

```text
ToolOutputEntry:
  index        monotonically increasing id across the session
  turn         incremented by begin_turn() for every user input
  kind         "function" | "mcp"
  name         tool name from the LLM
  arguments    compact argument summary (TOOL_CALL_PREVIEW_MAX_CHARS)
  text         model-visible result (TOOL_OUTPUT_MAX_CHARS cap)
  total_chars  original untruncated length
  spill_path   full spilled output path (or None)
  truncated    whether text was capped
```

- `begin_turn()` is called at the top of `CLI._process_user_input()`.
- `record_output(...)` is called by `execute_tool_call()` after truncation.
- Ring buffer `deque(maxlen=100)`; no disk persistence (spill files already exist).
- `viewer_outputs()` returns `(entries, label)` — current turn, else the newest non-empty turn
  (`label` = `"this turn"` / `"last turn"`).

`limits.py` gains a metadata-returning variant:

- `TruncatedOutput(text, total_chars, spill_path, truncated)`.
- `truncate_tool_output_meta(...)` implements the existing head+tail/spill logic and returns the
  metadata; `truncate_tool_output(...)` delegates and returns `.text` so all existing callers/tests
  keep working. Spill path is captured before the marker string is built.

## Viewer

`yaicli/tool_output_viewer.py` — `prompt_toolkit.Application(full_screen=True)`:

- Alternate screen: closing restores the REPL screen; nothing is appended to scrollback.
- `HSplit(header, VSplit(list | separator | body), footer)`:
  - header: `Tool outputs · <label> · N result(s)` + selected entry title (`[i/N] name · kind ·
    chars · truncated/full-file indicator`);
  - list: `FormattedTextControl` rendering `▸  1. name  (12,345c)`; selection reversed;
  - body: read-only `Buffer` + `BufferControl`, wrapped, cursor-driven scrolling;
  - footer: key help, or a transient notice (`f` states).
- Keys: `↑/↓` select list entry (list pane) / move content cursor (body pane); `Tab`/`Shift+Tab`,
  `←`/`→` switch pane; `PgUp/PgDn`, `Home`/`End` scroll body; `f` toggle model-visible ↔ full
  spilled text (read once, cached per entry, capped at `MAX_FULL_TEXT_CHARS=1_000_000`); `q`,
  `Esc`, `Ctrl+O`, `Ctrl+C` close.
- Body document layout:

  ```text
  @ Function call: execute_shell_command
  arguments: {"command": "pytest -q", "timeout": 120}

  <model-visible text or full spilled text>

  … full output saved to /path/to/tool-outputs/2026…txt
  ```

- `build_viewer_app(entries, label, *, input=None, output=None)` is injectable for tests
  (pipe input + `DummyOutput`, feed `q` to exit).

## REPL wiring

- `Ctrl+O` key binding (in `_setup_key_bindings`) no longer prints: it calls
  `event.app.exit(exception=ToolOutputViewerRequested())` (verified: prompt raised the custom
  exception; raising directly from the handler hangs the event loop — do not do that).
- `_run_repl()` catches `ToolOutputViewerRequested` around `session.prompt(...)`, runs
  `CLI._open_tool_output_viewer()` (synchronous `Application.run()` between prompts), then
  `continue`s the loop.
- `/show-output` (`CmdHandler.handle_show_output`) calls the same CLI method; bare/legacy CLI
  objects fall back to `tools.show_last_tool_output(console)`.
- `open_tool_output_viewer(console)`:
  - empty history → dim notice;
  - not a TTY → dim notice + inline last-output panel (headless/CI safe);
  - viewer exception → dim notice + inline panel (never kills the REPL).

## Generation-time toggle (v0.19.1 follow-up)

Goal: generation keeps running while the viewer is open; closing the viewer redraws the
accumulated stream content back into the chat TUI.

Phased architecture (tracked as subtasks T1–T5):

- **T1 `yaicli/stream_bridge.py`**: `ThreadedStream` runs the completion generator in a worker
  thread and exposes the generator protocol (`__next__`/`send`) to the UI thread over a queue.
  Events: `chunk` / `console` / `done` / `error`; `ConfirmToolCall` waits for the decision handed
  back by `send()`; `abort()` cancels at the next chunk boundary. Console events are drained inside
  `__next__` so their order relative to chunks is preserved.
- **T2 worker output routing**: thread-dispatching console wrapper — writes from the worker are
  queued and replayed in order by the main thread; main-thread writes pass through; a dead bridge
  drops late writes from an abandoned worker instead of corrupting the terminal.
- **T3 CLI wiring**: `_handle_llm_response()` wraps the interactive streaming generator in the
  bridge. The existing Ctrl+O watcher/printer hook now pauses only the Rich `Live` rendering (not
  generation): open viewer → worker keeps producing → close → redraw accumulated content and
  continue. Headless/machine path stays on the classic generator.
- **T4 cancellation & history safety**: Ctrl+C aborts the turn in the UI thread; `abort()` stops
  the worker at its next boundary. The worker mutates a *copy* of the message list; the copy is
  adopted only on success and discarded on abort, so a lingering worker cannot corrupt the next
  turn's history. Tool confirmations requested while the viewer is open are queued and handled
  after it closes.
- **T5 verification**: full regression (stream-json, confirmations, tool policy, headless),
  docs/spec updates.

Known trade-off: a worker blocked in a long provider read or tool execution cannot be interrupted
synchronously (Python signals only reach the main thread); it finishes later, its output goes to a
dead bridge and its message copy is discarded. Tool side effects may still complete — documented.

Interim fallback: the committed paused implementation (`7fcea5f`) stays the default until T3/T4
land; if the bridge cannot start, the CLI falls back to the paused path.

## Alternatives considered

- **Inline print (shipped in `a0db5eb`)**: rejected — scrollback cannot be collapsed; a long
  result still floods the screen when expanded.
- **`less`/`$PAGER` subprocess**: close, but platform-dependent and awkward on Windows.
- **One-document transcript**: simpler, but the user prefers a two-pane selector for turns with
  many tool calls.
- **Show truly full output by default**: rejected — reading multi-MB spill files into a
  prompt_toolkit Buffer is slow; `f` opt-in keeps the default fast.

## Risks / mitigations

- Prompt app nested inside the REPL event loop → use the exception-signal pattern instead of a
  nested `Application.run()`.
- Very many tool calls in one turn → list scrolls; ring buffer caps memory at 100 entries.
- ANSI/OSC injection via tool text → `untrusted_text`/`strip_control_chars` already applied at
  record time; viewer renders via prompt_toolkit `Document` (no Rich markup interpretation).
- Headless runs → viewer unreachable and guarded by the TTY check.
