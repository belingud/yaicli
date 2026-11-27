"""Pure formatting of planning instructions and execution progress."""

from __future__ import annotations

from typing import Any, List

from .model import PlanMode, PlanSession

_PLAN_INSTRUCTIONS = (
    "YOU ARE NOW IN PLAN MODE. Plan mode is a read-only phase whose ONLY deliverable is an "
    "implementation plan the user can review and approve — not the implementation itself. In this "
    "mode you must follow these rules: (1) do NOT modify files, install anything, run builds/tests or "
    "change the workspace; (2) do NOT write the implementation, code, HTML or the final answer the "
    "user asked for — replying with the deliverable here is a failure; (3) research the task with the "
    "read-only tools first (read files, search, web pages, read-only shell); (4) end the turn by "
    "calling submit_plan with a concrete, ordered step list where every step has a title and "
    "acceptance criteria. submit_plan is the ONLY way to leave plan mode: it shows the plan to the "
    "user for approval. If the task is small, submit a short 1-3 step plan instead of answering. If "
    "you need a clarification, ask one short question in text and wait. Never claim any work is done."
)


_REVISION_INSTRUCTIONS = (
    "YOU ARE NOW IN PLAN MODE (revising). Plan mode is read-only: the user is adjusting an already "
    "approved plan, and you must NOT write the implementation or the final answer. Research the "
    "changed requirements with the read-only tools, then call submit_plan with the complete updated "
    "step list, revision={next_revision} and a short change_summary. Keep existing step ids unchanged; "
    "new steps take ids S{n} and continue from there. submit_plan is the ONLY way to end planning "
    "here; it shows the diff for approval and then execution resumes."
)


_EXECUTION_INSTRUCTIONS = (
    "YOU ARE NOW EXECUTING AN APPROVED PLAN. Work through the todo list one step at a time and update "
    "it with todo_write. Keep exactly one step in_progress, mark it completed when done and move the "
    "next step to in_progress. Do not add or remove steps; re-enter plan mode (Shift+Tab) to revise "
    "the plan. Keep chat replies brief; the todo list is the source of truth for progress."
)


def _clip(text: str, max_chars: int) -> str:
    """Bounded text block with an explicit truncation marker."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    keep = max(16, max_chars - 24)
    return text[:keep].rstrip() + "\n… [plan context truncated]"


def _render_steps(steps: List[Any], *, limit: int = 20) -> List[str]:
    """Render plan steps (id/title + acceptance) for the model context."""
    lines: List[str] = ["Steps:"]
    for index, step in enumerate(list(steps)[:limit], start=1):
        step_id = str(getattr(step, "id", ""))
        title = str(getattr(step, "title", ""))
        acceptance = str(getattr(step, "acceptance", ""))
        lines.append(f" {index}. {step_id} {title}")
        if acceptance:
            lines.append(f"    acceptance: {acceptance}")
    return lines


def todo_summary(session: PlanSession, *, max_chars: int = 500) -> str:
    """Bounded todo status list injected into the execution context."""
    todos = session.todos
    if not todos:
        return ""
    total = len(todos)
    completed = sum(1 for todo in todos if todo.status == "completed")
    lines = [f"Todo {completed}/{total} completed"]
    for index, todo in enumerate(todos, start=1):
        suffix = f" — {todo.status}"
        if todo.status == "blocked" and todo.reason:
            suffix += f": {todo.reason}"
        lines.append(f"[todo {index}/{total}] {todo.id} {todo.content}{suffix}")
    return _clip("\n".join(lines), max_chars)


def plan_context_block(session: PlanSession, *, max_chars: int = 2000) -> str:
    """Build the plan-mode system prompt block (empty string outside plan modes)."""
    mode = session.mode
    if mode == PlanMode.RESEARCHING.value:
        lines = ["## Plan mode", _PLAN_INSTRUCTIONS]
        base = session.active_plan or session.draft_plan
        if base is not None:
            lines.append(f"Active plan: {getattr(base, 'id', '')} (revision {getattr(base, 'revision', 1)})")
            lines.append(f"Goal: {getattr(base, 'goal', '')}")
            lines.extend(_render_steps(list(getattr(base, "steps", []))))
        return _clip("\n".join(lines), max_chars)
    if mode == PlanMode.REVISING.value:
        active = session.active_plan
        base = session.revision_base or active
        revision = int(getattr(active, "revision", 1) or 1) if active is not None else 1
        next_revision = revision + 1
        step_count = len(getattr(base, "steps", [])) if base is not None else 0
        lines = [
            "## Plan mode (revising)",
            _REVISION_INSTRUCTIONS.format(next_revision=next_revision, n=step_count + 1),
        ]
        if base is not None:
            lines.append(f"Approved plan: {getattr(base, 'id', '')} (revision {getattr(base, 'revision', 1)})")
            lines.append(f"Goal: {getattr(base, 'goal', '')}")
            lines.extend(_render_steps(list(getattr(base, "steps", []))))
        summary = todo_summary(session)
        if summary:
            lines.append(summary)
        return _clip("\n".join(lines), max_chars)
    if mode == PlanMode.EXECUTING.value:
        active = session.active_plan
        if active is None:
            return ""
        completed, total = session.todo_progress()
        lines = [
            "## Plan execution",
            _EXECUTION_INSTRUCTIONS,
            f"Approved plan: {getattr(active, 'id', '')} (revision {getattr(active, 'revision', 1)})",
            f"Goal: {getattr(active, 'goal', '')}",
            f"Progress: {completed}/{total} steps completed",
        ]
        summary = todo_summary(session, max_chars=500)
        if summary:
            lines.append(summary)
        return _clip("\n".join(lines), max_chars)
    return ""
