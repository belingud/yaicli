# K14 multi-provider tool-call consistency

## Goal

Keep every tool call in multi-call turns across providers: Anthropic multiple tool_use blocks (non-stream+stream), Gemini streamed same-name calls, Ollama multiple calls, and single-call streaming providers share one accumulation/collection helper; LLMResponse + LLMClient handle all calls per turn with backward compatibility; per-provider tests under tests/llms/. No new deps; Python 3.10.

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
