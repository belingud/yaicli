import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

from .. import const as _const
from ..config import cfg
from ..console import get_console, get_error_console
from ..errors import (
    AgentError,
    ErrorKind,
    backoff_delay,
    classify_exception,
    parse_context_limit,
    retry_after_seconds,
)
from ..model_limits import (
    DEFAULT_CONTEXT_WINDOW,
    ModelLimits,
    context_input_budget,
    get_context_limits,
    record_learned_limit,
)
from ..runtime import SessionContext, bind_config
from ..schemas import (
    ChatMessage,
    ConfirmToolCall,
    LLMResponse,
    RefreshLive,
    ToolCall,
    ToolConfirmDecision,
    ToolPolicy,
)
from ..tokens import (
    estimate_messages_tokens,
    trim_messages_to_budget,
    trim_oldest_group,
)
from ..tools import execute_tool_call, tool_enabled
from ..tools.approval import (
    ToolApprovalManager,
    redact_text,
    summarize_arguments,
)
from ..tools.mcp import MCP_TOOL_NAME_PREFIX
from ..tools.policy import evaluate_tool_call
from ..tools.risk import RiskLevel
from ..usage import Usage, UsageTracker, estimate_usage
from .provider import ProviderFactory
from .tool_calls import dedupe_tool_calls

#: ``finish_reason`` value used when the tool-call depth limit stops the run.
DEPTH_LIMIT_FINISH_REASON = "depth_limit"


def _as_positive_int(value: Any) -> Optional[int]:
    """Best-effort positive-int parse (``None`` for unset/invalid values)."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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
        # ---- v0.23 K22 context-window resolution ----
        #: Normalized provider key; scopes the model-limits resolution/cache.
        "provider_key",
        #: Set after the one-time "unknown context window" stderr warning.
        "_limits_warned",
        #: Limits (window/source/detail) resolved for the last request budget.
        "last_context_limits",
        # ---- v0.22 K17 usage/cost observability ----
        #: Session token/cost/tool tracker (provider-reported + estimated usage).
        "usage_tracker",
        #: Usage of the most recent provider request round, or None before the first.
        "last_usage",
        #: True when the last top-level turn hit ``finish_reason == "length"``
        #: (the answer was truncated by MAX_TOKENS). Reset at the start of each turn.
        "output_truncated",
        #: Set after an oversized MAX_TOKENS was clamped to fit the context window
        #: (one stderr warning per client; the clamped value is written back to config).
        "_max_tokens_clamped",
        # Session-owned configuration and lazily constructed plan state.
        "runtime",
    )

    def __init__(
        self,
        provider_name: str,
        config: dict = cfg,
        verbose: bool = False,
        approval: Optional[ToolApprovalManager] = None,
        interactive: bool = True,
        runtime=None,
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
        self.runtime = runtime if runtime is not None else SessionContext(config)
        self.config = self.runtime.config
        self.verbose = verbose
        self.console = get_console()
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        self.enable_mcp = self.config["ENABLE_MCP"]
        self.approval = approval or ToolApprovalManager()
        self.interactive = interactive
        # v0.21 K10: normalizes on the first gate call; "standard" keeps v0.19 behaviour.
        self.tool_policy_mode: str = _const.DEFAULT_TOOL_POLICY
        self._tool_policy_warned: bool = False

        # Use provided provider or create one. The key is normalized once and kept
        # (``provider_key``) so model-limit resolution/caching uses the same scope
        # as the created provider, even if the config PROVIDER differs.
        provider_key = str(provider_name or "").strip().lower()
        if provider_key not in ProviderFactory.providers_map:
            self.console.print(f"Provider {provider_key} not found, using openai as default", style="yellow")
            provider_key = "openai"
        self.provider_key: str = provider_key
        self.provider = ProviderFactory.create_provider(
            provider_key, config=self.config, verbose=verbose, runtime=self.runtime, **kwargs
        )

        self.max_tool_call_depth = self.config["MAX_TOOL_CALL_DEPTH"]

        # ---- v0.19 K02/K05 state ----
        self.context_trimmed: bool = False
        self.depth_limit_reached: bool = False
        self.tool_denied: bool = False
        self.last_finish_reason: Optional[str] = None
        self.last_context_budget: int = 0
        self.last_tokens_estimate: int = 0
        self._context_retry_used: bool = False

        # ---- v0.23 K22 context-limit state ----
        self._limits_warned: bool = False
        self.last_context_limits: Optional[ModelLimits] = None

        # ---- v0.22 K17 usage/cost state ----
        self.usage_tracker: UsageTracker = UsageTracker()
        self.last_usage: Optional[Usage] = None
        self.output_truncated: bool = False
        self._max_tokens_clamped: bool = False

    @property
    def plan_session(self):
        return self.runtime.peek_plan_session()

    @plan_session.setter
    def plan_session(self, value):
        self.runtime.set_plan_session(value)

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
    def _provider_base_url(self) -> str:
        """Return the provider's effective base URL (``""`` for test doubles)."""
        base_url = getattr(self.provider, "base_url", "")
        return base_url if isinstance(base_url, str) else ""

    def _resolve_limits_and_budget(self) -> tuple:
        """Resolve the model limits and the per-request input budget (K22).

        Uses the layered resolver (:mod:`yaicli.model_limits`) with this client's
        provider metadata hook as the ``metadata`` layer. Side effects: stores
        :attr:`last_context_limits` and prints the one-time unknown-window warning
        (``source == "default"`` with a non-empty model) to stderr.
        """
        model = self._model_name()
        model_limits_fn = getattr(self.provider, "model_limits", None)
        fetcher = (lambda requested: model_limits_fn(requested)) if callable(model_limits_fn) else None
        limits = get_context_limits(
            self.provider_key,
            model,
            self.config,
            base_url=self._provider_base_url(),
            fetcher=fetcher,
        )
        budget = context_input_budget(
            limits,
            max_tokens=self.config.get("MAX_TOKENS"),
            safety_tokens=self.config.get("CONTEXT_SAFETY_TOKENS", 1024),
            override=self.config.get("CONTEXT_BUDGET_TOKENS"),
        )
        self._clamp_oversized_max_tokens(limits, budget)
        self.last_context_limits = limits
        self._warn_unknown_model_limits(limits, model)
        return limits, budget

    def _clamp_oversized_max_tokens(self, limits: ModelLimits, budget: int) -> None:
        """Clamp a MAX_TOKENS that would leave no room for the input (once).

        ``MAX_TOKENS`` is reserved out of the same context window as the input. A
        value close to (or above) the window — e.g. ``MAX_TOKENS=128000`` with the
        default 128k window — used to collapse the input budget to 1 token, so every
        request trimmed the entire conversation (a ``/load``-ed chat looked empty to
        the model even though ``/his`` had it). Clamp the effective output size for
        this process (input + output fit the window), warn on stderr, and keep the
        configuration coherent for the provider request.

        An explicit ``CONTEXT_BUDGET_TOKENS`` override is respected verbatim and
        disables this clamp.
        """
        if self._max_tokens_clamped:
            return
        if _as_positive_int(self.config.get("CONTEXT_BUDGET_TOKENS")) is not None:
            return
        requested = _as_positive_int(self.config.get("MAX_TOKENS"))
        if requested is None:
            return
        try:
            safety = max(0, int(self.config.get("CONTEXT_SAFETY_TOKENS", 1024) or 0))
        except (TypeError, ValueError):  # pragma: no cover - exotic config mappings
            safety = 1024
        cap = limits.window_for_budget()
        effective = max(1, cap - budget - safety)
        if requested <= effective:
            return
        self._max_tokens_clamped = True
        try:
            self.config["MAX_TOKENS"] = effective
        except (TypeError, AttributeError):  # pragma: no cover - read-only config mappings
            pass
        self._error_console().print(
            f"MAX_TOKENS={requested:,} + CONTEXT_SAFETY_TOKENS={safety:,} leaves no room for input "
            f"in the {cap:,}-token context window; using MAX_TOKENS={effective:,} for this session. "
            "Lower MAX_TOKENS in config.ini (or set MODEL_CONTEXT_WINDOWS to the model's real window) "
            "to silence this.",
            style="yellow",
        )

    def _warn_unknown_model_limits(self, limits: ModelLimits, model: str) -> None:
        """Warn once per client when the window is the conservative default (K22).

        Mirrors PRD Feature example 3: two plain stderr lines, ``dim yellow``, with
        a copy-pasteable override example. An empty model (tests/unconfigured) is
        never warned about; ``heuristic``/``catalog`` sources are known values.
        """
        if limits.source != "default" or not model or self._limits_warned:
            return
        self._limits_warned = True
        window = limits.window or DEFAULT_CONTEXT_WINDOW
        self._error_console().print(
            f'Context window for model "{model}" is unknown; assuming {window:,} tokens (source: default).\n'
            f'Set MODEL_CONTEXT_WINDOWS={{"{model}": 200000}} or CONTEXT_BUDGET_TOKENS to override.',
            style="dim yellow",
        )

    def _enforce_context_budget(self, messages: List[ChatMessage]) -> None:
        """Trim ``messages`` in place when it exceeds the per-request token budget.

        The caller's list object is mutated (``messages[:] = ...``) so the CLI keeps
        seeing the trimmed history. One short notice is printed to stderr so the
        user knows why older context disappeared.
        """
        try:
            _limits, budget = self._resolve_limits_and_budget()
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
        """Learn the real limit (when reported) and drop one turn group.

        The provider-reported upper bound (``errors.parse_context_limit``) is
        recorded *before* trimming so it survives even when there is no older turn
        group to drop. The budget is then recomputed from the learned limit and the
        request is retried **once** (never after content was already streamed).

        Returns True when the request may be retried.
        """
        if self._context_retry_used:
            return False
        self._context_retry_used = True

        learned_limit = parse_context_limit(exc)
        if learned_limit:
            try:
                record_learned_limit(
                    self.provider_key,
                    self._model_name(),
                    self._provider_base_url(),
                    learned_limit,
                    config=self.config,
                )
            except Exception:  # pragma: no cover - learning must never break a turn
                learned_limit = None
        learned_note = f"learned the real context limit ({learned_limit:,} tokens), " if learned_limit else ""

        result = trim_oldest_group(messages)
        if not result.removed_messages:
            return False
        messages[:] = result.messages
        # Recompute against the (now learned) limit; trim further when needed.
        try:
            _limits, budget = self._resolve_limits_and_budget()
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
            f"Provider rejected the request as too long; {learned_note}dropped "
            f"{result.removed_count} older message(s) and retrying once "
            f"({result.tokens_before:,} -> {self.last_tokens_estimate:,} est. tokens).",
            style="yellow",
        )
        return True

    @staticmethod
    def _raise_empty_response(finish_reason: Optional[str]) -> None:
        """Fail for a provider response with no text, reasoning or tool calls.

        Some failures are HTTP 200: pointing ``BASE_URL`` at a web page or a wrong
        API path makes the OpenAI SDK parse an empty stream and return no chunks at
        all. Without this check the CLI printed nothing and exited 0. The error is
        classified as :attr:`ErrorKind.EMPTY_RESPONSE` so the REPL/headless paths
        surface it (and JSON consumers get ``error.kind = "empty_response"``).
        """
        detail = "Provider returned an empty response (no text, no reasoning, no tool calls)"
        if finish_reason:
            detail += f" (finish_reason={finish_reason})"
        raise AgentError(
            f"{detail}. The endpoint answered but returned no model output; check BASE_URL "
            "(an OpenAI-compatible base URL usually ends with /v1), the API path and the model.",
            kind=ErrorKind.EMPTY_RESPONSE,
            retryable=False,
        )

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
        round_finish_reason: Optional[str] = None
        for llm_response in self._stream_provider(messages, stream, effective_tool_policy):
            yield llm_response  # Forward response to caller

            if llm_response.finish_reason:
                round_finish_reason = llm_response.finish_reason
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

        # A provider can answer with HTTP 200 while sending no usable payload at all
        # (a web page served by a wrong BASE_URL, a proxy error page parsed as an
        # empty SSE stream, ...). Before the tool-loop bookkeeping, fail loudly: a
        # silent empty answer used to look like success and hid broken endpoints.
        if not assistant_response_content and not assistant_reasoning_content and not collected_tool_calls:
            self._raise_empty_response(round_finish_reason)

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
            with bind_config(self.config):
                outcome = evaluate_tool_call(
                    gate_name,
                    raw_arguments,
                    config=self.config,
                    policy_mode=policy_mode,
                    confirm_enabled=confirm_enabled,
                    interactive=self.interactive,
                    approval=self.approval,
                    plan_state=getattr(self.plan_session, "mode", None) if self.plan_session is not None else None,
                    selected=tool_enabled(gate_name, runtime=self.runtime),
                )
            audit_risk = outcome.risk
            if outcome.error is not None:
                messages.append(
                    ChatMessage(
                        role=tool_role,
                        content=json.dumps({"error": outcome.error, "reason": outcome.reason}, ensure_ascii=False),
                        name=gate_name.removeprefix(MCP_TOOL_NAME_PREFIX),
                        tool_call_id=tool_call.id,
                    )
                )
                self._audit_tool_decision(
                    tool=gate_name,
                    risk=audit_risk,
                    policy=policy_mode,
                    decision="disabled" if outcome.error == "tool_disabled" else "denied",
                    source=outcome.source,
                    arguments=raw_arguments,
                    duration_ms=0.0,
                    reason=outcome.reason,
                )
                continue

            decision = outcome.decision
            source = outcome.source
            reason = outcome.reason
            prompted = decision is None
            if prompted:
                decision = (yield ConfirmToolCall(tool_call)) or ToolConfirmDecision.DENY

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
                    risk=audit_risk,
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
            function_result, ok = execute_tool_call(tool_call, announce=not prompted, runtime=self.runtime)
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
                risk=audit_risk,
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
