"""Token usage, cost estimation and session metrics (v0.22 K17).

Providers report token usage in wildly different shapes: an OpenAI
``ChatCompletion.usage`` object, an Anthropic ``Message.usage`` plus separate
``message_start``/``message_delta`` stream events, Gemini's ``usage_metadata``,
Mistral's ``UsageInfo`` and Ollama's ``prompt_eval_count``/``eval_count``. This
module normalizes all of them into one frozen :class:`Usage` value, accumulates
it per session (:class:`UsageTracker`), and turns tokens into an *estimated* USD
cost (:func:`estimate_cost`).

Design notes:

* The conversion helpers are duck-typed on purpose: they accept SDK models,
  ``SimpleNamespace``-style objects, plain dicts and test mocks. Anything that
  can not be read as an integer is treated as "not reported", so a provider that
  does not report usage (or a ``MagicMock`` in a test) yields ``None`` instead of
  bogus numbers.
* ``estimated=True`` marks heuristic numbers produced by
  :func:`estimate_usage` when no provider reported usage. Consumers must treat
  them as approximate.
* Pricing is a small built-in prefix table of common models, overridable per
  prefix through the ``MODEL_PRICING`` config dict (USD per 1M tokens). Unknown
  models return ``None``: callers show "unknown model pricing" instead of
  inventing a number. The built-in table is approximate; override it for exact
  accounting.
* This module is dependency free (stdlib + :mod:`yaicli.tokens`) and must stay
  cheap: it is imported by the provider/client/CLI request path.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .tokens import estimate_messages_tokens, estimate_tokens

#: Built-in price table: ``(model-prefix, input USD/1M tokens, output USD/1M tokens)``.
#: Prefixes are matched longest-first (see :func:`_match_pricing`), so family
#: entries (``gpt-4o``) coexist with specific ones (``gpt-4o-mini``).
#: Prices are approximate public list prices; override with ``MODEL_PRICING``.
BUILTIN_MODEL_PRICING: Tuple[Tuple[str, float, float], ...] = (
    # OpenAI
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.00),
    ("gpt-4.1-nano", 0.10, 0.40),
    ("gpt-4.1-mini", 0.40, 1.60),
    ("gpt-4.1", 2.00, 8.00),
    ("gpt-5-mini", 0.25, 2.00),
    ("gpt-5-nano", 0.05, 0.40),
    ("gpt-5", 1.25, 10.00),
    ("gpt-4-turbo", 10.00, 30.00),
    ("gpt-4", 30.00, 60.00),
    ("gpt-3.5-turbo", 0.50, 1.50),
    ("o4-mini", 1.10, 4.40),
    ("o3-mini", 1.10, 4.40),
    ("o3", 2.00, 8.00),
    # Anthropic (family prefixes; the substring pass handles claude-3-5-sonnet)
    ("claude-3-5-haiku", 0.80, 4.00),
    ("claude-haiku", 0.80, 4.00),
    ("claude-3-opus", 15.00, 75.00),
    ("claude-opus", 15.00, 75.00),
    ("claude-sonnet", 3.00, 15.00),
    # Google Gemini 2.x (flash/pro) and the 1.5 generation
    ("gemini-2.5-pro", 1.25, 10.00),
    ("gemini-2.5-flash", 0.30, 2.50),
    ("gemini-2.0-flash", 0.10, 0.40),
    ("gemini-2", 0.30, 2.50),
    ("gemini-1.5-pro", 1.25, 5.00),
    ("gemini-1.5-flash", 0.075, 0.30),
    # DeepSeek / Qwen / GLM families
    ("deepseek", 0.27, 1.10),
    ("qwen", 0.40, 1.20),
    ("glm", 0.60, 2.20),
)


@dataclass(frozen=True)
class Usage:
    """Normalized, immutable token usage for one provider request.

    ``total_tokens`` is kept explicit (providers disagree on whether it is
    reported or derivable); the conversion helpers always fill it.
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    estimated: bool = False

    def __add__(self, other: "Usage") -> "Usage":
        """Sum two usages field-wise; ``estimated`` is the logical OR."""
        if not isinstance(other, Usage):
            return NotImplemented
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            estimated=self.estimated or other.estimated,
        )

    def __radd__(self, other: Any) -> "Usage":
        """Support ``sum([...])``, whose start value is ``0``."""
        if other == 0:
            return self
        if isinstance(other, Usage):
            return self + other
        return NotImplemented

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain JSON-serializable dict of the usage fields."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "estimated": self.estimated,
        }


# ---------------------------------------------------------------------------
# Tolerant field readers
# ---------------------------------------------------------------------------
def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict, an SDK model or a plain object (duck-typed)."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_int(value: Any) -> Optional[int]:
    """Return ``value`` as an int when it really is a token count, else ``None``.

    Rejecting non-integers is what makes the helpers safe around provider SDKs
    that omit optional fields and around mocks (a ``MagicMock`` attribute is not
    an ``int``). Integral floats are accepted because JSON decoding may produce
    them; booleans are not.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _openai_total(prompt: int, completion: int, total: Optional[int]) -> int:
    return total if total is not None else prompt + completion


# ---------------------------------------------------------------------------
# Provider conversion helpers: return None when the provider reported no usage
# ---------------------------------------------------------------------------
def usage_from_openai(obj: Any) -> Optional[Usage]:
    """Convert an OpenAI ``ChatCompletion``/chunk/``usage`` payload to :class:`Usage`.

    Reads ``prompt_tokens``/``completion_tokens``/``total_tokens`` plus
    ``prompt_tokens_details.cached_tokens`` and
    ``completion_tokens_details.reasoning_tokens`` when present.
    """
    usage = _get(obj, "usage")
    if usage is None:
        return None
    prompt = _as_int(_get(usage, "prompt_tokens"))
    completion = _as_int(_get(usage, "completion_tokens"))
    total = _as_int(_get(usage, "total_tokens"))
    if prompt is None and completion is None and total is None:
        return None
    prompt = prompt or 0
    completion = completion or 0
    cached = _as_int(_get(_get(usage, "prompt_tokens_details"), "cached_tokens")) or 0
    reasoning = _as_int(_get(_get(usage, "completion_tokens_details"), "reasoning_tokens")) or 0
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=_openai_total(prompt, completion, total),
        cached_tokens=cached,
        reasoning_tokens=reasoning,
    )


def usage_from_anthropic(obj: Any) -> Optional[Usage]:
    """Convert an Anthropic ``Message`` / stream event to :class:`Usage`.

    Accepts either a non-streaming ``Message`` (``.usage.input_tokens`` /
    ``.usage.output_tokens``) or a raw stream event: ``message_start`` carries
    the usage under ``.message.usage`` while ``message_delta`` carries it under
    ``.usage``. One event only reports the part it knows about; the provider
    combines ``message_start`` input tokens with the final ``message_delta``
    output tokens.
    """
    return _anthropic_usage(_get(obj, "usage")) or _anthropic_usage(_get(_get(obj, "message"), "usage"))


def _anthropic_usage(usage: Any) -> Optional[Usage]:
    """Normalize one Anthropic usage payload (``Message.usage``/event ``usage``)."""
    if usage is None:
        return None
    prompt = _as_int(_get(usage, "input_tokens"))
    completion = _as_int(_get(usage, "output_tokens"))
    if prompt is None and completion is None:
        return None
    prompt = prompt or 0
    completion = completion or 0
    # Anthropic reports prompt-cache reads separately; those are the cached
    # (discounted) input tokens.
    cached = _as_int(_get(usage, "cache_read_input_tokens")) or 0
    return Usage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion, cached_tokens=cached
    )


def usage_from_gemini(obj: Any) -> Optional[Usage]:
    """Convert a google-genai response/chunk ``usage_metadata`` to :class:`Usage`."""
    metadata = _get(obj, "usage_metadata")
    if metadata is None:
        return None
    prompt = _as_int(_get(metadata, "prompt_token_count"))
    completion = _as_int(_get(metadata, "candidates_token_count"))
    total = _as_int(_get(metadata, "total_token_count"))
    if prompt is None and completion is None and total is None:
        return None
    prompt = prompt or 0
    completion = completion or 0
    cached = _as_int(_get(metadata, "cached_content_token_count")) or 0
    reasoning = _as_int(_get(metadata, "thoughts_token_count")) or 0
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=_openai_total(prompt, completion, total),
        cached_tokens=cached,
        reasoning_tokens=reasoning,
    )


def usage_from_mistral(obj: Any) -> Optional[Usage]:
    """Convert a Mistral ``ChatCompletionResponse``/stream event to :class:`Usage`.

    Non-streaming responses expose ``.usage``; streamed ``CompletionEvent``
    values put it under ``.data.usage``.
    """
    return _mistral_usage(_get(obj, "usage")) or _mistral_usage(_get(_get(obj, "data"), "usage"))


def _mistral_usage(usage: Any) -> Optional[Usage]:
    """Normalize one Mistral usage payload (``UsageInfo``/event ``data.usage``)."""
    if usage is None:
        return None
    prompt = _as_int(_get(usage, "prompt_tokens"))
    completion = _as_int(_get(usage, "completion_tokens"))
    total = _as_int(_get(usage, "total_tokens"))
    if prompt is None and completion is None and total is None:
        return None
    prompt = prompt or 0
    completion = completion or 0
    return Usage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=_openai_total(prompt, completion, total)
    )


def usage_from_ollama(obj: Any) -> Optional[Usage]:
    """Convert an Ollama ``ChatResponse``/chunk/stream chunk to :class:`Usage`.

    Ollama reports ``prompt_eval_count``/``eval_count`` (and only on the final
    stream message for streaming calls).
    """
    prompt = _as_int(_get(obj, "prompt_eval_count"))
    completion = _as_int(_get(obj, "eval_count"))
    if prompt is None and completion is None:
        return None
    prompt = prompt or 0
    completion = completion or 0
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------
def estimate_usage(messages: Optional[List[Any]], completion_text: str) -> Usage:
    """Estimate one request's usage from the request/response text.

    Uses :mod:`yaicli.tokens` (never a tokenizer): ``messages`` contributes the
    prompt tokens and ``completion_text`` the completion tokens. The result is
    marked ``estimated=True`` so callers can flag it in JSON/CLI output.
    """
    prompt = estimate_messages_tokens(messages) if messages else 0
    completion = estimate_tokens(completion_text) if completion_text else 0
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion, estimated=True)


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------
def _price_number(value: Any) -> Optional[float]:
    """Coerce a config price value to a finite non-negative float (else None)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except (TypeError, ValueError):
            return None
    else:
        return None
    if number < 0 or number != number or number in (float("inf"), float("-inf")):  # NaN/inf guard
        return None
    return number


def _config_mapping(config: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Return the config mapping to use, falling back to the global config."""
    if config is not None:
        return config if hasattr(config, "get") else {}
    try:
        from .config import cfg as global_cfg

        return global_cfg if hasattr(global_cfg, "get") else {}
    except Exception:  # pragma: no cover - config import must never break usage accounting
        return {}


def _pricing_overrides(config: Optional[Mapping[str, Any]]) -> Dict[str, Tuple[float, float]]:
    """Parse the ``MODEL_PRICING`` config value into ``{prefix: (input, output)}``.

    The config layer usually turns the JSON string into a dict; a raw JSON string
    is still accepted (hand-built configs/tests). Anything malformed is ignored
    (one bad entry must not disable the built-in table).
    """
    mapping = _config_mapping(config)
    try:
        raw = mapping.get("MODEL_PRICING") or {}
    except Exception:  # pragma: no cover - exotic config mappings
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, Mapping):
        return {}
    overrides: Dict[str, Tuple[float, float]] = {}
    for prefix, price in raw.items():
        if not isinstance(prefix, str) or not prefix.strip() or not isinstance(price, Mapping):
            continue
        input_price = _price_number(price.get("input"))
        output_price = _price_number(price.get("output"))
        if input_price is None or output_price is None:
            continue
        overrides[prefix.strip().lower()] = (input_price, output_price)
    return overrides


def _match_pricing(model: str, overrides: Mapping[str, Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """Return ``(input, output)`` prices for ``model`` or ``None`` when unknown.

    Prefixes are matched longest-first so a specific entry (``gpt-4o-mini``) wins
    over its family entry (``gpt-4o``). ``MODEL_PRICING`` overrides take
    precedence over the built-in table. A first pass matches the start of the
    model name; a second pass allows slash-qualified names such as
    ``openrouter/anthropic/claude-sonnet-4`` (substring match).
    """
    normalized = (model or "").strip().lower()
    if not normalized:
        return None
    entries: List[Tuple[str, Tuple[float, float]]] = [(prefix, pair) for prefix, pair in overrides.items()]
    entries.extend((prefix, (input_price, output_price)) for prefix, input_price, output_price in BUILTIN_MODEL_PRICING)
    entries.sort(key=lambda item: len(item[0]), reverse=True)
    for prefix, pair in entries:
        if normalized.startswith(prefix):
            return pair
    for prefix, pair in entries:
        if prefix in normalized:
            return pair
    return None


def estimate_cost(model: str, usage: Optional[Usage], config: Optional[Mapping[str, Any]] = None) -> Optional[float]:
    """Estimate the USD cost of ``usage`` for ``model`` (``None`` if unpriced).

    Uses the built-in prefix table plus ``MODEL_PRICING`` overrides and computes
    ``prompt_tokens * input / 1M + completion_tokens * output / 1M``. Unknown
    models (and malformed config) return ``None``; this function never raises.
    """
    if usage is None:
        return None
    try:
        pricing = _match_pricing(str(model or ""), _pricing_overrides(config))
        if pricing is None:
            return None
        input_price, output_price = pricing
        prompt = max(0, int(usage.prompt_tokens or 0))
        completion = max(0, int(usage.completion_tokens or 0))
        return (prompt / 1_000_000.0) * input_price + (completion / 1_000_000.0) * output_price
    except Exception:  # pragma: no cover - cost estimation must never break a turn
        return None


# ---------------------------------------------------------------------------
# Session tracker
# ---------------------------------------------------------------------------
class UsageTracker:
    """Accumulate usage and tool metrics for one session.

    The client records one usage snapshot per provider request round (provider
    reported or estimated) and one :meth:`record_tool` per executed tool call.
    :meth:`snapshot` returns the JSON-ready dict consumed by the CLI, the
    ``stream-json`` ``usage`` event and the ``/cost`` command.
    """

    def __init__(self, config: Optional[Mapping[str, Any]] = None):
        self.config = config
        self.total: Usage = Usage(0, 0, 0)
        self.by_model: Dict[str, Usage] = {}
        self.request_count: int = 0
        self.tool_calls: int = 0
        self.tool_duration_ms: float = 0.0
        self.tool_result_chars: int = 0

    @property
    def requests(self) -> int:
        """Number of recorded provider requests (alias of ``request_count``)."""
        return self.request_count

    def record(self, usage: Optional[Usage], model: Optional[str] = None) -> None:
        """Add one provider request's ``usage`` to the session totals."""
        if usage is None:
            return
        model_name = str(model or "").strip() or "unknown"
        self.total = self.total + usage
        self.by_model[model_name] = self.by_model.get(model_name, Usage(0, 0, 0)) + usage
        self.request_count += 1

    def record_tool(self, duration_ms: float, chars: int) -> None:
        """Record one executed tool call: wall-clock duration and result size."""
        self.tool_calls += 1
        try:
            self.tool_duration_ms += max(0.0, float(duration_ms))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            pass
        try:
            self.tool_result_chars += max(0, int(chars))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            pass

    def reset(self) -> None:
        """Forget all recorded usage/metrics (e.g. ``/clear`` or a new run)."""
        self.total = Usage(0, 0, 0)
        self.by_model = {}
        self.request_count = 0
        self.tool_calls = 0
        self.tool_duration_ms = 0.0
        self.tool_result_chars = 0

    def snapshot(self, config: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Return the JSON-ready session usage payload.

        Top-level ``cost_usd`` is the sum of the priced per-model costs (``None``
        when no model has a known price). Each ``models`` entry carries its own
        ``cost_usd`` (``None`` means "unknown model pricing"). All numbers are
        plain JSON types.
        """
        effective_config = config if config is not None else self.config
        models: Dict[str, Dict[str, Any]] = {}
        total_cost: Optional[float] = None
        for name, usage in self.by_model.items():
            cost = estimate_cost(name, usage, effective_config)
            if cost is not None:
                total_cost = cost if total_cost is None else total_cost + cost
            models[name] = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "estimated": usage.estimated,
                "cost_usd": cost,
            }
        return {
            "prompt_tokens": self.total.prompt_tokens,
            "completion_tokens": self.total.completion_tokens,
            "total_tokens": self.total.total_tokens,
            "cached_tokens": self.total.cached_tokens,
            "reasoning_tokens": self.total.reasoning_tokens,
            "estimated": self.total.estimated,
            "requests": self.request_count,
            "cost_usd": total_cost,
            "models": models,
            "tools": {
                "count": self.tool_calls,
                "duration_ms": round(self.tool_duration_ms, 2),
                "result_chars": self.tool_result_chars,
            },
        }


__all__ = [
    "BUILTIN_MODEL_PRICING",
    "Usage",
    "UsageTracker",
    "estimate_cost",
    "estimate_usage",
    "usage_from_anthropic",
    "usage_from_gemini",
    "usage_from_mistral",
    "usage_from_ollama",
    "usage_from_openai",
]
