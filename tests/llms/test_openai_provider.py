from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.openai_provider import OpenAIProvider
from yaicli.schemas import ChatMessage, ToolCall


class TestOpenAIProvider:
    """Test the OpenAI provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://fake-api.openai.com/v1",
            "MODEL": "gpt-4",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def mock_openai_client(self):
        """Create a properly mocked OpenAI client"""
        chat_mock = MagicMock()
        completions_mock = MagicMock()
        completions_mock.create = MagicMock()
        chat_mock.completions = completions_mock

        client_mock = MagicMock()
        client_mock.chat = chat_mock

        return client_mock

    def test_init(self, mock_config):
        """Test initialization of OpenAIProvider"""
        # Create a mock for OpenAI client class
        with patch("openai.OpenAI"):
            # Create provider
            provider = OpenAIProvider(config=mock_config)

            # Check initialization of client params
            assert provider.client_params == {
                "api_key": mock_config["API_KEY"],
                "base_url": mock_config["BASE_URL"],
                "default_headers": {
                    "X-Title": provider.APP_NAME,
                    "HTTP_Referer": provider.APP_REFERER,
                }
            }

            # Check initialization of completion params
            assert provider.completion_params == {
                "model": mock_config["MODEL"],
                "temperature": mock_config["TEMPERATURE"],
                "top_p": mock_config["TOP_P"],
                "max_completion_tokens": mock_config["MAX_TOKENS"],
                "timeout": mock_config["TIMEOUT"],
            }

    def test_init_with_extra_headers(self, mock_config):
        """Test initialization with extra headers"""
        extra_headers = {"X-Custom": "test"}
        mock_config["EXTRA_HEADERS"] = extra_headers

        with patch("openai.OpenAI"):
            provider = OpenAIProvider(config=mock_config)

            # Check headers were properly set
            assert provider.client_params["default_headers"] == {
                **extra_headers,
                "X-Title": provider.APP_NAME,
                "HTTP_Referer": provider.APP_REFERER,
            }

    def test_init_with_extra_body(self, mock_config):
        """Test initialization with extra body parameters"""
        extra_body = {"foo": "bar"}
        mock_config["EXTRA_BODY"] = extra_body

        with patch("openai.OpenAI"):
            provider = OpenAIProvider(config=mock_config)

            # Check extra_body was properly set
            assert provider.completion_params["extra_body"] == extra_body

    def test_convert_messages(self, mock_config):
        """Test message conversion"""
        # Create provider with OpenAI mocked
        with patch("openai.OpenAI"):
            provider = OpenAIProvider(config=mock_config)

            # Test basic message conversion
            messages = [
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi there"),
            ]

            expected = [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ]

            assert provider._convert_messages(messages) == expected

            # Test message with name
            messages = [ChatMessage(role="user", content="Hello", name="John")]
            expected = [{"role": "user", "content": "Hello", "name": "John"}]

            assert provider._convert_messages(messages) == expected

            # Test message with tool calls
            tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')
            messages = [ChatMessage(role="assistant", content="Let me check the weather", tool_calls=[tool_call])]

            converted = provider._convert_messages(messages)
            assert converted[0]["role"] == "assistant"
            assert converted[0]["content"] == "Let me check the weather"
            assert converted[0]["tool_calls"][0]["id"] == "call_123"
            assert converted[0]["tool_calls"][0]["type"] == "function"
            assert converted[0]["tool_calls"][0]["function"]["name"] == "get_weather"
            assert converted[0]["tool_calls"][0]["function"]["arguments"] == '{"location": "New York"}'

            # Test tool message with tool_call_id
            messages = [ChatMessage(role="tool", content="The weather is sunny", tool_call_id="call_123")]
            expected = [{"role": "tool", "content": "The weather is sunny", "tool_call_id": "call_123"}]

            assert provider._convert_messages(messages) == expected

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_non_streaming(self, mock_get_schemas, mock_config, mock_openai_client):
        """Test non-streaming completion request"""
        # Setup mock schemas
        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "test_func"}}]

        # Setup mock response
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Test response"
        mock_message.reasoning_content = None
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]

        # Configure mock client to return our response
        mock_openai_client.chat.completions.create.return_value = mock_response

        # Create provider with mocked OpenAI
        with patch("openai.OpenAI"):
            provider = OpenAIProvider(config=mock_config)
            # Replace the real client with our mock
            provider.client = mock_openai_client

            # Call completion
            messages = [ChatMessage(role="user", content="Hello")]
            responses = list(provider.completion(messages, stream=False))

            # Verify API call
            mock_openai_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["messages"] == [{"role": "user", "content": "Hello"}]
            assert call_kwargs["stream"] is False
            assert "tools" in call_kwargs

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "Test response"
            assert responses[0].finish_reason == "stop"
            assert responses[0].tool_call is None

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_tool_call(self, mock_get_schemas, mock_config, mock_openai_client):
        """Test completion with tool call response"""
        # Setup mock schemas
        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "get_weather"}}]

        # Setup mock response with tool call
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Let me check the weather"
        mock_message.reasoning_content = None

        # Mock tool call
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "get_weather"
        mock_tool_call.function.arguments = '{"location": "New York"}'
        mock_message.tool_calls = [mock_tool_call]

        mock_choice.message = mock_message
        mock_choice.finish_reason = "tool_calls"
        mock_response.choices = [mock_choice]

        # Configure mock client to return our response
        mock_openai_client.chat.completions.create.return_value = mock_response

        # Create provider with mocked OpenAI
        with patch("openai.OpenAI"):
            provider = OpenAIProvider(config=mock_config)
            # Replace the real client with our mock
            provider.client = mock_openai_client

            # Call completion
            messages = [ChatMessage(role="user", content="What's the weather in New York?")]
            responses = list(provider.completion(messages, stream=False))

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "Let me check the weather"
            assert responses[0].finish_reason == "tool_calls"
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.id == "call_123"
            assert responses[0].tool_call.name == "get_weather"
            assert responses[0].tool_call.arguments == '{"location": "New York"}'

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_with_reasoning_content(self, mock_get_schemas, mock_config, mock_openai_client):
        """Test completion with reasoning content"""
        # Setup mock schemas
        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "test_func"}}]

        # Setup mock response with reasoning content
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Final answer"
        mock_message.reasoning_content = None
        mock_message.model_extra = {"reasoning_content": "This is my reasoning"}
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]

        # Configure mock client to return our response
        mock_openai_client.chat.completions.create.return_value = mock_response

        # Create provider with mocked OpenAI
        with patch("openai.OpenAI"):
            provider = OpenAIProvider(config=mock_config)
            # Replace the real client with our mock
            provider.client = mock_openai_client

            # Call completion
            messages = [ChatMessage(role="user", content="A complex question")]
            responses = list(provider.completion(messages, stream=False))

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "Final answer"
            assert responses[0].reasoning == "This is my reasoning"
            assert responses[0].finish_reason == "stop"

    def test_detect_tool_role(self, mock_config):
        """Test detect_tool_role method"""
        with patch("openai.OpenAI"):
            provider = OpenAIProvider(config=mock_config)
            assert provider.detect_tool_role() == "tool"
