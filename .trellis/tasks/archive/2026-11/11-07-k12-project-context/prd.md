# K12 project context auto-load

## Goal

Auto-load AGENTS.md/CLAUDE.md/.yaicli.md from cwd up to the git root into the system prompt: bounded total size, truncation notice to stderr, config to disable (default on), no extra request when absent. New stdlib project_context module + cli wiring + tests. No new deps; Python 3.10.

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
