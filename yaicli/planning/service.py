"""Planning lifecycle, session tools and best-effort persistence side effects.

Terminal interaction belongs to the application coordinator. The lazy default
session remains here for compatible callers until explicit runtime ownership.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .. import const
from ..config import cfg
from ..runtime import current_config
from . import store as plan_store
from .editor import edit_plan_file, write_plan_editor_draft
from .model import (
    PLAN_READONLY_TOOL_NAMES,
    PLAN_SHELL_TOOL,
    SESSION_TOOL_NAMES,
    PlanMode,
    PlanSession,
    RevisionDiff,
    TodoItem,
    _now_iso,
    _step_payload,
    diff_plans,
    execution_tool_names,
    is_execution_mode_value,
    is_plan_mode_value,
    is_tool_allowed_in_plan,
    plan_tool_allowlist,
)
from .prompt import plan_context_block, todo_summary
from .store import _atomic_write_text
from .validation import (
    MAX_BLOCKED_REASON_CHARS,
    MAX_CHANGE_SUMMARY_CHARS,
    MAX_GOAL_CHARS,
    MAX_PLAN_BYTES,
    _invalid,
    validate_submit_plan,
    validate_todo_write,
)

if TYPE_CHECKING:
    from .store import Plan

_plan_session: Optional[PlanSession] = None


def get_plan_session() -> PlanSession:
    """Return the process-global plan session (created lazily)."""
    global _plan_session
    if _plan_session is None:
        _plan_session = PlanSession()
    return _plan_session


def set_plan_session(session: PlanSession) -> None:
    """Install an explicit plan session (tests / embedders)."""
    global _plan_session
    _plan_session = session


def reset_plan_session() -> None:
    """Drop the process-global plan session (next access creates a fresh one)."""
    global _plan_session
    _plan_session = None


def _utc_stamp() -> str:
    """UTC timestamp used by audit lines (same format as the tool audit)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit_enabled() -> bool:
    """True when the config asks for the audit log (absent key = opt out)."""
    try:
        config = current_config(cfg)
        if "TOOL_AUDIT" not in config:
            return False
        return bool(config.get("TOOL_AUDIT"))
    except (AttributeError, TypeError):  # pragma: no cover - exotic config mappings
        return False


def _audit_value(value: Any) -> Any:
    """Normalize one audit field into a JSON-safe, bounded value."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return value[:500]
        return value
    try:
        return str(value)[:500]
    except Exception:  # pragma: no cover - defensive repr failures
        return ""


def plan_audit(event: str, **fields: Any) -> None:
    """Append one ``plan.<event>`` JSON line to ``const.TOOL_AUDIT_PATH``.

    Best effort by design (``TOOL_AUDIT`` config switch, 0600, OSError-tolerant):
    an unwritable audit log must never affect planning or execution.
    """
    if not _audit_enabled():
        return
    try:
        record: Dict[str, Any] = {"ts": _utc_stamp(), "event": f"plan.{event}"}
        for key, value in fields.items():
            record[str(key)] = _audit_value(value)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        path = Path(const.TOOL_AUDIT_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:  # pragma: no cover - audit must never break the workflow
        pass


def _revision_diff_payload(diff: RevisionDiff, todos: List[TodoItem]) -> Dict[str, Any]:
    """JSON-ready revision diff included in the ``submit_plan`` tool result."""
    return {
        "summary": diff.summary(),
        "detail_lines": diff.detail_lines(),
        "todo_impact": diff.todo_impact(todos),
        "added": [_step_payload(step) for step in diff.added],
        "removed": [_step_payload(step) for step in diff.removed],
        "changed": [_step_payload(step) for step in diff.changed],
        "unchanged": [_step_payload(step) for step in diff.unchanged],
    }


def handle_submit_plan(arguments: Dict[str, Any], *, session: Optional[PlanSession] = None) -> Dict[str, Any]:
    """Handle one ``submit_plan`` tool call (first submission or a revision).

    Success (first submission) writes the draft plan file and moves the session
    to ``reviewing``; a revision only builds the in-memory draft + diff (the plan
    file is rewritten in place on approval). Returns JSON-ready data, never raises.
    """
    session = get_plan_session() if session is None else session
    try:
        if session.mode == PlanMode.REVIEWING.value:
            return {
                "success": False,
                "error": "plan_already_submitted",
                "reason": "A plan was already submitted and is waiting for the user to approve or cancel it.",
                "hint": "Wait for the approval panel; use [e] to edit the plan or [r] to keep planning.",
            }
        if session.mode not in (PlanMode.RESEARCHING.value, PlanMode.REVISING.value):
            return {
                "success": False,
                "error": "plan_not_active",
                "reason": "submit_plan is only available while planning.",
                "hint": "Enter plan mode with Shift+Tab or /plan, explore the task, then call submit_plan.",
            }
        mode = session.mode
        plan, error = validate_submit_plan(arguments, session=session, mode=mode)
        if error is not None:
            return error
        if plan is None:  # pragma: no cover - validate_submit_plan always pairs plan/error
            return _invalid("the plan could not be built")

        if mode == PlanMode.REVISING.value:
            active = session.active_plan
            diff = diff_plans(active, plan) if active is not None else RevisionDiff()
            session.draft_plan = plan
            session.diff = diff
            session.change_summary = plan.change_summary
            session.mode = PlanMode.REVIEWING.value
            plan_audit(
                "revise_submit",
                plan_id=plan.id,
                revision=plan.revision,
                change_summary=plan.change_summary,
                added=len(diff.added),
                removed=len(diff.removed),
                changed=len(diff.changed),
                steps=len(plan.steps),
            )
            return {
                "success": True,
                "plan_id": plan.id,
                "revision": plan.revision,
                "path": str(plan.path) if plan.path is not None else "",
                "steps": len(plan.steps),
                "revision_diff": _revision_diff_payload(diff, session.todos),
            }

        # ---- first submission: prune old terminal plans, write the draft ----
        try:
            if session.plans_root is not None and session.plan_dir is not None:
                plan_store.prune_plans(session.plans_root, session.plan_dir.name, session.keep)
        except Exception:  # pragma: no cover - pruning must never block a plan
            pass
        try:
            written = plan_store.write_plan(plan)
        except plan_store.PlanStoreError as exc:
            return {
                "success": False,
                "error": "plan_write_failed",
                "reason": f"cannot write plan file: {plan.path} ({exc})",
                "hint": "Check PLAN_DIR permissions or set PLAN_DIR to a writable directory.",
            }
        except OSError as exc:
            return {
                "success": False,
                "error": "plan_write_failed",
                "reason": f"cannot write plan file: {plan.path} ({exc})",
                "hint": "Check PLAN_DIR permissions or set PLAN_DIR to a writable directory.",
            }
        plan.path = written
        session.draft_plan = plan
        session.diff = None
        session.mode = PlanMode.REVIEWING.value
        plan_audit("submit", plan_id=plan.id, revision=plan.revision, steps=len(plan.steps), path=str(plan.path))
        return {
            "success": True,
            "plan_id": plan.id,
            "revision": plan.revision,
            "path": str(plan.path),
            "steps": len(plan.steps),
            "revision_diff": None,
        }
    except Exception as exc:  # pragma: no cover - never raise to the model
        return {
            "success": False,
            "error": "plan_error",
            "reason": f"submit_plan failed: {type(exc).__name__}: {exc}",
            "hint": "Try again; if the problem persists, exit plan mode with Shift+Tab.",
        }


def seed_todos(plan: "Plan") -> List[TodoItem]:
    """Seed the todo list from the approved plan (S1 in progress, rest pending)."""
    todos = [TodoItem(id=str(getattr(step, "id", "")), content=str(getattr(step, "title", ""))) for step in plan.steps]
    if todos:
        todos[0].status = "in_progress"
    return todos


def _changed_todo(todos: List[TodoItem], previous: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Describe the todo whose status changed in this update (REPL progress line).

    Only status transitions to ``in_progress``/``completed``/``blocked`` are
    reported (a plain rewrite without a status change prints nothing). When
    several change at once the most "active" one wins: in_progress > completed >
    blocked > pending.
    """
    priority = {"in_progress": 0, "completed": 1, "blocked": 2, "pending": 3}
    changed = [
        todo
        for todo in todos
        if previous.get(todo.id) != todo.status and todo.status in ("in_progress", "completed", "blocked")
    ]
    if not changed:
        return None
    best = sorted(changed, key=lambda todo: priority.get(todo.status, 9))[0]
    index = next((position for position, todo in enumerate(todos, start=1) if todo.id == best.id), 1)
    return {
        "index": index,
        "total": len(todos),
        "id": best.id,
        "title": best.content,
        "status": best.status,
    }


def handle_todo_write(arguments: Dict[str, Any], *, session: Optional[PlanSession] = None) -> Dict[str, Any]:
    """Handle one ``todo_write`` tool call during plan execution."""
    session = get_plan_session() if session is None else session
    try:
        if not session.is_executing:
            return {
                "success": False,
                "error": "todo_write_not_available",
                "reason": "todo_write is only available while executing an approved plan.",
                "hint": "Approve a plan first; todo_write does not run in plan mode.",
            }
        previous = {todo.id: todo.status for todo in session.todos}
        todos, error = validate_todo_write(arguments, session=session)
        if error is not None:
            return error
        if todos is None:  # pragma: no cover - validation always pairs list/error
            return {"success": False, "error": "invalid_todo", "reason": "invalid todo payload"}
        session.todos = todos
        completed = sum(1 for todo in todos if todo.status == "completed")
        blocked = sum(1 for todo in todos if todo.status == "blocked")
        in_progress = next((todo.id for todo in todos if todo.status == "in_progress"), "")
        current = _changed_todo(todos, previous)
        _write_todo_checkboxes(session)
        plan_audit(
            "todo.update",
            plan_id=session.active_plan_id,
            completed=completed,
            total=len(todos),
            blocked=blocked,
            in_progress=in_progress,
        )
        return {
            "success": True,
            "completed": completed,
            "total": len(todos),
            "blocked": blocked,
            "in_progress": in_progress,
            "current": current,
        }
    except Exception as exc:  # pragma: no cover - never raise to the model
        return {
            "success": False,
            "error": "plan_error",
            "reason": f"todo_write failed: {type(exc).__name__}: {exc}",
            "hint": "Try again; the todo list was not updated.",
        }


_STEP_LINE_RE = re.compile(r"^- \[[ xX]\] \*\*(S\d+)\*\*")


def _patch_todo_checkboxes(path: Path, todos: List[TodoItem]) -> None:
    """Write todo statuses back into the ``## Steps`` checkboxes of ``path``.

    The plan markdown (frontmatter + sections) is rendered by ``plan_store``; this
    only rewrites the checkbox/blocked marker of each step line so the persisted
    plan shows execution progress. Best effort: an IO error leaves the file as is.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return
    status_by_id = {todo.id: todo for todo in todos}
    lines = text.splitlines()
    in_steps = False
    changed = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower().startswith("## steps"):
            in_steps = True
            continue
        if in_steps and stripped.startswith("## "):
            in_steps = False
        if not in_steps:
            continue
        match = _STEP_LINE_RE.match(line)
        if match is None:
            continue
        todo = status_by_id.get(match.group(1))
        if todo is None:
            continue
        checkbox = "[x]" if todo.status == "completed" else "[ ]"
        new_line = re.sub(r"^- \[[ xX]\]", f"- {checkbox}", line, count=1)
        new_line = re.sub(r" \(blocked:.*\)\s*$", "", new_line)
        if todo.status == "blocked" and todo.reason:
            new_line += f" (blocked: {' '.join(todo.reason.split())})"
        if new_line != line:
            lines[index] = new_line
            changed = True
    if not changed:
        return
    try:
        _atomic_write_text(Path(path), "\n".join(lines) + "\n")
    except OSError:  # pragma: no cover - best effort persistence
        pass


def _write_todo_checkboxes(session: PlanSession) -> None:
    """Persist the current todo statuses into the active plan file (best effort)."""
    plan = session.active_plan
    if plan is None:
        return
    path = getattr(plan, "path", None)
    if path is None:
        return
    try:
        plan_store.write_plan(plan, path)
    except Exception:  # pragma: no cover - persistence must not stop execution
        return
    _patch_todo_checkboxes(Path(path), session.todos)


def rebuild_todos_after_revision(session: PlanSession) -> List[TodoItem]:
    """Rebuild the todo list after a revision, preserving unchanged statuses.

    * steps that still exist keep their todo status (completed/in_progress/blocked);
    * new steps start ``pending``;
    * a removed in-progress step leaves no in_progress todo: execution resumes and
      the model restarts the next step through ``todo_write``.
    """
    base = session.revision_base or session.active_plan
    draft = session.draft_plan
    if base is None or draft is None:
        return list(session.todos)
    previous = {todo.id: todo for todo in session.todos}
    todos: List[TodoItem] = []
    for step in getattr(draft, "steps", []):
        step_id = str(getattr(step, "id", ""))
        title = str(getattr(step, "title", ""))
        old = previous.get(step_id)
        if old is not None:
            todos.append(TodoItem(id=step_id, content=title, status=old.status, reason=old.reason))
        else:
            todos.append(TodoItem(id=step_id, content=title))
    return todos


def _copy_plan_for_write(plan: "Plan") -> None:
    """Write ``plan`` back to its path (best effort; used by lifecycle handlers)."""
    path = getattr(plan, "path", None)
    if path is None:
        return
    try:
        plan_store.write_plan(plan, path)
    except Exception:  # pragma: no cover - persistence is best effort here
        pass


def apply_revision(session: PlanSession) -> Dict[str, Any]:
    """Apply an approved revision in place and resume execution."""
    active = session.active_plan
    draft = session.draft_plan
    if active is None or draft is None:
        return {"success": False, "error": "no_revision", "reason": "there is no pending plan revision"}
    diff = session.diff or diff_plans(active, draft)
    session.revision_base = active
    session.draft_plan = draft
    todos = rebuild_todos_after_revision(session)
    active.goal = draft.goal
    active.assumptions = list(draft.assumptions)
    active.risks = list(draft.risks)
    active.not_doing = list(draft.not_doing)
    active.steps = list(draft.steps)
    active.revision = draft.revision
    active.change_summary = draft.change_summary
    active.updated = _now_iso()
    session.active_plan = active
    session.todos = todos
    session.draft_plan = None
    session.revision_base = None
    session.diff = None
    session.change_summary = ""
    session.mode = PlanMode.EXECUTING.value
    _copy_plan_for_write(active)
    path = getattr(active, "path", None)
    if path is not None:
        _patch_todo_checkboxes(Path(path), todos)
    resuming_at = next((todo.id for todo in todos if todo.status in ("in_progress", "pending")), "")
    plan_audit(
        "revise_apply",
        plan_id=str(getattr(active, "id", "")),
        revision=int(getattr(active, "revision", 1) or 1),
        resuming_at=resuming_at,
        added=len(diff.added),
        removed=len(diff.removed),
        changed=len(diff.changed),
    )
    return {
        "success": True,
        "plan_id": str(getattr(active, "id", "")),
        "revision": int(getattr(active, "revision", 1) or 1),
        "path": str(path) if path is not None else "",
        "resuming_at": resuming_at,
        "steps": len(getattr(active, "steps", [])),
        "todos": [todo.to_dict() for todo in todos],
    }


def approve_new_plan(session: PlanSession) -> Dict[str, Any]:
    """Approve the submitted draft: mark in-progress, seed todos, start executing."""
    draft = session.draft_plan
    if draft is None:
        return {"success": False, "error": "no_plan", "reason": "there is no submitted plan to approve"}
    draft.status = plan_store.PLAN_STATUS_IN_PROGRESS
    draft.approved_at = _now_iso()
    draft.updated = _now_iso()
    session.active_plan = draft
    session.draft_plan = None
    session.revision_base = None
    session.diff = None
    session.todos = seed_todos(draft)
    session.mode = PlanMode.EXECUTING.value
    _copy_plan_for_write(draft)
    path = getattr(draft, "path", None)
    if path is not None:
        _patch_todo_checkboxes(Path(path), session.todos)
    plan_audit(
        "approve",
        plan_id=str(getattr(draft, "id", "")),
        revision=int(getattr(draft, "revision", 1) or 1),
        steps=len(getattr(draft, "steps", [])),
    )
    return {
        "success": True,
        "plan_id": str(getattr(draft, "id", "")),
        "revision": int(getattr(draft, "revision", 1) or 1),
        "path": str(path) if path is not None else "",
        "steps": len(getattr(draft, "steps", [])),
        "todos": [todo.to_dict() for todo in session.todos],
    }


def finish_plan(session: PlanSession) -> Dict[str, Any]:
    """Mark the active plan done and clear the plan execution state."""
    active = session.active_plan
    if active is None:
        return {"success": False, "error": "no_plan", "reason": "there is no plan being executed"}
    completed, total = session.todo_progress()
    active.status = plan_store.PLAN_STATUS_DONE
    active.updated = _now_iso()
    _copy_plan_for_write(active)
    path = getattr(active, "path", None)
    if path is not None:
        _patch_todo_checkboxes(Path(path), session.todos)
    plan_audit(
        "done",
        plan_id=str(getattr(active, "id", "")),
        revision=int(getattr(active, "revision", 1) or 1),
        completed=completed,
        total=total,
    )
    result = {
        "success": True,
        "plan_id": str(getattr(active, "id", "")),
        "revision": int(getattr(active, "revision", 1) or 1),
        "path": str(path) if path is not None else "",
        "completed": completed,
        "total": total,
    }
    session.active_plan = None
    session.draft_plan = None
    session.revision_base = None
    session.diff = None
    session.todos = []
    session.change_summary = ""
    session.mode = PlanMode.NORMAL.value
    return result


def abort_plan(session: PlanSession) -> Dict[str, Any]:
    """Abort the active/draft plan (status aborted), clearing the session state."""
    target = session.active_plan or session.draft_plan
    if target is None:
        return {"success": False, "error": "no_plan", "reason": "no plan is active in this session"}
    target.status = plan_store.PLAN_STATUS_ABORTED
    target.updated = _now_iso()
    _copy_plan_for_write(target)
    path = getattr(target, "path", None)
    plan_audit(
        "abort",
        plan_id=str(getattr(target, "id", "")),
        revision=int(getattr(target, "revision", 1) or 1),
    )
    result = {
        "success": True,
        "plan_id": str(getattr(target, "id", "")),
        "revision": int(getattr(target, "revision", 1) or 1),
        "path": str(path) if path is not None else "",
    }
    session.active_plan = None
    session.draft_plan = None
    session.revision_base = None
    session.diff = None
    session.todos = []
    session.change_summary = ""
    session.mode = PlanMode.NORMAL.value
    return result


def pause_plan(session: PlanSession) -> None:
    """Pause execution: return to normal mode keeping the plan and todos."""
    session.mode = PlanMode.NORMAL.value
    plan_audit(
        "pause",
        plan_id=session.active_plan_id,
        completed=session.todo_progress()[0],
        total=session.todo_progress()[1],
    )


def resume_plan(session: PlanSession) -> bool:
    """Resume an in-progress plan (seed todos when missing); ``False`` when none."""
    active = session.active_plan
    if active is None or str(getattr(active, "status", "")) != plan_store.PLAN_STATUS_IN_PROGRESS:
        return False
    if not session.todos:
        session.todos = seed_todos(active)
    session.mode = PlanMode.EXECUTING.value
    plan_audit("resume", plan_id=session.active_plan_id, completed=session.todo_progress()[0], total=len(session.todos))
    return True


__all__ = [
    "MAX_BLOCKED_REASON_CHARS",
    "MAX_CHANGE_SUMMARY_CHARS",
    "MAX_GOAL_CHARS",
    "MAX_PLAN_BYTES",
    "PLAN_READONLY_TOOL_NAMES",
    "PLAN_SHELL_TOOL",
    "SESSION_TOOL_NAMES",
    "PlanMode",
    "PlanSession",
    "RevisionDiff",
    "TodoItem",
    "abort_plan",
    "apply_revision",
    "approve_new_plan",
    "diff_plans",
    "edit_plan_file",
    "execution_tool_names",
    "finish_plan",
    "get_plan_session",
    "handle_submit_plan",
    "handle_todo_write",
    "is_execution_mode_value",
    "is_plan_mode_value",
    "is_tool_allowed_in_plan",
    "pause_plan",
    "plan_audit",
    "plan_context_block",
    "plan_tool_allowlist",
    "rebuild_todos_after_revision",
    "reset_plan_session",
    "resume_plan",
    "seed_todos",
    "set_plan_session",
    "todo_summary",
    "validate_submit_plan",
    "validate_todo_write",
    "write_plan_editor_draft",
]
