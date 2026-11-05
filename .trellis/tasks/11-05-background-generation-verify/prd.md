# T5 — Regression, docs and specs for background generation

## Goal

Full regression suite, stream-json/confirmation/tool-policy checks, docs/spec updates, commit; release remains a separate explicit step.

## Requirements

- User docs describe background generation accurately (README, cli, interactive, commands,
  context-limits): Ctrl+O opens the viewer mid-answer, generation continues in the background, and
  closing redraws the accumulated answer.
- `cli-and-rendering` spec documents the watcher → ThreadedStream → WorkerConsole → printer hook
  pipeline, cancellation and abandoned-worker handling; `function-tool-guidelines` notes that
  `execute_tool_call` may run on the worker thread and must write only through its console.
- Full verification: `pytest -q`, `ruff check yaicli tests`, `mkdocs build --strict`.
- Commit docs + task updates; the v0.19.1 release remains a separate explicit step.

## Acceptance Criteria

- [x] docs/spec updated for background generation and cancellation semantics
- [x] `pytest` full suite green (1887+; final count recorded in the commit report)
- [x] `ruff check yaicli tests` and `mkdocs build --strict` green
- [x] commits: T5 docs/spec + task updates
- [ ] v0.19.1 release (explicit user request required)

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
