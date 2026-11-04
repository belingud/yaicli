"""Token estimation, context windows and turn-group-aware message trimming.

This module is the stdlib-only core of the v0.19 K02 "context economy" work. It is
imported on the request path (:mod:`yaicli.llms.client`) and by the slash-command
handler (:mod:`yaicli.cmd_handler`), so it must stay cheap and dependency free.

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
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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
#: Fallback context window for models missing from the table.
DEFAULT_CONTEXT_WINDOW = 128000
#: Local Ollama servers default to a small window unless configured otherwise.
OLLAMA_DEFAULT_CONTEXT_WINDOW = 8192
#: Fraction of the model window usable for *input* (the rest is output headroom).
CONTEXT_BUDGET_RATIO = 0.70

#: CJK ranges (Han, Hiragana/Katakana, Hangul, CJK punctuation/fullwidth forms).
_CJK_RE = re.compile(
    "[\u2e80-\u2eff\u2f00-\u2fdf\u3040-\u30ff\u3100-\u312f\u31a0-\u31bf"
    "\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\u3000-\u303f\uff00-\uffef]"
)

#: Model-name substring -> context window in tokens. Order matters: the first
#: substring found in the lowercased model name wins, so put specific names
#: (``gpt-4.1``) before generic ones (``gpt-4``).
MODEL_CONTEXT_WINDOWS: Tuple[Tuple[str, int], ...] = (
    # OpenAI
    ("gpt-4.1", 1047576),
    ("gpt-4o", 128000),
    ("gpt-4-turbo", 128000),
    ("gpt-4", 8192),
    ("gpt-5", 400000),
    ("gpt-3.5", 16385),
    ("o1", 200000),
    ("o3", 200000),
    ("o4", 200000),
    # Anthropic
    ("claude", 200000),
    # Google
    ("gemini", 1048576),
    # DeepSeek / Moonshot / Qwen / GLM / Grok families
    ("deepseek", 128000),
    ("moonshot", 131072),
    ("kimi", 131072),
    ("qwen", 131072),
    ("glm", 128000),
    ("chatglm", 128000),
    ("grok", 131072),
    # Others
    ("mistral", 128000),
    ("mixtral", 32768),
    ("command", 128000),
    ("cohere", 128000),
    ("minimax", 245760),
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
# Context windows and budget
# ---------------------------------------------------------------------------
def get_context_window(model: Optional[str] = None, provider: Optional[str] = None) -> int:
    """Return the context window (tokens) for ``model``.

    Falling back to 128k for an unknown model is intentionally optimistic: it is
    far more common for a modern model to have a large window than an 8k one, and
    the context-length self-heal covers the opposite case. Local Ollama servers
    are the exception — they default to a small window unless configured.
    """
    normalized = (model or "").strip().lower()
    for pattern, window in MODEL_CONTEXT_WINDOWS:
        if pattern in normalized:
            return window
    if provider and str(provider).strip().lower().startswith("ollama"):
        return OLLAMA_DEFAULT_CONTEXT_WINDOW
    return DEFAULT_CONTEXT_WINDOW


def resolve_context_budget(config: Optional[Mapping[str, Any]] = None, model: Optional[str] = None) -> int:
    """Resolve the per-request token budget.

    ``CONTEXT_BUDGET_TOKENS > 0`` wins verbatim; otherwise the budget is
    :data:`CONTEXT_BUDGET_RATIO` (70%) of the model context window. ``model``
    defaults to the configured ``MODEL``; ``PROVIDER`` is used for the local
    Ollama window fallback.
    """
    configured = 0
    provider = ""
    if config is not None:
        try:
            configured = int(config.get("CONTEXT_BUDGET_TOKENS") or 0)
        except (TypeError, ValueError):
            configured = 0
        if model is None:
            model = str(config.get("MODEL") or "")
        provider = str(config.get("PROVIDER") or "")
    if configured > 0:
        return configured
    window = get_context_window(model, provider)
    return max(1, int(window * CONTEXT_BUDGET_RATIO))


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
    """Estimated context usage breakdown shown by ``/context``."""

    system_tokens: int = 0
    history_tokens: int = 0
    tool_output_tokens: int = 0
    total_tokens: int = 0
    budget_tokens: int = 0
    remaining_tokens: int = 0
    used_percent: float = 0.0
    message_count: int = 0


def estimate_context_usage(
    messages: Optional[Sequence[Any]] = None,
    config: Optional[Mapping[str, Any]] = None,
    system_text: Optional[str] = None,
    model: Optional[str] = None,
) -> ContextUsage:
    """Estimate the usage breakdown for the interactive ``/context`` command.

    ``messages`` is the conversation history (system messages excluded — the
    role prompt is passed via ``system_text``); tool output is reported
    separately inside ``history_tokens``.
    """
    history = list(messages or ())
    system_tokens = estimate_tokens(system_text) if system_text else 0
    if system_tokens:
        system_tokens += MESSAGE_OVERHEAD_TOKENS
    history_tokens = _sum_messages(history)
    tool_output_tokens = 0
    for message in history:
        if _is_tool_result(message) or _role(message) in _TOOL_RESULT_ROLES:
            tool_output_tokens += estimate_message_tokens(message)
    if history:
        total = system_tokens + history_tokens + REQUEST_OVERHEAD_TOKENS
    else:
        total = system_tokens
    budget = resolve_context_budget(config, model)
    remaining = max(0, budget - total)
    used_percent = (total / budget * 100.0) if budget > 0 else 0.0
    return ContextUsage(
        system_tokens=system_tokens,
        history_tokens=history_tokens,
        tool_output_tokens=tool_output_tokens,
        total_tokens=total,
        budget_tokens=budget,
        remaining_tokens=remaining,
        used_percent=used_percent,
        message_count=len(history),
    )


__all__ = [
    "CHARS_PER_TOKEN",
    "CJK_TOKENS_PER_CHAR",
    "MESSAGE_OVERHEAD_TOKENS",
    "REQUEST_OVERHEAD_TOKENS",
    "IMAGE_TOKENS",
    "DEFAULT_CONTEXT_WINDOW",
    "OLLAMA_DEFAULT_CONTEXT_WINDOW",
    "CONTEXT_BUDGET_RATIO",
    "MODEL_CONTEXT_WINDOWS",
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
