"""Permission evaluation independent of provider requests and confirmation generators."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .. import const as _const
from ..schemas import ToolConfirmDecision
from .approval import parse_tool_arguments
from .risk import RiskLevel, ShellRisk, classify_shell_command, get_tool_risk

# Keep normal tool requests free of optional plan-mode imports.
_SESSION_STATE_TOOL_NAMES = frozenset({"submit_plan", "todo_write"})


@dataclass(frozen=True)
class ToolDecision:
    """One gate outcome; a missing decision requests interactive confirmation."""

    risk: RiskLevel
    decision: Optional[ToolConfirmDecision] = ToolConfirmDecision.ONCE
    source: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None


def _gate_shell_risk(gate_name: str, parsed_arguments: Optional[Dict[str, Any]]) -> Optional[ShellRisk]:
    """Classify a shell tool call before it runs (``None`` for non-shell tools).

    The command is the *decoded* ``command`` argument, i.e. the same value
    ``execute_tool_call`` passes to the tool after ``json_repair``. Classification
    is advisory: the gate decides whether to confirm/deny, never the classifier.
    """
    if gate_name != "execute_shell_command" or not isinstance(parsed_arguments, dict):
        return None
    command = parsed_arguments.get("command")
    if not isinstance(command, str):
        return None
    try:
        return classify_shell_command(command)
    except Exception:  # pragma: no cover - classification must never break the gate
        return ShellRisk(
            level=RiskLevel.exec,
            dangerous=True,
            reasons=["shell command could not be classified safely"],
        )


def _approval_match_source(approval: Any, gate_name: str, parsed_arguments: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return why a call is pre-approved (``session``/``persist``/``rule``) or None.

    Duck-typed: tests and embedders may pass a minimal approval object exposing only
    the v1 ``is_allowed(name)`` signature; such managers simply have no rules.
    """
    match_source = getattr(approval, "match_source", None)
    if callable(match_source):
        try:
            return match_source(gate_name, parsed_arguments)
        except TypeError:  # legacy is_allowed-only stub missing this signature
            try:
                return match_source(gate_name)
            except Exception:
                return None
        except Exception:  # pragma: no cover - approval lookup must never break a turn
            return None

    is_allowed = getattr(approval, "is_allowed", None)
    if callable(is_allowed):
        try:
            allowed = is_allowed(gate_name, parsed_arguments)
        except TypeError:  # v1 signature: is_allowed(name)
            try:
                allowed = is_allowed(gate_name)
            except Exception:
                return None
        except Exception:  # pragma: no cover
            return None
        if allowed:
            return "persist"
    return None


def _approval_run_allowed(approval: Any, gate_name: str) -> bool:
    """True when the per-run ``--allowed-tools`` patterns match this tool name."""
    method = getattr(approval, "is_run_allowed", None)
    if not callable(method):
        return False
    try:
        return bool(method(gate_name))
    except Exception:  # pragma: no cover - run grants must never break a turn
        return False


def _approval_auto_allow_read(approval: Any) -> bool:
    """True when ``--yes`` was given for this run."""
    return bool(getattr(approval, "auto_allow_read", False))


def _readonly_deny_reason(gate_name: str, risk: RiskLevel) -> str:
    """Actionable reason for a ``TOOL_POLICY=readonly`` hard deny (K10)."""
    return (
        f"Tool '{gate_name}' (risk: {risk.value}) is blocked by TOOL_POLICY=readonly, which denies "
        "write/exec tools even when they are pre-approved or confirmation is disabled; the call was "
        "declined. Set TOOL_POLICY=standard (config.ini) or YAI_TOOL_POLICY=standard (environment) "
        "to allow it, or use a read-only tool instead."
    )


def _permissions_path_text(approval: Any) -> str:
    """Config-file path shown in deny hints (never a secret)."""
    path = getattr(approval, "permissions_path", None)
    return str(path) if path else str(_const.TOOL_PERMISSIONS_PATH)


def _non_interactive_deny_reason(approval: Any, gate_name: str, risk: RiskLevel) -> str:
    """Explain a policy denial to the model (it must be able to adapt)."""
    return (
        f"Tool '{gate_name}' (risk: {risk.value}) requires confirmation, but this session has no "
        "interactive terminal; the call was declined. Pre-approve it with --allowed-tools, add a "
        f"rule to {_permissions_path_text(approval)}, or run interactively."
    )


def _dangerous_deny_reason(shell_risk: ShellRisk, *, non_interactive: bool) -> str:
    """Explain why a danger-classified shell command was refused."""
    details = "; ".join(shell_risk.reasons) or "dangerous command"
    if non_interactive:
        return (
            f"Dangerous shell command refused in a non-interactive session; the call was declined "
            f"({details}). Pre-approval flags can not override the danger classification."
        )
    return (
        "Confirmation is disabled (TOOL_CONFIRM=false) and this shell command is classified as "
        f"dangerous, so the call was declined ({details}). Enable TOOL_CONFIRM to approve it explicitly."
    )


def evaluate_tool_call(
    name: str,
    raw_arguments: Any,
    *,
    config: Any,
    policy_mode: str,
    confirm_enabled: bool,
    interactive: bool,
    approval: Any,
    plan_state: Optional[str],
    selected: bool,
) -> ToolDecision:
    """Resolve the existing selection/plan/danger/policy/approval precedence.

    The caller performs prompts, persists grants, records audit and adds messages.
    This function never executes a tool or talks to a provider.
    """
    arguments = parse_tool_arguments(raw_arguments)
    risk = get_tool_risk(name)
    audit_risk = RiskLevel.read if name in _SESSION_STATE_TOOL_NAMES else risk
    shell_risk = _gate_shell_risk(name, arguments)
    if not selected:
        return ToolDecision(
            audit_risk,
            source="tool_selection",
            reason=(
                f"Tool '{name}' is not offered in this run (ENABLED_TOOLS/--tools selection); "
                "it was not executed. Use one of the offered tools, or add this tool to ENABLED_TOOLS "
                "and ask again."
            ),
            error="tool_disabled",
        )
    if plan_state is not None or name in _SESSION_STATE_TOOL_NAMES:
        reason = None
        if plan_state in ("researching", "revising"):
            from ..planning.model import is_tool_allowed_in_plan

            try:
                allow_readonly_shell = bool(config.get("PLAN_ALLOW_READONLY_SHELL", True))
            except (TypeError, AttributeError):
                allow_readonly_shell = True
            if is_tool_allowed_in_plan(name, allow_readonly_shell=allow_readonly_shell):
                return ToolDecision(audit_risk, source="plan_mode")
            reason = (
                f"Tool '{name}' is not available in plan mode; planning is read-only. "
                "Use the read/network tools or a read-only shell command, then call submit_plan, "
                "or leave plan mode with Shift+Tab."
            )
        elif plan_state == "executing" and name == "todo_write":
            return ToolDecision(audit_risk, source="plan_mode")
        elif name in _SESSION_STATE_TOOL_NAMES:
            reason = (
                f"Tool '{name}' is not available in mode '{plan_state or 'normal'}': it only "
                "runs while planning (submit_plan) or while executing an approved plan (todo_write)."
            )
        if reason is not None:
            return ToolDecision(audit_risk, source="plan_mode", reason=reason, error="tool_not_available_in_mode")
    if shell_risk is not None and shell_risk.dangerous:
        if not interactive:
            return ToolDecision(
                audit_risk,
                ToolConfirmDecision.DENY,
                "non_interactive",
                _dangerous_deny_reason(shell_risk, non_interactive=True),
            )
        if not confirm_enabled:
            return ToolDecision(
                audit_risk,
                ToolConfirmDecision.DENY,
                "disabled",
                _dangerous_deny_reason(shell_risk, non_interactive=False),
            )
        return ToolDecision(audit_risk, None, "prompt")
    if policy_mode == "readonly":
        if risk in (RiskLevel.write, RiskLevel.exec):
            return ToolDecision(audit_risk, ToolConfirmDecision.DENY, "policy", _readonly_deny_reason(name, risk))
        return ToolDecision(audit_risk, source="policy")
    if policy_mode == "trusted":
        return ToolDecision(audit_risk, source="policy")
    if not confirm_enabled:
        return ToolDecision(audit_risk, source="disabled")
    match_source = _approval_match_source(approval, name, arguments)
    if match_source is not None:
        return ToolDecision(audit_risk, source=match_source)
    if _approval_run_allowed(approval, name):
        return ToolDecision(audit_risk, source="allowlist")
    if _approval_auto_allow_read(approval) and risk is RiskLevel.read:
        return ToolDecision(audit_risk, source="yes")
    if not interactive:
        return ToolDecision(
            audit_risk, ToolConfirmDecision.DENY, "non_interactive", _non_interactive_deny_reason(approval, name, risk)
        )
    return ToolDecision(audit_risk, None, "prompt")
