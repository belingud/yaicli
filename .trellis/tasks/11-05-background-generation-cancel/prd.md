# T4 — Cancellation and history safety

## Goal

Ctrl+C abort semantics, watcher lifecycle, discard worker-mutated messages on abort, queued tool confirmations while viewer is open, tests.

## Requirements

- History safety: in background mode the worker mutates a *copy* of the CLI message
  list; the copy is adopted only when the turn completes. An aborted/failed turn returns the
  untouched original list, so a worker that lingers cannot corrupt the next turn.
- `ThreadedStream.close(timeout)` returns whether the worker is still alive after the join.
- Abandoned-worker safety: each worker thread is registered to its own bridge
  (`get_bridge_for_current_thread`). A late print from an abandoned worker goes to its dead
  bridge and is dropped, even if a newer generation has already installed a new active bridge.
- CLI cleanup: on normal completion restore the routed consoles/client-provider console refs;
  when the worker is abandoned keep the routing installed so its future output is dropped and
  print a dim "still finishing" notice. Console wrappers are unwrapped before re-wrapping so
  repeated abandoned generations do not build chains.
- Ctrl+C keeps raising KeyboardInterrupt on the UI thread; the turn aborts and the prompt is
  available again; the worker stops at its next chunk boundary.

## Acceptance Criteria

- [x] aborted turn leaves the original message list untouched; successful turn adopts the copy
- [x] handled provider error returns the original list (no partial history pollution)
- [x] `close()` reports a blocked worker as alive
- [x] per-thread bridge registry routes/drops abandoned-worker prints correctly
- [x] abandoned worker keeps console routing installed + dim notice; normal end restores it
- [x] `tests/test_stream_bridge.py`, `tests/test_worker_console.py`, `tests/test_cli.py` pass

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
