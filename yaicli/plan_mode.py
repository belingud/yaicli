"""Persistent plan mode state machine (v0.24 K23).

Plan mode turns an agent task into two phases: a **read-only research** phase that
ends with :func:`handle_submit_plan` (the only exit), and an **execution** phase
driven by ``todo_write`` after the user approved the plan.

This module owns:

* the session state machine (``normal`` / ``researching`` / ``revising`` /
  ``reviewing`` / ``executing``) and the process-global singleton shared by the
  CLI, the tool execution path and the LLM client;
* the tool-visibility rules (which builtin/session tools are offered while
  planning vs. executing);
* ``submit_plan`` / ``todo_write`` validation and persistence side effects
  (plan files, todo checkboxes, audit lines);
* plan revisions: ``diff`` rendering data and the in-place plan.md update;
* the plan context block injected into the system prompt, and the todo summary;
* the ``$EDITOR`` draft/edit helpers used by the approval panel.

Design notes / boundaries:

* This module never imports :mod:`yaicli.tools`, :mod:`yaicli.cli` or
  :mod:`yaicli.printer` (the tool layer imports this module lazily instead), and
  it never renders Rich output: user-visible rendering belongs to the CLI/printer.
* The plan files are written by the CLI side only (plan_store); agent filesystem
  tools are refused under the plans root by ``tools/workspace.py``.
* Expected failures are returned in-band as JSON-ready dicts and never raised to
  the model. User-visible messages match the frozen implement contract (§13).
"""

from __future__ import annotations

import enum
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import const, plan_store
from .config import cfg

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .plan_store import Plan, PlanStep

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


#: Builtin read/network tools exposed while planning (never write/exec tools).
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
#: The controlled read-only shell tool (validated by :mod:`yaicli.plan_shell`).
PLAN_SHELL_TOOL = "execute_shell_command"
#: Session-state tools: they mutate plan/todo state, never the workspace.
SESSION_TOOL_NAMES = frozenset({"submit_plan", "todo_write"})

#: Maximum accepted length of the model-supplied plan fields.
MAX_GOAL_CHARS = 500
MAX_CHANGE_SUMMARY_CHARS = 500
MAX_BLOCKED_REASON_CHARS = 500
#: Maximum serialized size of one submitted plan (bytes, UTF-8).
MAX_PLAN_BYTES = 8 * 1024

_ERROR_HINT = "Fix the arguments and call submit_plan again; nothing was saved."


# ---------------------------------------------------------------------------
# Tool visibility helpers (consumed by yaicli.tools)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Todo items
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Revision diff
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Plan session
# ---------------------------------------------------------------------------
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


def _utc_stamp() -> str:
    """UTC timestamp used by audit lines (same format as the tool audit)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Global singleton (shared by CLI / tools / client)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Audit (best effort JSONL, same file/format as the tool audit)
# ---------------------------------------------------------------------------
def _audit_enabled() -> bool:
    """True when the config asks for the audit log (absent key = opt out)."""
    try:
        if "TOOL_AUDIT" not in cfg:
            return False
        return bool(cfg.get("TOOL_AUDIT"))
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


# ---------------------------------------------------------------------------
# Plan validation
# ---------------------------------------------------------------------------
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


def handle_submit_plan(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Handle one ``submit_plan`` tool call (first submission or a revision).

    Success (first submission) writes the draft plan file and moves the session
    to ``reviewing``; a revision only builds the in-memory draft + diff (the plan
    file is rewritten in place on approval). Returns JSON-ready data, never raises.
    """
    session = get_plan_session()
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


# ---------------------------------------------------------------------------
# todo_write
# ---------------------------------------------------------------------------
def seed_todos(plan: "Plan") -> List[TodoItem]:
    """Seed the todo list from the approved plan (S1 in progress, rest pending)."""
    todos = [TodoItem(id=str(getattr(step, "id", "")), content=str(getattr(step, "title", ""))) for step in plan.steps]
    if todos:
        todos[0].status = "in_progress"
    return todos


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


def handle_todo_write(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Handle one ``todo_write`` tool call during plan execution."""
    session = get_plan_session()
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


def _atomic_write_text(path: Path, text: str) -> None:
    """Atomically write ``text`` to ``path`` with 0600 permissions (temp + replace)."""
    path = Path(path)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, text.encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(str(temp), str(path))
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - Windows / exotic filesystems
            pass
    except BaseException:
        try:
            temp.unlink()
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Revision / lifecycle handlers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Context blocks / summaries
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# $EDITOR helpers
# ---------------------------------------------------------------------------
def write_plan_editor_draft(session: PlanSession, plan: "Plan") -> Path:
    """Write a hidden draft file (``.<id>.editor.md``, 0600) for the ``[e]`` action."""
    directory = session.plan_dir
    if directory is None:
        plan_path = getattr(plan, "path", None)
        directory = Path(plan_path).parent if plan_path is not None else Path.cwd()
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover - caller surfaces the write error
        pass
    path = directory / f".{getattr(plan, 'id', 'plan')}.editor.md"
    _atomic_write_text(path, plan.to_markdown())
    return path


def edit_plan_file(path: Path) -> Tuple[bool, str]:
    """Open ``path`` in ``$EDITOR`` (fallback ``vi``) and re-validate the plan file.

    Returns ``(True, "")`` when the edited file parses, else ``(False, error)``
    with the user-visible reason (never raises).
    """
    path = Path(path)
    editor = os.environ.get("EDITOR", "").strip() or "vi"
    try:
        argv = shlex.split(editor)
    except ValueError:  # pragma: no cover - malformed EDITOR value
        argv = [editor]
    if not argv:
        argv = ["vi"]
    try:
        completed = subprocess.run(argv + [str(path)], check=False)
    except (OSError, ValueError):
        return False, "cannot open editor; plan unchanged"
    except Exception:  # pragma: no cover - defensive
        return False, "cannot open editor; plan unchanged"
    if int(getattr(completed, "returncode", 0) or 0) != 0:
        return False, "cannot open editor; plan unchanged"
    try:
        plan_store.read_plan(path)
    except plan_store.PlanStoreError as exc:
        return False, f"invalid plan file: {path}: {exc}"
    except (OSError, ValueError) as exc:
        return False, f"invalid plan file: {path}: {exc}"
    return True, ""


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
