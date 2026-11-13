"""Minimal httpx transport for the OpenAI Chat Completions wire format.

Why this module exists (v0.24 P1-c): the ``openai`` Python SDK imports its whole
``openai.types`` tree (~650ms measured on the one-shot path), which dominated
the first-request latency of ``ai "..."``. The request YAICLI actually makes is
a single ``POST {base_url}/chat/completions`` (JSON body + SSE stream), so the
same HTTP work can be done with ``httpx`` — already a base dependency whose
marginal import cost on that path is ~45ms.

Design constraints (see ``.trellis/spec/py/provider-guidelines.md``):

* **No SDK import here.** This module imports stdlib + httpx only. It is
  imported lazily by ``OpenAIProvider.create_client()`` when the lite transport
  is selected, and must never import ``openai``.
* **Duck-typed parity with the SDK.** The provider handlers in
  :mod:`yaicli.llms.openai_wire` read response objects by attribute
  (``choices[0].message.content``, ``delta.tool_calls[i].index``, ``usage``,
  ``model_extra``). The small classes below reproduce exactly those fields, so
  the same handler code serves both transports and behavior can not drift.
* **Errors stay classified.** HTTP failures carry the real ``httpx.Response``
  (``status_code``/``text``/``json()``/``headers``) so
  :func:`yaicli.errors.wrap_provider_exception` and
  :func:`yaicli.errors.retry_after_seconds` classify them exactly like SDK
  errors. Network/timeout failures get an explicit kind because httpx exception
  class names do not always match the message patterns in ``errors.py``.
* **No hidden retries.** The SDK retries connection errors/429/5xx internally;
  the lite transport does not, because YAICLI's own retry layer
  (``LLMClient`` + ``RETRY_*``) owns user-visible retry semantics. This keeps
  the process from sleeping twice for one failure.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional

import httpx

from .. import __version__
from ..errors import ErrorKind
from ..exceptions import ProviderError

#: Path appended to the configured base URL (the SDK does the same).
CHAT_COMPLETIONS_PATH = "/chat/completions"
#: Default request timeout when neither client params nor the request carry one.
DEFAULT_TIMEOUT_SECONDS = 60.0
#: Top-level chunk keys that are protocol envelope, not provider extras.
_ENVELOPE_KEYS = frozenset({"id", "object", "created", "model", "system_fingerprint", "service_tier"})
#: Message keys the provider handler reads directly; everything else is an extra.
_MESSAGE_KEYS = frozenset({"role", "content", "tool_calls", "function_call"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class LiteAPIError(ProviderError):
    """HTTP error response from the lite transport.

    Mirrors the part of the SDK's ``APIStatusError`` surface that YAICLI relies
    on: ``status_code`` and a real ``httpx.Response`` (``.text``/``.json()``/
    ``.headers``). ``yaicli.errors`` duck-types both, so classification, retry
    policy and rendered messages match the SDK path. ``body`` keeps the parsed
    error document (or the raw text) for callers/tests.
    """

    def __init__(self, response: httpx.Response, message: Optional[str] = None):
        self.response = response
        self.status_code = response.status_code
        self.body = _response_body(response)
        detail = _error_detail(self.body) or "(empty error body)"
        super().__init__(message or f"HTTP {self.status_code}: {detail}", status_code=self.status_code)


def _response_body(response: httpx.Response) -> Any:
    """Return the parsed JSON error body, falling back to raw text."""
    try:
        return response.json()
    except Exception:
        try:
            return response.text
        except Exception:  # pragma: no cover - response already closed without body
            return ""


def _error_detail(body: Any) -> str:
    """Extract a readable message from an OpenAI-style error document."""
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        elif isinstance(error, str) and error.strip():
            return error.strip()
        try:
            return json.dumps(body, ensure_ascii=False, default=str)
        except (TypeError, ValueError):  # pragma: no cover - exotic payload
            return str(body)
    text = str(body or "")
    return text.strip()


def _classify_httpx_error(exc: httpx.HTTPError) -> ProviderError:
    """Map an httpx transport failure to the error kind YAICLI retries on.

    ``errors.classify_exception`` matches some httpx classes by name
    (``ReadTimeout`` → timeout, ``RemoteProtocolError`` → network) but not all
    (``ReadError``/``ConnectError`` messages vary); an explicit kind keeps the
    lite path's retry/UX behavior deterministic and identical to the SDK path.
    """
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(f"Request timed out: {exc}", kind=ErrorKind.TIMEOUT, retryable=True)
    return ProviderError(f"Network error: {exc}", kind=ErrorKind.NETWORK, retryable=True)


# ---------------------------------------------------------------------------
# Duck-typed response objects (same shape the provider handlers read from SDK
# models). Kept deliberately small: only the fields YAICLI consumes.
# ---------------------------------------------------------------------------
class LiteFunctionCall:
    """``message.tool_calls[i].function`` / delta ``function``."""

    __slots__ = ("name", "arguments")

    def __init__(self, payload: Mapping[str, Any]):
        name = payload.get("name")
        arguments = payload.get("arguments")
        self.name = name if isinstance(name, str) else None
        self.arguments = arguments if isinstance(arguments, str) else None


class LiteToolCall:
    """One complete tool call in a non-streaming response."""

    __slots__ = ("id", "index", "type", "function")

    def __init__(self, payload: Mapping[str, Any]):
        call_id = payload.get("id")
        index = payload.get("index")
        function = payload.get("function")
        self.id = call_id if isinstance(call_id, str) else None
        self.index = index if isinstance(index, int) else None
        self.type = payload.get("type")
        self.function = LiteFunctionCall(function) if isinstance(function, Mapping) else None


class LiteMessage:
    """``choices[i].message`` for a non-streaming Chat Completion."""

    __slots__ = ("role", "content", "reasoning_content", "tool_calls", "model_extra")

    def __init__(self, payload: Mapping[str, Any]):
        self.role = payload.get("role")
        content = payload.get("content")
        self.content = content if isinstance(content, str) else ("" if content is None else content)
        reasoning = payload.get("reasoning_content")
        self.reasoning_content = reasoning if isinstance(reasoning, str) else ""
        tool_calls = payload.get("tool_calls")
        self.tool_calls = (
            [LiteToolCall(call) for call in tool_calls if isinstance(call, Mapping)]
            if isinstance(tool_calls, list)
            else None
        )
        self.model_extra: Dict[str, Any] = {k: v for k, v in payload.items() if k not in _MESSAGE_KEYS}


class LiteChoice:
    """``choices[i]`` for a non-streaming Chat Completion."""

    __slots__ = ("message", "finish_reason", "index")

    def __init__(self, payload: Mapping[str, Any]):
        message = payload.get("message")
        self.message = LiteMessage(message if isinstance(message, Mapping) else {})
        self.finish_reason = payload.get("finish_reason")
        self.index = payload.get("index")


class LiteCompletion:
    """Non-streaming Chat Completion response (``ChatCompletion`` lookalike)."""

    __slots__ = ("choices", "usage", "_payload")

    def __init__(self, payload: Mapping[str, Any]):
        self._payload = dict(payload)
        choices = payload.get("choices")
        self.choices = [LiteChoice(choice) for choice in choices if isinstance(choice, Mapping)] if isinstance(
            choices, list
        ) else []
        self.usage = payload.get("usage")

    def to_dict(self) -> Dict[str, Any]:
        """Raw payload (used for the "HTTP 200 with an error document" path)."""
        return dict(self._payload)


class LiteDelta:
    """``choices[i].delta`` for one SSE chunk."""

    __slots__ = ("content", "tool_calls", "model_extra")

    def __init__(self, payload: Mapping[str, Any]):
        content = payload.get("content")
        self.content = content if isinstance(content, str) else ""
        tool_calls = payload.get("tool_calls")
        self.model_extra: Dict[str, Any] = dict(payload)
        self.tool_calls = (
            [LiteToolCall(call) for call in tool_calls if isinstance(call, Mapping)]
            if isinstance(tool_calls, list)
            else None
        )

    # The wire layer sometimes falls back to ``dict(delta)`` when a delta has no
    # extras (``_get_reasoning_content(getattr(delta, "model_extra", None) or
    # delta)``). Expose the mapping protocol so the SDK and lite shapes behave the
    # same for an empty delta (e.g. a bare ``finish_reason`` chunk).
    def keys(self):
        return self.model_extra.keys()

    def __getitem__(self, key: str) -> Any:
        return self.model_extra[key]


class LiteStreamChoice:
    """``choices[i]`` for one SSE chunk."""

    __slots__ = ("delta", "finish_reason", "index")

    def __init__(self, payload: Mapping[str, Any]):
        delta = payload.get("delta")
        self.delta = LiteDelta(delta if isinstance(delta, Mapping) else {})
        self.finish_reason = payload.get("finish_reason")
        self.index = payload.get("index")


class LiteChunk:
    """One streaming chunk (``ChatCompletionChunk`` lookalike).

    ``model_extra`` exposes unknown top-level keys (notably ``{"error": ...}``,
    which some proxies send instead of failing the HTTP request) so
    ``OpenAIWireProvider._first_chunk_error`` can classify it.
    """

    __slots__ = ("choices", "usage", "model_extra", "_payload")

    def __init__(self, payload: Mapping[str, Any]):
        self._payload = dict(payload)
        choices = payload.get("choices")
        self.choices = [
            LiteStreamChoice(choice) for choice in choices if isinstance(choice, Mapping)
        ] if isinstance(choices, list) else []
        self.usage = payload.get("usage")
        self.model_extra: Dict[str, Any] = {k: v for k, v in payload.items() if k not in _ENVELOPE_KEYS and k not in ("choices", "usage")}

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._payload)


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------
def iter_sse_data(lines: Iterable[str]) -> Iterator[str]:
    """Yield one ``data:`` payload per SSE event.

    Tolerates the dialect differences found in the wild: comment lines
    (``: keep-alive``), blank separators, ``event:``/``id:``/``retry:`` fields,
    one-space stripping after the colon, and multi-line ``data`` payloads (SSE
    joins them with ``"\n"``). The caller decides how to decode each payload.
    """
    data_lines: List[str] = []
    for line in lines:
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        # event:/id:/retry:/unknown fields are irrelevant for Chat Completions.
    if data_lines:
        yield "\n".join(data_lines)


def iter_chunks(response: httpx.Response) -> Iterator[LiteChunk]:
    """Decode an SSE response into :class:`LiteChunk` objects.

    ``[DONE]`` terminates the stream. Malformed JSON is a provider protocol
    failure (not assistant content), so it raises a classified error. The HTTP
    response is always closed when the generator exits or is closed early.
    """
    try:
        for data in iter_sse_data(response.iter_lines()):
            if data.strip() == "[DONE]":
                break
            try:
                payload = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                raise ProviderError(f"Malformed streaming payload from provider: {data[:200]!r}")
            if not isinstance(payload, Mapping):
                continue
            yield LiteChunk(payload)
    except httpx.HTTPError as exc:
        raise _classify_httpx_error(exc) from exc
    finally:
        response.close()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class LiteChatCompletions:
    """``client.chat.completions`` lookalike backed by httpx."""

    def __init__(self, client: LiteChatClient) -> None:
        self._client = client

    def create(self, **params: Any) -> Any:
        """Perform one Chat Completions request.

        Mirrors ``openai.resources.chat.completions.Completions.create``:
        returns a :class:`LiteCompletion` for non-streaming requests and a
        lazy :class:`LiteChunk` iterator for streaming ones. ``timeout`` /
        ``extra_body`` / ``extra_headers`` / ``extra_query`` are request
        options (not JSON body members), matching the SDK's handling.
        """
        stream = bool(params.pop("stream", False))
        timeout = params.pop("timeout", None)
        extra_body = params.pop("extra_body", None)
        extra_headers = params.pop("extra_headers", None)
        extra_query = params.pop("extra_query", None)

        body = dict(params)
        # ``stream`` is a payload field (unlike timeout/extra_*): the request body
        # asks for SSE, the return type is decided above.
        body["stream"] = stream
        if isinstance(extra_body, Mapping):
            _deep_merge(body, extra_body)

        headers = self._client.build_headers(stream=stream, extra=extra_headers)
        query = self._client.build_query(extra_query)
        url = self._client.url
        request_timeout = _coerce_timeout(timeout)
        # Only forward ``timeout`` when the request really carries one, otherwise
        # httpx would disable the client default (the SDK keeps its client timeout).
        timeout_kwargs: Dict[str, Any] = {} if request_timeout is None else {"timeout": request_timeout}
        try:
            if stream:
                request = self._client.http.build_request(
                    "POST", url, json=body, headers=headers, params=query or None, **timeout_kwargs
                )
                response = self._client.http.send(request, stream=True)
                if response.status_code >= 400:
                    response.read()
                    raise LiteAPIError(response)
                return iter_chunks(response)
            response = self._client.http.post(url, json=body, headers=headers, params=query or None, **timeout_kwargs)
        except httpx.HTTPError as exc:
            raise _classify_httpx_error(exc) from exc
        if response.status_code >= 400:
            raise LiteAPIError(response)
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(f"Provider returned invalid JSON: {response.text[:200]!r}") from exc
        if not isinstance(payload, Mapping):
            raise ProviderError(f"Provider returned an unexpected JSON payload: {str(payload)[:200]}")
        return LiteCompletion(payload)


class _LiteChatNamespace:
    """``client.chat`` lookalike."""

    def __init__(self, completions: LiteChatCompletions) -> None:
        self.completions = completions


class LiteChatClient:
    """httpx-based replacement for ``openai.OpenAI`` on the Chat Completions path.

    Only the surface used by :class:`~yaicli.llms.openai_wire.OpenAIWireProvider`
    is implemented: ``client.chat.completions.create(**params)``. The constructor
    takes the same ``client_params`` dict produced by
    ``OpenAIProvider.get_client_params()`` (``api_key``/``base_url``/
    ``default_headers``, plus optional ``default_query``/``timeout``).

    Proxies are inherited from the environment (``httpx.Client(trust_env=True)``,
    the default): ``HTTP(S)_PROXY``/``NO_PROXY`` work exactly as they do for the
    SDK's own httpx transport. For tests, pass ``http_client=`` with an
    ``httpx.MockTransport`` to avoid network access entirely.
    """

    def __init__(
        self,
        client_params: Mapping[str, Any],
        *,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        params = dict(client_params)
        api_key = params.pop("api_key", None)
        base_url = params.pop("base_url", "") or ""
        default_headers = params.pop("default_headers", None) or {}
        extra_headers = params.pop("extra_headers", None) or {}
        default_query = params.pop("default_query", None)
        timeout = params.pop("timeout", None)

        self._api_key = api_key if isinstance(api_key, str) else None
        self._headers: Dict[str, str] = {str(k): str(v) for k, v in {**default_headers, **extra_headers}.items()}
        self._query: Dict[str, Any] = dict(default_query) if isinstance(default_query, Mapping) else {}
        self._base_url = str(base_url).rstrip("/")
        self._timeout = float(timeout) if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) else (
            DEFAULT_TIMEOUT_SECONDS
        )
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.Client(timeout=self._timeout)
        self.chat = _LiteChatNamespace(LiteChatCompletions(self))

    # -- accessors used by LiteChatCompletions -----------------------------
    @property
    def http(self) -> httpx.Client:
        return self._http

    @property
    def url(self) -> str:
        return f"{self._base_url}{CHAT_COMPLETIONS_PATH}"

    def build_headers(self, *, stream: bool, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, str]:
        """Effective request headers (auth + provider headers + overrides)."""
        headers = dict(self._headers)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "text/event-stream" if stream else "application/json"
        headers["User-Agent"] = f"yaicli/{__version__} (lite)"
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if isinstance(extra, Mapping):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    def build_query(self, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Effective query parameters (client ``default_query`` + per-request)."""
        query = dict(self._query)
        if isinstance(extra, Mapping):
            query.update(extra)
        return query

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        """Close the underlying httpx client (no-op for injected clients)."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "LiteChatClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best-effort resource cleanup
        try:
            self.close()
        except Exception:
            pass


def create_lite_client(client_params: Mapping[str, Any], **kwargs: Any) -> LiteChatClient:
    """Factory used by ``OpenAIProvider.create_client()``."""
    return LiteChatClient(client_params, **kwargs)


def _coerce_timeout(timeout: Any) -> Optional[float]:
    """Return a float timeout for httpx, or ``None`` to use the client default."""
    if isinstance(timeout, bool):
        return None
    if isinstance(timeout, (int, float)):
        value = float(timeout)
        return value if value > 0 else None
    return None


def _deep_merge(target: Dict[str, Any], source: Mapping[str, Any]) -> None:
    """Merge ``source`` into ``target``; nested mappings merge, scalars override."""
    for key, value in source.items():
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _deep_merge(current, value)
        else:
            target[key] = value
