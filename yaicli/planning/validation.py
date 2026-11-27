"""Validation of model-supplied plan and todo arguments."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import store as plan_store
from .model import (
    PlanMode,
    PlanSession,
    TodoItem,
    _now_iso,
    _positive_int,
    _step_payload,
)

if TYPE_CHECKING:
    from .store import Plan

MAX_GOAL_CHARS = 500


MAX_CHANGE_SUMMARY_CHARS = 500


MAX_BLOCKED_REASON_CHARS = 500


MAX_PLAN_BYTES = 8 * 1024


_ERROR_HINT = "Fix the arguments and call submit_plan again; nothing was saved."


def _clean_text(value: Any) -> str:
    """Normalize a model-supplied scalar to a stripped single-line-ish string."""
    if value is None:
        return ""
    return str(value).strip()


def _string_list(value: Any, field_name: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """Validate/normalize an optional list-of-strings argument."""
    if value is None:
        return [], None
    if not isinstance(value, (list, tuple)):
        return None, f"{field_name} must be a list of strings"
    items: List[str] = []
    for entry in value:
        text = _clean_text(entry)
        if text:
            items.append(text)
    return items, None


def _invalid(reason: str, hint: str = _ERROR_HINT) -> Dict[str, Any]:
    """Build the structured ``submit_plan`` validation error returned to the model."""
    return {"success": False, "error": "invalid_plan", "reason": reason, "hint": hint}


def _invalid_todo(
    reason: str, hint: str = "Fix the todo list and call todo_write again; nothing was changed."
) -> Dict[str, Any]:
    """Build the structured ``todo_write`` validation error returned to the model."""
    return {"success": False, "error": "invalid_todo", "reason": reason, "hint": hint}


def _plan_serialized_size(payload: Dict[str, Any]) -> int:
    """UTF-8 size of the serialized plan payload (validation cap)."""
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return MAX_PLAN_BYTES + 1


def _build_steps(
    raw_steps: Any,
    *,
    max_steps: int,
    assign_ids: bool,
    existing_ids: Optional[set] = None,
    next_new_id: int = 1,
) -> Tuple[Optional[List[Any]], Optional[str]]:
    """Validate the submitted steps and build ``plan_store.PlanStep`` objects.

    ``assign_ids=True`` numbers every step ``S1..Sn`` (first plan). Otherwise the
    submitted ids must either match an existing plan step or be the next new ids
    ``S{n+1}, S{n+2}, ...`` in submission order (revision).
    """
    if not isinstance(raw_steps, (list, tuple)):
        return None, "steps must be a list of step objects"
    if len(raw_steps) < 1:
        return None, "a plan needs at least 1 step"
    if len(raw_steps) > max_steps:
        return None, f"a plan may contain at most {max_steps} steps (got {len(raw_steps)})"
    existing = set(existing_ids or ())
    used_ids: set = set()
    expected_new = max(1, int(next_new_id))
    steps: List[Any] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            return None, f"step {index} must be an object with title and acceptance"
        title = _clean_text(raw_step.get("title"))
        acceptance = _clean_text(raw_step.get("acceptance"))
        detail = _clean_text(raw_step.get("detail"))
        if not title:
            return None, f"step {index} needs a non-empty title"
        if not acceptance:
            return None, f"step {index} needs non-empty acceptance criteria (how to verify it)"
        if assign_ids:
            step_id = f"S{index}"
        else:
            step_id = _clean_text(raw_step.get("id"))
            if not step_id:
                return None, f"step {index} needs an id (existing step id or the next new id)"
            if step_id in used_ids:
                return None, f"step id {step_id!r} is used more than once"
            if step_id not in existing:
                # New steps must extend the plan sequentially, skipping ids that
                # already exist (a revision may have removed a step id before).
                while f"S{expected_new}" in existing or f"S{expected_new}" in used_ids:
                    expected_new += 1
                expected_id = f"S{expected_new}"
                if step_id != expected_id:
                    return None, (
                        f"step id {step_id!r} is not valid for a revision: use an existing step id "
                        f"or the next new id {expected_id}"
                    )
                expected_new += 1
        if step_id in used_ids:
            return None, f"step id {step_id!r} is used more than once"
        used_ids.add(step_id)
        steps.append(plan_store.PlanStep(id=step_id, title=title, detail=detail, acceptance=acceptance))
    return steps, None


def validate_submit_plan(
    arguments: Any,
    *,
    session: PlanSession,
    mode: str,
) -> Tuple[Optional["Plan"], Optional[dict]]:
    """Validate one ``submit_plan`` call.

    Returns ``(plan, None)`` when the arguments are valid, else
    ``(None, {"error": "invalid_plan", "reason": ..., "hint": ...})``. Never raises.
    """
    payload = arguments if isinstance(arguments, dict) else {}
    max_steps = _positive_int(session.max_steps, 20)
    goal = _clean_text(payload.get("goal"))
    if not goal:
        return None, _invalid("goal is required")
    if len(goal) > MAX_GOAL_CHARS:
        return None, _invalid(f"goal must be at most {MAX_GOAL_CHARS} characters")
    assumptions, error = _string_list(payload.get("assumptions"), "assumptions")
    if error is not None:
        return None, _invalid(error)
    risks, error = _string_list(payload.get("risks"), "risks")
    if error is not None:
        return None, _invalid(error)
    not_doing, error = _string_list(payload.get("not_doing"), "not_doing")
    if error is not None:
        return None, _invalid(error)

    if mode == PlanMode.REVISING.value:
        active = session.active_plan
        if active is None:
            return None, _invalid("no approved plan is active, so there is nothing to revise")
        raw_revision = payload.get("revision", 0)
        expected_revision = int(getattr(active, "revision", 1) or 1) + 1
        if isinstance(raw_revision, bool) or not isinstance(raw_revision, int):
            return None, _invalid(
                f"revision must be the integer {expected_revision} (the approved plan revision is "
                f"{expected_revision - 1})"
            )
        if raw_revision != expected_revision:
            return None, _invalid(
                f"revision must be {expected_revision} (the approved plan revision is {expected_revision - 1})"
            )
        change_summary = _clean_text(payload.get("change_summary"))
        if not change_summary:
            return None, _invalid("change_summary is required for a plan revision")
        if len(change_summary) > MAX_CHANGE_SUMMARY_CHARS:
            return None, _invalid(f"change_summary must be at most {MAX_CHANGE_SUMMARY_CHARS} characters")
        active_ids = {str(getattr(step, "id", "")) for step in getattr(active, "steps", [])}
        steps, error = _build_steps(
            payload.get("steps"),
            max_steps=max_steps,
            assign_ids=False,
            existing_ids=active_ids,
            next_new_id=len(active_ids) + 1,
        )
        if error is not None:
            return None, _invalid(error)
        step_payloads = [_step_payload(step) for step in steps or []]
        size = _plan_serialized_size(
            {
                "goal": goal,
                "assumptions": assumptions,
                "steps": step_payloads,
                "risks": risks,
                "not_doing": not_doing,
                "revision": raw_revision,
                "change_summary": change_summary,
            }
        )
        if size > MAX_PLAN_BYTES:
            return None, _invalid(f"plan is too large ({size} bytes); the serialized limit is 8 KB")
        try:
            plan = plan_store.Plan(
                id=str(getattr(active, "id", "")),
                goal=goal,
                steps=steps or [],
                assumptions=assumptions or [],
                risks=risks or [],
                not_doing=not_doing or [],
                status=str(getattr(active, "status", plan_store.PLAN_STATUS_IN_PROGRESS)),
                revision=expected_revision,
                session_id=str(getattr(active, "session_id", "")),
                created=str(getattr(active, "created", "")) or _now_iso(),
                updated=_now_iso(),
                cwd=str(getattr(active, "cwd", "")) or str(session.cwd),
                project_key=str(getattr(active, "project_key", "")),
                model=str(getattr(active, "model", "")) or session.model,
                base_rev=str(getattr(active, "base_rev", "")) or session.base_rev,
                approved_at=str(getattr(active, "approved_at", "")),
                change_summary=change_summary,
                path=getattr(active, "path", None),
            )
        except Exception as exc:  # pragma: no cover - plan_store contract mismatch
            return None, _invalid(f"could not build the revised plan: {type(exc).__name__}: {exc}")
        return plan, None

    # ---- first submission -------------------------------------------------
    if session.plan_dir is None:
        return None, _invalid("plan mode is not configured (no plans directory)", "Restart the CLI and try again.")
    steps, error = _build_steps(payload.get("steps"), max_steps=max_steps, assign_ids=True)
    if error is not None:
        return None, _invalid(error)
    step_payloads = [_step_payload(step) for step in steps or []]
    size = _plan_serialized_size(
        {
            "goal": goal,
            "assumptions": assumptions,
            "steps": step_payloads,
            "risks": risks,
            "not_doing": not_doing,
        }
    )
    if size > MAX_PLAN_BYTES:
        return None, _invalid(f"plan is too large ({size} bytes); the serialized limit is 8 KB")
    try:
        path = plan_store.new_plan_path(session.plan_dir, goal)
    except Exception as exc:
        return None, _invalid(
            f"cannot write plan file in {session.plan_dir}: {type(exc).__name__}: {exc}",
            "Check PLAN_DIR permissions or set PLAN_DIR to a writable directory.",
        )
    try:
        project_key = plan_store.project_key(session.cwd)
    except Exception:  # pragma: no cover - defensive
        project_key = ""
    base_rev = session.base_rev or session._current_git_rev()
    try:
        plan = plan_store.Plan(
            id=path.stem,
            goal=goal,
            steps=steps or [],
            assumptions=assumptions or [],
            risks=risks or [],
            not_doing=not_doing or [],
            status=plan_store.PLAN_STATUS_DRAFT,
            revision=1,
            session_id=session.session_id,
            created=_now_iso(),
            updated=_now_iso(),
            cwd=str(session.cwd),
            project_key=project_key,
            model=session.model,
            base_rev=base_rev,
            path=path,
        )
    except Exception as exc:  # pragma: no cover - plan_store contract mismatch
        return None, _invalid(f"could not build the plan: {type(exc).__name__}: {exc}")
    return plan, None


def validate_todo_write(
    arguments: Any,
    *,
    session: PlanSession,
) -> Tuple[Optional[List[TodoItem]], Optional[dict]]:
    """Validate a full ``todo_write`` payload against the current plan revision.

    The list must be 1:1 with the current revision's steps (no additions or
    removals), keep each step's content, contain at most one ``in_progress``
    entry and give a reason (<= 500 chars) for every ``blocked`` entry.
    """
    payload = arguments if isinstance(arguments, dict) else {}
    active = session.active_plan
    if active is None:
        return None, _invalid_todo(
            "there is no plan being executed",
            "todo_write is only available while executing an approved plan.",
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, (list, tuple)):
        return None, _invalid_todo(
            "items must be a list of todo objects",
            "Pass every step of the current plan revision as {id, content, status, reason}.",
        )
    steps = list(getattr(active, "steps", []))
    step_by_id = {str(getattr(step, "id", "")): step for step in steps}
    if not raw_items:
        return None, _invalid_todo(
            "items must contain one entry per plan step",
            "Include every step of the current plan revision.",
        )
    seen: set = set()
    in_progress = 0
    todos: List[TodoItem] = []
    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            return None, _invalid_todo(
                f"item {index} must be an object",
                "Pass every step of the current plan revision as {id, content, status, reason}.",
            )
        todo_id = _clean_text(raw_item.get("id"))
        if not todo_id:
            return None, _invalid_todo(f"item {index} needs an id")
        if todo_id in seen:
            return None, _invalid_todo(f"duplicate todo id {todo_id!r}")
        seen.add(todo_id)
        step = step_by_id.get(todo_id)
        if step is None:
            known = ", ".join(step_by_id)
            return None, _invalid_todo(
                f"todo id {todo_id!r} is not a step of the current plan revision ({known})",
                "todo_write cannot add or remove steps; submit a plan revision for that.",
            )
        content = _clean_text(raw_item.get("content"))
        expected_content = str(getattr(step, "title", ""))
        if content and content != expected_content:
            return None, _invalid_todo(
                f"todo {todo_id} content cannot be changed (expected {expected_content!r})",
                "Only status/reason may change; use a plan revision to change step titles.",
            )
        status = _clean_text(raw_item.get("status")).lower() or "pending"
        if status not in plan_store.PLAN_TODO_STATUSES:
            return None, _invalid_todo(
                f"todo {todo_id} status must be one of {', '.join(plan_store.PLAN_TODO_STATUSES)}"
            )
        reason = _clean_text(raw_item.get("reason"))
        if status == "blocked" and not reason:
            return None, _invalid_todo(f"todo {todo_id} is blocked and needs a reason")
        if len(reason) > MAX_BLOCKED_REASON_CHARS:
            return None, _invalid_todo(f"todo {todo_id} reason must be at most {MAX_BLOCKED_REASON_CHARS} characters")
        if status == "in_progress":
            in_progress += 1
        if status != "blocked":
            reason = ""
        todos.append(TodoItem(id=todo_id, content=expected_content, status=status, reason=reason))
    missing = [step_id for step_id in step_by_id if step_id not in seen]
    if missing:
        return None, _invalid_todo(
            "todo_write must include every step of the current plan revision; missing: " + ", ".join(missing),
            "todo_write replaces the whole list; include unchanged steps too.",
        )
    if in_progress > 1:
        return None, _invalid_todo(
            "at most one todo may be in_progress",
            "Mark the finished step completed before starting the next one.",
        )
    order = {step_id: index for index, step_id in enumerate(step_by_id)}
    todos.sort(key=lambda todo: order.get(todo.id, 0))
    return todos, None
