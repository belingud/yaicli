from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.moonshot_provider import MoonshotProvider
from yaicli.schemas import ChatMessage, ToolCall


class TestMoonshotProvider:
    """Test the Moonshot provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_moonshot_api_key",
            "BASE_URL": "https://api.moonshot.cn/v1",
            "MODEL": "moonshot-v1-8k",
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
    def mock_config_minimal(self):
        """Fixture to create a minimal configuration"""
        return {
            "API_KEY": "fake_moonshot_api_key",
            "MODEL": "moonshot-v1-8k",
            "ENABLE_FUNCTIONS": False,
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
        """Test initialization of MoonshotProvider"""
        # Create a mock for OpenAI client class
        with patch("openai.OpenAI"):
            # Create provider
            provider = MoonshotProvider(config=mock_config)

            # Check initialization of client params
            assert provider.client_params == {
                "api_key": mock_config["API_KEY"],
                "base_url": mock_config["BASE_URL"],
                "default_headers": {
                    "X-Title": provider.APP_NAME,
                    "HTTP_Referer": provider.APP_REFERER,
                },
            }

            # Check initialization of completion params
            assert provider.completion_params == {
                "model": mock_config["MODEL"],
                "temperature": mock_config["TEMPERATURE"],
                "top_p": mock_config["TOP_P"],
                "max_tokens": mock_config["MAX_TOKENS"],
                "timeout": mock_config["TIMEOUT"],
            }

    def test_init_with_default_base_url(self, mock_config):
        """Test initialization with default base URL"""
        mock_config["BASE_URL"] = None  # Set to None instead of removing the key

        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)

            # Should use default Moonshot URL
            assert provider.client_params["base_url"] == MoonshotProvider.DEFAULT_BASE_URL

    def test_init_with_extra_headers(self, mock_config):
        """Test initialization with extra headers"""
        extra_headers = {"X-Custom": "test"}
        mock_config["EXTRA_HEADERS"] = extra_headers

        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)

            # Check headers were properly set
            assert provider.client_params["default_headers"] == {
                **extra_headers,
                "X-Title": provider.APP_NAME,
                "HTTP_Referer": provider.APP_REFERER,
            }

    def test_init_with_extra_body(self, mock_config):
        """Test initialization with extra body parameters"""
        extra_body = {"custom_param": "value"}
        mock_config["EXTRA_BODY"] = extra_body

        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)

            # Check extra_body was properly set
            assert provider.completion_params["extra_body"] == extra_body

    def test_init_without_api_key(self, mock_config):
        """Test error when API key is not provided"""
        mock_config.pop("API_KEY")

        with pytest.raises(ValueError, match="API_KEY is required"):
            MoonshotProvider(config=mock_config)

    def test_completion_params_keys(self, mock_config):
        """Test that completion params keys are properly mapped"""
        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)

            # Check that the provider uses the correct parameter mapping
            expected_keys = {
                "model": "MODEL",
                "temperature": "TEMPERATURE",
                "top_p": "TOP_P",
                "max_tokens": "MAX_TOKENS",
                "timeout": "TIMEOUT",
                "extra_body": "EXTRA_BODY",
            }
            assert provider.COMPLETION_PARAMS_KEYS == expected_keys

    def test_convert_messages(self, mock_config):
        """Test message conversion inherited from OpenAIProvider"""
        # Create provider with OpenAI mocked
        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)

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
            tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "Beijing"}')
            messages = [ChatMessage(role="assistant", content="Let me check the weather", tool_calls=[tool_call])]

            converted = provider._convert_messages(messages)
            assert converted[0]["role"] == "assistant"
            assert converted[0]["content"] == "Let me check the weather"
            assert converted[0]["tool_calls"][0]["id"] == "call_123"
            assert converted[0]["tool_calls"][0]["type"] == "function"
            assert converted[0]["tool_calls"][0]["function"]["name"] == "get_weather"
            assert converted[0]["tool_calls"][0]["function"]["arguments"] == '{"location": "Beijing"}'

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
        mock_message.content = "This is a response from Moonshot"
        mock_message.reasoning_content = None
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]

        # Configure mock client to return our response
        mock_openai_client.chat.completions.create.return_value = mock_response

        # Create provider with mocked OpenAI
        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)
            # Replace the real client with our mock
            provider.client = mock_openai_client

            # Call completion
            messages = [ChatMessage(role="user", content="Hello Moonshot")]
            responses = list(provider.completion(messages, stream=False))

            # Verify API call
            mock_openai_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["messages"] == [{"role": "user", "content": "Hello Moonshot"}]
            assert call_kwargs["stream"] is False
            assert "tools" in call_kwargs

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "This is a response from Moonshot"
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
        mock_message.content = "I'll check the weather for you"
        mock_message.reasoning_content = None

        # Mock tool call
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_456"
        mock_tool_call.function.name = "get_weather"
        mock_tool_call.function.arguments = '{"location": "Shanghai"}'
        mock_message.tool_calls = [mock_tool_call]

        mock_choice.message = mock_message
        mock_choice.finish_reason = "tool_calls"
        mock_response.choices = [mock_choice]

        # Configure mock client to return our response
        mock_openai_client.chat.completions.create.return_value = mock_response

        # Create provider with mocked OpenAI
        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)
            # Replace the real client with our mock
            provider.client = mock_openai_client

            # Call completion
            messages = [ChatMessage(role="user", content="What's the weather in Shanghai?")]
            responses = list(provider.completion(messages, stream=False))

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "I'll check the weather for you"
            assert responses[0].finish_reason == "tool_calls"
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.id == "call_456"
            assert responses[0].tool_call.name == "get_weather"
            assert responses[0].tool_call.arguments == '{"location": "Shanghai"}'

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_streaming(self, mock_get_schemas, mock_config, mock_openai_client):
        """Test streaming completion request"""
        # Setup mock schemas
        mock_get_schemas.return_value = []

        # Create mock streaming response
        mock_chunks = []

        # First chunk with content
        chunk1 = MagicMock()
        choice1 = MagicMock()
        delta1 = MagicMock()
        delta1.content = "Hello "
        delta1.tool_calls = None
        choice1.delta = delta1
        choice1.finish_reason = None
        chunk1.choices = [choice1]
        mock_chunks.append(chunk1)

        # Second chunk with more content
        chunk2 = MagicMock()
        choice2 = MagicMock()
        delta2 = MagicMock()
        delta2.content = "from Moonshot!"
        delta2.tool_calls = None
        choice2.delta = delta2
        choice2.finish_reason = "stop"
        chunk2.choices = [choice2]
        mock_chunks.append(chunk2)

        # Mock stream response
        mock_stream = MagicMock()
        mock_stream.__iter__ = lambda self: iter(mock_chunks)
        mock_openai_client.chat.completions.create.return_value = mock_stream

        # Create provider with mocked OpenAI
        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)
            # Replace the real client with our mock
            provider.client = mock_openai_client

            # Call streaming completion
            messages = [ChatMessage(role="user", content="Hello")]
            responses = list(provider.completion(messages, stream=True))

            # Verify API call
            mock_openai_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["stream"] is True

            # Verify streaming responses
            assert len(responses) == 2
            assert responses[0].content == "Hello "
            assert responses[0].finish_reason is None
            assert responses[1].content == "from Moonshot!"
            assert responses[1].finish_reason == "stop"

    def test_detect_tool_role(self, mock_config):
        """Test detect_tool_role method"""
        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)
            assert provider.detect_tool_role() == "tool"

    def test_inheritance_from_openai_provider(self, mock_config):
        """Test that MoonshotProvider correctly inherits from OpenAIProvider"""
        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)

            # Check that it's an instance of the expected classes
            from yaicli.llms.providers.openai_provider import OpenAIProvider

            assert isinstance(provider, OpenAIProvider)
            assert isinstance(provider, MoonshotProvider)

            # Check that it has the expected attributes and methods
            assert hasattr(provider, "completion")
            assert hasattr(provider, "_convert_messages")
            assert hasattr(provider, "detect_tool_role")
            assert hasattr(provider, "DEFAULT_BASE_URL")
            assert hasattr(provider, "COMPLETION_PARAMS_KEYS")

    def test_moonshot_specific_configuration(self, mock_config):
        """Test Moonshot-specific configuration values"""
        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)

            # Test Moonshot-specific defaults
            assert provider.DEFAULT_BASE_URL == "https://api.moonshot.cn/v1"

            # Test that the parameter mapping is appropriate for Moonshot
            expected_params = {
                "model": "MODEL",
                "temperature": "TEMPERATURE",
                "top_p": "TOP_P",
                "max_tokens": "MAX_TOKENS",
                "timeout": "TIMEOUT",
                "extra_body": "EXTRA_BODY",
            }
            assert provider.COMPLETION_PARAMS_KEYS == expected_params

    def test_verbose_mode(self, mock_config, mock_openai_client):
        """Test verbose mode functionality"""
        # Setup mock response
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Test response"
        mock_message.reasoning_content = None
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("openai.OpenAI"), patch("yaicli.tools.get_openai_schemas") as mock_schemas:
            mock_schemas.return_value = []

            # Create provider in verbose mode
            provider = MoonshotProvider(config=mock_config, verbose=True)
            provider.client = mock_openai_client

            # Mock console
            provider.console = MagicMock()

            # Call completion
            messages = [ChatMessage(role="user", content="Test")]
            list(provider.completion(messages, stream=False))

            # Verify verbose output was called
            provider.console.print.assert_called()

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_with_mcp_enabled_setting(self, mock_get_schemas, mock_config, mock_openai_client):
        """Test that MCP setting is properly configured"""
        mock_config["ENABLE_MCP"] = True
        mock_get_schemas.return_value = []

        # Setup mock response
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Response"
        mock_message.reasoning_content = None
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("yaicli.llms.providers.openai_provider.get_openai_mcp_tools") as mock_mcp_tools:
            mock_mcp_tools.return_value = []

            with patch("openai.OpenAI"):
                provider = MoonshotProvider(config=mock_config)
                provider.client = mock_openai_client

                # Verify MCP is enabled in the provider
                assert provider.enable_mcp is True

                # Call completion
                messages = [ChatMessage(role="user", content="Test")]
                list(provider.completion(messages, stream=False))

                # Verify the call was made
                mock_openai_client.chat.completions.create.assert_called_once()
                mock_mcp_tools.assert_called_once()

    def test_completion_with_disabled_functions(self, mock_config, mock_openai_client):
        """Test completion with functions disabled"""
        mock_config["ENABLE_FUNCTIONS"] = False
        mock_config["ENABLE_MCP"] = False

        # Setup mock response
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Response without tools"
        mock_message.reasoning_content = None
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("openai.OpenAI"):
            provider = MoonshotProvider(config=mock_config)
            provider.client = mock_openai_client

            # Call completion
            messages = [ChatMessage(role="user", content="Test without tools")]
            list(provider.completion(messages, stream=False))

            # Verify no tools were included
            call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
            assert "tools" not in call_kwargs or not call_kwargs.get("tools")
