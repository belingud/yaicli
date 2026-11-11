"""Token estimation, context budget and turn-group-aware message trimming.

This module is the SDK-free core of the v0.19 K02 "context economy" work. It is
imported on the request path (:mod:`yaicli.llms.client`) and by the slash-command
handler (:mod:`yaicli.cmd_handler`), so it must stay cheap and dependency free.

Since v0.23 K22 the *window* and the *budget formula* are not defined here: they
are delegated to :mod:`yaicli.model_limits` (single source of truth). This module
only estimates tokens (a conservative heuristic), trims whole turn groups and
assembles the ``/context`` usage breakdown.

The estimator is deliberately a heuristic, not a tokenizer: exact token counts
differ per provider/model, and the goal is "never send a payload the model will
reject", which only needs a conservative, monotonic estimate:

* latin/ASCII text: ~3.5 characters per token;
* CJK text: ~1 token per character (much denser);
* a fixed overhead per message (role markers/separators) and per request;
* images: one high-detail image worth of tokens (plus base64 payload density).

Trimming is **turn-group** aware: a group is one user message plus the
assistant/tool messages that follow it. Groups are dropped whole, oldest first,
so an ``assistant`` message carrying ``tool_calls`` can never be separated from
its ``tool`` results (the pairing invariant providers enforce).
"""

import math
import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .model_limits import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_SAFETY_TOKENS,
    OLLAMA_DEFAULT_CONTEXT_WINDOW,
    ModelLimits,
    context_input_budget,
    get_context_limits,
)

#: Rough characters-per-token for latin/ASCII text.
CHARS_PER_TOKEN = 3.5
#: CJK characters are much denser: ~1 token per character (conservative).
CJK_TOKENS_PER_CHAR = 1.0
#: Fixed framing overhead per message (role markers, separators).
MESSAGE_OVERHEAD_TOKENS = 4
#: A request carries a few priming tokens beyond the sum of its messages.
REQUEST_OVERHEAD_TOKENS = 3
#: Token charge for one image input (high-detail image estimate).
IMAGE_TOKENS = 850

#: CJK ranges (Han, Hiragana/Katakana, Hangul, CJK punctuation/fullwidth forms).
_CJK_RE = re.compile(
    "[\u2e80-\u2eff\u2f00-\u2fdf\u3040-\u30ff\u3100-\u312f\u31a0-\u31bf"
    "\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\u3000-\u303f\uff00-\uffef]"
)

#: Kinds of messages that carry a tool result rather than a new user turn.
_TOOL_RESULT_ROLES = ("tool", "function")


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------
def estimate_tokens(text: Any) -> int:
    """Estimate the number of tokens in ``text`` (``None``/``""`` -> 0).

    Latin text is charged ``len / 3.5``; every CJK character is charged one token.
    The result is rounded up and never lower than 1 for non-empty text, so the
    estimate is monotonic with respect to added content.
    """
    if text is None:
        return 0
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    raw = cjk * CJK_TOKENS_PER_CHAR + other / CHARS_PER_TOKEN
    return max(1, int(math.ceil(raw)))


def _field(message: Any, name: str, default: Any = None) -> Any:
    """Read a field from a :class:`ChatMessage` or a plain OpenAI-style dict."""
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def _image_tokens(message: Any) -> int:
    """Estimate image tokens: one high-detail image plus base64 payload density."""
    total = 0
    images = _field(message, "images") or ()
    try:
        iterable = list(images)
    except TypeError:  # pragma: no cover - defensive
        iterable = []
    for image in iterable:
        data = _field(image, "data", "") or ""
        is_url = bool(_field(image, "is_url", False))
        if not isinstance(data, str):
            data = str(data)
        # A remote URL is billed as one image; local base64 payloads are much
        # denser (roughly one token per four base64 characters).
        payload = 0 if is_url else len(data) // 4
        total += max(IMAGE_TOKENS, IMAGE_TOKENS + payload)
    return total


def estimate_message_tokens(message: Any) -> int:
    """Estimate the tokens one message contributes to the request payload."""
    tokens = MESSAGE_OVERHEAD_TOKENS
    tokens += estimate_tokens(_field(message, "content"))
    tokens += estimate_tokens(_field(message, "reasoning"))
    tokens += estimate_tokens(_field(message, "name"))
    tokens += estimate_tokens(_field(message, "tool_call_id"))
    for tool_call in _field(message, "tool_calls") or ():
        tokens += 2  # Call framing (id/type/function keys)
        tokens += estimate_tokens(_field(tool_call, "id"))
        tokens += estimate_tokens(_field(tool_call, "name"))
        tokens += estimate_tokens(_field(tool_call, "arguments"))
    tokens += _image_tokens(message)
    return tokens


def _sum_messages(messages: Sequence[Any]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def estimate_messages_tokens(messages: Optional[Sequence[Any]]) -> int:
    """Estimate the tokens of a complete message list (request framing included)."""
    if not messages:
        return 0
    return _sum_messages(messages) + REQUEST_OVERHEAD_TOKENS


# ---------------------------------------------------------------------------
# Context windows and budget (delegated to :mod:`yaicli.model_limits`)
# ---------------------------------------------------------------------------
def _config_getter(config: Optional[Mapping[str, Any]]) -> Optional[Callable[..., Any]]:
    """Return ``config.get`` when ``config`` is mapping-like, else ``None``."""
    getter = getattr(config, "get", None)
    return getter if callable(getter) else None


def _as_text(value: Any) -> str:
    """Coerce a config value to a string (``None`` -> ``""``)."""
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _as_int(value: Any) -> Optional[int]:
    """Coerce a config value to ``int``; ``None`` when unset or not numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _budget_inputs(config: Optional[Mapping[str, Any]]) -> Tuple[Optional[int], int, Optional[int]]:
    """Return ``(max_tokens, safety_tokens, override)`` for the budget formula.

    Missing keys fall back to ``MAX_TOKENS`` unset (no output reserve) and
    :data:`yaicli.model_limits.DEFAULT_SAFETY_TOKENS`; a present-but-invalid
    value is ignored rather than crashing a request.
    """
    getter = _config_getter(config)
    if getter is None:
        return None, DEFAULT_SAFETY_TOKENS, None
    max_tokens = _as_int(getter("MAX_TOKENS"))
    safety_tokens = _as_int(getter("CONTEXT_SAFETY_TOKENS", DEFAULT_SAFETY_TOKENS))
    return max_tokens, 0 if safety_tokens is None else safety_tokens, _as_int(getter("CONTEXT_BUDGET_TOKENS"))


def _resolve_limits(
    config: Optional[Mapping[str, Any]],
    model: Optional[str],
    provider: Optional[str],
) -> ModelLimits:
    """Resolve model limits, defaulting model/provider from ``config``."""
    getter = _config_getter(config)
    if provider is None:
        provider = _as_text(getter("PROVIDER")) if getter is not None else ""
    if model is None:
        model = _as_text(getter("MODEL")) if getter is not None else ""
    return get_context_limits(_as_text(provider), _as_text(model), config)


def get_context_window(model: Optional[str] = None, provider: Optional[str] = None) -> int:
    """Return the resolved context window (tokens) for ``model``/``provider``.

    Kept as a compatibility wrapper (old imports/tests): the authoritative
    resolution (user -> learned -> metadata -> catalog -> heuristic -> default)
    lives in :func:`yaicli.model_limits.get_context_limits`. A local Ollama
    server without metadata/catalog data resolves to its small default window.
    """
    limits = get_context_limits(_as_text(provider), _as_text(model), None)
    return int(limits.window or DEFAULT_CONTEXT_WINDOW)


def resolve_context_budget(
    config: Optional[Mapping[str, Any]] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> int:
    """Resolve the per-request input-token budget (v0.23 K22 formula).

    ``budget = max(1, min(window, max_input) - MAX_TOKENS - CONTEXT_SAFETY_TOKENS)``
    via :func:`yaicli.model_limits.context_input_budget`; ``CONTEXT_BUDGET_TOKENS > 0``
    still overrides the result verbatim (backward-compatible escape hatch).
    ``model``/``provider`` default to the configured ``MODEL``/``PROVIDER``.
    """
    limits = _resolve_limits(config, model, provider)
    max_tokens, safety_tokens, override = _budget_inputs(config)
    return context_input_budget(
        limits,
        max_tokens=max_tokens,
        safety_tokens=safety_tokens,
        override=override,
    )


# ---------------------------------------------------------------------------
# Turn groups and pairing invariant
# ---------------------------------------------------------------------------
def _role(message: Any) -> str:
    role = _field(message, "role")
    return role if isinstance(role, str) else ""


def _is_tool_result(message: Any) -> bool:
    """True when ``message`` carries a tool result.

    Gemini uses ``role="user"`` for function responses, so the presence of a
    ``tool_call_id`` is the reliable discriminator (the client always sets it).
    """
    if _field(message, "tool_call_id"):
        return True
    return _role(message) in _TOOL_RESULT_ROLES and _role(message) != "user"


def _starts_turn(message: Any) -> bool:
    """True when ``message`` opens a new user turn (not a tool result)."""
    return _role(message) == "user" and not _field(message, "tool_call_id")


def split_turn_groups(messages: Sequence[Any]) -> Tuple[List[Any], List[List[Any]]]:
    """Split ``messages`` into ``(leading_system_messages, turn_groups)``.

    Leading ``system`` messages (role prompt, persistent context) are returned
    separately because they are always preserved. Every remaining message lands
    in exactly one group; a group starts at a real user message, so an
    ``assistant``(tool_calls) message and its following tool results stay within
    the same group. Leading non-system messages (e.g. a legacy orphan assistant
    message) form their own group instead of leaking into the preserved prefix.
    """
    items = list(messages)
    prefix: List[Any] = []
    index = 0
    while index < len(items) and _role(items[index]) == "system":
        prefix.append(items[index])
        index += 1

    groups: List[List[Any]] = []
    current: List[Any] = []
    for message in items[index:]:
        if _starts_turn(message) and current:
            groups.append(current)
            current = []
        current.append(message)
    if current:
        groups.append(current)
    return prefix, groups


def _tool_call_ids(message: Any) -> List[str]:
    ids = []
    for tool_call in _field(message, "tool_calls") or ():
        call_id = _field(tool_call, "id")
        if isinstance(call_id, str) and call_id:
            ids.append(call_id)
    return ids


def _with_tool_calls(message: Any, tool_calls: List[Any]) -> Any:
    """Return a copy of ``message`` with a filtered ``tool_calls`` list."""
    if isinstance(message, dict):
        copied = dict(message)
        copied["tool_calls"] = tool_calls
        return copied
    try:
        return replace(message, tool_calls=tool_calls)
    except (TypeError, ValueError):  # pragma: no cover - duck-typed message object
        try:
            message.tool_calls = tool_calls
        except Exception:
            pass
        return message


def repair_tool_pairing(messages: Sequence[Any]) -> List[Any]:
    """Return ``messages`` with invalid tool pairing removed.

    Two protocol violations are repaired:

    * an orphan tool result (``tool_call_id`` with no preceding
      ``assistant`` message that requested it) is dropped;
    * an ``assistant`` tool call that never received a tool result is removed
      from that assistant message (its text content is kept).

    Valid input is returned as the same objects, unchanged.
    """
    items = list(messages)
    pending: Dict[str, Any] = {}
    unanswered: set = set()
    assistant_entries: List[Tuple[int, List[Any]]] = []
    result: List[Any] = []
    changed = False

    def finalize_pending() -> None:
        nonlocal pending
        if pending:
            unanswered.update(pending)
            pending = {}

    for message in items:
        if _is_tool_result(message):
            call_id = _field(message, "tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                changed = True  # orphan tool result: drop it
                continue
            pending.pop(call_id, None)
            result.append(message)
            continue

        # Any non-tool message ends the opportunity for the previous assistant's
        # tool calls to receive their results.
        finalize_pending()
        if _role(message) == "assistant":
            raw_calls = list(_field(message, "tool_calls") or ())
            result.append(message)
            if raw_calls:
                assistant_entries.append((len(result) - 1, raw_calls))
                pending = {_field(call, "id"): call for call in raw_calls if _field(call, "id")}
            continue

        result.append(message)

    finalize_pending()
    if unanswered:
        for position, calls in assistant_entries:
            if not any(_field(call, "id") in unanswered for call in calls):
                continue
            kept_calls = [call for call in calls if _field(call, "id") not in unanswered]
            result[position] = _with_tool_calls(result[position], kept_calls)
            changed = True

    return result if changed else items


def validate_tool_pairing(messages: Sequence[Any]) -> List[str]:
    """Return a list of tool-pairing protocol errors (empty list = valid).

    Used by the tests and by :func:`trim_messages_to_budget` as a safety net.
    """
    errors: List[str] = []
    pending: Dict[str, int] = {}
    for index, message in enumerate(messages):
        if _is_tool_result(message):
            call_id = _field(message, "tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                errors.append(f"message {index}: orphan tool result {call_id!r}")
                continue
            pending.pop(call_id, None)
            continue
        if pending:
            for call_id in pending:
                errors.append(f"message {index}: tool call {call_id!r} has no matching tool result")
            pending = {}
        if _role(message) == "assistant":
            for call_id in _tool_call_ids(message):
                pending[call_id] = index
    for call_id in pending:
        errors.append(f"end: tool call {call_id!r} has no matching tool result")
    return errors


# ---------------------------------------------------------------------------
# Trimming
# ---------------------------------------------------------------------------
@dataclass
class TrimResult:
    """Outcome of :func:`trim_messages_to_budget`."""

    messages: List[Any]
    removed_messages: List[Any]
    tokens_before: int
    tokens_after: int

    @property
    def removed_count(self) -> int:
        """How many messages were dropped."""
        return len(self.removed_messages)

    @property
    def trimmed(self) -> bool:
        """True when at least one message was dropped."""
        return bool(self.removed_messages)

    @property
    def saved_tokens(self) -> int:
        """Estimated tokens removed from the request."""
        return max(0, self.tokens_before - self.tokens_after)


def _cap_group_count(groups: List[List[Any]], max_messages: Optional[int]) -> List[List[Any]]:
    """Drop oldest groups until the retained message count fits ``max_messages``.

    A whole group always wins over the cap (never split a turn), and at least one
    group is always retained.
    """
    if max_messages is None or not groups:
        return groups
    limit = max(1, int(max_messages))
    kept: List[List[Any]] = []
    total = 0
    for group in reversed(groups):
        if kept and total + len(group) > limit:
            break
        kept.append(group)
        total += len(group)
    kept.reverse()
    return kept


def _finish_trim(original: List[Any], prefix: List[Any], groups: List[List[Any]], tokens_before: int) -> TrimResult:
    retained = repair_tool_pairing(list(prefix) + [message for group in groups for message in group])
    kept_ids = {id(message) for message in retained}
    removed = [message for message in original if id(message) not in kept_ids]
    return TrimResult(
        messages=retained,
        removed_messages=removed,
        tokens_before=tokens_before,
        tokens_after=estimate_messages_tokens(retained),
    )


def trim_messages_to_budget(
    messages: Sequence[Any],
    budget: int,
    keep_recent_groups: Optional[int] = None,
    max_messages: Optional[int] = None,
) -> TrimResult:
    """Trim ``messages`` to ``budget`` tokens at whole-turn-group boundaries.

    Modes:

    * ``keep_recent_groups is None``: keep the newest groups that fit into
      ``budget`` tokens (the preserved system prefix is always kept, even when it
      alone exceeds the budget) — at least one group always survives.
    * ``keep_recent_groups=N``: keep exactly the newest ``N`` groups and ignore
      the token budget (used by ``/compact``). ``max_messages`` can still cap the
      retained message count.

    Leading system/context messages are always preserved. The returned messages
    additionally pass through :func:`repair_tool_pairing`, so trimming can never
    produce an orphan ``tool`` message or an unanswered ``tool_calls`` message.
    """
    original = list(messages)
    tokens_before = estimate_messages_tokens(original)
    prefix, groups = split_turn_groups(original)

    if keep_recent_groups is not None:
        keep = max(1, int(keep_recent_groups))
        selected = list(groups[-keep:]) if groups else []
        selected = _cap_group_count(selected, max_messages)
    else:
        effective_budget = max(1, int(budget))
        used = _sum_messages(prefix)
        selected = []
        for group in reversed(groups):
            group_tokens = _sum_messages(group)
            if selected and used + group_tokens > effective_budget:
                break
            selected.append(group)
            used += group_tokens
        selected.reverse()
        selected = _cap_group_count(selected, max_messages)

    return _finish_trim(original, prefix, selected, tokens_before)


def trim_oldest_group(messages: Sequence[Any]) -> TrimResult:
    """Drop the oldest turn group (first fallback of the context-length self-heal).

    Returns an unchanged result when there is no older group to drop (a session
    with a single user turn): the caller must then fail with an actionable error.
    """
    original = list(messages)
    tokens_before = estimate_messages_tokens(original)
    prefix, groups = split_turn_groups(original)
    if len(groups) <= 1:
        return TrimResult(
            messages=original,
            removed_messages=[],
            tokens_before=tokens_before,
            tokens_after=tokens_before,
        )
    return _finish_trim(original, prefix, groups[1:], tokens_before)


# ---------------------------------------------------------------------------
# REPL /command helpers
# ---------------------------------------------------------------------------
@dataclass
class ContextUsage:
    """Estimated context usage breakdown shown by ``/context``.

    The four request buckets are reported separately so the UI can render the
    v0.23 K22 layout:

    * ``system_tokens`` — the role prompt (``system_text``);
    * ``project_tokens`` — the auto-loaded project instructions block
      (``extra_system_text``);
    * ``extra_tokens`` — persistent ``/add context`` messages (``extra_messages``);
    * ``history_tokens`` — the conversation history (tool output summarized in
      ``tool_output_tokens``);
    * ``overhead_tokens`` — the fixed request priming tokens
      (:data:`REQUEST_OVERHEAD_TOKENS`); shown as its own row so the rendered
      buckets add up to ``total_tokens``.

    ``window_tokens``/``max_output_tokens``/``source``/``detail`` come from the
    resolved :class:`yaicli.model_limits.ModelLimits`; ``reserve_tokens`` is
    ``MAX_TOKENS + CONTEXT_SAFETY_TOKENS``. ``source == "default"`` means the
    window is unknown (the caller should tell the user how to override it).
    """

    system_tokens: int = 0
    project_tokens: int = 0
    extra_tokens: int = 0
    history_tokens: int = 0
    tool_output_tokens: int = 0
    overhead_tokens: int = 0
    total_tokens: int = 0
    budget_tokens: int = 0
    remaining_tokens: int = 0
    used_percent: float = 0.0
    message_count: int = 0
    window_tokens: int = 0
    max_output_tokens: int = 0
    source: str = ""
    detail: str = ""
    reserve_tokens: int = 0


def _text_block_tokens(text: Optional[str]) -> int:
    """Estimate one system-prompt text block (framing overhead included)."""
    tokens = estimate_tokens(text)
    return tokens + MESSAGE_OVERHEAD_TOKENS if tokens else 0


def estimate_context_usage(
    messages: Optional[Sequence[Any]] = None,
    config: Optional[Mapping[str, Any]] = None,
    system_text: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    extra_system_text: Optional[str] = None,
    extra_messages: Optional[Sequence[Any]] = None,
) -> ContextUsage:
    """Estimate the usage breakdown for the interactive ``/context`` command.

    ``messages`` is the conversation history (system messages excluded — the role
    prompt is passed via ``system_text``). ``extra_system_text`` is the project
    instruction block and ``extra_messages`` are persistent ``/add context``
    messages; both are reported as their own buckets and counted in the total.
    Tool output is reported inside ``history_tokens``.
    """
    history = list(messages or ())
    extra = list(extra_messages or ())
    system_tokens = _text_block_tokens(system_text)
    project_tokens = _text_block_tokens(extra_system_text)
    history_tokens = _sum_messages(history)
    extra_tokens = _sum_messages(extra)
    tool_output_tokens = 0
    for message in history:
        if _is_tool_result(message) or _role(message) in _TOOL_RESULT_ROLES:
            tool_output_tokens += estimate_message_tokens(message)

    total = system_tokens + project_tokens + extra_tokens + history_tokens
    overhead_tokens = REQUEST_OVERHEAD_TOKENS if (history or project_tokens or extra_tokens) else 0
    total += overhead_tokens

    limits = _resolve_limits(config, model, provider)
    budget = resolve_context_budget(config, model, provider)
    max_tokens, safety_tokens, _override = _budget_inputs(config)
    reserve_tokens = max(0, max_tokens or 0) + max(0, safety_tokens)
    remaining = max(0, budget - total)
    used_percent = (total / budget * 100.0) if budget > 0 else 0.0
    return ContextUsage(
        system_tokens=system_tokens,
        project_tokens=project_tokens,
        extra_tokens=extra_tokens,
        history_tokens=history_tokens,
        tool_output_tokens=tool_output_tokens,
        overhead_tokens=overhead_tokens,
        total_tokens=total,
        budget_tokens=budget,
        remaining_tokens=remaining,
        used_percent=used_percent,
        message_count=len(history),
        window_tokens=int(limits.window or limits.max_input or DEFAULT_CONTEXT_WINDOW),
        max_output_tokens=int(limits.max_output or 0),
        source=limits.source,
        detail=limits.detail,
        reserve_tokens=reserve_tokens,
    )


__all__ = [
    "CHARS_PER_TOKEN",
    "CJK_TOKENS_PER_CHAR",
    "MESSAGE_OVERHEAD_TOKENS",
    "REQUEST_OVERHEAD_TOKENS",
    "IMAGE_TOKENS",
    "DEFAULT_CONTEXT_WINDOW",
    "OLLAMA_DEFAULT_CONTEXT_WINDOW",
    "ContextUsage",
    "TrimResult",
    "estimate_tokens",
    "estimate_message_tokens",
    "estimate_messages_tokens",
    "get_context_window",
    "resolve_context_budget",
    "split_turn_groups",
    "repair_tool_pairing",
    "validate_tool_pairing",
    "trim_messages_to_budget",
    "trim_oldest_group",
    "estimate_context_usage",
]
