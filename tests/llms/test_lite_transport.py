"""Unit tests for the v0.24 httpx lite transport (no SDK, no network).

The lite transport (:mod:`yaicli.llms.lite_transport`) replaces the openai SDK on
the Chat Completions request path for the ``openai`` / ``openai-compatible``
providers. Every test injects an ``httpx.MockTransport`` — nothing here touches
the network — and asserts the wire contract (URL/headers/body/query), the
duck-typed response parsing (JSON + SSE), the classified error surface and the
transport-selection rule. SDK/lite response parity on the *same* payloads lives
in ``test_lite_parity.py``.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from yaicli.errors import AgentError, ErrorKind, classify_exception, retry_after_seconds, wrap_provider_exception
from yaicli.exceptions import ProviderError
from yaicli.llms.lite_transport import (
    LiteAPIError,
    LiteChatClient,
    LiteChunk,
    LiteCompletion,
    create_lite_client,
    iter_chunks,
    iter_sse_data,
)
from yaicli.llms.providers.deepseek_provider import DeepSeekProvider
from yaicli.llms.providers.openai_compatible_provider import OpenAICompatibleProvider
from yaicli.llms.providers.openai_provider import OpenAIAzure, OpenAIProvider
from yaicli.schemas import ChatMessage
from yaicli.usage import Usage, usage_from_openai

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://lite.example.com/v1"
STREAM_HEADERS = {"content-type": "text/event-stream"}
DEFAULT_HEADERS = {"X-Title": "yaicli-tests", "HTTP_Referer": "https://example.test"}


def _config(**overrides):
    """Provider config for a lite-capable provider (no network is ever used)."""
    config = {
        "API_KEY": "fake_api_key",
        "BASE_URL": BASE_URL,
        "MODEL": "gpt-4o-mini",
        "TEMPERATURE": 0.7,
        "TOP_P": 1.0,
        "MAX_TOKENS": 128,
        "TIMEOUT": 60,
        "EXTRA_HEADERS": None,
        "EXTRA_BODY": None,
        "ENABLE_FUNCTIONS": False,
        "ENABLE_MCP": False,
    }
    config.update(overrides)
    return config


def _messages():
    return [ChatMessage(role="user", content="hi")]


def _lite_client(http, **params):
    """Build a LiteChatClient over an injected (mock-backed) httpx client."""
    client_params = {
        "api_key": "sk-lite-test",
        "base_url": BASE_URL,
        "default_headers": dict(DEFAULT_HEADERS),
    }
    client_params.update(params)
    return LiteChatClient(client_params, http_client=http)


def _completion_payload(
    content="Hello world",
    *,
    finish_reason="stop",
    message_extra=None,
    usage=None,
    tool_calls=None,
):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    if message_extra:
        message.update(message_extra)
    payload = {
        "id": "chatcmpl-lite",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def _chunk_payload(content=None, *, finish_reason=None, delta_extra=None, usage=None, choices=True):
    payload = {
        "id": "chatcmpl-lite-chunk",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "gpt-4o-mini",
    }
    if choices:
        delta = {}
        if content is not None:
            delta["content"] = content
        if delta_extra:
            delta.update(delta_extra)
        payload["choices"] = [{"index": 0, "delta": delta, "finish_reason": finish_reason}]
    else:
        payload["choices"] = []
    if usage is not None:
        payload["usage"] = usage
    return payload


def _sse_bytes(*payloads):
    return "".join(f"data: {json.dumps(payload)}\n\n" for payload in payloads).encode()


def _sse_response(*payloads):
    return httpx.Response(200, content=_sse_bytes(*payloads), headers=STREAM_HEADERS)


def _json_handler(payload, *, status=200):
    def handler(request):
        return httpx.Response(status, json=payload)

    return handler


def _recording_handler(response, requests):
    def handler(request):
        requests.append(request)
        return response

    return handler


@pytest.fixture
def http_factory():
    """Create MockTransport-backed httpx clients and close them after the test."""
    created = []

    def make(handler):
        http = httpx.Client(transport=httpx.MockTransport(handler))
        created.append(http)
        return http

    yield make
    for http in created:
        http.close()


@pytest.fixture
def lite_provider(http_factory):
    """Build a real OpenAI-wire provider whose transport client is mocked."""

    def factory(handler, *, provider_cls=OpenAIProvider, **config_overrides):
        config_overrides.setdefault("LITE_TRANSPORT", True)
        provider = provider_cls(config=_config(**config_overrides))
        provider.client = LiteChatClient(provider.client_params, http_client=http_factory(handler))
        provider.console = MagicMock()
        return provider

    return factory


# ---------------------------------------------------------------------------
# Request parity: URL / method / headers / query / body
# ---------------------------------------------------------------------------
class TestRequestParity:
    def test_posts_json_to_chat_completions_url(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests))
        )

        client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])

        assert len(requests) == 1
        request = requests[0]
        assert request.method == "POST"
        assert str(request.url) == f"{BASE_URL}/chat/completions"
        assert request.headers["content-type"] == "application/json"

    def test_base_url_trailing_slash_is_normalized(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests)),
            base_url=f"{BASE_URL}/",
        )

        client.chat.completions.create(model="gpt-4o-mini", messages=[])

        assert str(requests[0].url) == f"{BASE_URL}/chat/completions"

    def test_sends_auth_default_headers_and_accept(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests))
        )

        client.chat.completions.create(model="gpt-4o-mini", messages=[])

        headers = requests[0].headers
        assert headers["authorization"] == "Bearer sk-lite-test"
        assert headers["x-title"] == "yaicli-tests"
        assert headers["http_referer"] == "https://example.test"
        assert headers["accept"] == "application/json"
        assert headers["user-agent"].startswith("yaicli/")
        assert headers["user-agent"].endswith("(lite)")

    def test_streaming_request_asks_for_event_stream(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(_sse_response(_chunk_payload("hi", finish_reason="stop")), requests))
        )

        stream = client.chat.completions.create(model="gpt-4o-mini", messages=[], stream=True)
        list(stream)

        assert requests[0].headers["accept"] == "text/event-stream"

    def test_client_level_extra_headers_are_sent(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests)),
            extra_headers={"X-Client-Extra": "client"},
        )

        client.chat.completions.create(model="gpt-4o-mini", messages=[])

        assert requests[0].headers["x-client-extra"] == "client"

    def test_per_request_extra_headers_are_sent_and_override(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests))
        )

        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[],
            extra_headers={"X-Per-Request": "request", "X-Title": "override"},
        )

        headers = requests[0].headers
        assert headers["x-per-request"] == "request"
        assert headers["x-title"] == "override"

    def test_default_and_extra_query_parameters_are_forwarded(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests)),
            default_query={"tenant": "t1", "api-version": "v1"},
        )

        client.chat.completions.create(model="gpt-4o-mini", messages=[], extra_query={"api-version": "v2", "q": "x"})

        params = dict(requests[0].url.params)
        assert params == {"tenant": "t1", "api-version": "v2", "q": "x"}

    def test_body_contains_completion_params_messages_and_tools(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests))
        )
        tools = [{"type": "function", "function": {"name": "get_weather", "description": "weather"}}]

        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.3,
            tools=tools,
        )

        body = json.loads(requests[0].content)
        assert body == {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.3,
            "tools": tools,
            "stream": False,
        }

    def test_stream_flag_is_in_body_and_selects_streaming_return_type(self, http_factory):
        requests = []

        def handler(request):
            requests.append(request)
            if json.loads(request.content)["stream"]:
                return _sse_response(_chunk_payload("hi", finish_reason="stop"))
            return httpx.Response(200, json=_completion_payload())

        client = _lite_client(http_factory(handler))

        streamed = client.chat.completions.create(model="gpt-4o-mini", messages=[], stream=True)
        assert hasattr(streamed, "__next__")
        chunks = list(streamed)

        assert json.loads(requests[0].content)["stream"] is True
        assert isinstance(chunks[0], LiteChunk)
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=[], stream=False)
        assert isinstance(completion, LiteCompletion)
        assert json.loads(requests[1].content)["stream"] is False

    def test_extra_body_is_deep_merged_and_overrides_scalars(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests))
        )

        client.chat.completions.create(
            model="base-model",
            messages=[],
            logit_bias={"a": 1},
            extra_body={"model": "override-model", "logit_bias": {"b": 2}, "response_format": {"type": "json_object"}},
        )

        body = json.loads(requests[0].content)
        assert body["model"] == "override-model"
        assert body["logit_bias"] == {"a": 1, "b": 2}
        assert body["response_format"] == {"type": "json_object"}
        assert body["stream"] is False

    def test_request_options_are_not_part_of_the_json_body(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests))
        )

        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[],
            timeout=5,
            extra_headers={"X-One": "1"},
            extra_query={"q": "v"},
        )

        body = json.loads(requests[0].content)
        for key in ("timeout", "extra_headers", "extra_query"):
            assert key not in body

    def test_per_request_timeout_reaches_the_http_layer(self, http_factory):
        requests = []
        client = _lite_client(
            http_factory(_recording_handler(httpx.Response(200, json=_completion_payload()), requests))
        )

        client.chat.completions.create(model="gpt-4o-mini", messages=[], timeout=2.5)

        timeout = requests[0].extensions.get("timeout")
        assert timeout is not None
        assert timeout["read"] == 2.5
        assert timeout["connect"] == 2.5


# ---------------------------------------------------------------------------
# Non-streaming response parsing
# ---------------------------------------------------------------------------
class TestNonStreamParsing:
    def test_completion_exposes_content_and_to_dict(self, http_factory):
        payload = _completion_payload("Hello from lite")
        client = _lite_client(http_factory(_json_handler(payload)))

        completion = client.chat.completions.create(model="gpt-4o-mini", messages=[])

        assert isinstance(completion, LiteCompletion)
        assert completion.choices[0].message.content == "Hello from lite"
        assert completion.choices[0].finish_reason == "stop"
        assert completion.to_dict() == payload

    def test_completion_exposes_reasoning_content(self, http_factory):
        payload = _completion_payload("answer", message_extra={"reasoning_content": "thinking hard"})
        client = _lite_client(http_factory(_json_handler(payload)))

        completion = client.chat.completions.create(model="gpt-4o-mini", messages=[])

        message = completion.choices[0].message
        assert message.reasoning_content == "thinking hard"
        assert message.model_extra["reasoning_content"] == "thinking hard"

    def test_completion_exposes_parallel_tool_calls(self, http_factory):
        payload = _completion_payload(
            None,
            finish_reason="tool_calls",
            tool_calls=[
                {
                    "id": "call_a",
                    "type": "function",
                    "function": {"name": "fs_read_file", "arguments": '{"path": "a.txt"}'},
                },
                {
                    "id": "call_b",
                    "type": "function",
                    "function": {"name": "fs_read_file", "arguments": '{"path": "b.txt"}'},
                },
            ],
        )
        client = _lite_client(http_factory(_json_handler(payload)))

        completion = client.chat.completions.create(model="gpt-4o-mini", messages=[])

        tool_calls = completion.choices[0].message.tool_calls
        assert tool_calls is not None
        assert [call.id for call in tool_calls] == ["call_a", "call_b"]
        assert [call.function.name for call in tool_calls] == ["fs_read_file", "fs_read_file"]
        assert [call.function.arguments for call in tool_calls] == ['{"path": "a.txt"}', '{"path": "b.txt"}']

    def test_completion_usage_including_detail_fields(self, http_factory):
        payload = _completion_payload(
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "prompt_tokens_details": {"cached_tokens": 2},
                "completion_tokens_details": {"reasoning_tokens": 3},
            }
        )
        client = _lite_client(http_factory(_json_handler(payload)))

        completion = client.chat.completions.create(model="gpt-4o-mini", messages=[])

        assert completion.usage["prompt_tokens"] == 10
        assert usage_from_openai(completion) == Usage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            cached_tokens=2,
            reasoning_tokens=3,
        )

    def test_invalid_json_raises_provider_error(self, http_factory):
        client = _lite_client(http_factory(lambda request: httpx.Response(200, text="not-json")))

        with pytest.raises(ProviderError, match="invalid JSON"):
            client.chat.completions.create(model="gpt-4o-mini", messages=[])

    def test_non_object_json_payload_raises_provider_error(self, http_factory):
        client = _lite_client(http_factory(lambda request: httpx.Response(200, json=["unexpected"])))

        with pytest.raises(ProviderError, match="unexpected JSON payload"):
            client.chat.completions.create(model="gpt-4o-mini", messages=[])


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------
class TestSSEParsing:
    def test_iter_sse_data_joins_multiline_and_ignores_noise(self):
        lines = [
            ": keep-alive",
            "",
            "event: message",
            'data: {"a": 1}',
            "",
            "id: 7",
            "retry: 100",
            'data: {"b":',
            "data: 2}",
            "",
            "data: [DONE]",
        ]

        assert list(iter_sse_data(lines)) == ['{"a": 1}', '{"b":\n2}', "[DONE]"]

    def test_iter_sse_data_flushes_final_event_without_blank_line(self):
        assert list(iter_sse_data(["data: first", "data: second"])) == ["first\nsecond"]

    def test_stream_yields_one_chunk_per_event(self, http_factory):
        payloads = [
            _chunk_payload("Hel"),
            _chunk_payload("lo", finish_reason="stop"),
        ]
        client = _lite_client(http_factory(lambda request: _sse_response(*payloads)))

        chunks = list(client.chat.completions.create(model="gpt-4o-mini", messages=[], stream=True))

        assert all(isinstance(chunk, LiteChunk) for chunk in chunks)
        assert [chunk.choices[0].delta.content for chunk in chunks] == ["Hel", "lo"]
        assert chunks[-1].choices[0].finish_reason == "stop"

    def test_stream_tolerates_comments_event_lines_and_blank_lines(self, http_factory):
        body = (
            b": keep-alive\n\n"
            b"event: message\n"
            b'data: {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "m",'
            b' "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": null}]}\n\n'
            b"\n\n"
            b'data: {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "m",'
            b' "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        client = _lite_client(http_factory(lambda request: httpx.Response(200, content=body, headers=STREAM_HEADERS)))

        chunks = list(client.chat.completions.create(model="m", messages=[], stream=True))

        assert [chunk.choices[0].delta.content for chunk in chunks] == ["Hi", ""]
        assert chunks[-1].choices[0].finish_reason == "stop"

    def test_stream_stops_at_done_marker(self, http_factory):
        body = _sse_bytes(_chunk_payload("before")) + b"data: [DONE]\n\n" + _sse_bytes(_chunk_payload("after"))
        client = _lite_client(http_factory(lambda request: httpx.Response(200, content=body, headers=STREAM_HEADERS)))

        chunks = list(client.chat.completions.create(model="m", messages=[], stream=True))

        assert [chunk.choices[0].delta.content for chunk in chunks] == ["before"]

    def test_usage_only_chunk_is_parsed(self, http_factory):
        payload = _chunk_payload(choices=False, usage={"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10})
        client = _lite_client(http_factory(lambda request: _sse_response(payload)))

        chunks = list(client.chat.completions.create(model="m", messages=[], stream=True))

        assert chunks[0].choices == []
        assert chunks[0].usage == {"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10}
        assert usage_from_openai(chunks[0]) == Usage(prompt_tokens=9, completion_tokens=1, total_tokens=10)

    def test_parallel_interleaved_fragmented_tool_calls(self, http_factory):
        payloads = [
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_a",
                                    "type": "function",
                                    "function": {"name": "get_weather", "arguments": ""},
                                },
                                {
                                    "index": 1,
                                    "id": "call_b",
                                    "type": "function",
                                    "function": {"name": "get_time", "arguments": ""},
                                },
                            ],
                        },
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '{"city": "Paris"}'}},
                                {"index": 1, "function": {"arguments": '{"tz": "UTC"}'}},
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "m",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            },
        ]
        client = _lite_client(http_factory(lambda request: _sse_response(*payloads)))

        chunks = list(client.chat.completions.create(model="m", messages=[], stream=True))

        first_fragments = chunks[0].choices[0].delta.tool_calls
        assert [(tool.index, tool.id, tool.function.name) for tool in first_fragments] == [
            (0, "call_a", "get_weather"),
            (1, "call_b", "get_time"),
        ]
        second_fragments = chunks[1].choices[0].delta.tool_calls
        assert [(tool.index, tool.function.arguments) for tool in second_fragments] == [
            (0, '{"city": "Paris"}'),
            (1, '{"tz": "UTC"}'),
        ]

    def test_tool_call_without_index_exposes_none(self, http_factory):
        payload = _chunk_payload(
            delta_extra={
                "tool_calls": [
                    {"id": "call_x", "type": "function", "function": {"name": "f", "arguments": "{}"}},
                ]
            },
            finish_reason="tool_calls",
        )
        client = _lite_client(http_factory(lambda request: _sse_response(payload)))

        chunks = list(client.chat.completions.create(model="m", messages=[], stream=True))

        assert chunks[0].choices[0].delta.tool_calls[0].index is None
        assert chunks[0].choices[0].delta.tool_calls[0].id == "call_x"

    def test_malformed_json_raises_provider_error(self, http_factory):
        client = _lite_client(
            http_factory(lambda request: httpx.Response(200, content=b"data: {not-json}\n\n", headers=STREAM_HEADERS))
        )
        stream = client.chat.completions.create(model="m", messages=[], stream=True)

        with pytest.raises(ProviderError, match="Malformed streaming payload"):
            list(stream)

    def test_response_is_closed_after_stream_is_exhausted(self, http_factory):
        captured = {}

        def handler(request):
            response = _sse_response(_chunk_payload("hi", finish_reason="stop"))
            captured["response"] = response
            return response

        client = _lite_client(http_factory(handler))
        list(client.chat.completions.create(model="m", messages=[], stream=True))

        assert captured["response"].is_closed is True

    def test_response_is_closed_when_stream_is_closed_early(self, http_factory):
        captured = {}

        def handler(request):
            response = _sse_response(_chunk_payload("one"), _chunk_payload("two", finish_reason="stop"))
            captured["response"] = response
            return response

        client = _lite_client(http_factory(handler))
        stream = client.chat.completions.create(model="m", messages=[], stream=True)
        next(stream)
        stream.close()

        assert captured["response"].is_closed is True

    def test_http_error_on_streaming_request_raises_before_iteration(self, http_factory):
        client = _lite_client(http_factory(_json_handler({"error": {"message": "bad request"}}, status=400)))

        with pytest.raises(LiteAPIError) as excinfo:
            client.chat.completions.create(model="m", messages=[], stream=True)

        assert excinfo.value.status_code == 400

    def test_iter_chunks_classifies_mid_stream_read_errors(self):
        class _BrokenStream:
            def __init__(self):
                self.closed = False

            def iter_lines(self):
                yield 'data: {"choices": [{"index": 0, "delta": {"content": "x"}}]}'
                raise httpx.ReadTimeout("stream broke")

            def close(self):
                self.closed = True

        broken = _BrokenStream()
        with pytest.raises(ProviderError) as excinfo:
            list(iter_chunks(broken))

        assert excinfo.value.kind is ErrorKind.TIMEOUT
        assert excinfo.value.retryable is True
        assert broken.closed is True


# ---------------------------------------------------------------------------
# Error surface + classification parity
# ---------------------------------------------------------------------------
class TestErrors:
    def test_http_error_exposes_status_body_and_response(self, http_factory):
        body = {"error": {"message": "bad parameter", "type": "invalid_request_error"}}
        client = _lite_client(http_factory(_json_handler(body, status=400)))

        with pytest.raises(LiteAPIError) as excinfo:
            client.chat.completions.create(model="m", messages=[])

        error = excinfo.value
        assert error.status_code == 400
        assert error.body == body
        assert isinstance(error.response, httpx.Response)
        assert error.response.status_code == 400
        assert error.response.json() == body
        assert "bad parameter" in str(error)

    def test_http_error_with_non_json_body_keeps_raw_text(self, http_factory):
        client = _lite_client(http_factory(lambda request: httpx.Response(502, text="upstream exploded")))

        with pytest.raises(LiteAPIError) as excinfo:
            client.chat.completions.create(model="m", messages=[])

        assert excinfo.value.body == "upstream exploded"
        assert "upstream exploded" in str(excinfo.value)
        assert classify_exception(excinfo.value).kind is ErrorKind.PROVIDER

    @pytest.mark.parametrize(
        "status, kind, retryable",
        [
            (400, ErrorKind.BAD_REQUEST, False),
            (401, ErrorKind.AUTH, False),
            (403, ErrorKind.AUTH, False),
            (404, ErrorKind.BAD_REQUEST, False),
            (429, ErrorKind.RATE_LIMIT, True),
            (500, ErrorKind.PROVIDER, True),
            (503, ErrorKind.PROVIDER, True),
        ],
    )
    def test_errors_are_classified_by_status(self, http_factory, status, kind, retryable):
        client = _lite_client(http_factory(_json_handler({"error": {"message": "request failed"}}, status=status)))

        with pytest.raises(LiteAPIError) as excinfo:
            client.chat.completions.create(model="m", messages=[])

        classified = classify_exception(excinfo.value)
        assert classified.kind is kind
        assert classified.retryable is retryable
        assert classified.status_code == status

    def test_wrap_provider_exception_preserves_classification(self, http_factory):
        client = _lite_client(http_factory(_json_handler({"error": {"message": "rate limited"}}, status=429)))

        with pytest.raises(LiteAPIError) as excinfo:
            client.chat.completions.create(model="m", messages=[])

        wrapped = wrap_provider_exception(excinfo.value, "OpenAI", detail=str(excinfo.value.body))
        assert wrapped.kind is ErrorKind.RATE_LIMIT
        assert wrapped.status_code == 429
        assert wrapped.retryable is True
        assert wrapped.message.startswith("OpenAI API error: ")

    def test_retry_after_header_is_available(self, http_factory):
        client = _lite_client(
            http_factory(
                lambda request: httpx.Response(
                    429, json={"error": {"message": "slow down"}}, headers={"Retry-After": "2.5"}
                )
            )
        )

        with pytest.raises(LiteAPIError) as excinfo:
            client.chat.completions.create(model="m", messages=[])

        assert retry_after_seconds(excinfo.value) == 2.5

    def test_connect_error_is_classified_as_network(self, http_factory):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        client = _lite_client(http_factory(handler))

        with pytest.raises(ProviderError) as excinfo:
            client.chat.completions.create(model="m", messages=[])

        assert excinfo.value.kind is ErrorKind.NETWORK
        assert excinfo.value.retryable is True

    def test_read_timeout_is_classified_as_timeout(self, http_factory):
        def handler(request):
            raise httpx.ReadTimeout("read timed out")

        client = _lite_client(http_factory(handler))

        with pytest.raises(ProviderError) as excinfo:
            client.chat.completions.create(model="m", messages=[])

        assert excinfo.value.kind is ErrorKind.TIMEOUT
        assert excinfo.value.retryable is True


# ---------------------------------------------------------------------------
# Provider integration over the lite transport
# ---------------------------------------------------------------------------
class TestProviderIntegration:
    def test_stream_options_rejection_is_retried_once_without_it(self, lite_provider):
        requests = []
        bodies = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(request)
            bodies.append(body)
            if len(bodies) == 1:
                return httpx.Response(
                    400, json={"error": {"message": "Unrecognized request argument supplied: stream_options"}}
                )
            return _sse_response(_chunk_payload("plain", finish_reason="stop"))

        provider = lite_provider(handler)

        responses = list(provider.completion(_messages(), stream=True))

        assert [response.content for response in responses] == ["plain"]
        assert len(requests) == 2
        assert bodies[0]["stream_options"] == {"include_usage": True}
        assert "stream_options" not in bodies[1]
        assert bodies[0]["messages"] == bodies[1]["messages"] == [{"role": "user", "content": "hi"}]

    def test_unrelated_400_is_not_retried(self, lite_provider):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(400, json={"error": {"message": "model not found"}})

        provider = lite_provider(handler)

        with pytest.raises(AgentError) as excinfo:
            list(provider.completion(_messages(), stream=True))

        assert excinfo.value.kind is ErrorKind.BAD_REQUEST
        assert len(requests) == 1

    def test_non_streaming_provider_request_has_no_stream_options(self, lite_provider):
        bodies = []

        def handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=_completion_payload("hello"))

        provider = lite_provider(handler)

        responses = list(provider.completion(_messages(), stream=False))

        assert [response.content for response in responses] == ["hello"]
        assert "stream_options" not in bodies[0]
        assert bodies[0]["stream"] is False

    def test_streaming_provider_requests_include_usage(self, lite_provider):
        bodies = []

        def handler(request):
            bodies.append(json.loads(request.content))
            return _sse_response(
                _chunk_payload("hi", finish_reason="stop"),
                _chunk_payload(choices=False, usage={"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}),
            )

        provider = lite_provider(handler)

        responses = list(provider.completion(_messages(), stream=True))

        assert bodies[0]["stream_options"] == {"include_usage": True}
        assert [response.content for response in responses] == ["hi", ""]
        assert responses[-1].usage == Usage(prompt_tokens=4, completion_tokens=2, total_tokens=6)

    def test_first_chunk_error_payload_raises_classified_error(self, lite_provider):
        def handler(request):
            return _sse_response({"error": {"message": "boom", "type": "invalid_request_error"}})

        provider = lite_provider(handler)
        collected = []

        with pytest.raises(AgentError) as excinfo:
            for response in provider.completion(_messages(), stream=True):
                collected.append(response)

        assert collected == []
        assert excinfo.value.kind is ErrorKind.PROVIDER
        assert "boom" in str(excinfo.value)

    def test_http_200_without_choices_raises_classified_error(self, lite_provider):
        provider = lite_provider(_json_handler({"error": {"message": "no choices in this body"}}))

        with pytest.raises(AgentError) as excinfo:
            list(provider.completion(_messages(), stream=False))

        assert "no choices in this body" in str(excinfo.value)

    def test_http_error_is_classified_and_body_is_printed(self, lite_provider):
        provider = lite_provider(
            _json_handler({"error": {"message": "Incorrect API key provided"}}, status=401),
        )

        with pytest.raises(AgentError) as excinfo:
            list(provider.completion(_messages(), stream=False))

        assert excinfo.value.kind is ErrorKind.AUTH
        assert excinfo.value.status_code == 401
        assert excinfo.value.retryable is False
        printed = [str(call.args[0]) for call in provider.console.print.call_args_list if call.args]
        assert any("Error Response" in text for text in printed)

    def test_malformed_stream_is_wrapped_as_agent_error(self, lite_provider):
        def handler(request):
            return httpx.Response(200, content=b"data: oops\n\n", headers=STREAM_HEADERS)

        provider = lite_provider(handler)

        with pytest.raises(AgentError) as excinfo:
            list(provider.completion(_messages(), stream=True))

        assert "Malformed streaming payload" in str(excinfo.value)

    def test_connect_error_is_wrapped_as_agent_error(self, lite_provider):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        provider = lite_provider(handler)

        with pytest.raises(AgentError) as excinfo:
            list(provider.completion(_messages(), stream=False))

        assert excinfo.value.kind is ErrorKind.NETWORK
        assert excinfo.value.retryable is True

    def test_tool_call_without_index_is_accumulated_by_id(self, lite_provider):
        first = _chunk_payload(
            "",
            delta_extra={
                "tool_calls": [
                    {
                        "id": "call_x",
                        "type": "function",
                        "function": {"name": "fs_read_file", "arguments": '{"path": "a.txt"}'},
                    }
                ]
            },
        )
        second = _chunk_payload("", finish_reason="tool_calls")
        provider = lite_provider(lambda request: _sse_response(first, second))

        responses = list(provider.completion(_messages(), stream=True))

        tool_responses = [response for response in responses if response.tool_call]
        assert len(tool_responses) == 1
        assert tool_responses[0].tool_call.id == "call_x"
        assert tool_responses[0].tool_call.name == "fs_read_file"
        assert tool_responses[0].tool_call.arguments == '{"path": "a.txt"}'


# ---------------------------------------------------------------------------
# Transport selection + verbose reporting
# ---------------------------------------------------------------------------
class _CustomOpenAIProvider(OpenAIProvider):
    """A user-defined subclass must keep the SDK transport (exact-name match)."""


class _CustomClientOpenAIProvider(OpenAIProvider):
    """A subclass providing an SDK client class must keep the SDK transport."""

    CLIENT_CLS = MagicMock()


class TestTransportSelection:
    def test_openai_provider_defaults_to_lite(self):
        provider = OpenAIProvider(config=_config())
        try:
            assert isinstance(provider.client, LiteChatClient)
        finally:
            provider.client.close()

    def test_openai_provider_uses_lite_when_enabled(self):
        provider = OpenAIProvider(config=_config(LITE_TRANSPORT=True))
        try:
            assert isinstance(provider.client, LiteChatClient)
        finally:
            provider.client.close()

    def test_openai_provider_uses_sdk_when_disabled(self):
        with patch("openai.OpenAI") as mock_cls:
            provider = OpenAIProvider(config=_config(LITE_TRANSPORT=False))

        assert provider.client is mock_cls.return_value
        assert not isinstance(provider.client, LiteChatClient)

    def test_openai_compatible_provider_uses_lite(self):
        provider = OpenAICompatibleProvider(config=_config(LITE_TRANSPORT=True))
        try:
            assert isinstance(provider.client, LiteChatClient)
        finally:
            provider.client.close()

    def test_openai_compatible_provider_uses_sdk_when_disabled(self):
        with patch("openai.OpenAI") as mock_cls:
            provider = OpenAICompatibleProvider(config=_config(LITE_TRANSPORT=False))

        assert provider.client is mock_cls.return_value

    def test_other_openai_family_provider_always_uses_sdk(self):
        with patch("openai.OpenAI") as mock_cls:
            provider = DeepSeekProvider(config=_config(LITE_TRANSPORT=True))

        assert provider.client is mock_cls.return_value

    def test_user_subclass_always_uses_sdk(self):
        with patch("openai.OpenAI") as mock_cls:
            provider = _CustomOpenAIProvider(config=_config(LITE_TRANSPORT=True))

        assert provider.client is mock_cls.return_value

    def test_custom_client_cls_subclass_always_uses_sdk(self):
        provider = _CustomClientOpenAIProvider(config=_config(LITE_TRANSPORT=True))

        assert provider.client is _CustomClientOpenAIProvider.CLIENT_CLS.return_value

    def test_azure_always_uses_sdk(self):
        config = {
            "API_KEY": "azure-key",
            "API_VERSION": "2024-01-01",
            "AZURE_ENDPOINT": "https://example.openai.azure.com/",
            "AZURE_DEPLOYMENT": "gpt-4",
            "MODEL": "gpt-4",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
            "LITE_TRANSPORT": True,
        }

        with patch("openai.AzureOpenAI") as mock_cls:
            provider = OpenAIAzure(config=config)

        assert provider.client is mock_cls.return_value
        assert not isinstance(provider.client, LiteChatClient)

    def test_verbose_reports_lite_transport(self):
        console = MagicMock()
        with patch("yaicli.llms.openai_wire.get_console", return_value=console):
            provider = OpenAIProvider(config=_config(), verbose=True)
        try:
            console.print.assert_any_call("Transport: lite (httpx)")
        finally:
            provider.client.close()

    def test_verbose_reports_sdk_transport(self):
        console = MagicMock()
        with (
            patch("yaicli.llms.openai_wire.get_console", return_value=console),
            patch("openai.OpenAI"),
        ):
            OpenAIProvider(config=_config(LITE_TRANSPORT=False), verbose=True)

        console.print.assert_any_call("Transport: openai SDK")

    def test_verbose_is_silent_without_the_flag(self):
        console = MagicMock()
        with patch("yaicli.llms.openai_wire.get_console", return_value=console):
            provider = OpenAIProvider(config=_config())
        try:
            console.print.assert_not_called()
        finally:
            provider.client.close()


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------
class TestClientLifecycle:
    def test_create_lite_client_factory(self, http_factory):
        http = http_factory(_json_handler(_completion_payload()))
        client = create_lite_client({"api_key": "k", "base_url": BASE_URL}, http_client=http)

        assert isinstance(client, LiteChatClient)
        assert client.url == f"{BASE_URL}/chat/completions"

    def test_close_closes_an_owned_http_client(self):
        client = LiteChatClient({"api_key": "k", "base_url": BASE_URL})
        assert client.http.is_closed is False

        client.close()

        assert client.http.is_closed is True

    def test_close_leaves_an_injected_http_client_open(self, http_factory):
        http = http_factory(_json_handler(_completion_payload()))
        client = LiteChatClient({"api_key": "k", "base_url": BASE_URL}, http_client=http)

        client.close()

        assert http.is_closed is False  # the caller owns it; the fixture closes it

    def test_context_manager_closes_the_client(self):
        with LiteChatClient({"api_key": "k", "base_url": BASE_URL}) as client:
            assert client.http.is_closed is False

        assert client.http.is_closed is True


# ---------------------------------------------------------------------------
# Import boundary: the lite modules must never import the SDK
# ---------------------------------------------------------------------------
def _run_python(code):
    env = os.environ.copy()
    with tempfile.TemporaryDirectory() as home:
        env["HOME"] = home
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )


class TestImportBoundary:
    @pytest.mark.parametrize("module", ["yaicli.llms.lite_transport", "yaicli.llms.openai_wire"])
    def test_transport_modules_do_not_import_openai(self, module):
        proc = _run_python(f"import sys\nimport {module}\nprint('openai' in sys.modules)\n")

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "False", proc.stdout

    @pytest.mark.parametrize(
        "module",
        ["yaicli.llms.providers.openai_provider", "yaicli.llms.providers.openai_compatible_provider"],
    )
    def test_provider_modules_keep_the_sdk_import_lazy(self, module):
        proc = _run_python(f"import sys\nimport {module}\nprint('openai' in sys.modules)\n")

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "False", proc.stdout
