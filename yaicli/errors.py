"""Error classification, retry policy and process exit codes.

Provides one vocabulary for LLM/network/tool failures so that providers, the
tool-calling client and the CLI agree on *what* failed, *whether it is worth
retrying* and *which message/exit code the user sees*. Standard library only:
this module is imported on the request path and by provider modules.

Exit codes (v0.19 headless contract):

- 0   success
- 1   handled error
- 2   usage / argument error (typer handles those, kept here for consistency)
- 3   tool call denied and `--fail-on-tool-denied` was requested
- 130 interrupted by SIGINT
- 141 broken pipe (`ai --help | head`; may also exit 0 quietly)
"""

import re
from typing import Any, Optional

try:  # Python >= 3.11
    from enum import StrEnum  # type: ignore
except ImportError:  # pragma: no cover - Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatible with python below 3.11"""


from .exceptions import ProviderError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_TOOL_DENIED = 3
EXIT_SIGINT = 130
EXIT_EPIPE = 141


class ErrorKind(StrEnum):  # type: ignore
    """High-level failure categories used for retry/UX decisions."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    CONTEXT_LENGTH = "context_length"
    NETWORK = "network"
    TIMEOUT = "timeout"
    BAD_REQUEST = "bad_request"
    PROVIDER = "provider"
    TOOL = "tool"
    CONFIG = "config"
    DEPTH_LIMIT = "depth_limit"
    INTERRUPTED = "interrupted"
    #: ``--plan`` headless run ended without the model submitting a plan (K23).
    PLAN_NOT_SUBMITTED = "plan_not_submitted"
    UNKNOWN = "unknown"


#: Kinds that are safe to retry (the request did not fail because of the payload).
RETRYABLE_KINDS = frozenset(
    {
        ErrorKind.RATE_LIMIT,
        ErrorKind.NETWORK,
        ErrorKind.TIMEOUT,
    }
)

#: HTTP status codes that indicate a transient provider-side failure.
RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


_CONTEXT_LENGTH_PATTERNS = (
    "context length",
    "context_length",
    "context window",
    "maximum context",
    "max context",
    "too many tokens",
    "reduce the length",
    "prompt is too long",
    "input is too long",
    "request too large",
    "string too long",
    "exceeds the maximum",
    "token limit",
)

_AUTH_PATTERNS = (
    "invalid api key",
    "incorrect api key",
    "api key not valid",
    "unauthorized",
    "authentication",
    "permission denied",
    "invalid_api_key",
)

_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota",
    "resource exhausted",
    "overloaded",
)

_TIMEOUT_PATTERNS = (
    "timed out",
    "timeout",
    "read timeout",
    "connect timeout",
    "deadline exceeded",
    "took too long",
)

_NETWORK_PATTERNS = (
    "connection error",
    "connection reset",
    "connection refused",
    "connection aborted",
    "network",
    "getaddrinfo",
    "name or service not known",
    "temporary failure in name resolution",
    "ssl",
    "certificate verify failed",
    "remote disconnected",
    "server disconnected",
    "disconnected",
    "broken pipe",
)

#: Lower-case exception-class-name fragments. ``classify_exception`` lower-cases
#: the class-name chain before matching, so these must be lower case too. This is
#: what maps ``httpx.ConnectError``/``httpx.ReadTimeout`` (which carry no HTTP
#: status and a generic message) to network/timeout without importing httpx.
_CLASS_NAME_TIMEOUT_PATTERNS = ("timeout",)
_CLASS_NAME_NETWORK_PATTERNS = (
    "connect",
    "connection",
    "network",
    "proxy",
    "ssl",
    "disconnect",
    "remoteprotocol",
)

#: Patterns that carry the *real* context limit in provider error text. Each entry
#: is ``(compiled regex, group index of the limit)``; the first match wins. The
#: client learns the extracted value and recomputes the request budget from it.
_CONTEXT_LIMIT_PATTERNS: tuple[tuple[re.Pattern, int], ...] = (
    # OpenAI: "This model's maximum context length is 128000 tokens."
    (re.compile(r"maximum context length is (\d+)\s*tokens", re.IGNORECASE), 1),
    # Same wording without the "tokens" word.
    (re.compile(r"maximum context length is (\d+)", re.IGNORECASE), 1),
    # Anthropic: "prompt is too long: 210000 tokens > 200000 maximum".
    (re.compile(r"prompt is too long:\s*\d+\s*tokens\s*>\s*(\d+)", re.IGNORECASE), 1),
    # "<input> + <reserved> > <limit>" style (the limit is the last number).
    (re.compile(r"(\d+)\s*\+\s*(\d+)\s*>\s*(\d+)"), 3),
    # Gemini: "exceeds the maximum number of tokens allowed (1048576)."
    (re.compile(r"exceeds the maximum number of tokens allowed\s*\((\d+)\)", re.IGNORECASE), 1),
)


#: Short actionable hint per kind (used by the CLI/REPL to tell users what to do).
_KIND_HINTS = {
    ErrorKind.AUTH: "Check API_KEY / YAI_API_KEY and the provider's base URL.",
    ErrorKind.RATE_LIMIT: "The provider is rate-limiting; retry later or lower request frequency.",
    ErrorKind.CONTEXT_LENGTH: "The conversation exceeds the model context window; use /clear or /compact.",
    ErrorKind.NETWORK: "Network error: check connectivity, proxy and BASE_URL.",
    ErrorKind.TIMEOUT: "The request timed out; increase TIMEOUT or retry.",
    ErrorKind.BAD_REQUEST: "The provider rejected the request; check MODEL/provider parameters.",
    ErrorKind.PROVIDER: "The provider returned an error; retry or check provider status.",
    ErrorKind.DEPTH_LIMIT: "The tool-call depth limit was reached; raise --max-turns to continue.",
    ErrorKind.INTERRUPTED: "Interrupted.",
    ErrorKind.TOOL: "A tool call failed.",
    ErrorKind.CONFIG: "Configuration error; fix the config.ini entry.",
    ErrorKind.UNKNOWN: "Unexpected error; run with --verbose for details.",
}


class AgentError(ProviderError):
    """A classified failure with retry/UX metadata.

    Subclasses ``ProviderError`` so existing handlers that catch provider errors
    keep working, while the CLI can inspect ``kind``/``retryable``.
    """

    def __init__(
        self,
        message: str,
        kind: ErrorKind = ErrorKind.UNKNOWN,
        *,
        status_code: Optional[int] = None,
        retryable: Optional[bool] = None,
        user_message: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ):
        if retryable is None:
            retryable = kind in RETRYABLE_KINDS or (status_code is not None and status_code in RETRYABLE_STATUS_CODES)
        super().__init__(message, kind=kind, status_code=status_code, retryable=bool(retryable))
        self.user_message = user_message or message
        self.cause = cause

    @property
    def hint(self) -> str:
        """A short actionable hint for the user."""
        return _KIND_HINTS.get(self.kind, _KIND_HINTS[ErrorKind.UNKNOWN])

    def __str__(self) -> str:
        return self.message


def _pattern_match(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in patterns)


def _status_code(exc: BaseException) -> Optional[int]:
    for attr in ("status_code", "http_status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int) and 100 <= value <= 599:
        return value
    return None


def _response_text(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    text = getattr(response, "text", None)
    if isinstance(text, str) and text:
        return text
    return ""


def _class_name_chain(exc: BaseException) -> str:
    names = []
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__name__)
        current = current.__cause__ or current.__context__
    return " ".join(names)


def classify_exception(exc: BaseException) -> AgentError:
    """Map an arbitrary provider/network exception to an :class:`AgentError`.

    Classification order: explicit kind → HTTP status → exception class name →
    message patterns → unknown. The function is intentionally duck-typed so it
    works with openai/anthropic/httpx/gemini/ollama exceptions without importing
    any of their SDKs.
    """
    if isinstance(exc, AgentError):
        return exc

    text = str(exc) or repr(exc)
    response_text = _response_text(exc)
    haystack = f"{text}\n{response_text}"
    status = _status_code(exc)
    class_names = _class_name_chain(exc)

    explicit_kind = getattr(exc, "kind", None)
    if isinstance(explicit_kind, ErrorKind):
        kind = explicit_kind
    elif isinstance(explicit_kind, str):
        try:
            kind = ErrorKind(explicit_kind)
        except ValueError:
            kind = None
    else:
        kind = None

    if kind is None:
        if status is not None:
            if status in (401, 403):
                kind = ErrorKind.AUTH
            elif status == 429:
                kind = ErrorKind.RATE_LIMIT
            elif status in (408, 504):
                kind = ErrorKind.TIMEOUT
            elif status == 400:
                kind = (
                    ErrorKind.CONTEXT_LENGTH
                    if _pattern_match(haystack, _CONTEXT_LENGTH_PATTERNS)
                    else ErrorKind.BAD_REQUEST
                )
            elif status in RETRYABLE_STATUS_CODES:
                kind = ErrorKind.PROVIDER
            elif 400 <= status < 500:
                kind = ErrorKind.BAD_REQUEST
            else:
                kind = ErrorKind.PROVIDER
        elif _pattern_match(class_names, _CLASS_NAME_TIMEOUT_PATTERNS):
            kind = ErrorKind.TIMEOUT
        elif _pattern_match(class_names, _CLASS_NAME_NETWORK_PATTERNS):
            kind = ErrorKind.NETWORK
        elif _pattern_match(haystack, _CONTEXT_LENGTH_PATTERNS):
            kind = ErrorKind.CONTEXT_LENGTH
        elif _pattern_match(haystack, _AUTH_PATTERNS):
            kind = ErrorKind.AUTH
        elif _pattern_match(haystack, _RATE_LIMIT_PATTERNS):
            kind = ErrorKind.RATE_LIMIT
        elif _pattern_match(haystack, _TIMEOUT_PATTERNS):
            kind = ErrorKind.TIMEOUT
        elif _pattern_match(haystack, _NETWORK_PATTERNS):
            kind = ErrorKind.NETWORK
        else:
            kind = ErrorKind.UNKNOWN

    retryable = kind in RETRYABLE_KINDS or kind == ErrorKind.PROVIDER
    if status is not None:
        retryable = status in RETRYABLE_STATUS_CODES
    if kind in (ErrorKind.AUTH, ErrorKind.BAD_REQUEST, ErrorKind.CONTEXT_LENGTH):
        retryable = False

    return AgentError(
        str(exc),
        kind=kind,
        status_code=status,
        retryable=retryable,
        user_message=_human_message(str(exc), kind, status),
        cause=exc,
    )


def _human_message(message: str, kind: ErrorKind, status: Optional[int]) -> str:
    detail = message.strip()
    if len(detail) > 800:
        detail = detail[:780] + "…"
    prefix = f"{kind.value}"
    if status is not None:
        prefix += f" (HTTP {status})"
    if detail:
        return f"{prefix}: {detail}\nHint: {_KIND_HINTS.get(kind, '')}".rstrip()
    return f"{prefix}\nHint: {_KIND_HINTS.get(kind, '')}".rstrip()


def is_retryable(exc: BaseException) -> bool:
    """Return True when the failure is safe to retry (rate limit / network / timeout / 5xx)."""
    return classify_exception(exc).retryable


def retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Parse a ``Retry-After`` delay from an exception's headers.

    Supports both the delta-seconds form (``Retry-After: 2``) and the HTTP-date
    form (``Retry-After: Wed, 21 Oct 2015 07:28:00 GMT``). Missing, malformed or
    negative values yield ``None``/``0.0``; callers cap the value via
    :func:`backoff_delay` so a hostile header can not stall the process.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except (AttributeError, TypeError):
        return None
    return _parse_retry_after(raw)


def _parse_retry_after(raw: Any) -> Optional[float]:
    """Parse a raw Retry-After header value into seconds (``None`` when unusable)."""
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    # HTTP-date form. Imported lazily: the request path only needs this on errors.
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime

    try:
        parsed = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())


def backoff_delay(
    attempt: int,
    base: float = 1.0,
    max_delay: float = 8.0,
    retry_after: Optional[float] = None,
    jitter: bool = True,
) -> float:
    """Exponential backoff with optional jitter, capped by ``max_delay``.

    ``attempt`` is 0-based (first retry = 0). A provider-supplied Retry-After
    wins but is still capped so a hostile/buggy header can not stall the CLI.
    """
    import random

    if retry_after is not None:
        return min(max(float(retry_after), 0.0), max_delay)
    delay = min(max_delay, max(0.0, float(base) * (2**attempt)))
    if jitter and delay > 0:
        delay += random.uniform(0, min(0.5, delay / 2))
    return delay


def ensure_agent_error(exc: BaseException, default_kind: ErrorKind = ErrorKind.UNKNOWN) -> AgentError:
    """Return ``exc`` as an AgentError, using ``default_kind`` for unclassified errors."""
    error = classify_exception(exc)
    if error.kind is ErrorKind.UNKNOWN and default_kind is not ErrorKind.UNKNOWN:
        error.kind = default_kind
        error.user_message = _human_message(error.message, default_kind, error.status_code)
    return error


def is_context_length_error(exc: BaseException) -> bool:
    """Return True when the failure means "the request exceeds the context window"."""
    return classify_exception(exc).kind is ErrorKind.CONTEXT_LENGTH


def parse_context_limit(exc: BaseException) -> Optional[int]:
    """Extract the real context-window limit from a provider context-length error.

    The client learns this value (``model_limits.record_learned_limit``) and
    recomputes its request budget from it before the single self-heal retry, so a
    model missing from every static source stops being guessed forever. Supported
    wordings (case-insensitive), in order:

    * OpenAI: ``"maximum context length is 128000 tokens"`` (and the same phrase
      without ``tokens``);
    * Anthropic: ``"prompt is too long: 210000 tokens > 200000"``;
    * ``"<input> + <max_tokens> > <limit>"`` (limit = last number);
    * Gemini: ``"exceeds the maximum number of tokens allowed (1048576)"``.

    Returns ``None`` when no positive numeric limit is present — e.g. bare
    ``context_length_exceeded`` codes or Ollama's number-less ``"input length
    exceeds the context length"``. The exception message *and* the attached HTTP
    response body are searched; classification is not changed by this helper.
    """
    if exc is None:  # defensive: callers pass the caught exception
        return None
    try:
        text = str(exc) or ""
    except Exception:  # pragma: no cover - hostile __str__ must not break a turn
        text = ""
    try:
        body = _response_text(exc)
    except Exception:  # pragma: no cover - defensive: duck-typed response objects
        body = ""
    haystack = f"{text}\n{body}"
    for pattern, group in _CONTEXT_LIMIT_PATTERNS:
        match = pattern.search(haystack)
        if match is None:
            continue
        try:
            limit = int(match.group(group))
        except (TypeError, ValueError):  # pragma: no cover - regex guarantees digits
            continue
        return limit if limit > 0 else None
    return None


def wrap_provider_exception(
    exc: BaseException,
    provider: Optional[str] = None,
    detail: Optional[str] = None,
) -> AgentError:
    """Classify a provider/network exception and add provider context to the message.

    Providers call this around their SDK/HTTP calls so an API failure surfaces as
    a classified :class:`AgentError` (preserving ``kind``/``status_code``/
    ``retryable``) instead of a bare SDK exception or, worse, assistant content::

        try:
            response = self.client.chat(**params)
        except Exception as e:
            raise wrap_provider_exception(e, "Cohere") from e

    ``detail`` replaces the raw exception text in the message (used for response
    bodies); already-classified errors are returned as-is unless a ``detail`` or
    ``provider`` prefix is requested.
    """
    classified = classify_exception(exc)
    raw_detail = detail if detail is not None else classified.message
    raw_detail = (raw_detail or "").strip() or f"{type(exc).__name__} (no message)"
    message = f"{provider} API error: {raw_detail}" if provider else raw_detail
    return AgentError(
        message,
        kind=classified.kind,
        status_code=classified.status_code,
        retryable=classified.retryable,
        user_message=_human_message(message, classified.kind, classified.status_code),
        cause=exc,
    )


def provider_response_error(
    provider: Optional[str],
    body: Any,
    default_kind: ErrorKind = ErrorKind.PROVIDER,
) -> AgentError:
    """Build a classified error for an in-band API error body.

    Some providers/proxies report failures with HTTP 200: the response has no
    choices/candidates and the payload *is* the error document. Returning that
    body as assistant content turns a failure into a fake answer, so providers
    raise this instead. The body text is classified with the usual message
    patterns (auth/rate-limit/context-length/network) and falls back to
    ``default_kind`` when nothing matches.
    """
    text = body if isinstance(body, str) else repr(body)
    text = text.strip()
    if not text:
        text = "empty response (no choices or candidates)"
    classified = classify_exception(RuntimeError(text))
    kind = classified.kind if classified.kind is not ErrorKind.UNKNOWN else default_kind
    retryable = classified.retryable if classified.kind is not ErrorKind.UNKNOWN else kind is ErrorKind.PROVIDER
    message = f"{provider} API error: {text}" if provider else f"API error: {text}"
    return AgentError(
        message,
        kind=kind,
        status_code=classified.status_code,
        retryable=retryable,
        user_message=_human_message(message, kind, None),
    )


def error_kind_summary(error: BaseException) -> str:
    """Short one-line summary used by the CLI/REPL when reporting a failure."""
    agent_error = classify_exception(error)
    status = f" [HTTP {agent_error.status_code}]" if agent_error.status_code else ""
    return f"{agent_error.kind.value}{status}: {agent_error.message}"


__all__ = [
    "EXIT_OK",
    "EXIT_ERROR",
    "EXIT_USAGE",
    "EXIT_TOOL_DENIED",
    "EXIT_SIGINT",
    "EXIT_EPIPE",
    "ErrorKind",
    "AgentError",
    "classify_exception",
    "is_retryable",
    "is_context_length_error",
    "parse_context_limit",
    "retry_after_seconds",
    "backoff_delay",
    "ensure_agent_error",
    "wrap_provider_exception",
    "provider_response_error",
    "error_kind_summary",
    "RETRYABLE_KINDS",
    "RETRYABLE_STATUS_CODES",
]
