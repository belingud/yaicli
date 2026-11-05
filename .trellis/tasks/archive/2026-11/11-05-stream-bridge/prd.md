# T1 — StreamBridge worker generator adapter

## Goal

ThreadedStream adapter: worker thread pulls the completion generator, event queue for chunks, ConfirmToolCall decision handshake, abort/cancel, console event channel; unit tests only, not wired into the CLI yet.

## Requirements

- `yaicli/stream_bridge.py::ThreadedStream` runs a completion generator on a daemon worker
  thread and implements the generator protocol (`__next__`/`send`) for `Printer.display_stream`.
- One FIFO queue carries `chunk` / `console` / `done` / `error` events, preserving the order of
  streamed chunks and worker console prints; `on_console(*args, **kwargs)` replays console events
  on the UI thread from `__next__`.
- `ConfirmToolCall` pauses the worker until the UI thread calls `send(decision)`.
- `abort()` cancels at the next chunk boundary and drops late console events; `close(timeout)` joins.
- No imports of console/CLI/printer modules (unit-testable in isolation); no CLI wiring yet.

## Acceptance Criteria

- [x] chunks are forwarded in order and `StopIteration`/worker exceptions surface on the UI thread
- [x] console events are replayed in order before the next chunk; late events are dropped after abort
- [x] confirmation decisions reach the generator through `send()`
- [x] abort unblocks a pending confirmation and stops the worker; `close()` is bounded
- [x] `tests/test_stream_bridge.py` + `ruff check` green; no production code uses it yet

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
