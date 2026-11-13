"""K05 error layer: classification, retry policy and provider error surfaces.

Two contracts are covered here:

1. ``yaicli/errors.py``: classification of SDK/HTTP/network exceptions,
   ``Retry-After`` parsing, backoff caps/jitter, ``AgentError`` hints and
   backward compatibility of the legacy ``ProviderError("message")`` constructor.
2. Provider surfaces: every registered provider must raise a classified
   ``AgentError`` on an API/network failure (request time *and* mid-stream) and
   must never yield the error text as assistant content.

Everything is duck-typed / mocked: no provider SDK is contacted.
"""

import copy
import importlib
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from yaicli.errors import (
    EXIT_EPIPE,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_SIGINT,
    EXIT_TOOL_DENIED,
    EXIT_USAGE,
    RETRYABLE_KINDS,
    RETRYABLE_STATUS_CODES,
    AgentError,
    ErrorKind,
    backoff_delay,
    classify_exception,
    ensure_agent_error,
    error_kind_summary,
    is_context_length_error,
    is_retryable,
    parse_context_limit,
    provider_response_error,
    retry_after_seconds,
    wrap_provider_exception,
)
from yaicli.exceptions import ProviderError, YaicliError
from yaicli.llms.provider import ProviderFactory
from yaicli.schemas import ChatMessage


# ---------------------------------------------------------------------------
# Duck-typed fakes (no provider SDK imports needed for classification tests)
# ---------------------------------------------------------------------------


class FakeResponse:
    """Minimal HTTP response (openai/anthropic style ``exc.response``)."""

    def __init__(self, status_code=None, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeHTTPError(Exception):
    """Duck-typed provider/HTTP failure with configurable attributes."""

    def __init__(self, message="boom", status_code=None, response=None, headers=None, kind=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if response is not None:
            self.response = response
        if headers is not None:
            self.headers = headers
        if kind is not None:
            self.kind = kind


class ConnectError(Exception):
    """httpx.ConnectError-like class (class-name fallback, no message hints)."""


class ReadTimeout(Exception):
    """httpx.ReadTimeout-like class (class-name fallback, no message hints)."""


# ---------------------------------------------------------------------------
# classify_exception: status codes, class names, message patterns
# ---------------------------------------------------------------------------

_STATUS_MATRIX = [
    (401, ErrorKind.AUTH, False),
    (403, ErrorKind.AUTH, False),
    (404, ErrorKind.BAD_REQUEST, False),
    (408, ErrorKind.TIMEOUT, True),
    (409, ErrorKind.PROVIDER, True),
    (425, ErrorKind.PROVIDER, True),
    (429, ErrorKind.RATE_LIMIT, True),
    (500, ErrorKind.PROVIDER, True),
    (502, ErrorKind.PROVIDER, True),
    (503, ErrorKind.PROVIDER, True),
    (504, ErrorKind.TIMEOUT, True),
]


@pytest.mark.parametrize("status,kind,retryable", _STATUS_MATRIX)
def test_classify_http_status(status, kind, retryable):
    error = classify_exception(FakeHTTPError("provider failure", status_code=status))

    assert isinstance(error, AgentError)
    assert error.kind is kind
    assert error.status_code == status
    assert error.retryable is retryable


def test_classify_400_bad_request():
    error = classify_exception(FakeHTTPError("invalid temperature", status_code=400))

    assert error.kind is ErrorKind.BAD_REQUEST
    assert error.retryable is False


@pytest.mark.parametrize(
    "message",
    [
        "This model's maximum context length is 8192 tokens",
        "context_length_exceeded",
        "input is too long for requested model",
        "too many tokens in the request",
        "prompt is too long: 200000 tokens > 128000 maximum",
        "exceeds the maximum number of tokens",
    ],
)
def test_classify_400_context_length(message):
    error = classify_exception(FakeHTTPError(message, status_code=400))

    assert error.kind is ErrorKind.CONTEXT_LENGTH
    assert error.status_code == 400
    assert error.retryable is False
    assert is_context_length_error(FakeHTTPError(message, status_code=400)) is True


def test_classify_400_context_length_from_response_body():
    """Anthropic/Gemini put the detail in the response body, not str(exc)."""
    response = FakeResponse(status_code=400, text='{"error": {"message": "prompt is too long"}}')
    error = classify_exception(FakeHTTPError("Bad Request", response=response))

    assert error.kind is ErrorKind.CONTEXT_LENGTH
    assert error.status_code == 400


@pytest.mark.parametrize(
    "message,kind",
    [
        ("invalid api key", ErrorKind.AUTH),
        ("Incorrect API key provided", ErrorKind.AUTH),
        ("authentication failed", ErrorKind.AUTH),
        ("permission denied", ErrorKind.AUTH),
        ("rate limit reached for requests", ErrorKind.RATE_LIMIT),
        ("Too Many Requests", ErrorKind.RATE_LIMIT),
        ("resource exhausted", ErrorKind.RATE_LIMIT),
        ("quota exceeded", ErrorKind.RATE_LIMIT),
        ("request timed out", ErrorKind.TIMEOUT),
        ("deadline exceeded", ErrorKind.TIMEOUT),
        ("connection reset by peer", ErrorKind.NETWORK),
        ("getaddrinfo failed", ErrorKind.NETWORK),
        ("SSL certificate verify failed", ErrorKind.NETWORK),
        ("server disconnected", ErrorKind.NETWORK),
        ("maximum context length exceeded", ErrorKind.CONTEXT_LENGTH),
        ("something totally unexpected", ErrorKind.UNKNOWN),
    ],
)
def test_classify_message_pattern_fallbacks(message, kind):
    error = classify_exception(RuntimeError(message))

    assert error.kind is kind


@pytest.mark.parametrize(
    "exc_cls,kind",
    [
        (httpx.ConnectError, ErrorKind.NETWORK),
        (httpx.ConnectTimeout, ErrorKind.TIMEOUT),
        (httpx.ReadTimeout, ErrorKind.TIMEOUT),
        (httpx.WriteTimeout, ErrorKind.TIMEOUT),
        (httpx.PoolTimeout, ErrorKind.TIMEOUT),
        (httpx.RemoteProtocolError, ErrorKind.NETWORK),
        (httpx.ProxyError, ErrorKind.NETWORK),
    ],
)
def test_classify_httpx_exception_by_class_name(exc_cls, kind):
    """httpx exceptions carry no status; class names decide (no message hints)."""
    error = classify_exception(exc_cls("boom"))

    assert error.kind is kind
    assert error.status_code is None
    assert error.retryable is True


@pytest.mark.parametrize("exc_cls,kind", [(ConnectError, ErrorKind.NETWORK), (ReadTimeout, ErrorKind.TIMEOUT)])
def test_classify_custom_exception_class_name_fallback(exc_cls, kind):
    error = classify_exception(exc_cls("x"))

    assert error.kind is kind
    assert error.retryable is True


def test_classify_httpx_http_status_error_keeps_status():
    request = httpx.Request("POST", "https://api.example.com/v1/chat")
    response = httpx.Response(429, text="slow down", request=request)
    exc = httpx.HTTPStatusError("rate limited", request=request, response=response)

    error = classify_exception(exc)

    assert error.kind is ErrorKind.RATE_LIMIT
    assert error.status_code == 429
    assert error.retryable is True


def test_classify_duck_typed_status_sources():
    class HttpStatusError(Exception):
        http_status = 503

    class CodedError(Exception):
        code = 401

    class ResponseError(Exception):
        def __init__(self):
            super().__init__("nope")
            self.response = FakeResponse(status_code=403)

    assert classify_exception(HttpStatusError("x")).kind is ErrorKind.PROVIDER
    assert classify_exception(CodedError("x")).kind is ErrorKind.AUTH
    assert classify_exception(ResponseError()).kind is ErrorKind.AUTH


def test_classify_status_wins_over_message_patterns():
    """HTTP status is authoritative: a 429 is retryable even if it says 'invalid key'."""
    error = classify_exception(FakeHTTPError("invalid api key", status_code=429))

    assert error.kind is ErrorKind.RATE_LIMIT
    assert error.retryable is True


def test_classify_explicit_kind_on_exception():
    assert classify_exception(FakeHTTPError("x", kind="rate_limit")).kind is ErrorKind.RATE_LIMIT
    assert classify_exception(FakeHTTPError("x", kind=ErrorKind.CONTEXT_LENGTH)).kind is ErrorKind.CONTEXT_LENGTH
    # Unknown string kinds fall through to the other strategies.
    assert classify_exception(FakeHTTPError("connection reset", kind="not-a-kind")).kind is ErrorKind.NETWORK


def test_classify_retries_original_agent_error_unchanged():
    original = AgentError("rate limited", kind=ErrorKind.RATE_LIMIT, retryable=True)

    assert classify_exception(original) is original


def test_classify_sets_cause_and_keeps_message():
    original = FakeHTTPError("boom", status_code=500)

    error = classify_exception(original)

    assert error.cause is original
    assert "boom" in str(error)
    assert error.user_message.startswith("provider")


def test_classify_unknown_error():
    error = classify_exception(RuntimeError("??"))

    assert error.kind is ErrorKind.UNKNOWN
    assert error.status_code is None
    assert error.retryable is False
    assert "verbose" in error.hint


# ---------------------------------------------------------------------------
# Retry policy helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status,retryable", [(401, False), (403, False), (400, False), (429, True), (500, True)])
def test_is_retryable_matches_classification(status, retryable):
    exc = FakeHTTPError("x", status_code=status)

    assert is_retryable(exc) is retryable


def test_is_retryable_network_and_timeout():
    assert is_retryable(httpx.ConnectError("x")) is True
    assert is_retryable(httpx.ReadTimeout("x")) is True
    assert is_retryable(RuntimeError("x")) is False


def test_retryable_constants_are_sane():
    assert {408, 429, 500, 502, 503, 504} <= RETRYABLE_STATUS_CODES
    assert 400 not in RETRYABLE_STATUS_CODES
    assert 401 not in RETRYABLE_STATUS_CODES
    assert RETRYABLE_KINDS == {ErrorKind.RATE_LIMIT, ErrorKind.NETWORK, ErrorKind.TIMEOUT}


def test_is_context_length_error():
    assert is_context_length_error(FakeHTTPError("maximum context length exceeded", status_code=400)) is True
    assert is_context_length_error(httpx.ConnectError("x")) is False


# ---------------------------------------------------------------------------
# Retry-After parsing
# ---------------------------------------------------------------------------


def test_retry_after_from_exception_headers_dict():
    assert retry_after_seconds(FakeHTTPError("x", headers={"Retry-After": "2"})) == 2.0


def test_retry_after_from_response_headers_case_insensitive():
    response = FakeResponse(status_code=429, headers={"retry-after": "1.5"})
    assert retry_after_seconds(FakeHTTPError("x", response=response)) == 1.5


def test_retry_after_from_httpx_response_headers():
    request = httpx.Request("POST", "https://api.example.com/v1/chat")
    response = httpx.Response(429, headers={"Retry-After": "3"}, request=request)
    exc = httpx.HTTPStatusError("rate limited", request=request, response=response)

    assert retry_after_seconds(exc) == 3.0


def test_retry_after_missing_or_invalid():
    assert retry_after_seconds(RuntimeError("x")) is None
    assert retry_after_seconds(FakeHTTPError("x", headers={})) is None
    assert retry_after_seconds(FakeHTTPError("x", headers={"Retry-After": "not-a-number"})) is None
    assert retry_after_seconds(FakeHTTPError("x", headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})) == 0.0


def test_retry_after_negative_is_clamped():
    assert retry_after_seconds(FakeHTTPError("x", headers={"Retry-After": "-5"})) == 0.0


def test_retry_after_http_date_in_the_future():
    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    header = future.strftime("%a, %d %b %Y %H:%M:%S GMT")

    delay = retry_after_seconds(FakeHTTPError("x", headers={"Retry-After": header}))

    assert delay is not None
    assert 20.0 < delay <= 31.0


# ---------------------------------------------------------------------------
# Exponential backoff
# ---------------------------------------------------------------------------


def test_backoff_without_jitter_is_exponential_and_capped():
    delays = [backoff_delay(attempt, base=1.0, max_delay=8.0, jitter=False) for attempt in range(6)]

    assert delays == [1.0, 2.0, 4.0, 8.0, 8.0, 8.0]


def test_backoff_respects_custom_base_and_max():
    assert [backoff_delay(a, base=2.0, max_delay=5.0, jitter=False) for a in range(4)] == [2.0, 4.0, 5.0, 5.0]


def test_backoff_jitter_stays_within_bounds():
    for attempt in (0, 1, 2, 5):
        for _ in range(20):
            delay = backoff_delay(attempt, base=1.0, max_delay=8.0)
            expected_base = min(8.0, 2.0**attempt)
            assert expected_base <= delay <= expected_base + 0.5


def test_backoff_never_negative_and_zero_base():
    assert backoff_delay(3, base=0.0, jitter=False) == 0.0
    assert backoff_delay(3, base=0.0) == 0.0
    assert backoff_delay(0, base=-1.0, jitter=False) == 0.0


def test_backoff_retry_after_wins_but_is_capped():
    assert backoff_delay(0, retry_after=5.0) == 5.0
    assert backoff_delay(0, retry_after=100.0, max_delay=8.0) == 8.0
    assert backoff_delay(3, retry_after=-2.0) == 0.0


# ---------------------------------------------------------------------------
# AgentError / ProviderError compatibility and UX metadata
# ---------------------------------------------------------------------------


def test_agent_error_is_a_provider_error():
    error = AgentError("boom", kind=ErrorKind.NETWORK)

    assert isinstance(error, ProviderError)
    assert isinstance(error, YaicliError)
    assert isinstance(error, Exception)


def test_legacy_provider_error_message_constructor_still_works():
    """v0.18 call sites (and third-party handlers) keep working unchanged."""
    error = ProviderError("legacy failure")

    assert error.message == "legacy failure"
    assert str(error) == "legacy failure"
    assert error.kind is None
    assert error.status_code is None
    assert error.retryable is None

    with pytest.raises(ProviderError):
        raise error


def test_provider_error_accepts_classified_metadata():
    error = ProviderError("boom", kind=ErrorKind.AUTH, status_code=401, retryable=False)

    assert error.kind is ErrorKind.AUTH
    assert error.status_code == 401
    assert error.retryable is False


def test_agent_error_defaults():
    error = AgentError("boom")

    assert error.kind is ErrorKind.UNKNOWN
    assert error.status_code is None
    assert error.retryable is False
    assert error.user_message == "boom"
    assert error.cause is None
    assert str(error) == "boom"


@pytest.mark.parametrize("kind", list(ErrorKind))
def test_agent_error_has_hint_for_every_kind(kind):
    error = AgentError("boom", kind=kind)

    assert isinstance(error.hint, str)
    assert error.hint


def test_agent_error_kind_implies_retryable():
    for kind in (ErrorKind.RATE_LIMIT, ErrorKind.NETWORK, ErrorKind.TIMEOUT):
        assert AgentError("x", kind=kind).retryable is True
    for kind in (ErrorKind.AUTH, ErrorKind.BAD_REQUEST, ErrorKind.CONTEXT_LENGTH, ErrorKind.TOOL):
        assert AgentError("x", kind=kind).retryable is False


def test_agent_error_status_code_can_make_it_retryable():
    assert AgentError("x", status_code=503).retryable is True
    assert AgentError("x", status_code=400).retryable is False


def test_agent_error_explicit_retryable_and_custom_user_message():
    error = AgentError(
        "boom",
        kind=ErrorKind.AUTH,
        retryable=True,
        user_message="Check your API key.",
        cause=ValueError("inner"),
    )

    assert error.retryable is True
    assert error.user_message == "Check your API key."
    assert error.cause is not None
    assert error.hint  # kind hint still available


# ---------------------------------------------------------------------------
# classify / helpers used by providers and the client retry loop
# ---------------------------------------------------------------------------


def test_ensure_agent_error_default_kind_applied_to_unknown():
    error = ensure_agent_error(RuntimeError("weird"), default_kind=ErrorKind.TOOL)

    assert error.kind is ErrorKind.TOOL
    assert error.user_message.startswith("tool")


def test_ensure_agent_error_keeps_existing_classification():
    error = ensure_agent_error(FakeHTTPError("slow down", status_code=429), default_kind=ErrorKind.TOOL)

    assert error.kind is ErrorKind.RATE_LIMIT


def test_error_kind_summary():
    summary = error_kind_summary(FakeHTTPError("slow down", status_code=429))

    assert "rate_limit" in summary
    assert "HTTP 429" in summary
    assert "slow down" in summary


def test_wrap_provider_exception_preserves_classification():
    original = httpx.ConnectError("connection refused")

    error = wrap_provider_exception(original, "Ollama")

    assert isinstance(error, AgentError)
    assert error.kind is ErrorKind.NETWORK
    assert error.retryable is True
    assert error.cause is original
    assert str(error) == "Ollama API error: connection refused"
    assert error.user_message.startswith("network")


def test_wrap_provider_exception_uses_detail_and_status():
    original = FakeHTTPError("Error code: 429", status_code=429, response=FakeResponse(429, text="slow down"))

    error = wrap_provider_exception(original, "Cohere", detail="slow down")

    assert str(error) == "Cohere API error: slow down"
    assert error.kind is ErrorKind.RATE_LIMIT
    assert error.status_code == 429
    assert error.retryable is True


def test_wrap_provider_exception_without_provider_label():
    error = wrap_provider_exception(RuntimeError("kaboom"))

    assert str(error) == "kaboom"
    assert error.kind is ErrorKind.UNKNOWN


def test_provider_response_error_classifies_in_band_bodies():
    assert provider_response_error("Gemini", {"error": "invalid api key"}).kind is ErrorKind.AUTH
    assert provider_response_error("Gemini", "maximum context length exceeded").kind is ErrorKind.CONTEXT_LENGTH
    assert provider_response_error("Gemini", "too many requests").kind is ErrorKind.RATE_LIMIT


def test_provider_response_error_defaults_to_provider_retryable():
    error = provider_response_error("Mistral", '{"error": "no choices"}')

    assert error.kind is ErrorKind.PROVIDER
    assert error.retryable is True
    assert "Mistral API error" in str(error)
    assert "no choices" in str(error)


def test_provider_response_error_empty_body():
    error = provider_response_error("OpenAI", "")

    assert error.kind is ErrorKind.PROVIDER
    assert "empty response" in str(error)


def test_exit_code_constants():
    assert EXIT_OK == 0
    assert EXIT_ERROR == 1
    assert EXIT_USAGE == 2
    assert EXIT_TOOL_DENIED == 3
    assert EXIT_SIGINT == 130
    assert EXIT_EPIPE == 141


# ---------------------------------------------------------------------------
# Provider surface matrix: every registered provider raises classified errors
# ---------------------------------------------------------------------------

#: A superset config covering every family's required keys (all values fake).
MATRIX_CONFIG = {
    "API_KEY": "fake_api_key",
    "BASE_URL": None,
    "MODEL": "test-model",
    "TEMPERATURE": 0.7,
    "TOP_P": 1.0,
    "TOP_K": 40,
    "MAX_TOKENS": 128,
    "TIMEOUT": 10,
    "EXTRA_HEADERS": {},
    "EXTRA_BODY": None,
    "ENABLE_FUNCTIONS": False,
    "ENABLE_MCP": False,
    "LITE_TRANSPORT": False,
    "FREQUENCY_PENALTY": 0.0,
    "STREAM": False,
    # Spark
    "API_SECRET": "secret",
    "APP_ID": "app",
    # AWS-backed providers (Cohere Bedrock/Sagemaker, Anthropic Bedrock)
    "AWS_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "fake-access-key",
    "AWS_SECRET_ACCESS_KEY": "fake-secret-key",
    "AWS_SESSION_TOKEN": "fake-session-token",
    # Vertex providers
    "PROJECT": "fake-project",
    "LOCATION": "us-central1",
    "PROJECT_ID": "fake-project",
    "CLOUD_ML_REGION": "us-central1",
    # Azure
    "AZURE_AD_TOKEN": "fake-token",
    "API_VERSION": "2024-01-01",
    "AZURE_ENDPOINT": "https://fake.openai.azure.com",
}


def _provider_family_classes():
    """Import the provider family bases lazily (optional SDKs live in providers)."""
    from yaicli.llms.providers.anthropic_provider import AnthropicProvider
    from yaicli.llms.providers.cohere_provider import CohereProvider
    from yaicli.llms.providers.gemini_provider import GeminiProvider
    from yaicli.llms.providers.mistral_provider import MistralProvider
    from yaicli.llms.providers.ollama_provider import OllamaProvider
    from yaicli.llms.providers.openai_provider import OpenAIProvider

    return {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
        "cohere": CohereProvider,
        "ollama": OllamaProvider,
        "mistral": MistralProvider,
    }


def _make_provider(provider_key):
    """Instantiate a registered provider completely offline."""
    module_path, class_name = ProviderFactory.providers_map[provider_key]
    module = importlib.import_module(module_path, package="yaicli.llms")
    provider_cls = getattr(module, class_name)

    with ExitStack() as stack:
        if hasattr(provider_cls, "CLIENT_CLS"):
            stack.enter_context(patch.object(provider_cls, "CLIENT_CLS", MagicMock()))
        # Gemini builds its client from the module-level ``genai`` object.
        stack.enter_context(patch("yaicli.llms.providers.gemini_provider.genai.Client", MagicMock()))
        # Ollama builds its client from the module-level ``ollama`` object.
        stack.enter_context(patch("yaicli.llms.providers.ollama_provider.ollama.Client", MagicMock()))
        provider = provider_cls(config=copy.deepcopy(MATRIX_CONFIG))

    provider.console = MagicMock()
    return provider


def _family_of(provider):
    for name, base in _provider_family_classes().items():
        if isinstance(provider, base):
            return name
    raise AssertionError(f"Unknown provider family: {type(provider).__name__}")


def _arm_request_error(provider, error):
    """Replace the provider client so the next request fails like an HTTP layer."""
    client = MagicMock()
    family = _family_of(provider)
    if family == "openai":
        client.chat.completions.create.side_effect = error
    elif family == "anthropic":
        client.messages.create.side_effect = error
    elif family == "gemini":
        client.chats.create.side_effect = error
    elif family == "cohere":
        client.chat.side_effect = error
        client.chat_stream.side_effect = error
    elif family == "ollama":
        client.chat.side_effect = error
    elif family == "mistral":
        client.chat.complete.side_effect = error
        client.chat.stream.side_effect = error
    provider.client = client
    return provider


def _arm_stream_handlers(provider):
    """Make the client request succeed so the (patched) stream handler is reached."""
    client = MagicMock()
    family = _family_of(provider)
    if family == "openai":
        client.chat.completions.create.return_value = MagicMock()
    elif family == "anthropic":
        client.messages.create.return_value = MagicMock()
    elif family == "gemini":
        client.chats.create.return_value = MagicMock()
    elif family == "cohere":
        client.chat_stream.return_value = MagicMock()
    elif family == "ollama":
        client.chat.return_value = MagicMock()
    elif family == "mistral":
        client.chat.stream.return_value = MagicMock()
    provider.client = client
    return provider


MESSAGES = [ChatMessage(role="user", content="hi")]


@pytest.mark.parametrize("provider_key", sorted(ProviderFactory.providers_map))
def test_provider_raises_classified_error_instead_of_content(provider_key):
    """No registered provider may swallow an API error or return it as content."""
    error = FakeHTTPError("rate limited", status_code=429)

    provider = _arm_request_error(_make_provider(provider_key), error)
    collected = []
    with pytest.raises(AgentError) as excinfo:
        for response in provider.completion(MESSAGES, stream=False):
            collected.append(response)

    assert collected == [], f"{provider_key} yielded error text as assistant content"
    assert excinfo.value.kind is ErrorKind.RATE_LIMIT
    assert excinfo.value.status_code == 429
    assert excinfo.value.retryable is True
    assert "API error" in str(excinfo.value)


@pytest.mark.parametrize("provider_key", sorted(ProviderFactory.providers_map))
def test_provider_midstream_breakage_raises_classified_error(provider_key):
    """A stream that breaks mid-iteration must raise, not silently end."""
    provider = _make_provider(provider_key)
    provider = _arm_stream_handlers(provider)
    handler_name = "_handle_streaming_response" if _family_of(provider) == "cohere" else "_handle_stream_response"

    with patch.object(provider, handler_name, side_effect=httpx.ReadTimeout("read timed out")):
        with pytest.raises(AgentError) as excinfo:
            list(provider.completion(MESSAGES, stream=True))

    assert excinfo.value.kind is ErrorKind.TIMEOUT
    assert excinfo.value.retryable is True
    assert "API error" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Uniform TIMEOUT: every family forwards config TIMEOUT to its SDK/HTTP layer
# ---------------------------------------------------------------------------


def _openai_family_keys():
    from yaicli.llms.providers.openai_provider import OpenAIProvider

    keys = []
    for key, (module_path, class_name) in ProviderFactory.providers_map.items():
        module = importlib.import_module(module_path, package="yaicli.llms")
        if issubclass(getattr(module, class_name), OpenAIProvider):
            keys.append(key)
    return sorted(keys)


@pytest.mark.parametrize("provider_key", _openai_family_keys())
def test_openai_family_honors_config_timeout(provider_key):
    """TIMEOUT is either a per-request param or a client default for every OpenAI-family provider."""
    provider = _make_provider(provider_key)

    client_timeout = (getattr(provider, "client_params", None) or {}).get("timeout")
    assert provider.completion_params.get("timeout") == MATRIX_CONFIG["TIMEOUT"] or (
        client_timeout == MATRIX_CONFIG["TIMEOUT"]
    ), f"{provider_key} ignores config TIMEOUT"


def test_anthropic_honors_config_timeout():
    provider = _make_provider("anthropic")
    assert provider.client_params["timeout"] == MATRIX_CONFIG["TIMEOUT"]


def test_cohere_honors_config_timeout():
    provider = _make_provider("cohere")
    assert provider.client_params["timeout"] == MATRIX_CONFIG["TIMEOUT"]


def test_gemini_honors_config_timeout():
    provider = _make_provider("vertexai")
    config = provider.get_chat_config()
    assert config.http_options.timeout == MATRIX_CONFIG["TIMEOUT"] * 1000  # milliseconds


def test_mistral_honors_config_timeout():
    provider = _make_provider("mistral")
    assert provider.get_client_params()["timeout_ms"] == MATRIX_CONFIG["TIMEOUT"] * 1000  # milliseconds


def test_ollama_honors_config_timeout():
    module = importlib.import_module("yaicli.llms.providers.ollama_provider", package="yaicli.llms")
    client_cls = MagicMock()

    with patch.object(module.ollama, "Client", client_cls):
        module.OllamaProvider(config=copy.deepcopy(MATRIX_CONFIG))

    assert client_cls.call_args.kwargs["timeout"] == MATRIX_CONFIG["TIMEOUT"]


# ---------------------------------------------------------------------------
# v0.23 K22: learning the real context limit from provider error text
# ---------------------------------------------------------------------------


class TestParseContextLimit:
    """``parse_context_limit`` extracts the hard limit used by the self-heal path."""

    def test_openai_maximum_context_length_with_tokens(self):
        exc = FakeHTTPError(
            "This model's maximum context length is 128000 tokens. However, your messages resulted in 150000 tokens.",
            status_code=400,
        )
        assert parse_context_limit(exc) == 128000

    def test_maximum_context_length_without_tokens_word(self):
        exc = FakeHTTPError("maximum context length is 32768", status_code=400)
        assert parse_context_limit(exc) == 32768

    def test_anthropic_prompt_too_long(self):
        exc = FakeHTTPError("prompt is too long: 210000 tokens > 200000 maximum", status_code=400)
        assert parse_context_limit(exc) == 200000

    def test_sum_gt_limit_returns_the_last_number(self):
        exc = FakeHTTPError("request validation failed: 210000 + 8192 > 200000", status_code=400)
        assert parse_context_limit(exc) == 200000

    def test_gemini_maximum_tokens_allowed(self):
        exc = FakeHTTPError(
            "The input token count (1234567) exceeds the maximum number of tokens allowed (1048576).",
            status_code=400,
        )
        assert parse_context_limit(exc) == 1048576

    def test_code_without_number_returns_none(self):
        assert parse_context_limit(FakeHTTPError("context_length_exceeded", status_code=400)) is None

    def test_ollama_numberless_message_returns_none(self):
        exc = FakeHTTPError("input length exceeds the context length", status_code=400)
        assert parse_context_limit(exc) is None

    def test_unrelated_error_returns_none(self):
        assert parse_context_limit(FakeHTTPError("rate limited", status_code=429)) is None
        assert parse_context_limit(RuntimeError("")) is None
        assert parse_context_limit(httpx.ConnectError("connection refused")) is None

    def test_searches_the_http_response_body_too(self):
        response = FakeResponse(
            status_code=400,
            text='{"error": {"message": "This model\'s maximum context length is 100000 tokens."}}',
        )
        exc = FakeHTTPError("400 Bad Request", status_code=400, response=response)
        assert parse_context_limit(exc) == 100000

    def test_response_body_limit_wins_when_message_has_none(self):
        response = FakeResponse(
            status_code=400,
            text="prompt is too long: 9000 tokens > 8192 maximum",
        )
        exc = FakeHTTPError("bad request", status_code=400, response=response)
        assert parse_context_limit(exc) == 8192

    def test_classification_is_unchanged(self):
        """Adding the parser must not change how errors are classified."""
        exc = FakeHTTPError("This model's maximum context length is 128000 tokens.", status_code=400)
        assert classify_exception(exc).kind is ErrorKind.CONTEXT_LENGTH
        assert is_context_length_error(exc) is True
        assert parse_context_limit(exc) == 128000
