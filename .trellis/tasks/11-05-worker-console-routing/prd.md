# T2 Worker-thread console routing

## Goal

Thread-dispatching console wrapper: writes from the generation worker are queued and replayed in order on the main thread; main-thread writes pass through; dropped when the bridge is dead; unit tests.

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
