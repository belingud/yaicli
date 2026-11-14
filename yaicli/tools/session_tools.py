"""Session-state tools: ``submit_plan`` and ``todo_write`` (v0.24 K23).

These two tools do not touch the workspace. They read/update the process-global
:class:`yaicli.plan_mode.PlanSession` (plan draft, todo list) and are exposed by
``yaicli.tools`` only in their matching mode:

* ``submit_plan`` — plan mode (researching/revising), the only way to end planning;
* ``todo_write`` — plan execution mode, after the user approved the plan.

Schemas are regular :class:`~yaicli.function_schema.OpenAISchema` models so the
OpenAI/Anthropic/Gemini generators all see one definition. Every ``execute``
returns a JSON string and reports expected failures in-band (never raises).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from .. import plan_mode
from ..function_schema import OpenAISchema

#: Session tool names exposed by this module (plan/todo state only).
SESSION_TOOL_NAMES = frozenset({"submit_plan", "todo_write"})


def _json(payload: Any) -> str:
    """Serialize a tool result payload for the model (never raises)."""
    try:
        return json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return json.dumps({"error": "json_serialization_failed"}, ensure_ascii=False)


def _as_payload(item: Any) -> Any:
    """Convert a pydantic model / dict item into a plain JSON-ready dict."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    if isinstance(item, dict):
        return dict(item)
    return item


def _as_str_list(value: Any) -> List[str]:
    """Best-effort list-of-strings normalization (execution adapters)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(entry) for entry in value if entry is not None]
    return []


class PlanStepInput(OpenAISchema):
    """One step of a plan submitted for approval."""

    id: str = Field(
        default="",
        description=(
            "Step id of an existing step when revising an approved plan (S1, S2, ...). "
            "Leave empty for a first submission; ids are assigned automatically."
        ),
    )
    title: str = Field(
        ...,
        description="Short imperative title of the step.",
    )
    detail: str = Field(
        default="",
        description="Optional implementation notes for the step.",
    )
    acceptance: str = Field(
        ...,
        description="How the step is verified (command, test or observable result). Required.",
    )

    class Config:
        title = "PlanStepInput"


class TodoItemInput(OpenAISchema):
    """One todo entry, 1:1 with a step of the current plan revision."""

    id: str = Field(
        ...,
        description="Step id of the current plan revision (S1, S2, ...).",
    )
    content: str = Field(
        default="",
        description="The step title. Omit it; todo entries cannot change step content.",
    )
    status: str = Field(
        ...,
        description="One of: pending, in_progress, completed, blocked.",
    )
    reason: str = Field(
        default="",
        description="Required when status is blocked: why the step cannot proceed.",
    )

    class Config:
        title = "TodoItemInput"


class SubmitPlanFunction(OpenAISchema):
    """Submit the implementation plan for the user to approve.

    Call this only in plan mode, as the final action of the planning phase: plan
    mode is read-only, so explore first (read files, search, read-only shell) and
    then submit the complete plan. The user reviews it in a panel and approves,
    edits or sends you back to planning. For a plan revision while already
    executing a plan, pass revision = current revision + 1, a change_summary and
    the complete updated step list.
    """

    goal: str = Field(
        ...,
        description="One-sentence goal of the plan (at most 500 characters).",
    )
    assumptions: List[str] = Field(
        default=[],
        description="Assumptions the plan relies on (optional).",
    )
    steps: List[PlanStepInput] = Field(
        ...,
        description=(
            "Ordered implementation steps (at most PLAN_MAX_STEPS, default 20). Every step needs a "
            "title and acceptance criteria; ids are assigned automatically on a first submission."
        ),
    )
    risks: List[str] = Field(
        default=[],
        description="Risks or trade-offs the user should know about (optional).",
    )
    not_doing: List[str] = Field(
        default=[],
        description="Work explicitly excluded from this plan (optional).",
    )
    revision: int = Field(
        default=0,
        description=(
            "Only for a revision while a plan is executing: the current plan revision + 1. "
            "Leave 0 for a first submission."
        ),
    )
    change_summary: str = Field(
        default="",
        description="Only for a revision: one-line summary of what changed and why (required, max 500).",
    )

    class Config:
        title = "submit_plan"

    @classmethod
    def execute(
        cls,
        goal: str,
        assumptions: List[str] = [],
        steps: List[PlanStepInput] = [],
        risks: List[str] = [],
        not_doing: List[str] = [],
        revision: int = 0,
        change_summary: str = "",
    ) -> str:
        """Validate/submit the plan through :func:`yaicli.plan_mode.handle_submit_plan`."""
        payload = {
            "goal": goal,
            "assumptions": _as_str_list(assumptions),
            "steps": [_as_payload(step) for step in (steps or [])],
            "risks": _as_str_list(risks),
            "not_doing": _as_str_list(not_doing),
            "revision": revision,
            "change_summary": change_summary,
        }
        return _json(plan_mode.handle_submit_plan(payload))


class TodoWriteFunction(OpenAISchema):
    """Update the todo list of the approved plan while executing it.

    Send the complete list, one entry per step of the current plan revision: step
    ids and step titles cannot change (adding or removing steps requires an
    approved plan revision). Keep exactly one step in_progress; mark it completed
    when done and move the next step to in_progress. Use blocked with a reason
    when a step cannot proceed.
    """

    items: List[TodoItemInput] = Field(
        ...,
        description="Every todo entry of the current plan revision, in step order.",
    )

    class Config:
        title = "todo_write"

    @classmethod
    def execute(cls, items: List[TodoItemInput] = []) -> str:
        """Validate/apply the todo list through :func:`yaicli.plan_mode.handle_todo_write`."""
        payload = {"items": [_as_payload(item) for item in (items or [])]}
        return _json(plan_mode.handle_todo_write(payload))


#: Tool name -> schema class (also defines the per-mode availability).
_SESSION_FUNCTIONS = {
    "submit_plan": SubmitPlanFunction,
    "todo_write": TodoWriteFunction,
}


def _schemas_for(mode: Any) -> List[type]:
    """Return the session tool classes offered in ``mode``."""
    normalized = str(mode or "")
    if normalized == "plan":
        return [SubmitPlanFunction]
    if normalized == "execution":
        return [TodoWriteFunction]
    return []


def openai_schemas(mode: str) -> List[dict]:
    """OpenAI-format session tool schemas for ``mode`` (``plan``/``execution``)."""
    return [{"type": "function", "function": cls.openai_schema} for cls in _schemas_for(mode)]


def anthropic_schemas(mode: str) -> List[dict]:
    """Anthropic-format session tool schemas for ``mode``."""
    return [cls.anthropic_schema for cls in _schemas_for(mode)]


def gemini_functions(mode: str) -> List[Any]:
    """Gemini-format session tool callables for ``mode``."""
    from .function import wrap_gemini_function

    functions: List[Any] = []
    for cls in _schemas_for(mode):
        wrapped = wrap_gemini_function(cls.execute)
        wrapped.__name__ = cls.openai_schema["name"]
        wrapped.__doc__ = cls.openai_schema.get("description", "")
        functions.append(wrapped)
    return functions


def execute_session_tool(name: str, arguments: Dict[str, Any]) -> str:
    """Execute one session tool by name; always returns a JSON string.

    Invalid arguments and unexpected failures are reported in-band so the model
    can fix its call (the same convention as the builtin tools).
    """
    func = _SESSION_FUNCTIONS.get(str(name or ""))
    if func is None:
        return _json(
            {
                "success": False,
                "error": "unknown_session_tool",
                "reason": f"{name!r} is not a session tool",
                "hint": "Available session tools: submit_plan (plan mode), todo_write (execution).",
            }
        )
    payload = arguments if isinstance(arguments, dict) else {}
    try:
        result = func.execute(**payload)
    except TypeError as exc:
        return _json(
            {
                "success": False,
                "error": "invalid_arguments",
                "reason": f"invalid arguments for {name}: {exc}",
                "hint": "Call the tool again with arguments matching its schema.",
            }
        )
    except Exception as exc:  # pragma: no cover - defensive: tools must never raise
        return _json(
            {
                "success": False,
                "error": "tool_error",
                "reason": f"{name} failed: {type(exc).__name__}: {exc}",
            }
        )
    if not isinstance(result, str):
        result = _json(result)
    _emit_todo_progress(name, result)
    return result


def _emit_todo_progress(name: str, result: str) -> None:
    """Print one REPL todo progress line after a successful state change.

    ``handle_todo_write`` reports the changed todo as ``current``; the display line
    is ``[todo i/N] Sx <title>`` (contract §13). Rendering lives here (not in
    plan_mode, which is Rich-free) and goes through ``yaicli.tools.console`` so
    headless/machine runs route it to stderr. Never raises.
    """
    if name != "todo_write":
        return
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return
    if not isinstance(payload, dict) or not payload.get("success"):
        return
    current = payload.get("current")
    if not isinstance(current, dict):
        return
    try:
        index = int(current.get("index") or 0)
        total = int(current.get("total") or 0)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return
    todo_id = str(current.get("id") or "")
    title = str(current.get("title") or "")
    if index <= 0 or total <= 0 or not todo_id:
        return
    try:
        from ..console import safe_text
        from .. import tools as tools_module

        tools_module.console.print(f"[todo {index}/{total}] {safe_text(todo_id)} {safe_text(title)}", style="cyan")
    except Exception:  # pragma: no cover - progress display must never break the tool
        pass


def session_tool_available(name: str, mode: Any) -> bool:
    """True when session tool ``name`` is offered in the given tool mode."""
    normalized = str(mode or "")
    tool_name = str(name or "")
    if tool_name == "submit_plan":
        return normalized == "plan"
    if tool_name == "todo_write":
        return normalized == "execution"
    return False


__all__ = [
    "SESSION_TOOL_NAMES",
    "PlanStepInput",
    "SubmitPlanFunction",
    "TodoItemInput",
    "TodoWriteFunction",
    "anthropic_schemas",
    "execute_session_tool",
    "gemini_functions",
    "openai_schemas",
    "session_tool_available",
]
