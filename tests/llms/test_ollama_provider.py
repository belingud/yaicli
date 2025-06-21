from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.ollama_provider import OllamaProvider
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall


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
            "THINK": "false",
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
        assert provider.completion_params["model"] == mock_config["MODEL"]
        assert provider.completion_params["temperature"] == mock_config["TEMPERATURE"]
        assert provider.completion_params["top_p"] == mock_config["TOP_P"]
        assert provider.completion_params["num_predict"] == mock_config["MAX_TOKENS"]
        assert provider.completion_params["timeout"] == mock_config["TIMEOUT"]
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

        responses = list(provider._handle_normal_response(mock_response))
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

        responses = list(provider._handle_normal_response(mock_response))
        assert len(responses) == 1
        assert responses[0].content == "I'll check that"
        assert responses[0].tool_call is not None
        assert responses[0].tool_call.name == "get_weather"
        assert responses[0].tool_call.arguments == '{"location": "New York"}'

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
        responses = list(provider._handle_stream_response([chunk1, chunk2, chunk3]))

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
