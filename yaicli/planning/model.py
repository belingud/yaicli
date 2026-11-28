"""Planning state, todo/revision models and tool visibility rules.

This layer has no terminal, provider or configuration dependency.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import store as plan_store

if TYPE_CHECKING:
    from .store import Plan, PlanStep

try:  # Python 3.11+
    from enum import StrEnum as _StrEnumBase
except ImportError:  # pragma: no cover - Python 3.10 fallback

    class _StrEnumBase(str, enum.Enum):  # type: ignore[no-redef]
        """Minimal ``StrEnum`` backport for Python 3.10."""

        def __str__(self) -> str:
            return str(self.value)


class PlanMode(_StrEnumBase):
    """Session mode of the persistent plan workflow."""

    NORMAL = "normal"
    RESEARCHING = "researching"
    REVISING = "revising"
    REVIEWING = "reviewing"
    EXECUTING = "executing"


PLAN_READONLY_TOOL_NAMES = frozenset(
    {
        "fs_read_file",
        "fs_list_directory",
        "fs_search_files",
        "fs_get_filesystem_info",
        "fs_read_image",
        "fetch_webpage",
        "web_search",
        "get_weather",
    }
)


PLAN_SHELL_TOOL = "execute_shell_command"


SESSION_TOOL_NAMES = frozenset({"submit_plan", "todo_write"})


def plan_tool_allowlist(allow_readonly_shell: bool = True) -> frozenset[str]:
    """Return the tool names offered while in plan mode.

    Args:
        allow_readonly_shell: Whether the controlled read-only shell is enabled
            (``PLAN_ALLOW_READONLY_SHELL``). When false, plan mode offers no shell
            at all.
    """
    allowed = set(PLAN_READONLY_TOOL_NAMES)
    allowed.add("submit_plan")
    if allow_readonly_shell:
        allowed.add(PLAN_SHELL_TOOL)
    return frozenset(allowed)


def execution_tool_names() -> frozenset[str]:
    """Return the extra session tools offered while executing an approved plan."""
    return frozenset({"todo_write"})


def is_tool_allowed_in_plan(name: str, allow_readonly_shell: bool = True) -> bool:
    """True when ``name`` may run in the read-only planning phase."""
    return str(name or "") in plan_tool_allowlist(allow_readonly_shell)


def is_plan_mode_value(mode: Optional[str]) -> bool:
    """True for the read-only planning modes (researching / revising)."""
    return mode in (PlanMode.RESEARCHING.value, PlanMode.REVISING.value)


def is_execution_mode_value(mode: Optional[str]) -> bool:
    """True for the plan execution mode."""
    return mode == PlanMode.EXECUTING.value


@dataclass
class TodoItem:
    """One execution todo, 1:1 with a step of the current plan revision."""

    id: str
    content: str
    status: str = "pending"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return the JSON-ready session form of this todo."""
        return {"id": self.id, "content": self.content, "status": self.status, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: Any) -> "TodoItem":
        """Restore one todo from session JSON (tolerant, never raises)."""
        payload = data if isinstance(data, dict) else {}
        status = str(payload.get("status") or "pending").strip().lower()
        if status not in plan_store.PLAN_TODO_STATUSES:
            status = "pending"
        return cls(
            id=str(payload.get("id") or "").strip(),
            content=str(payload.get("content") or "").strip(),
            status=status,
            reason=str(payload.get("reason") or "").strip(),
        )


def _step_payload(step: "PlanStep") -> Dict[str, Any]:
    """JSON-ready dict of one plan step (works for both dataclass flavours)."""
    to_dict = getattr(step, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return {
        "id": getattr(step, "id", ""),
        "title": getattr(step, "title", ""),
        "detail": getattr(step, "detail", ""),
        "acceptance": getattr(step, "acceptance", ""),
    }


@dataclass
class RevisionDiff:
    """Step-level difference between the approved plan and a submitted revision."""

    added: List["PlanStep"] = field(default_factory=list)
    removed: List["PlanStep"] = field(default_factory=list)
    changed: List["PlanStep"] = field(default_factory=list)
    unchanged: List["PlanStep"] = field(default_factory=list)

    def summary(self) -> str:
        """One-line change summary, e.g. ``Changes: +1 step  ~1 step  -0 steps``."""
        return f"Changes: +{len(self.added)} step  ~{len(self.changed)} step  -{len(self.removed)} steps"

    def detail_lines(self, max_lines: int = 12) -> List[str]:
        """Per-step change lines (`` + S5 title`` / `` ~ S4 title`` / `` - S3 title``)."""
        lines: List[str] = []
        lines.extend(
            f" + {_step_payload(step).get('id', '')} {_step_payload(step).get('title', '')}" for step in self.added
        )
        lines.extend(
            f" ~ {_step_payload(step).get('id', '')} {_step_payload(step).get('title', '')}" for step in self.changed
        )
        lines.extend(
            f" - {_step_payload(step).get('id', '')} {_step_payload(step).get('title', '')}" for step in self.removed
        )
        if max_lines > 0 and len(lines) > max_lines:
            hidden = len(lines) - max_lines + 1
            lines = lines[: max_lines - 1] + [f" … +{hidden} more changes"]
        return lines

    def todo_impact(self, todos: List[TodoItem]) -> str:
        """Explain which todo statuses survive this revision (for the review panel)."""
        removed_ids = {str(_step_payload(step).get("id", "")) for step in self.removed}
        added_ids = [str(_step_payload(step).get("id", "")) for step in self.added]
        parts: List[str] = []
        kept_completed = [todo.id for todo in todos if todo.status == "completed" and todo.id not in removed_ids]
        removed_completed = [todo.id for todo in todos if todo.status == "completed" and todo.id in removed_ids]
        if kept_completed:
            parts.append(f"completed {', '.join(kept_completed)} kept")
        if removed_completed:
            parts.append(f"completed {', '.join(removed_completed)} removed")
        in_progress = [todo.id for todo in todos if todo.status == "in_progress"]
        if in_progress:
            parts.append(f"{in_progress[0]} still in progress")
        blocked = [todo.id for todo in todos if todo.status == "blocked"]
        if blocked:
            parts.append(f"blocked {', '.join(blocked)} kept")
        if added_ids:
            parts.append(f"new {', '.join(added_ids)} pending")
        return "Todo impact: " + ("; ".join(parts) if parts else "no todo state to preserve") + "."


def diff_plans(old: "Plan", new: "Plan") -> RevisionDiff:
    """Compute the step diff between the approved plan and a revision."""
    old_by_id = {str(getattr(step, "id", "")): step for step in getattr(old, "steps", [])}
    seen: set = set()
    diff = RevisionDiff()
    for step in getattr(new, "steps", []):
        step_id = str(getattr(step, "id", ""))
        previous = old_by_id.get(step_id)
        if previous is None:
            diff.added.append(step)
            continue
        seen.add(step_id)
        # ``detail`` is optional implementation notes: a revision that omits it is
        # not a step change (title/acceptance are the contractual fields).
        old_tuple = (str(getattr(previous, "title", "")), str(getattr(previous, "acceptance", "")))
        new_tuple = (str(getattr(step, "title", "")), str(getattr(step, "acceptance", "")))
        if old_tuple != new_tuple:
            diff.changed.append(step)
        else:
            diff.unchanged.append(step)
    for step_id, step in old_by_id.items():
        if step_id not in seen:
            diff.removed.append(step)
    return diff


@dataclass
class PlanSession:
    """All persistent plan state of one REPL session.

    The object is shared (process-global singleton) by the CLI, the tool
    execution path and the LLM client. It owns no rendering and no TTY logic.
    """

    mode: str = PlanMode.NORMAL.value
    #: The approved plan currently being executed (status ``in-progress``).
    active_plan: Optional["Plan"] = None
    #: A submitted plan waiting for approval (first submission or a revision).
    draft_plan: Optional["Plan"] = None
    #: The approved plan before a revision (used to compute the diff / discard it).
    revision_base: Optional["Plan"] = None
    diff: Optional[RevisionDiff] = None
    todos: List[TodoItem] = field(default_factory=list)
    session_id: str = ""
    #: Plans root of this process (``cfg["PLAN_DIR"]`` or ``<config-dir>/plans``).
    plans_root: Optional[Path] = None
    #: This project's plan directory (``plans_root/<project-key>``).
    plan_dir: Optional[Path] = None
    cwd: Path = field(default_factory=Path.cwd)
    model: str = ""
    base_rev: str = ""
    change_summary: str = ""
    max_steps: int = 20
    keep: int = 80
    allow_readonly_shell: bool = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def configure(
        self,
        *,
        plans_root: Path,
        cwd: Optional[Path] = None,
        model: str = "",
        session_id: str = "",
        max_steps: int = 20,
        keep: int = 80,
        allow_readonly_shell: bool = True,
    ) -> None:
        """Configure the session paths/limits once (CLI startup / plan entry)."""
        self.reset()
        self.plans_root = Path(plans_root)
        self.cwd = Path(cwd) if cwd is not None else Path.cwd()
        self.model = str(model or "")
        self.session_id = str(session_id or "")
        self.max_steps = _positive_int(max_steps, 20)
        self.keep = _positive_int(keep, 80)
        self.allow_readonly_shell = bool(allow_readonly_shell)
        try:
            self.plan_dir = plan_store.project_plan_dir(self.plans_root, self.cwd)
        except Exception:  # pragma: no cover - defensive path resolution
            self.plan_dir = None

    def reset(self) -> None:
        """Forget all plan/todo state (configuration fields are kept)."""
        self.mode = PlanMode.NORMAL.value
        self.active_plan = None
        self.draft_plan = None
        self.revision_base = None
        self.diff = None
        self.todos = []
        self.base_rev = ""
        self.change_summary = ""

    def enter_researching(self) -> None:
        """Enter the read-only research phase (keeps an active plan for context)."""
        self.draft_plan = None
        self.revision_base = None
        self.diff = None
        self.change_summary = ""
        self.mode = PlanMode.RESEARCHING.value
        self.base_rev = self._current_git_rev()

    def enter_revising(self) -> None:
        """Enter the revision phase for the plan currently being executed."""
        active = self.active_plan
        self.draft_plan = None
        self.revision_base = active
        self.diff = None
        self.change_summary = ""
        self.mode = PlanMode.REVISING.value
        if active is not None:
            self.base_rev = str(getattr(active, "base_rev", "") or self._current_git_rev())

    def cancel_draft(self) -> None:
        """Drop an unapproved draft and leave planning (paused execution is kept)."""
        self.draft_plan = None
        self.revision_base = None
        self.diff = None
        self.change_summary = ""
        self.mode = PlanMode.NORMAL.value
        if self.active_plan is None:
            self.todos = []

    def to_session_dict(self) -> Dict[str, Any]:
        """Return the ``Chat.plan`` session JSON (empty dict without a plan).

        Covers both an executing (``in-progress``) plan and a saved draft
        (``[s]``ave only): the persisted session pointer is what lets ``--resume``
        print the "unfinished plan found" hint. Todos are only included when the
        plan is being executed (there are none for a draft).
        """
        plan = self.active_plan or self.draft_plan
        if plan is None:
            return {}
        path = getattr(plan, "path", None)
        payload: Dict[str, Any] = {
            "id": str(getattr(plan, "id", "")),
            "path": str(path) if path is not None else "",
            "status": str(getattr(plan, "status", "")),
            "revision": int(getattr(plan, "revision", 1) or 1),
            "session_id": str(getattr(plan, "session_id", "")),
            "base_rev": str(getattr(plan, "base_rev", "")),
            "updated": _now_iso(),
        }
        if self.todos:
            payload["todos"] = [todo.to_dict() for todo in self.todos]
        return payload

    def restore_from_session(
        self,
        data: dict,
        *,
        session_id: str,
        plans_root: Path,
        cwd: Path,
    ) -> Optional[str]:
        """Restore an unfinished plan from ``Chat.plan`` (session resume).

        Always restores in ``NORMAL`` mode: resuming never re-enters plan mode.
        An ``in-progress`` plan is restored into :attr:`active_plan`; a saved
        ``draft`` plan is restored into :attr:`draft_plan` (so ``/plan review`` can
        reopen it without pretending it is executing). Returns ``None`` on success,
        otherwise the one-line failure detail
        ``saved plan not found/inconsistent; starting in normal mode``.
        """
        detail = "saved plan not found/inconsistent; starting in normal mode"
        try:
            self.plans_root = Path(plans_root)
            self.cwd = Path(cwd)
            try:
                self.plan_dir = plan_store.project_plan_dir(self.plans_root, self.cwd)
            except Exception:  # pragma: no cover - defensive
                self.plan_dir = None
            if not isinstance(data, dict) or not data:
                return detail
            plan_id = str(data.get("id") or "").strip()
            path_text = str(data.get("path") or "").strip()
            if not plan_id or not path_text:
                return detail
            path = Path(path_text)
            if not path.is_file():
                return detail
            try:
                plan = plan_store.read_plan(path)
            except plan_store.PlanStoreError:
                return detail
            except (OSError, ValueError):
                return detail
            if str(getattr(plan, "id", "")) != plan_id:
                return detail
            stored_status = str(data.get("status") or "").strip()
            if stored_status not in (plan_store.PLAN_STATUS_DRAFT, plan_store.PLAN_STATUS_IN_PROGRESS):
                return detail
            if str(getattr(plan, "status", "")) != stored_status:
                return detail
            if str(getattr(plan, "session_id", "")) != str(session_id or ""):
                return detail
            todos: List[TodoItem] = []
            raw_todos = data.get("todos")
            if isinstance(raw_todos, list):
                for item in raw_todos:
                    todo = TodoItem.from_dict(item)
                    if todo.id:
                        todos.append(todo)
            if stored_status == plan_store.PLAN_STATUS_DRAFT:
                self.draft_plan = plan
                self.active_plan = None
            else:
                self.active_plan = plan
                self.draft_plan = None
            self.revision_base = None
            self.diff = None
            self.todos = todos
            self.change_summary = ""
            self.base_rev = str(getattr(plan, "base_rev", ""))
            self.mode = PlanMode.NORMAL.value
            return None
        except Exception:  # pragma: no cover - resume must never crash the REPL
            return detail

    # ------------------------------------------------------------------
    # Properties / summaries
    # ------------------------------------------------------------------
    @property
    def is_plan_mode(self) -> bool:
        """True while researching or revising (the read-only planning phase)."""
        return is_plan_mode_value(self.mode)

    @property
    def is_reviewing(self) -> bool:
        """True while a submitted plan waits for the approval panel."""
        return self.mode == PlanMode.REVIEWING.value

    @property
    def is_executing(self) -> bool:
        """True while an approved plan is being executed."""
        return is_execution_mode_value(self.mode)

    @property
    def active_plan_id(self) -> str:
        """Id of the active (executing) plan, or an empty string."""
        plan = self.active_plan
        return str(getattr(plan, "id", "") or "") if plan is not None else ""

    def all_todos_completed(self) -> bool:
        """True when every todo of the current plan is completed."""
        return bool(self.todos) and all(todo.status == "completed" for todo in self.todos)

    def todo_progress(self) -> Tuple[int, int]:
        """Return ``(completed, total)`` for the current todo list."""
        return (sum(1 for todo in self.todos if todo.status == "completed"), len(self.todos))

    def todo_snapshot(self) -> Tuple[Tuple[str, str], ...]:
        """Return an immutable ``((id, status), ...)`` snapshot for progress detection."""
        return tuple((todo.id, todo.status) for todo in self.todos)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _current_git_rev(self) -> str:
        try:
            return plan_store.git_rev(self.cwd)
        except Exception:  # pragma: no cover - git is optional
            return ""


def _positive_int(value: Any, default: int) -> int:
    """Coerce a config value to a positive int, falling back to ``default``."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _now_iso() -> str:
    """Current local time as an ISO-8601 string (plan file timestamps)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")
