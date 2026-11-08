import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

from .. import const as _const
from ..config import cfg
from ..console import get_console, get_error_console
from ..errors import AgentError, ErrorKind, backoff_delay, classify_exception, retry_after_seconds
from ..schemas import ChatMessage, ConfirmToolCall, LLMResponse, RefreshLive, ToolCall, ToolConfirmDecision, ToolPolicy
from ..tokens import (
    estimate_messages_tokens,
    resolve_context_budget,
    trim_messages_to_budget,
    trim_oldest_group,
)
from ..tools import execute_tool_call
from ..tools.approval import (
    ToolApprovalManager,
    parse_tool_arguments,
    redact_text,
    summarize_arguments,
)
from ..tools.mcp import MCP_TOOL_NAME_PREFIX
from ..tools.risk import RiskLevel, ShellRisk, classify_shell_command, get_tool_risk
from ..usage import Usage, UsageTracker, estimate_usage
from .provider import ProviderFactory
from .tool_calls import dedupe_tool_calls

#: ``finish_reason`` value used when the tool-call depth limit stops the run.
DEPTH_LIMIT_FINISH_REASON = "depth_limit"


class LLMClient:
    """
    LLM Client that coordinates provider interactions and tool calling

    This class handles the higher level logic of:
    1. Getting responses from LLM providers
    2. Managing tool calls and their execution
    3. Handling conversation flow with tools
    """

    __slots__ = (
        "config",
        "verbose",
        "console",
        "enable_function",
        "enable_mcp",
        "max_tool_call_depth",
        "provider",
        "approval",
        "interactive",
        # ---- v0.21 K10 permission policy mode ----
        #: Effective ``TOOL_POLICY`` mode (readonly/standard/trusted), normalized
        #: once per gate call and recorded in every audit line.
        "tool_policy_mode",
        #: Set after the one-time invalid-TOOL_POLICY stderr warning.
        "_tool_policy_warned",
        # ---- v0.19 K02/K05 outcome + context state (read by the CLI) ----
        #: True when conversation history was trimmed to fit the token budget.
        "context_trimmed",
        #: True when the tool-call depth limit stopped the run.
        "depth_limit_reached",
        #: True when at least one tool call was denied by the approval gate.
        "tool_denied",
        #: ``finish_reason`` of the last provider response (``depth_limit`` when the
        #: depth limit fired).
        "last_finish_reason",
        #: Estimated token budget / prompt size of the last request (for /context).
        "last_context_budget",
        "last_tokens_estimate",
        #: One context-length self-heal per top-level request.
        "_context_retry_used",
        # ---- v0.22 K17 usage/cost observability ----
        #: Session token/cost/tool tracker (provider-reported + estimated usage).
        "usage_tracker",
        #: Usage of the most recent provider request round, or None before the first.
        "last_usage",
        #: True when the last top-level turn hit ``finish_reason == "length"``
        #: (the answer was truncated by MAX_TOKENS). Reset at the start of each turn.
        "output_truncated",
    )

    def __init__(
        self,
        provider_name: str,
        config: dict = cfg,
        verbose: bool = False,
        approval: Optional[ToolApprovalManager] = None,
        interactive: bool = True,
        **kwargs,
    ):
        """
        Initialize LLM client

        Args:
            provider_name: Name of the provider to use, default to openai if not known
            config: Configuration dictionary
            verbose: Whether to enable verbose logging
            approval: Tool approval manager (created if not provided)
            interactive: Whether the session can prompt the user (TTY available)
        """
        self.config = config
        self.verbose = verbose
        self.console = get_console()
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        self.enable_mcp = self.config["ENABLE_MCP"]
        self.approval = approval or ToolApprovalManager()
        self.interactive = interactive
        # v0.21 K10: normalizes on the first gate call; "standard" keeps v0.19 behaviour.
        self.tool_policy_mode: str = _const.DEFAULT_TOOL_POLICY
        self._tool_policy_warned: bool = False

        # Use provided provider or create one
        if provider_name not in ProviderFactory.providers_map:
            self.console.print(f"Provider {provider_name} not found, using openai as default", style="yellow")
            provider_name = "openai"
        self.provider = ProviderFactory.create_provider(provider_name, config=config, verbose=verbose, **kwargs)

        self.max_tool_call_depth = self.config["MAX_TOOL_CALL_DEPTH"]

        # ---- v0.19 K02/K05 state ----
        self.context_trimmed: bool = False
        self.depth_limit_reached: bool = False
        self.tool_denied: bool = False
        self.last_finish_reason: Optional[str] = None
        self.last_context_budget: int = 0
        self.last_tokens_estimate: int = 0
        self._context_retry_used: bool = False

        # ---- v0.22 K17 usage/cost state ----
        self.usage_tracker: UsageTracker = UsageTracker()
        self.last_usage: Optional[Usage] = None
        self.output_truncated: bool = False

    # ------------------- usage / cost (v0.22 K17) -------------------
    @property
    def session_usage(self) -> Usage:
        """Accumulated session usage (provider-reported plus estimated)."""
        return self.usage_tracker.total

    def usage_snapshot(self) -> Dict[str, Any]:
        """JSON-ready session usage/metrics payload (CLI JSON, stream-json, ``/cost``)."""
        return self.usage_tracker.snapshot(self.config)

    # ------------------- diagnostics -------------------
    @staticmethod
    def _error_console():
        """Diagnostics (trim notices, retries, depth warnings) always go to stderr."""
        return get_error_console()

    # ------------------- context budget (K02) -------------------
    def _enforce_context_budget(self, messages: List[ChatMessage]) -> None:
        """Trim ``messages`` in place when it exceeds the per-request token budget.

        The caller's list object is mutated (``messages[:] = ...``) so the CLI keeps
        seeing the trimmed history. One short notice is printed to stderr so the
        user knows why older context disappeared.
        """
        try:
            budget = resolve_context_budget(self.config, self._model_name())
        except Exception:  # pragma: no cover - config lookups must never break a turn
            budget = 0
        tokens = estimate_messages_tokens(messages)
        self.last_context_budget = budget
        self.last_tokens_estimate = tokens
        if budget <= 0 or tokens <= budget:
            return

        result = trim_messages_to_budget(messages, budget)
        self.last_tokens_estimate = result.tokens_after
        if not result.removed_messages:
            return
        messages[:] = result.messages
        self.context_trimmed = True
        self._error_console().print(
            f"Context over budget: trimmed {len(result.removed_messages)} older messages "
            f"({result.tokens_before} -> {result.tokens_after} est. tokens, budget {budget}).",
            style="dim yellow",
        )

    def _heal_context_length(self, messages: List[ChatMessage], exc: BaseException) -> bool:
        """Drop one extra turn group (and trim to budget) for a context-length 400.

        Returns True when the request may be retried once. The retry is allowed at
        most once per top-level request, and never after content was already
        streamed to the user (retrying then would duplicate output).
        """
        if self._context_retry_used:
            return False
        self._context_retry_used = True

        result = trim_oldest_group(messages)
        if not result.removed_messages:
            return False
        messages[:] = result.messages
        # If the heuristic still says "over budget", trim further before retrying.
        try:
            budget = resolve_context_budget(self.config, self._model_name())
        except Exception:  # pragma: no cover - config lookups must never break a turn
            budget = 0
        if budget > 0 and estimate_messages_tokens(messages) > budget:
            further = trim_messages_to_budget(messages, budget)
            if further.removed_messages:
                messages[:] = further.messages
        self.context_trimmed = True
        self.last_context_budget = budget
        self.last_tokens_estimate = estimate_messages_tokens(messages)
        self._error_console().print(
            f"Provider rejected the request as too long; dropped {result.removed_count} older "
            f"message(s) and retrying once ({result.tokens_before} -> "
            f"{self.last_tokens_estimate} est. tokens).",
            style="yellow",
        )
        return True

    def _model_name(self) -> str:
        try:
            return str(self.config.get("MODEL") or "")
        except Exception:  # pragma: no cover - defensive config mapping
            return ""

    # ------------------- retry / self-heal wrapper (K05) -------------------
    def _retry_policy(self) -> tuple:
        """Return ``(enabled, max_retries, base_delay, max_delay)`` from config."""
        try:
            enabled = bool(self.config.get("RETRY_ENABLED", True))
        except Exception:  # pragma: no cover
            enabled = True
        try:
            max_retries = max(0, int(self.config.get("RETRY_MAX", 2)))
        except (TypeError, ValueError):
            max_retries = 2
        try:
            base_delay = max(0.0, float(self.config.get("RETRY_BASE_DELAY", 1.0)))
        except (TypeError, ValueError):
            base_delay = 1.0
        try:
            max_delay = max(0.0, float(self.config.get("RETRY_MAX_DELAY", 8.0)))
        except (TypeError, ValueError):
            max_delay = 8.0
        return enabled, max_retries, base_delay, max_delay

    def _stream_provider(
        self,
        messages: List[ChatMessage],
        stream: bool,
        tool_policy: ToolPolicy,
    ) -> Generator[LLMResponse, None, None]:
        """Call the provider, applying context self-heal and transient-error retries.

        * ``context_length`` failures: trim one extra turn group and retry **once**
          (never retry blindly; auth/bad-request/rate-limit are handled separately).
        * rate-limit / network / timeout / 5xx failures: exponential backoff retry
          (``RETRY_ENABLED``/``RETRY_MAX``/``RETRY_BASE_DELAY``), but only when
          nothing has been streamed yet — a stream that broke after partial output
          raises a clear :class:`AgentError` instead of silently duplicating text.
        """
        enabled, max_retries, base_delay, max_delay = self._retry_policy()
        attempt = 0
        while True:
            started = False
            try:
                for response in self.provider.completion(messages, stream=stream, tool_policy=tool_policy):
                    started = True
                    yield response
                return
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                error = classify_exception(exc)

                if error.kind is ErrorKind.CONTEXT_LENGTH and not started:
                    if self._heal_context_length(messages, exc):
                        continue
                    raise AgentError(
                        f"Context length exceeded and automatic trimming could not fix it "
                        f"({error.message}). Use /clear or /compact, then retry; "
                        "or raise CONTEXT_BUDGET_TOKENS for models with a larger window.",
                        kind=ErrorKind.CONTEXT_LENGTH,
                        cause=exc,
                    ) from exc

                if started:
                    # Partial content was already shown: retrying would duplicate it
                    # and re-run any tool the model was about to request.
                    raise AgentError(
                        f"Streaming failed after partial content ({error.kind.value}): {error.message}. "
                        "The partial answer was not saved; retry the turn.",
                        kind=error.kind,
                        cause=exc,
                    ) from exc

                if not enabled or attempt >= max_retries or not error.retryable:
                    raise

                delay = backoff_delay(
                    attempt,
                    base=base_delay,
                    max_delay=max_delay,
                    retry_after=retry_after_seconds(exc),
                )
                self._error_console().print(
                    f"Provider error ({error.kind.value}); retrying in {delay:.1f}s ({attempt + 1}/{max_retries})...",
                    style="yellow",
                )
                if delay > 0:
                    time.sleep(delay)
                attempt += 1

    # ------------------- completion -------------------
    def completion_with_tools(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
        recursion_depth: int = 0,
        tool_policy: Optional[ToolPolicy] = None,
    ) -> Generator[Union[LLMResponse, RefreshLive, ConfirmToolCall], Optional[ToolConfirmDecision], None]:
        """
        Get completion from provider with tool calling support

        Args:
            messages: List of messages for the conversation
            stream: Whether to stream the response
            recursion_depth: Current recursion depth for tool calls

        Yields:
            LLMResponse objects and control signals
        """
        if recursion_depth >= self.max_tool_call_depth:
            self.depth_limit_reached = True
            self.last_finish_reason = DEPTH_LIMIT_FINISH_REASON
            self._error_console().print(
                f"Reached tool-call limit ({self.max_tool_call_depth}). Use --max-turns to adjust.",
                style="bold yellow",
            )
            # Structured end-of-run signal: the display layer renders nothing for an
            # empty content, and the CLI maps ``depth_limit_reached`` to its exit code.
            yield LLMResponse(content="", finish_reason=DEPTH_LIMIT_FINISH_REASON)
            return

        if recursion_depth == 0:
            # A new user request gets its own (single) context-length self-heal
            # and its own truncation flag (K17: one MAX_TOKENS warning per turn).
            self._context_retry_used = False
            self.output_truncated = False

        effective_tool_policy = self.provider.resolve_tool_policy(tool_policy)

        # Trace-visible budget bookkeeping (also used by /context in the REPL).
        self._enforce_context_budget(messages)

        # Get completion from provider and collect response data
        assistant_response_content = ""
        assistant_reasoning_content = ""  # Collect reasoning content
        # A provider response/stream can carry several calls (parallel tool use).
        # Collect every one, in arrival order; duplicates (a streaming provider
        # re-yielding the same accumulated call) are removed by id below.
        collected_tool_calls: List[ToolCall] = []

        # Stream responses and collect data
        # Usage is attached by providers to exactly one response per request round;
        # record the first non-None snapshot only so re-yielded/duplicate snapshots
        # (streaming providers may repeat calls) can never double-count tokens.
        round_usage: Optional[Usage] = None
        for llm_response in self._stream_provider(messages, stream, effective_tool_policy):
            yield llm_response  # Forward response to caller

            if llm_response.finish_reason:
                self.last_finish_reason = llm_response.finish_reason
                if llm_response.finish_reason == "length":
                    # MAX_TOKENS truncation: surfaced by the CLI as a warning and
                    # in JSON output instead of silently ending the answer.
                    self.output_truncated = True

            response_usage = getattr(llm_response, "usage", None)
            if response_usage is not None and round_usage is None:
                round_usage = response_usage

            # Collect content and tool calls for potential tool execution
            if llm_response.content:
                assistant_response_content += llm_response.content
            if llm_response.reasoning:  # Collect reasoning content
                assistant_reasoning_content += llm_response.reasoning
            response_tool_calls = getattr(llm_response, "tool_calls", None)
            if not response_tool_calls:
                # Duck-typed/legacy response objects may only expose the singular view.
                legacy_tool_call = getattr(llm_response, "tool_call", None)
                response_tool_calls = [legacy_tool_call] if legacy_tool_call is not None else []
            collected_tool_calls.extend(response_tool_calls)

        # Record this request's usage: exactly once per provider round.
        if round_usage is not None:
            self.last_usage = round_usage
            self.usage_tracker.record(round_usage, self._model_name())
        else:
            # The provider reported nothing (e.g. an OpenAI-compatible proxy that
            # rejects stream_options): estimate once for this request so token/cost
            # visibility still works, flagged ``estimated``.
            completion_text = assistant_response_content
            if assistant_reasoning_content:
                completion_text += assistant_reasoning_content
            estimated_usage = estimate_usage(messages, completion_text)
            self.last_usage = estimated_usage
            self.usage_tracker.record(estimated_usage, self._model_name())

        # Dedupe by id (streaming providers may repeat a snapshot) and make sure
        # every call has an id so the assistant message and tool results match.
        tool_calls = dedupe_tool_calls(collected_tool_calls)
        valid_tool_calls = self._get_valid_tool_calls(tool_calls, effective_tool_policy)
        if self.verbose and tool_calls and len(valid_tool_calls) != len(tool_calls):
            skipped_tools = [tool_call.name for tool_call in tool_calls if tool_call not in valid_tool_calls]
            self.console.print(f"Skipping disallowed tool calls: {', '.join(skipped_tools)}", style="dim yellow")

        assistant_message = ChatMessage(
            role="assistant",
            content=assistant_response_content,
            tool_calls=valid_tool_calls,
            reasoning=assistant_reasoning_content if assistant_reasoning_content else None,  # Save reasoning
        )
        messages.append(assistant_message)

        if not valid_tool_calls:
            return

        # Execute tools and continue conversation
        yield from self._execute_tools_and_continue(
            messages,
            valid_tool_calls,
            stream,
            recursion_depth,
            effective_tool_policy,
        )

    def _get_valid_tool_calls(self, tool_calls: List[ToolCall], tool_policy: ToolPolicy) -> List[ToolCall]:
        """Filter tool calls based on enabled features, preserving arrival order."""
        valid_tool_calls = []

        for tool_call in tool_calls:
            if self.verbose:
                self.console.print(f"Raw tool call name: {tool_call.name}")
            is_mcp = tool_call.name.startswith(MCP_TOOL_NAME_PREFIX)

            if is_mcp and tool_policy.enable_mcp:
                valid_tool_calls.append(tool_call)
            elif not is_mcp and tool_policy.enable_functions:
                valid_tool_calls.append(tool_call)

        return valid_tool_calls

    # ------------------- approval gate helpers (v0.19 K06) -------------------
    def _gate_shell_risk(self, gate_name: str, parsed_arguments: Optional[Dict[str, Any]]) -> Optional[ShellRisk]:
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

    def _approval_match_source(self, gate_name: str, parsed_arguments: Optional[Dict[str, Any]]) -> Optional[str]:
        """Return why a call is pre-approved (``session``/``persist``/``rule``) or None.

        Duck-typed: tests and embedders may pass a minimal approval object exposing only
        the v1 ``is_allowed(name)`` signature; such managers simply have no rules.
        """
        match_source = getattr(self.approval, "match_source", None)
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

        is_allowed = getattr(self.approval, "is_allowed", None)
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

    def _approval_run_allowed(self, gate_name: str) -> bool:
        """True when the per-run ``--allowed-tools`` patterns match this tool name."""
        method = getattr(self.approval, "is_run_allowed", None)
        if not callable(method):
            return False
        try:
            return bool(method(gate_name))
        except Exception:  # pragma: no cover - run grants must never break a turn
            return False

    def _approval_auto_allow_read(self) -> bool:
        """True when ``--yes`` was given for this run."""
        return bool(getattr(self.approval, "auto_allow_read", False))

    # ------------------- permission policy mode (v0.21 K10) -------------------
    def _resolve_tool_policy_mode(self) -> str:
        """Resolve and normalize the session-wide ``TOOL_POLICY`` mode.

        The mode comes from the layered config (``YAI_TOOL_POLICY`` env >
        config.ini > default ``standard``). Comparison is case-insensitive and
        whitespace-trimmed; an empty value means unset (uses the default silently),
        while any other unrecognized value falls back to ``standard`` with exactly
        ONE stderr warning per client — never per tool call. The resolved value is
        cached on the instance and recorded in every audit line.
        """
        raw: Any
        try:
            raw = self.config.get("TOOL_POLICY", _const.DEFAULT_TOOL_POLICY)
        except (AttributeError, TypeError):  # pragma: no cover - exotic config mappings
            raw = _const.DEFAULT_TOOL_POLICY
        mode = str(raw).strip().lower() if raw is not None else ""
        if not mode:
            mode = _const.DEFAULT_TOOL_POLICY
        if mode in _const.TOOL_POLICY_MODES:
            self.tool_policy_mode = mode
            return mode

        if not self._tool_policy_warned:
            self._tool_policy_warned = True
            self._error_console().print(
                f"Invalid TOOL_POLICY value {raw!r}; falling back to "
                f"'{_const.DEFAULT_TOOL_POLICY}' (valid values: {', '.join(_const.TOOL_POLICY_MODES)}).",
                style="yellow",
            )
        self.tool_policy_mode = _const.DEFAULT_TOOL_POLICY
        return self.tool_policy_mode

    @staticmethod
    def _readonly_deny_reason(gate_name: str, risk: RiskLevel) -> str:
        """Actionable reason for a ``TOOL_POLICY=readonly`` hard deny (K10)."""
        return (
            f"Tool '{gate_name}' (risk: {risk.value}) is blocked by TOOL_POLICY=readonly, which denies "
            "write/exec tools even when they are pre-approved or confirmation is disabled; the call was "
            "declined. Set TOOL_POLICY=standard (config.ini) or YAI_TOOL_POLICY=standard (environment) "
            "to allow it, or use a read-only tool instead."
        )

    def _remember_approval(self, gate_name: str, decision: ToolConfirmDecision) -> None:
        """Store a SESSION/PERSIST prompt decision on the approval manager."""
        if decision == ToolConfirmDecision.SESSION:
            allow_session = getattr(self.approval, "allow_session", None)
            if callable(allow_session):
                allow_session(gate_name)
        elif decision == ToolConfirmDecision.PERSIST:
            allow_persist = getattr(self.approval, "allow_persist", None)
            if not callable(allow_persist):
                return
            try:
                allow_persist(gate_name)
            except OSError:
                # Persisting failed (e.g., disk/permission); keep it for the session.
                allow_session = getattr(self.approval, "allow_session", None)
                if callable(allow_session):
                    allow_session(gate_name)
                self.console.print(
                    f"Could not persist approval for '{gate_name}'; allowed for this session only.",
                    style="yellow",
                )

    def _permissions_path_text(self) -> str:
        """Config-file path shown in deny hints (never a secret)."""
        path = getattr(self.approval, "permissions_path", None)
        return str(path) if path else str(_const.TOOL_PERMISSIONS_PATH)

    def _non_interactive_deny_reason(self, gate_name: str, risk: RiskLevel) -> str:
        """Explain a policy denial to the model (it must be able to adapt)."""
        return (
            f"Tool '{gate_name}' (risk: {risk.value}) requires confirmation, but this session has no "
            "interactive terminal; the call was declined. Pre-approve it with --allowed-tools, add a "
            f"rule to {self._permissions_path_text()}, or run interactively."
        )

    @staticmethod
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

    def _audit_enabled(self) -> bool:
        """True when this config asks for the tool audit log.

        ``TOOL_AUDIT`` is ``true`` in the shipped config; a hand-built embedding config
        that omits the key opts out (keeps unit tests from writing the real config dir).
        """
        try:
            if "TOOL_AUDIT" not in self.config:
                return False
            return bool(self.config["TOOL_AUDIT"])
        except (TypeError, AttributeError):  # pragma: no cover - exotic config mappings
            return False

    def _audit_tool_decision(
        self,
        *,
        tool: str,
        risk: RiskLevel,
        decision: str,
        source: Optional[str],
        arguments: Any,
        duration_ms: float,
        policy: str,
        reason: Optional[str] = None,
    ) -> None:
        """Append one JSON line per gate decision to ``const.TOOL_AUDIT_PATH``.

        Best effort by design: an unwritable/odd log must never affect a tool call.
        The file is opened append-only with mode ``0600`` on creation. ``policy`` is
        the effective ``TOOL_POLICY`` mode (v0.21 K10) recorded on every decision.
        """
        if not self._audit_enabled():
            return
        try:
            record: Dict[str, Any] = {
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tool": str(tool),
                "risk": risk.value if isinstance(risk, RiskLevel) else str(risk),
                "policy": str(policy),
                "decision": decision,
                "source": source or "prompt",
                "args_summary": summarize_arguments(tool, arguments),
                "duration_ms": max(0, int(round(duration_ms))),
            }
            if reason:
                record["reason"] = redact_text(str(reason))[:300]
            line = json.dumps(record, ensure_ascii=False) + "\n"
            path = Path(_const.TOOL_AUDIT_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
        except Exception:  # pragma: no cover - audit must never break tool execution
            pass

    def _execute_tools_and_continue(
        self,
        messages: List[ChatMessage],
        tool_calls: List[ToolCall],
        stream: bool,
        recursion_depth: int,
        tool_policy: ToolPolicy,
    ) -> Generator[Union[LLMResponse, RefreshLive, ConfirmToolCall], Optional[ToolConfirmDecision], None]:
        """Execute tool calls and continue the conversation.

        Each tool call passes through the v0.19 K06 permission gate before it runs.
        The session-wide ``TOOL_POLICY`` mode (v0.21 K10) is a hard ceiling/floor:

        * ``standard`` (default): the v0.19 flow — rules, then ``--allowed-tools``,
          then ``--yes`` (read only), then prompt or non-interactive deny;
        * ``readonly``: auto-allows ``read``/``network`` tools and hard-denies
          ``write``/``exec`` tools (approvals, ``--yes``, ``--allowed-tools`` and
          ``TOOL_CONFIRM=false`` cannot override the deny);
        * ``trusted``: auto-allows every non-dangerous tool without prompting.

        Independently of the mode, a danger-classified shell command keeps its
        precedence: interactive confirmation (denied when ``TOOL_CONFIRM=false``) or
        a non-interactive deny. Denied calls still receive a matching structured
        ``{"error": "tool_denied", "reason": ...}`` tool result so the provider request
        stays valid, and one audit line (including the effective ``policy``) is
        appended per decision when ``TOOL_AUDIT`` is on.
        """
        # Signal that new content is coming
        yield RefreshLive()

        # Assistant message has already been added to messages in completion_with_tools

        # Execute each tool call and add results to messages
        tool_role = self.provider.detect_tool_role()
        try:
            confirm_enabled = bool(self.config.get("TOOL_CONFIRM", True))
        except (TypeError, AttributeError):  # pragma: no cover - exotic config mappings
            confirm_enabled = True
        # v0.21 K10: normalize TOOL_POLICY once per gate, not per tool call.
        policy_mode = self._resolve_tool_policy_mode()

        for tool_call in tool_calls:
            # Capture the gate-time name: MCP names keep the _mcp__ prefix here,
            # but execute_tool_call strips it in place at execution time.
            gate_name = getattr(tool_call, "name", "") or ""
            raw_arguments = getattr(tool_call, "arguments", "")
            parsed_arguments = parse_tool_arguments(raw_arguments)
            risk = get_tool_risk(gate_name)
            shell_risk = self._gate_shell_risk(gate_name, parsed_arguments)
            dangerous = bool(shell_risk is not None and shell_risk.dangerous)

            decision = ToolConfirmDecision.ONCE
            source: Optional[str] = None
            reason: Optional[str] = None
            prompted = False

            if dangerous:
                # A danger-classified shell command can never be auto-approved: it needs
                # an explicit interactive confirmation, and non-interactive runs refuse it.
                # This branch keeps its precedence in every TOOL_POLICY mode (K10).
                if not self.interactive:
                    decision, source = ToolConfirmDecision.DENY, "non_interactive"
                    reason = self._dangerous_deny_reason(shell_risk, non_interactive=True)
                elif not confirm_enabled:
                    decision, source = ToolConfirmDecision.DENY, "disabled"
                    reason = self._dangerous_deny_reason(shell_risk, non_interactive=False)
                else:
                    decision = (yield ConfirmToolCall(tool_call)) or ToolConfirmDecision.DENY
                    prompted = True
                    source = "prompt"
            elif policy_mode == "readonly":
                # K10 hard ceiling: no approval, run-grant or TOOL_CONFIRM=false escape.
                if risk in (RiskLevel.write, RiskLevel.exec):
                    decision, source = ToolConfirmDecision.DENY, "policy"
                    reason = self._readonly_deny_reason(gate_name, risk)
                else:
                    decision, source = ToolConfirmDecision.ONCE, "policy"
            elif policy_mode == "trusted":
                # K10 floor: every non-dangerous tool runs without a prompt.
                decision, source = ToolConfirmDecision.ONCE, "policy"
            elif not confirm_enabled:
                decision, source = ToolConfirmDecision.ONCE, "disabled"
            else:
                match_source = self._approval_match_source(gate_name, parsed_arguments)
                if match_source is not None:
                    decision, source = ToolConfirmDecision.ONCE, match_source
                elif self._approval_run_allowed(gate_name):
                    decision, source = ToolConfirmDecision.ONCE, "allowlist"
                elif self._approval_auto_allow_read() and risk is RiskLevel.read:
                    decision, source = ToolConfirmDecision.ONCE, "yes"
                elif not self.interactive:
                    decision, source = ToolConfirmDecision.DENY, "non_interactive"
                    reason = self._non_interactive_deny_reason(gate_name, risk)
                else:
                    decision = (yield ConfirmToolCall(tool_call)) or ToolConfirmDecision.DENY
                    prompted = True
                    source = "prompt"

            if decision in (ToolConfirmDecision.SESSION, ToolConfirmDecision.PERSIST):
                self._remember_approval(gate_name, decision)

            if decision == ToolConfirmDecision.DENY:
                self.tool_denied = True
                if reason is None:
                    reason = "The user declined to execute this tool."
                denied_result = json.dumps({"error": "tool_denied", "reason": reason}, ensure_ascii=False)
                messages.append(
                    ChatMessage(
                        role=tool_role,
                        content=denied_result,
                        # De-prefix MCP names to match the executed path (execute_tool_call
                        # strips the prefix), so the result name is consistent either way.
                        name=gate_name.removeprefix(MCP_TOOL_NAME_PREFIX),
                        tool_call_id=tool_call.id,
                    )
                )
                self._audit_tool_decision(
                    tool=gate_name,
                    risk=risk,
                    policy=policy_mode,
                    decision="denied",
                    source=source,
                    arguments=raw_arguments,
                    duration_ms=0.0,
                    reason=reason,
                )
                if source != "prompt":
                    # Policy denial: one stderr diagnostic so the operator (not just the
                    # model) knows why nothing ran. stdout stays clean in machine mode.
                    self._error_console().print(f"Tool '{gate_name}' was denied: {reason}", style="yellow")
                continue

            # Avoid double-printing the call: the prompt already showed it when we prompted.
            started_at = time.perf_counter()
            function_result, ok = execute_tool_call(tool_call, announce=not prompted)
            duration_ms = (time.perf_counter() - started_at) * 1000.0
            # K17 tool metrics: executed calls only (denied calls never ran), with
            # the real wall-clock duration and the size of the result as the model sees it.
            self.usage_tracker.record_tool(duration_ms, len(function_result) if isinstance(function_result, str) else 0)

            messages.append(
                ChatMessage(
                    role=tool_role,
                    content=function_result,
                    name=tool_call.name,
                    tool_call_id=tool_call.id,
                )
            )
            self._audit_tool_decision(
                tool=gate_name,
                risk=risk,
                policy=policy_mode,
                decision="allowed" if ok else "error",
                source=source,
                arguments=raw_arguments,
                duration_ms=duration_ms,
            )

        # Continue the conversation with updated history
        yield from self.completion_with_tools(
            messages,
            stream=stream,
            recursion_depth=recursion_depth + 1,
            tool_policy=tool_policy,
        )
