from unittest.mock import MagicMock, patch

import httpx
import pytest

from yaicli.errors import AgentError, ErrorKind
from yaicli.llms.providers.ollama_provider import OllamaProvider
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall, ToolPolicy
from yaicli.usage import Usage


def _http_error(status: int, message: str = "boom") -> httpx.HTTPStatusError:
    """Build an httpx status error the way the Ollama SDK/HTTP layer would."""
    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    response = httpx.Response(status, json={"error": message}, request=request)
    return httpx.HTTPStatusError(message, request=request, response=response)


class TestOllamaProvider:
    """Tests for the Ollama provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "BASE_URL": "http://localhost:11434",
            "MODEL": "llama3",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            "THINK": "false",
            "FREQUENCY_PENALTY": 0.0,
        }

    @pytest.fixture
    def mock_client(self):
        """Fixture to create a mock Ollama client"""
        with patch("ollama.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            yield mock_client

    def test_init(self, mock_config):
        """Test initialization of OllamaProvider"""
        provider = OllamaProvider(config=mock_config)

        # Check initialization parameters
        assert provider.host == mock_config["BASE_URL"]
        assert provider.enable_function == mock_config["ENABLE_FUNCTIONS"]
        assert provider.think is False  # Based on "THINK": "false"

    def test_detect_tool_role(self, mock_config):
        """Test detect_tool_role method"""
        provider = OllamaProvider(config=mock_config)
        assert provider.detect_tool_role() == "tool"

    def test_convert_messages(self, mock_config):
        """Test message conversion for Ollama format"""
        provider = OllamaProvider(config=mock_config)

        # Test basic message conversion
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there"),
        ]

        converted = provider._convert_messages(messages)
        assert len(converted) == 2
        assert converted[0]["role"] == "user"
        assert converted[0]["content"] == "Hello"
        assert converted[1]["role"] == "assistant"
        assert converted[1]["content"] == "Hi there"

        # Test with tool calls
        tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')
        messages = [ChatMessage(role="assistant", content=None, tool_calls=[tool_call])]

        converted = provider._convert_messages(messages)
        assert len(converted) == 1
        assert converted[0]["role"] == "assistant"
        assert "tool_calls" in converted[0]
        assert len(converted[0]["tool_calls"]) == 1
        assert converted[0]["tool_calls"][0]["id"] == "call_123"
        assert converted[0]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert converted[0]["tool_calls"][0]["function"]["arguments"] == {"location": "New York"}

        # Test with tool responses
        messages = [ChatMessage(role="tool", content="Sunny, 25°C", tool_call_id="call_123")]

        converted = provider._convert_messages(messages)
        assert len(converted) == 1
        assert converted[0]["role"] == "tool"
        assert converted[0]["content"] == "Sunny, 25°C"
        assert converted[0]["tool_call_id"] == "call_123"

        # Test with user message and name
        messages = [ChatMessage(role="user", content="Hello", name="John")]

        converted = provider._convert_messages(messages)
        assert len(converted) == 1
        assert converted[0]["role"] == "user"
        assert converted[0]["content"] == "Hello"
        assert converted[0]["name"] == "John"

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_non_streaming(self, mock_get_schemas, mock_config, mock_client):
        """Test non-streaming completion request"""
        # Setup mock tools
        mock_tools = [{"type": "function", "function": {"name": "test_func"}}]
        mock_get_schemas.return_value = mock_tools

        # Setup mock response
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Test response"
        mock_message.thinking = None
        mock_message.tool_calls = None
        mock_response.message = mock_message

        mock_client.chat.return_value = mock_response

        # Create provider and call completion
        provider = OllamaProvider(config=mock_config)

        # Call completion with mocked response handling
        with patch.object(provider, "_handle_normal_response", return_value=[LLMResponse(content="Test response")]):
            with patch.object(provider, "enable_function", True):  # Ensure functions are enabled
                messages = [ChatMessage(role="user", content="Hello")]
                responses = list(provider.completion(messages, stream=False))

                # Verify API call
                mock_client.chat.assert_called_once()
                call_kwargs = mock_client.chat.call_args.kwargs

                assert call_kwargs["model"] == mock_config["MODEL"]
                assert call_kwargs["messages"] == provider._convert_messages(messages)
                assert call_kwargs["stream"] is False
                assert call_kwargs["options"]["temperature"] == mock_config["TEMPERATURE"]

                # Don't directly compare tools, just verify it was called with some tools
                assert "tools" in call_kwargs

                # Verify response
                assert len(responses) == 1
                assert responses[0].content == "Test response"

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_request_tool_policy_disables_tools(self, mock_get_schemas, mock_config, mock_client):
        """Test request-scoped policy suppresses Ollama tools for a single request."""
        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "test_func"}}]

        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Test response"
        mock_message.thinking = None
        mock_message.tool_calls = None
        mock_response.message = mock_message
        mock_client.chat.return_value = mock_response

        provider = OllamaProvider(config=mock_config)

        with patch.object(provider, "_handle_normal_response", return_value=[LLMResponse(content="Test response")]):
            messages = [ChatMessage(role="user", content="Hello")]
            list(provider.completion(messages, stream=False, tool_policy=ToolPolicy(False, False)))

        call_kwargs = mock_client.chat.call_args.kwargs
        assert "tools" not in call_kwargs

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_with_tool_call(self, mock_get_schemas, mock_config, mock_client):
        """Test completion with tool call response"""
        # Setup mock tools
        mock_tools = [{"type": "function", "function": {"name": "get_weather"}}]
        mock_get_schemas.return_value = mock_tools

        # Setup mock response with tool call
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Let me check the weather"
        mock_message.thinking = "I should use the weather tool"

        # Mock tool call in response
        mock_tool_call = {
            "id": "call_123",
            "type": "function",
            "function": {"name": "get_weather", "arguments": {"location": "New York"}},
        }
        mock_message.tool_calls = [mock_tool_call]
        mock_response.message = mock_message

        mock_client.chat.return_value = mock_response

        # Create provider and call completion
        provider = OllamaProvider(config=mock_config)

        # Mock response handler to provide controlled output
        with patch.object(
            provider,
            "_handle_normal_response",
            return_value=[
                LLMResponse(
                    content="Let me check the weather",
                    reasoning="I should use the weather tool",
                    tool_call=ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}'),
                )
            ],
        ):
            messages = [ChatMessage(role="user", content="What's the weather in New York?")]
            responses = list(provider.completion(messages, stream=False))

            # Verify responses
            assert len(responses) == 1
            assert responses[0].content == "Let me check the weather"
            assert responses[0].reasoning == "I should use the weather tool"
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.id == "call_123"
            assert responses[0].tool_call.name == "get_weather"
            assert responses[0].tool_call.arguments == '{"location": "New York"}'

    @patch("yaicli.tools.get_openai_schemas")
    def test_handle_normal_response(self, mock_get_schemas, mock_config):
        """Test handling of non-streaming response"""
        # Create provider
        provider = OllamaProvider(config=mock_config)

        # Test normal text response
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Hello, world!"
        mock_message.thinking = "Thinking process"
        mock_message.tool_calls = None
        mock_response.message = mock_message

        responses = list(provider._handle_normal_response(mock_response, tool_calls_enabled=True))
        assert len(responses) == 1
        assert responses[0].content == "Hello, world!"
        assert responses[0].reasoning == "Thinking process"
        assert responses[0].tool_call is None

        # Test response with tool call
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "I'll check that"
        mock_message.thinking = None
        mock_tool_call = {"id": "tc_123", "function": {"name": "get_weather", "arguments": {"location": "New York"}}}
        mock_message.tool_calls = [mock_tool_call]
        mock_response.message = mock_message

        responses = list(provider._handle_normal_response(mock_response, tool_calls_enabled=True))
        assert len(responses) == 1
        assert responses[0].content == "I'll check that"
        assert responses[0].tool_call is not None
        assert responses[0].tool_call.name == "get_weather"
        assert responses[0].tool_call.arguments == '{"location": "New York"}'

        responses = list(provider._handle_normal_response(mock_response, tool_calls_enabled=False))
        assert responses[0].tool_call is None

    @patch("yaicli.tools.get_openai_schemas")
    def test_handle_stream_response(self, mock_get_schemas, mock_config):
        """Test handling of streaming response"""
        # Create provider
        provider = OllamaProvider(config=mock_config)

        # Create mock stream chunks
        chunk1 = MagicMock()
        chunk1.message.content = "Hello"
        chunk1.message.thinking = "Let me think"
        chunk1.message.tool_calls = None

        chunk2 = MagicMock()
        chunk2.message.content = " world"
        chunk2.message.thinking = ""
        chunk2.message.tool_calls = None

        chunk3 = MagicMock()
        chunk3.message.content = "!"
        chunk3.message.thinking = ""
        tool_call = {"id": "tc_123", "function": {"name": "get_weather", "arguments": {"location": "New York"}}}
        chunk3.message.tool_calls = [tool_call]

        # Process events
        responses = list(provider._handle_stream_response([chunk1, chunk2, chunk3], tool_calls_enabled=True))

        # We should have 3 content chunks and 1 tool call
        assert len(responses) == 4
        assert responses[0].content == "Hello"
        assert responses[0].reasoning == "Let me think"
        assert responses[1].content == " world"
        assert responses[2].content == "!"

        # The final response should be the tool call
        assert responses[3].tool_call is not None
        assert responses[3].tool_call.name == "get_weather"
        assert responses[3].tool_call.arguments == '{"location": "New York"}'

    @patch("yaicli.llms.providers.ollama_provider.get_openai_schemas", return_value=[])
    def test_completion_api_error_raises_classified(self, mock_get_schemas, mock_config, mock_client):
        """An Ollama API error must raise a classified AgentError, never assistant content."""
        mock_client.chat.side_effect = _http_error(429)

        provider = OllamaProvider(config=mock_config)
        with pytest.raises(AgentError) as excinfo:
            list(provider.completion([ChatMessage(role="user", content="hi")], stream=False))

        assert excinfo.value.kind is ErrorKind.RATE_LIMIT
        assert excinfo.value.status_code == 429
        assert excinfo.value.retryable is True
        assert "Ollama API error" in str(excinfo.value)

    @patch("yaicli.llms.providers.ollama_provider.get_openai_schemas", return_value=[])
    def test_completion_error_does_not_write_assistant_history_content(
        self, mock_get_schemas, mock_config, mock_client
    ):
        """Regression: the error text is never yielded as an assistant message."""
        mock_client.chat.side_effect = RuntimeError("model not found")

        provider = OllamaProvider(config=mock_config)
        collected = []
        with pytest.raises(AgentError):
            for response in provider.completion([ChatMessage(role="user", content="hi")], stream=False):
                collected.append(response)

        assert collected == []

    @patch("yaicli.llms.providers.ollama_provider.get_openai_schemas", return_value=[])
    def test_completion_stream_midstream_error_raises_classified(self, mock_get_schemas, mock_config, mock_client):
        """A stream that breaks mid-iteration is surfaced as a classified timeout."""

        def broken_stream():
            chunk = MagicMock()
            chunk.message.content = "partial"
            chunk.message.thinking = None
            chunk.message.tool_calls = None
            yield chunk
            raise httpx.ReadTimeout("read timed out")

        mock_client.chat.return_value = broken_stream()

        provider = OllamaProvider(config=mock_config)
        collected = []
        with pytest.raises(AgentError) as excinfo:
            for response in provider.completion([ChatMessage(role="user", content="hi")], stream=True):
                collected.append(response)

        assert [r.content for r in collected] == ["partial"]
        assert excinfo.value.kind is ErrorKind.TIMEOUT
        assert excinfo.value.retryable is True


class TestOllamaUsage:
    """v0.22 K17: Ollama ``prompt_eval_count``/``eval_count`` reaches LLMResponse."""

    @pytest.fixture
    def mock_config(self):
        return {
            "BASE_URL": "http://localhost:11434",
            "MODEL": "llama3",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
            "THINK": "false",
            "FREQUENCY_PENALTY": 0.0,
        }

    def _provider(self, config):
        with patch("ollama.Client", return_value=MagicMock()):
            return OllamaProvider(config=config)

    @staticmethod
    def _chunk(content="", thinking="", tool_calls=None, prompt_eval_count=None, eval_count=None):
        chunk = MagicMock()
        chunk.message.content = content
        chunk.message.thinking = thinking
        chunk.message.tool_calls = tool_calls
        chunk.prompt_eval_count = prompt_eval_count
        chunk.eval_count = eval_count
        return chunk

    def test_non_stream_usage_attached(self, mock_config):
        provider = self._provider(mock_config)
        response = MagicMock()
        response.message.content = "hi"
        response.message.thinking = ""
        response.message.tool_calls = None
        response.prompt_eval_count = 9
        response.eval_count = 4

        responses = list(provider._handle_normal_response(response, tool_calls_enabled=False))

        assert len(responses) == 1
        assert responses[0].usage == Usage(9, 4, 13)

    def test_stream_usage_terminal_response(self, mock_config):
        provider = self._provider(mock_config)
        chunks = [
            self._chunk(content="hi"),
            self._chunk(prompt_eval_count=9, eval_count=4),
        ]

        responses = list(provider._handle_stream_response(chunks, tool_calls_enabled=False))

        assert responses[0].content == "hi"
        assert responses[-1].usage == Usage(9, 4, 13)

    def test_stream_usage_attached_to_tool_call_response(self, mock_config):
        provider = self._provider(mock_config)
        tool_call = {"id": "tc_1", "function": {"name": "fs_read_file", "arguments": {"path": "a.txt"}}}
        chunks = [self._chunk(tool_calls=[tool_call], prompt_eval_count=5, eval_count=6)]

        responses = list(provider._handle_stream_response(chunks, tool_calls_enabled=True))

        assert len(responses) == 1
        assert responses[0].tool_call is not None
        assert responses[0].usage == Usage(5, 6, 11)


# ---------------------------------------------------------------------------
# v0.23 K22: provider metadata hook
# ---------------------------------------------------------------------------


class TestOllamaModelLimits:
    """``OllamaProvider.model_limits`` reads ``/api/show``'s ``model_info``."""

    @pytest.fixture
    def provider(self):
        config = {
            "BASE_URL": "http://localhost:11434",
            "MODEL": "llama3",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
            "THINK": "false",
            "FREQUENCY_PENALTY": 0.0,
            "NUM_CTX": 4096,
        }
        with patch("ollama.Client") as client_cls:
            mock_client = MagicMock()
            client_cls.return_value = mock_client
            provider = OllamaProvider(config=config)
        return provider

    def test_returns_largest_context_length_from_model_info(self, provider):
        info = MagicMock()
        info.model_info = {
            "general.architecture": "llama",
            "llama.context_length": 32768,
            "llama.rope.scaling.original_context_length": 8192,
            "some.other.context_length": 16384,
        }
        provider.client.show.return_value = info

        limits = provider.model_limits("qwen2.5:7b")

        assert limits is not None
        assert limits.window == 32768
        assert limits.source == "metadata"
        assert limits.detail == "ollama /api/show"
        provider.client.show.assert_called_once_with("qwen2.5:7b")

    def test_num_ctx_is_ignored(self, provider):
        """User decision (K22): only model metadata is authoritative, not NUM_CTX."""
        info = MagicMock()
        info.model_info = {"llama.context_length": 8192}
        provider.client.show.return_value = info

        assert provider.model_limits("llama3").window == 8192  # not the config NUM_CTX 4096

    def test_ignores_non_positive_and_non_numeric_values(self, provider):
        info = MagicMock()
        info.model_info = {
            "zero.context_length": 0,
            "negative.context_length": -1,
            "text.context_length": "not-a-number",
            "ok.context_length": "131072",
        }
        provider.client.show.return_value = info

        assert provider.model_limits("llama3").window == 131072

    def test_no_usable_context_length_returns_none(self, provider):
        info = MagicMock()
        info.model_info = {"general.architecture": "llama", "zero.context_length": 0}
        provider.client.show.return_value = info

        assert provider.model_limits("llama3") is None

    def test_missing_model_info_returns_none(self, provider):
        info = MagicMock()
        info.model_info = None
        provider.client.show.return_value = info

        assert provider.model_limits("llama3") is None

    def test_show_failure_returns_none_silently(self, provider, capsys):
        provider.client.show.side_effect = RuntimeError("connection refused")

        assert provider.model_limits("llama3") is None
        assert capsys.readouterr().err == ""

    def test_empty_model_returns_none_without_probe(self, provider):
        assert provider.model_limits("") is None
        provider.client.show.assert_not_called()

    def test_no_provider_side_caching(self, provider):
        info = MagicMock()
        info.model_info = {"llama.context_length": 8192}
        provider.client.show.return_value = info

        first = provider.model_limits("llama3")
        second = provider.model_limits("llama3")

        assert first == second
        assert provider.client.show.call_count == 2
