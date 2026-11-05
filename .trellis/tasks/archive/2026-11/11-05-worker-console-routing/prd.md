# T2 — Worker-thread console routing

## Goal

Thread-dispatching console wrapper: writes from the generation worker are queued and replayed in order on the main thread; main-thread writes pass through; dropped when the bridge is dead; unit tests.

## Requirements

- `yaicli/worker_console.py::WorkerConsole` wraps a Rich console; `print` dispatches:
  main thread → real console; worker thread + live bridge → `bridge.put_console(...)`
  (replayed in order by the UI thread); worker thread without a bridge → real console
  (legacy); worker thread on a dead bridge → dropped.
- `ThreadedStream` console events carry a `stderr` flag and the bridge exposes an
  active-bridge registry (`set_active_bridge`/`get_active_bridge`/`clear_active_bridge`).
- `install_worker_console_routing(main, error)` swaps `yaicli.tools.console` and
  `yaicli.console._error_console`, returns `WorkerConsoleRouting` with `.main`/`.error`
  wrappers and an idempotent `restore()`.

## Acceptance Criteria

- [x] main-thread prints still reach the real console unchanged
- [x] worker prints are queued (not written) while a bridge is active and replayed in order
- [x] stderr console events keep their target flag
- [x] no-bridge worker prints keep the legacy pass-through; dead-bridge prints are dropped
- [x] install/restore swaps the consoles and is idempotent; routing does not block the worker
- [x] `tests/test_worker_console.py` + T1 tests green, ruff clean

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
