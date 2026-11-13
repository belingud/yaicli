"""K14: multi-provider tool-call consistency.

Every provider must retain **all** tool calls of one response/stream, including
parallel calls and calls that share the same function name. These tests pin the
fixes for the providers that used to keep only one call
(anthropic non-stream/stream, gemini stream, ollama, chatglm, minimax, ai21,
mistral, openai-compatible, cohere) plus the end-to-end ``LLMClient`` plural
collection path.
"""

from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.client import LLMClient
from yaicli.llms.provider import Provider
from yaicli.llms.providers.ai21_provider import AI21Provider
from yaicli.llms.providers.anthropic_provider import AnthropicProvider
from yaicli.llms.providers.chatglm_provider import ChatglmProvider
from yaicli.llms.providers.cohere_provider import CohereProvider
from yaicli.llms.providers.gemini_provider import GeminiProvider
from yaicli.llms.providers.minimax_provider import MinimaxProvider
from yaicli.llms.providers.mistral_provider import MistralProvider
from yaicli.llms.providers.ollama_provider import OllamaProvider
from yaicli.llms.providers.openai_compatible_provider import OpenAICompatibleProvider
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall, ToolPolicy

BASE_CONFIG = {
    "API_KEY": "fake_api_key",
    "BASE_URL": None,
    "MODEL": "test-model",
    "TEMPERATURE": 0.7,
    "TOP_P": 1.0,
    "MAX_TOKENS": 128,
    "TIMEOUT": 10,
    "EXTRA_HEADERS": {},
    "EXTRA_BODY": None,
    "ENABLE_FUNCTIONS": False,
    "ENABLE_MCP": False,
    "LITE_TRANSPORT": False,
    "FREQUENCY_PENALTY": 0.0,
    "STREAM": False,
    "TOOL_CONFIRM": False,
    "MAX_TOOL_CALL_DEPTH": 5,
    "PROVIDER": "openai",
}


def _config(**overrides):
    config = dict(BASE_CONFIG)
    config.update(overrides)
    return config


def _collect_calls(responses):
    """Flatten the tool calls of a list of LLMResponse objects (in order)."""
    calls = []
    for response in responses:
        calls.extend(response.tool_calls)
    return calls


class TestAnthropicMultiToolCalls:
    """anthropic_provider used to overwrite a single tool_call slot."""

    @pytest.fixture
    def provider(self):
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            return AnthropicProvider(config=_config())

    def test_non_stream_keeps_every_tool_use_block(self, provider):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Checking two things"

        first = MagicMock()
        first.type = "tool_use"
        first.id = "tool_1"
        first.name = "get_weather"
        first.input = {"city": "Paris"}

        second = MagicMock()
        second.type = "tool_use"
        second.id = "tool_2"
        second.name = "get_time"
        second.input = {"timezone": "UTC"}

        response = MagicMock()
        response.content = [text_block, first, second]
        response.stop_reason = "tool_use"

        responses = list(provider._handle_normal_response(response))

        assert len(responses) == 1
        calls = responses[0].tool_calls
        assert [call.id for call in calls] == ["tool_1", "tool_2"]
        assert [call.name for call in calls] == ["get_weather", "get_time"]
        assert calls[1].arguments == '{"timezone": "UTC"}'
        # Legacy view still points at the first call.
        assert responses[0].tool_call is calls[0]
        assert responses[0].content == "Checking two things"

    @staticmethod
    def _stream_events(calls):
        """Build the Anthropic event sequence for several complete tool_use blocks."""
        events = []
        start = MagicMock()
        start.type = "message_start"
        events.append(start)
        for call in calls:
            block_start = MagicMock()
            block_start.type = "content_block_start"
            block_start.content_block = MagicMock()
            block_start.content_block.type = "tool_use"
            block_start.content_block.id = call.id
            block_start.content_block.name = call.name
            events.append(block_start)

            delta = MagicMock()
            delta.type = "content_block_delta"
            delta.delta = MagicMock(spec=["partial_json"])
            delta.delta.partial_json = call.arguments
            events.append(delta)

            block_stop = MagicMock()
            block_stop.type = "content_block_stop"
            events.append(block_stop)

        message_delta = MagicMock()
        message_delta.type = "message_delta"
        message_delta.delta = MagicMock(spec=["stop_reason"])
        message_delta.delta.stop_reason = "tool_use"
        events.append(message_delta)

        message_stop = MagicMock()
        message_stop.type = "message_stop"
        events.append(message_stop)
        return events

    def test_stream_keeps_every_tool_use_block(self, provider):
        calls = [
            ToolCall(id="tool_1", name="get_weather", arguments='{"city": "Paris"}'),
            ToolCall(id="tool_2", name="get_time", arguments='{"tz": "UTC"}'),
        ]

        responses = list(provider._handle_stream_response(self._stream_events(calls)))

        seen = {call.id: call for call in _collect_calls(responses)}
        assert list(seen) == ["tool_1", "tool_2"]
        assert seen["tool_2"].arguments == '{"tz": "UTC"}'

    def test_stream_never_emits_a_partial_call(self, provider):
        calls = [
            ToolCall(id="tool_1", name="get_weather", arguments='{"city": "Paris"}'),
            ToolCall(id="tool_2", name="get_time", arguments='{"tz": "UTC"}'),
        ]

        responses = list(provider._handle_stream_response(self._stream_events(calls)))
        first_call_response = next(i for i, response in enumerate(responses) if response.tool_calls)

        # Calls are only surfaced on message_delta/message_stop (the last two
        # events), after every block has been finalized — never mid-block.
        assert first_call_response >= len(responses) - 2


class TestGeminiMultiToolCalls:
    """gemini_provider used to merge same-name streamed function calls."""

    @pytest.fixture
    def provider(self):
        with patch("google.genai.Client", MagicMock()):
            return GeminiProvider(config=_config())

    @staticmethod
    def _fc_part(name, args):
        part = MagicMock()
        fc = MagicMock()
        fc.name = name
        fc.args = args
        part.function_call = fc
        part.thought = None
        return part

    @staticmethod
    def _chunk(parts, finish_reason=None):
        chunk = MagicMock()
        candidate = MagicMock()
        content = MagicMock()
        content.parts = parts
        candidate.content = content
        candidate.finish_reason = finish_reason
        chunk.candidates = [candidate]
        return chunk

    def test_stream_same_name_calls_stay_distinct(self, provider):
        chunks = [
            self._chunk([self._fc_part("get_weather", {"city": "Paris"})]),
            self._chunk([self._fc_part("get_weather", {"city": "London"})]),
        ]

        responses = list(provider._handle_stream_response(chunks))

        calls = _collect_calls(responses)
        assert len(calls) == 2
        assert calls[0].name == calls[1].name == "get_weather"
        assert calls[0].arguments != calls[1].arguments
        assert calls[0].id != calls[1].id

    def test_stream_two_same_name_calls_in_one_chunk(self, provider):
        chunks = [
            self._chunk(
                [
                    self._fc_part("get_weather", {"city": "Paris"}),
                    self._fc_part("get_weather", {"city": "London"}),
                ],
                finish_reason="stop",
            )
        ]

        calls = _collect_calls(list(provider._handle_stream_response(chunks)))

        assert len(calls) == 2
        assert [call.name for call in calls] == ["get_weather", "get_weather"]


class TestOllamaMultiToolCalls:
    """ollama_provider used to keep only the first call."""

    @pytest.fixture
    def provider(self):
        with patch("yaicli.llms.providers.ollama_provider.ollama.Client", MagicMock()):
            return OllamaProvider(config=_config(FREQUENCY_PENALTY=0.0))

    @staticmethod
    def _ollama_calls():
        return [
            {"id": "tc_1", "function": {"name": "get_weather", "arguments": {"city": "Paris"}}},
            {"id": "tc_2", "function": {"name": "get_time", "arguments": {"tz": "UTC"}}},
        ]

    def test_non_stream_keeps_every_call(self, provider):
        response = MagicMock()
        response.message.content = "Checking two things"
        response.message.thinking = None
        response.message.tool_calls = self._ollama_calls()

        responses = list(provider._handle_normal_response(response, tool_calls_enabled=True))

        assert len(responses) == 1
        calls = responses[0].tool_calls
        assert [call.id for call in calls] == ["tc_1", "tc_2"]
        assert [call.name for call in calls] == ["get_weather", "get_time"]
        assert calls[0].arguments == '{"city": "Paris"}'

    def test_stream_keeps_every_call(self, provider):
        text_chunk = MagicMock()
        text_chunk.message.content = "Checking"
        text_chunk.message.thinking = None
        text_chunk.message.tool_calls = None

        tool_chunk = MagicMock()
        tool_chunk.message.content = ""
        tool_chunk.message.thinking = None
        tool_chunk.message.tool_calls = self._ollama_calls()

        responses = list(provider._handle_stream_response([text_chunk, tool_chunk], tool_calls_enabled=True))

        calls = _collect_calls(responses)
        assert [call.id for call in calls] == ["tc_1", "tc_2"]
        assert len(calls) == 2


class TestChatglmMultiToolCalls:
    """chatglm_provider used a single tool_call slot (partial calls leaked too)."""

    @pytest.fixture
    def provider(self):
        with patch.object(ChatglmProvider, "CLIENT_CLS", MagicMock()):
            return ChatglmProvider(config=_config())

    @staticmethod
    def _tool(index, call_id=None, name=None, arguments=None):
        tool = MagicMock()
        tool.index = index
        tool.id = call_id
        tool.function = MagicMock()
        tool.function.name = name
        tool.function.arguments = arguments
        return tool

    @staticmethod
    def _chunk(tool_calls=None, content="", finish_reason=None):
        chunk = MagicMock()
        choice = MagicMock()
        delta = MagicMock()
        delta.content = content
        delta.model_extra = None
        delta.tool_calls = tool_calls
        choice.delta = delta
        choice.finish_reason = finish_reason
        chunk.choices = [choice]
        return chunk

    def test_stream_interleaved_parallel_calls(self, provider):
        chunks = [
            self._chunk(
                tool_calls=[
                    self._tool(0, "call_a", "fs_read_file", ""),
                    self._tool(1, "call_b", "fs_read_file", ""),
                ]
            ),
            self._chunk(
                tool_calls=[
                    self._tool(1, None, None, '{"path": "b.txt"}'),
                    self._tool(0, None, None, '{"path": "a.txt"}'),
                ]
            ),
            self._chunk(finish_reason="tool_calls"),
        ]

        responses = list(provider._handle_stream_response(chunks))

        calls = _collect_calls(responses)
        assert [call.id for call in calls] == ["call_a", "call_b"]
        assert [call.arguments for call in calls] == ['{"path": "a.txt"}', '{"path": "b.txt"}']
        # Only the final response carries calls (no partial snapshots).
        assert [response for response in responses[:-1] if response.tool_calls] == []

    def test_non_stream_keeps_every_message_tool_call(self, provider):
        first_tool = MagicMock()
        first_tool.id = "call_a"
        first_tool.function.name = "fs_read_file"
        first_tool.function.arguments = '{"path": "a.txt"}'

        second_tool = MagicMock()
        second_tool.id = "call_b"
        second_tool.function.name = "fs_read_file"
        second_tool.function.arguments = '{"path": "b.txt"}'

        message = MagicMock()
        message.content = ""
        message.reasoning_content = None
        message.model_extra = None
        message.tool_calls = [first_tool, second_tool]

        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "tool_calls"
        response = MagicMock()
        response.choices = [choice]

        responses = list(provider._handle_normal_response(response))

        assert len(responses[0].tool_calls) == 2
        assert [call.id for call in responses[0].tool_calls] == ["call_a", "call_b"]


class TestMinimaxMultiToolCalls:
    """minimax_provider inherited a single-call streaming loop."""

    @pytest.fixture
    def provider(self):
        with patch.object(MinimaxProvider, "CLIENT_CLS", MagicMock()):
            return MinimaxProvider(config=_config())

    @staticmethod
    def _tool(index, call_id=None, name=None, arguments=None):
        tool = MagicMock()
        tool.index = index
        tool.id = call_id
        tool.function = MagicMock()
        tool.function.name = name
        tool.function.arguments = arguments
        return tool

    @staticmethod
    def _chunk(tool_calls=None, content="", finish_reason=None):
        chunk = MagicMock()
        choice = MagicMock()
        delta = MagicMock()
        delta.content = content
        delta.model_extra = None
        delta.tool_calls = tool_calls
        choice.delta = delta
        choice.finish_reason = finish_reason
        chunk.choices = [choice]
        return chunk

    def test_stream_keeps_parallel_calls(self, provider):
        chunks = [
            self._chunk(
                tool_calls=[
                    self._tool(0, "call_a", "get_weather", ""),
                    self._tool(1, "call_b", "get_time", ""),
                ]
            ),
            self._chunk(
                tool_calls=[
                    self._tool(0, None, None, '{"city": "Paris"}'),
                    self._tool(1, None, None, '{"tz": "UTC"}'),
                ]
            ),
            self._chunk(finish_reason="tool_calls"),
        ]

        calls = _collect_calls(list(provider._handle_stream_response(chunks)))

        assert [call.id for call in calls] == ["call_a", "call_b"]
        assert [call.name for call in calls] == ["get_weather", "get_time"]
        assert calls[1].arguments == '{"tz": "UTC"}'


class TestAI21MultiToolCalls:
    """ai21_provider replaced the whole call slot on every chunk."""

    @pytest.fixture
    def provider(self):
        with patch.object(AI21Provider, "CLIENT_CLS", MagicMock()):
            return AI21Provider(config=_config())

    @staticmethod
    def _tool(call_id=None, name=None, arguments=None):
        tool = MagicMock()
        tool.id = call_id
        tool.function = MagicMock()
        tool.function.name = name
        tool.function.arguments = arguments
        return tool

    @staticmethod
    def _chunk(tool_calls=None, content="", finish_reason=None):
        chunk = MagicMock()
        choice = MagicMock()
        delta = MagicMock()
        delta.content = content
        delta.model_extra = None
        delta.tool_calls = tool_calls
        choice.delta = delta
        choice.finish_reason = finish_reason
        chunk.choices = [choice]
        return chunk

    def test_stream_keeps_parallel_calls(self, provider):
        chunks = [
            self._chunk(
                tool_calls=[
                    self._tool("call_a", "get_weather", ""),
                    self._tool("call_b", "get_time", ""),
                ]
            ),
            self._chunk(
                tool_calls=[
                    self._tool("call_a", None, '{"city": "Paris"}'),
                    self._tool("call_b", None, '{"tz": "UTC"}'),
                ],
                finish_reason="tool_calls",
            ),
        ]

        calls = _collect_calls(list(provider._handle_stream_response(chunks)))

        assert [call.id for call in calls] == ["call_a", "call_b"]
        assert calls[0].arguments == '{"city": "Paris"}'
        assert calls[1].arguments == '{"tz": "UTC"}'


class TestMistralMultiToolCalls:
    """mistral_provider used a single tool call in stream and non-stream modes."""

    @pytest.fixture
    def provider(self):
        with patch("mistralai.Mistral"), patch("warnings.filterwarnings"):
            return MistralProvider(config=_config())

    @staticmethod
    def _tool(call_id, name, arguments):
        tool = MagicMock()
        tool.id = call_id
        tool.function = MagicMock()
        tool.function.name = name
        tool.function.arguments = arguments
        return tool

    def test_non_stream_keeps_every_call(self, provider):
        message = MagicMock()
        message.content = ""
        message.tool_calls = [
            self._tool("call_a", "get_weather", '{"city": "Paris"}'),
            self._tool("call_b", "get_time", '{"tz": "UTC"}'),
        ]
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "tool_calls"
        response = MagicMock()
        response.choices = [choice]

        responses = list(provider._handle_normal_response(response))

        assert [call.id for call in responses[0].tool_calls] == ["call_a", "call_b"]
        assert responses[0].tool_calls[1].arguments == '{"tz": "UTC"}'

    def test_stream_keeps_parallel_calls(self, provider):
        def chunk(tool_calls=None, content="", finish_reason=None):
            stream_chunk = MagicMock()
            choice = MagicMock()
            delta = MagicMock()
            delta.content = content
            delta.tool_calls = tool_calls
            choice.delta = delta
            choice.finish_reason = finish_reason
            stream_chunk.data.choices = [choice]
            return stream_chunk

        chunks = [
            chunk(
                tool_calls=[
                    self._tool("call_a", "get_weather", ""),
                    self._tool("call_b", "get_time", ""),
                ]
            ),
            chunk(
                tool_calls=[
                    self._tool("call_a", None, '{"city": "Paris"}'),
                    self._tool("call_b", None, '{"tz": "UTC"}'),
                ],
                finish_reason="tool_calls",
            ),
        ]

        calls = _collect_calls(list(provider._handle_stream_response(chunks)))

        assert [call.id for call in calls] == ["call_a", "call_b"]
        assert calls[0].arguments == '{"city": "Paris"}'
        assert calls[1].arguments == '{"tz": "UTC"}'


class TestOpenAICompatibleMultiToolCalls:
    """The generic compatible endpoint mixed parallel call arguments."""

    @pytest.fixture
    def provider(self):
        with patch.object(OpenAICompatibleProvider, "CLIENT_CLS", MagicMock()):
            return OpenAICompatibleProvider(config=_config())

    @staticmethod
    def _tool(call_id=None, name=None, arguments=""):
        tool = MagicMock()
        tool.id = call_id
        tool.function = MagicMock()
        tool.function.name = name
        tool.function.arguments = arguments
        return tool

    @staticmethod
    def _chunk(tool_calls=None, content="", finish_reason=None):
        chunk = MagicMock()
        choice = MagicMock()
        delta = MagicMock()
        delta.content = content
        delta.model_extra = None
        delta.tool_calls = tool_calls
        choice.delta = delta
        choice.finish_reason = finish_reason
        chunk.choices = [choice]
        return chunk

    def test_stream_keeps_parallel_calls(self, provider):
        chunks = [
            self._chunk(
                tool_calls=[
                    self._tool("call_a", "fs_read_file", ""),
                    self._tool("call_b", "fs_read_file", ""),
                ]
            ),
            self._chunk(
                tool_calls=[
                    self._tool(None, None, '{"path": "a.txt"}'),
                    self._tool(None, None, '{"path": "b.txt"}'),
                ]
            ),
            self._chunk(finish_reason="tool_calls"),
        ]

        calls = _collect_calls(list(provider._handle_stream_response(chunks)))

        assert [call.id for call in calls] == ["call_a", "call_b"]
        assert [call.arguments for call in calls] == ['{"path": "a.txt"}', '{"path": "b.txt"}']

    def test_complete_json_calls_are_emitted_early(self, provider):
        chunk = self._chunk(
            tool_calls=[
                self._tool("call_a", "fs_read_file", '{"path": "a.txt"}'),
                self._tool("call_b", "fs_read_file", '{"path": "b.txt"}'),
            ]
        )

        responses = list(provider._handle_stream_response([chunk]))

        assert len(responses) == 1
        assert [call.id for call in responses[0].tool_calls] == ["call_a", "call_b"]
        assert responses[0].finish_reason == "tool_calls"


class TestCohereMultiToolCalls:
    """cohere returns tool-call events; verify every call is yielded."""

    @pytest.fixture
    def provider(self):
        with patch.object(CohereProvider, "create_client", return_value=MagicMock()):
            return CohereProvider(config=_config())

    @staticmethod
    def _tool(call_id, name, arguments):
        tool = MagicMock()
        tool.id = call_id
        tool.function = MagicMock()
        tool.function.name = name
        tool.function.arguments = arguments
        return tool

    def test_non_stream_keeps_every_call(self, provider):
        response = MagicMock()
        response.message.content = []
        response.message.tool_plan = "Using two tools"
        response.message.tool_calls = [
            self._tool("call_a", "get_weather", '{"city": "Paris"}'),
            self._tool("call_b", "get_time", '{"tz": "UTC"}'),
        ]

        responses = list(provider._handle_normal_response(response))

        calls = _collect_calls(responses)
        assert [call.id for call in calls] == ["call_a", "call_b"]
        assert [call.name for call in calls] == ["get_weather", "get_time"]

    def test_stream_keeps_every_call(self, provider):
        def tool_events(call_id, name, arguments):
            start = MagicMock()
            start.type = "tool-call-start"
            start.delta.message.tool_calls = MagicMock()
            start.delta.message.tool_calls.id = call_id
            start.delta.message.tool_calls.function.name = name
            start.delta.message.tool_calls.function.arguments = ""
            delta = MagicMock()
            delta.type = "tool-call-delta"
            delta.delta.message.tool_calls.function.arguments = arguments
            end = MagicMock()
            end.type = "tool-call-end"
            return [start, delta, end]

        events = tool_events("call_a", "get_weather", '{"city": "Paris"}')
        events += tool_events("call_b", "get_time", '{"tz": "UTC"}')

        calls = _collect_calls(list(provider._handle_streaming_response(events)))

        assert [call.id for call in calls] == ["call_a", "call_b"]
        assert calls[1].arguments == '{"tz": "UTC"}'


# ---------------------------------------------------------------------------
# End-to-end: the client executes every call carried by one response
# ---------------------------------------------------------------------------


class ScriptedMultiCallProvider(Provider):
    """Provider double returning one batch of responses per invocation."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = 0
        self.config = {"ENABLE_FUNCTIONS": True, "ENABLE_MCP": False}
        self.enable_function = True
        self.enable_mcp = False

    def completion(self, messages, stream=False, tool_policy=None):
        self.calls += 1
        batch = self.batches.pop(0) if self.batches else [LLMResponse(content="done", finish_reason="stop")]
        yield from batch

    def detect_tool_role(self):
        return "tool"


class TestClientMultiCallTurns:
    @pytest.fixture
    def mock_config(self):
        return _config(ENABLE_FUNCTIONS=True, ENABLE_MCP=False)

    @patch("yaicli.llms.client.execute_tool_call")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_one_response_with_two_calls_executes_both(self, mock_factory, mock_execute_tool, mock_config):
        """A single provider response carrying two calls must execute both."""
        first = ToolCall(id="call_a", name="fs_read_file", arguments='{"path": "a.txt"}')
        second = ToolCall(id="call_b", name="fs_read_file", arguments='{"path": "b.txt"}')
        provider = ScriptedMultiCallProvider(
            [
                [LLMResponse(content="Reading both files", finish_reason="tool_calls", tool_calls=[first, second])],
                [LLMResponse(content="Both files read", finish_reason="stop")],
            ]
        )
        mock_factory.return_value = provider
        mock_execute_tool.side_effect = lambda tool_call, announce=True: (f"result-{tool_call.id}", True)

        client = LLMClient(provider_name="openai", config=mock_config)
        messages = [ChatMessage(role="user", content="read a.txt and b.txt")]
        responses = list(client.completion_with_tools(messages, stream=False))

        assert mock_execute_tool.call_count == 2
        assert [call.args[0].id for call in mock_execute_tool.call_args_list] == ["call_a", "call_b"]

        assistant = [message for message in messages if message.role == "assistant"][0]
        assert [call.id for call in assistant.tool_calls] == ["call_a", "call_b"]

        tool_messages = [message for message in messages if message.role == "tool"]
        assert [message.tool_call_id for message in tool_messages] == ["call_a", "call_b"]
        assert [message.content for message in tool_messages] == ["result-call_a", "result-call_b"]

        assert any(getattr(response, "content", "") == "Both files read" for response in responses)

    @patch("yaicli.llms.client.execute_tool_call")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_repeated_stream_snapshots_are_executed_once(self, mock_factory, mock_execute_tool, mock_config):
        """Streaming providers may repeat a call snapshot; the client dedupes by id."""
        call = ToolCall(id="call_a", name="fs_read_file", arguments='{"path": "a.txt"}')
        provider = ScriptedMultiCallProvider(
            [
                [
                    LLMResponse(content="Reading", finish_reason=None, tool_calls=[call]),
                    LLMResponse(content="", finish_reason="tool_calls", tool_calls=[call]),
                ],
                [LLMResponse(content="done", finish_reason="stop")],
            ]
        )
        mock_factory.return_value = provider
        mock_execute_tool.return_value = ("result", True)

        client = LLMClient(provider_name="openai", config=mock_config)
        list(client.completion_with_tools([ChatMessage(role="user", content="go")], stream=True))

        assert mock_execute_tool.call_count == 1

    @patch("yaicli.llms.client.execute_tool_call")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_calls_are_filtered_by_tool_policy_but_order_is_kept(
        self, mock_factory, mock_execute_tool, mock_config
    ):
        """Filtering must not reorder or drop the allowed calls."""
        allowed = ToolCall(id="call_a", name="fs_read_file", arguments="{}")
        mcp = ToolCall(id="call_b", name="_mcp__clock", arguments="{}")
        provider = ScriptedMultiCallProvider(
            [
                [LLMResponse(finish_reason="tool_calls", tool_calls=[allowed, mcp])],
                [LLMResponse(content="done", finish_reason="stop")],
            ]
        )
        mock_factory.return_value = provider
        mock_execute_tool.return_value = ("ok", True)

        client = LLMClient(provider_name="openai", config=mock_config)
        list(client.completion_with_tools([ChatMessage(role="user", content="go")], tool_policy=ToolPolicy(True, False)))

        assert [call.args[0].id for call in mock_execute_tool.call_args_list] == ["call_a"]
