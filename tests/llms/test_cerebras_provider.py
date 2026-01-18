from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.cerebras_provider import CerebrasProvider
from yaicli.schemas import ChatMessage


class TestCerebrasProvider:
    """Test the Cerebras provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://custom.cerebras.api.com/v1",
            "MODEL": "llama3.1-70b",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            "FREQUENCY_PENALTY": 0.0,
        }

    @pytest.fixture
    def mock_cerebras_client(self):
        """Create a properly mocked Cerebras client"""
        chat_mock = MagicMock()
        completions_mock = MagicMock()
        completions_mock.create = MagicMock()
        chat_mock.completions = completions_mock

        client_mock = MagicMock()
        client_mock.chat = chat_mock

        return client_mock

    def test_init_default_base_url(self):
        """Test initialization with default BASE_URL"""
        config = {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "llama3.1-70b",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=config)

            # Check default base URL is used
            assert provider.client_params["base_url"] == CerebrasProvider.DEFAULT_BASE_URL
            assert provider.client_params["base_url"] == "https://api.cerebras.ai"
            assert provider.client_params["api_key"] == config["API_KEY"]

    def test_init_custom_base_url(self, mock_config):
        """Test initialization with custom BASE_URL"""
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)

            # Check custom base URL is used
            assert provider.client_params["base_url"] == mock_config["BASE_URL"]
            assert provider.client_params["api_key"] == mock_config["API_KEY"]

    def test_init_client_params(self, mock_config):
        """Test initialization of client parameters"""
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)

            # Check warm_tcp_connection is set to False
            assert provider.client_params["warm_tcp_connection"] is False

            # Check other client params
            expected_client_params = {
                "api_key": mock_config["API_KEY"],
                "base_url": mock_config["BASE_URL"],
                "warm_tcp_connection": False,
                "default_headers": {
                    "X-Title": provider.APP_NAME,
                    "HTTP_Referer": provider.APP_REFERER,
                },
            }
            assert provider.client_params == expected_client_params

    def test_init_completion_params(self, mock_config):
        """Test initialization of completion parameters"""
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)

            # Check completion params mapping
            expected_completion_params = {
                "model": mock_config["MODEL"],
                "temperature": mock_config["TEMPERATURE"],
                "top_p": mock_config["TOP_P"],
                "max_completion_tokens": mock_config["MAX_TOKENS"],
                "timeout": mock_config["TIMEOUT"],
            }
            assert provider.completion_params == expected_completion_params

    def test_init_with_extra_headers(self, mock_config):
        """Test initialization with extra headers"""
        extra_headers = {"X-Custom": "test"}
        mock_config["EXTRA_HEADERS"] = extra_headers

        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)

            # Check headers were properly merged
            assert provider.client_params["default_headers"] == {
                **extra_headers,
                "X-Title": provider.APP_NAME,
                "HTTP_Referer": provider.APP_REFERER,
            }

    def test_init_with_extra_body(self, mock_config):
        """Test initialization with extra body parameters"""
        extra_body = {"foo": "bar"}
        mock_config["EXTRA_BODY"] = extra_body

        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)

            # Check extra_body was properly set
            assert provider.completion_params["extra_body"] == extra_body

    def test_client_class(self, mock_config):
        """Test that the correct client class is used"""
        with patch.object(CerebrasProvider, "CLIENT_CLS") as mock_cerebras:
            mock_client_instance = MagicMock()
            mock_cerebras.return_value = mock_client_instance

            provider = CerebrasProvider(config=mock_config)

            # Verify Cerebras client class is used
            assert provider.CLIENT_CLS == mock_cerebras
            # Verify client was instantiated during initialization
            mock_cerebras.assert_called_once_with(**provider.client_params)

    def test_completion_params_keys_mapping(self, mock_config):
        """Test completion parameters keys mapping"""
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)

            # Check the mapping is correct
            expected_mapping = {
                "model": "MODEL",
                "temperature": "TEMPERATURE",
                "top_p": "TOP_P",
                "max_completion_tokens": "MAX_TOKENS",
                "timeout": "TIMEOUT",
                "extra_body": "EXTRA_BODY",
            }
            assert provider.COMPLETION_PARAMS_KEYS == expected_mapping

    def test_convert_messages(self, mock_config):
        """Test message conversion functionality inherited from OpenAIProvider"""
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)

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

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_non_streaming(self, mock_get_schemas, mock_config, mock_cerebras_client):
        """Test non-streaming completion request"""
        # Setup mock schemas
        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "test_func"}}]

        # Setup mock response
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Test response from Cerebras"
        mock_message.reasoning_content = None
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]

        # Configure mock client to return our response
        mock_cerebras_client.chat.completions.create.return_value = mock_response

        # Create provider with mocked Cerebras client
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)
            # Replace the real client with our mock
            provider.client = mock_cerebras_client

            # Call completion
            messages = [ChatMessage(role="user", content="Hello")]
            responses = list(provider.completion(messages, stream=False))

            # Verify API call
            mock_cerebras_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_cerebras_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["messages"] == [{"role": "user", "content": "Hello"}]
            assert call_kwargs["stream"] is False
            assert "tools" in call_kwargs

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "Test response from Cerebras"
            assert responses[0].finish_reason == "stop"
            assert responses[0].tool_call is None

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_tool_call(self, mock_get_schemas, mock_config, mock_cerebras_client):
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
        mock_cerebras_client.chat.completions.create.return_value = mock_response

        # Create provider with mocked Cerebras client
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)
            # Replace the real client with our mock
            provider.client = mock_cerebras_client

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

    def test_detect_tool_role(self, mock_config):
        """Test detect_tool_role method inherited from OpenAIProvider"""
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)
            assert provider.detect_tool_role() == "tool"

    def test_inheritance_from_openai_provider(self, mock_config):
        """Test that CerebrasProvider correctly inherits from OpenAIProvider"""
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)

            # Check that it inherits from OpenAIProvider
            from yaicli.llms.providers.openai_provider import OpenAIProvider

            assert isinstance(provider, OpenAIProvider)

            # Check that specific methods are available
            assert hasattr(provider, "_convert_messages")
            assert hasattr(provider, "completion")
            assert hasattr(provider, "detect_tool_role")

    def test_get_client_params_override(self, mock_config):
        """Test that get_client_params method correctly overrides parent implementation"""
        with patch("cerebras.cloud.sdk.Cerebras"):
            provider = CerebrasProvider(config=mock_config)

            # Get client params
            client_params = provider.get_client_params()

            # Verify warm_tcp_connection is specifically set to False
            assert "warm_tcp_connection" in client_params
            assert client_params["warm_tcp_connection"] is False

            # Verify other params are still present
            assert "api_key" in client_params
            assert "base_url" in client_params
            assert "default_headers" in client_params

    def test_minimal_config(self):
        """Test provider with minimal configuration"""
        minimal_config = {
            "API_KEY": "test_key",
            "MODEL": "llama3.1-8b",
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

        with patch("yaicli.llms.providers.cerebras_provider.Cerebras"):
            provider = CerebrasProvider(config=minimal_config)

            # Should use defaults for missing values
            assert provider.client_params["base_url"] == CerebrasProvider.DEFAULT_BASE_URL
            assert provider.client_params["warm_tcp_connection"] is False
            assert provider.completion_params["model"] == minimal_config["MODEL"]
