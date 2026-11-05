# T3 — Background generation CLI wiring

## Goal

Use StreamBridge for interactive streaming: Ctrl+O opens the viewer while the worker keeps generating; closing redraws accumulated content; headless/machine path unchanged; tests.

## Requirements

- Interactive TTY streaming runs `completion_with_tools()` on a `ThreadedStream` worker; the
  REPL/main thread consumes the adapter through the unchanged `Printer.display_stream()`.
- Ctrl+O during generation opens the viewer while the worker keeps producing; closing redraws the
  accumulated content and streaming continues (the printer pause hook now pauses rendering only).
- Worker console output is routed (`install_worker_console_routing` + client/provider consoles) and
  replayed in order by the main thread; consoles are restored after a normal turn.
- Headless/machine runs and non-TTY sessions keep the classic generator path (no worker, no
  watcher, no console routing).
- `ThreadedStream` starts lazily on the first `__next__`, so console routing and the active-bridge
  registration are in place before the generator produces anything.

## Acceptance Criteria

- [x] interactive streaming runs through the bridge; content matches the classic path
- [x] Ctrl+O mid-generation opens the viewer and the worker keeps generating (test sleeps in a
      fake viewer; later chunks are still rendered)
- [x] worker prints are replayed on the main thread against the real console
- [x] consoles/client/provider consoles restored after a normal turn; active bridge cleared
- [x] headless path never creates a watcher/bridge and calls display_stream without pause hooks
- [x] cleanup on KeyboardInterrupt restores consoles and clears the registry
- [x] full suite 1880 passed, ruff clean, mkdocs --strict green

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
