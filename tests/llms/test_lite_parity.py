"""SDK / lite transport parity: the same wire payload must parse identically.

Both transports share :class:`yaicli.llms.openai_wire.OpenAIWireProvider`, so the
handlers are the same code — the risk is a shape difference between the openai
SDK models and the duck-typed lite objects. Each test feeds one wire payload
twice:

* **SDK path** — ``ChatCompletion.model_validate`` / ``ChatCompletionChunk.model_validate``
  (the real SDK models, dev dependency only) returned by a fake SDK client;
* **lite path** — the raw JSON body / SSE bytes through ``LiteChatClient`` with
  an ``httpx.MockTransport``.

The normalized ``(content, reasoning, finish_reason, tool_calls, usage)``
sequence must be equal (v0.24 PRD R3/R9, design §7.2).
"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from yaicli.errors import AgentError, ErrorKind
from yaicli.llms.lite_transport import LiteChatClient
from yaicli.llms.providers.openai_compatible_provider import OpenAICompatibleProvider
from yaicli.llms.providers.openai_provider import OpenAIProvider
from yaicli.schemas import ChatMessage

BASE_URL = "https://parity.example.com/v1"
STREAM_HEADERS = {"content-type": "text/event-stream"}


def _config(**overrides):
    config = {
        "API_KEY": "fake_parity_key",
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


def _normalize(responses):
    """Reduce LLMResponse objects to the fields the parity contract compares."""
    normalized = []
    for response in responses:
        tool_calls = tuple((call.id, call.name, call.arguments) for call in response.tool_calls)
        usage = None
        if response.usage is not None:
            usage = (
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens,
                response.usage.cached_tokens,
                response.usage.reasoning_tokens,
            )
        normalized.append((response.content, response.reasoning, response.finish_reason, tool_calls, usage))
    return normalized


@pytest.fixture
def http_factory():
    created = []

    def make(handler):
        http = httpx.Client(transport=httpx.MockTransport(handler))
        created.append(http)
        return http

    yield make
    for http in created:
        http.close()


def _sdk_provider(provider_cls, response):
    """A provider whose SDK client returns the parsed SDK model(s)."""
    with patch("openai.OpenAI"):
        provider = provider_cls(config=_config(LITE_TRANSPORT=False))
    client = MagicMock()
    client.chat.completions.create.return_value = response
    provider.client = client
    provider.console = MagicMock()
    return provider


def _lite_provider(http_factory, provider_cls, handler):
    """A provider whose client is the httpx lite transport over a mock handler."""
    provider = provider_cls(config=_config(LITE_TRANSPORT=True))
    provider.client = LiteChatClient(provider.client_params, http_client=http_factory(handler))
    provider.console = MagicMock()
    return provider


def _completion_payload(content="Hello", *, finish_reason="stop", message_extra=None, usage=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    if message_extra:
        message.update(message_extra)
    payload = {
        "id": "chatcmpl-parity",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def _chunk_payload(delta=None, finish_reason=None, *, usage=None, choices=True):
    payload = {
        "id": "chatcmpl-parity-chunk",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "gpt-4o-mini",
    }
    payload["choices"] = [{"index": 0, "delta": delta or {}, "finish_reason": finish_reason}] if choices else []
    if usage is not None:
        payload["usage"] = usage
    return payload


def _sse_response(*payloads):
    body = "".join(f"data: {json.dumps(payload)}\n\n" for payload in payloads) + "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers=STREAM_HEADERS)


def _json_handler(payload):
    def handler(request):
        return httpx.Response(200, json=payload)

    return handler


def _sse_handler(*payloads):
    def handler(request):
        return _sse_response(*payloads)

    return handler


def _collect(provider, *, stream):
    return list(provider.completion(_messages(), stream=stream))


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------
class TestPlainTextParity:
    def test_non_stream_text_and_usage(self, http_factory):
        payload = _completion_payload(
            "Hello from the wire",
            usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        )

        sdk = _sdk_provider(OpenAIProvider, ChatCompletion.model_validate(payload))
        lite = _lite_provider(http_factory, OpenAIProvider, _json_handler(payload))

        sdk_responses = _normalize(_collect(sdk, stream=False))
        lite_responses = _normalize(_collect(lite, stream=False))

        assert sdk_responses == lite_responses
        assert sdk_responses == [("Hello from the wire", "", "stop", (), (5, 3, 8, 0, 0))]

    def test_stream_text_and_terminal_usage(self, http_factory):
        payloads = [
            _chunk_payload({"content": "Hel"}),
            _chunk_payload({"content": "lo"}),
            _chunk_payload({"content": "!"}, "stop"),
            _chunk_payload(choices=False, usage={"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}),
        ]
        sdk_chunks = [ChatCompletionChunk.model_validate(payload) for payload in payloads]

        sdk = _sdk_provider(OpenAIProvider, sdk_chunks)
        lite = _lite_provider(http_factory, OpenAIProvider, _sse_handler(*payloads))

        sdk_responses = _normalize(_collect(sdk, stream=True))
        lite_responses = _normalize(_collect(lite, stream=True))

        assert sdk_responses == lite_responses
        assert [entry[0] for entry in sdk_responses] == ["Hel", "lo", "!", ""]
        assert sdk_responses[-1][4] == (4, 3, 7, 0, 0)


# ---------------------------------------------------------------------------
# Reasoning + usage
# ---------------------------------------------------------------------------
class TestReasoningParity:
    def test_non_stream_reasoning_and_usage_details(self, http_factory):
        payload = _completion_payload(
            "answer",
            message_extra={"reasoning_content": "deep thought"},
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "prompt_tokens_details": {"cached_tokens": 2},
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        )

        sdk = _sdk_provider(OpenAIProvider, ChatCompletion.model_validate(payload))
        lite = _lite_provider(http_factory, OpenAIProvider, _json_handler(payload))

        sdk_responses = _normalize(_collect(sdk, stream=False))
        lite_responses = _normalize(_collect(lite, stream=False))

        assert sdk_responses == lite_responses
        # reasoning_content and both detail counters survive both parsers
        assert sdk_responses == [("answer", "deep thought", "stop", (), (10, 5, 15, 2, 3))]

    def test_stream_reasoning_keys_and_usage(self, http_factory):
        payloads = [
            _chunk_payload({"content": "Let me ", "reasoning_content": "think "}),
            _chunk_payload({"content": "answer", "reasoning": "hard"}),
            _chunk_payload({}, "stop"),
            _chunk_payload(choices=False, usage={"prompt_tokens": 6, "completion_tokens": 2, "total_tokens": 8}),
        ]
        sdk_chunks = [ChatCompletionChunk.model_validate(payload) for payload in payloads]

        sdk = _sdk_provider(OpenAIProvider, sdk_chunks)
        lite = _lite_provider(http_factory, OpenAIProvider, _sse_handler(*payloads))

        sdk_responses = _normalize(_collect(sdk, stream=True))
        lite_responses = _normalize(_collect(lite, stream=True))

        assert sdk_responses == lite_responses
        assert [entry[1] for entry in sdk_responses] == ["think ", "hard", None, None]
        assert sdk_responses[-1][4] == (6, 2, 8, 0, 0)


# ---------------------------------------------------------------------------
# Tool calls
# ---------------------------------------------------------------------------
class TestToolCallParity:
    def test_non_stream_parallel_tool_calls(self, http_factory):
        payload = _completion_payload(
            "Checking both",
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

        sdk = _sdk_provider(OpenAIProvider, ChatCompletion.model_validate(payload))
        lite = _lite_provider(http_factory, OpenAIProvider, _json_handler(payload))

        sdk_responses = _normalize(_collect(sdk, stream=False))
        lite_responses = _normalize(_collect(lite, stream=False))

        assert sdk_responses == lite_responses
        emitted = [entry[3] for entry in sdk_responses if entry[3]]
        assert emitted == [
            (("call_a", "fs_read_file", '{"path": "a.txt"}'),),
            (("call_b", "fs_read_file", '{"path": "b.txt"}'),),
        ]
        # assistant text is attached to the first response only
        assert [entry[0] for entry in sdk_responses] == ["Checking both", ""]

    def test_stream_parallel_fragmented_tool_calls(self, http_factory):
        payloads = [
            _chunk_payload(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_a",
                            "type": "function",
                            "function": {"name": "fs_read_file", "arguments": ""},
                        },
                        {
                            "index": 1,
                            "id": "call_b",
                            "type": "function",
                            "function": {"name": "fs_read_file", "arguments": ""},
                        },
                    ],
                }
            ),
            _chunk_payload(
                {
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": '{"path": "a'}},
                        {"index": 1, "function": {"arguments": '{"path": "b'}},
                    ]
                }
            ),
            _chunk_payload(
                {
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": '.txt"}'}},
                        {"index": 1, "function": {"arguments": '.txt"}'}},
                    ]
                }
            ),
            _chunk_payload({}, "tool_calls"),
        ]
        sdk_chunks = [ChatCompletionChunk.model_validate(payload) for payload in payloads]

        sdk = _sdk_provider(OpenAIProvider, sdk_chunks)
        lite = _lite_provider(http_factory, OpenAIProvider, _sse_handler(*payloads))

        sdk_responses = _normalize(_collect(sdk, stream=True))
        lite_responses = _normalize(_collect(lite, stream=True))

        assert sdk_responses == lite_responses
        emitted = [entry[3] for entry in sdk_responses if entry[3]]
        assert emitted == [
            (("call_a", "fs_read_file", '{"path": "a.txt"}'),),
            (("call_b", "fs_read_file", '{"path": "b.txt"}'),),
        ]


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider: complete-JSON tool calls without finish_reason
# ---------------------------------------------------------------------------
class TestCompatibleProviderParity:
    def test_complete_json_tool_call_emitted_early(self, http_factory):
        payloads = [
            _chunk_payload(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"location": "NYC"}'},
                        }
                    ]
                }
            ),
        ]
        sdk_chunks = [ChatCompletionChunk.model_validate(payload) for payload in payloads]

        sdk = _sdk_provider(OpenAICompatibleProvider, sdk_chunks)
        lite = _lite_provider(http_factory, OpenAICompatibleProvider, _sse_handler(*payloads))

        sdk_responses = _normalize(_collect(sdk, stream=True))
        lite_responses = _normalize(_collect(lite, stream=True))

        assert sdk_responses == lite_responses
        assert sdk_responses[0][2] == "tool_calls"  # finish_reason synthesized
        assert sdk_responses[0][3] == (("call_1", "get_weather", '{"location": "NYC"}'),)

    def test_incomplete_json_then_complete(self, http_factory):
        payloads = [
            _chunk_payload(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "f", "arguments": '{"x": '},
                        }
                    ]
                }
            ),
            _chunk_payload({"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}, "tool_calls"),
        ]
        sdk_chunks = [ChatCompletionChunk.model_validate(payload) for payload in payloads]

        sdk = _sdk_provider(OpenAICompatibleProvider, sdk_chunks)
        lite = _lite_provider(http_factory, OpenAICompatibleProvider, _sse_handler(*payloads))

        sdk_responses = _normalize(_collect(sdk, stream=True))
        lite_responses = _normalize(_collect(lite, stream=True))

        assert sdk_responses == lite_responses
        # first chunk: incomplete JSON -> nothing emitted yet
        assert sdk_responses[0][3] == ()
        # second chunk: finish_reason + complete JSON -> the call is emitted
        assert sdk_responses[1][2] == "tool_calls"
        assert sdk_responses[1][3] == (("call_1", "f", '{"x": 1}'),)


# ---------------------------------------------------------------------------
# HTTP 200 with an in-band error document
# ---------------------------------------------------------------------------
class TestInBandErrorParity:
    def test_non_stream_error_document(self, http_factory):
        payload = {
            "id": "chatcmpl-error",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "gpt-4o-mini",
            "choices": [],
            "error": {
                "message": "Incorrect API key provided",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            },
        }

        sdk = _sdk_provider(OpenAIProvider, ChatCompletion.model_validate(payload))
        lite = _lite_provider(http_factory, OpenAIProvider, _json_handler(payload))

        errors = []
        for provider in (sdk, lite):
            with pytest.raises(AgentError) as excinfo:
                list(provider.completion(_messages(), stream=False))
            errors.append(excinfo.value)

        assert all(error.kind is ErrorKind.AUTH for error in errors)
        assert all("Incorrect API key provided" in str(error) for error in errors)

    def test_stream_first_chunk_error(self, http_factory):
        payload = {
            "id": "chatcmpl-error-chunk",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o-mini",
            "choices": [],
            "error": {"message": "Incorrect API key provided", "type": "invalid_request_error"},
        }

        sdk = _sdk_provider(OpenAIProvider, [ChatCompletionChunk.model_validate(payload)])
        lite = _lite_provider(http_factory, OpenAIProvider, _sse_handler(payload))

        collected = []
        errors = []
        for provider in (sdk, lite):
            with pytest.raises(AgentError) as excinfo:
                for response in provider.completion(_messages(), stream=True):
                    collected.append(response)
            errors.append(excinfo.value)

        assert collected == []
        assert errors[0].kind is errors[1].kind
        assert all("Incorrect API key provided" in str(error) for error in errors)
