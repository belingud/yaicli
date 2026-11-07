# K13 session isolation and --resume

## Goal

Per-project chat sessions under ~/.yaicli/sessions/<cwd-hash>/ with 0700 dirs / 0600 files, model/provider/role/cwd metadata, a working --resume flag, and no silent new-session when --chat <title> misses. Respect CHAT_HISTORY_DIR override; keep old session files loadable. No new deps; Python 3.10.

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
