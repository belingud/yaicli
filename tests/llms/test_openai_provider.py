from unittest.mock import MagicMock, patch

import pytest

from yaicli.exceptions import ProviderError
from yaicli.llms.providers.openai_provider import OpenAIAzure, OpenAIProvider
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
                },
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


class TestOpenAIAzure:
    """Test the Azure OpenAI provider implementation"""

    @pytest.fixture
    def mock_azure_config(self):
        """Fixture to create a mock Azure configuration"""
        return {
            "API_KEY": "fake_azure_api_key",
            "API_VERSION": "2023-12-01-preview",
            "AZURE_ENDPOINT": "https://test-resource.openai.azure.com/",
            "AZURE_DEPLOYMENT": "gpt-4",
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
    def mock_azure_config_minimal(self):
        """Fixture to create a minimal Azure configuration"""
        return {
            "API_KEY": "fake_azure_api_key",
            "API_VERSION": "2023-12-01-preview",
            "AZURE_ENDPOINT": "https://test-resource.openai.azure.com/",
            "MODEL": "gpt-4",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def mock_azure_config_with_ad_token(self):
        """Fixture to create Azure configuration with AD token"""
        return {
            "API_KEY": "dummy_api_key",  # Satisfy base class validation
            "AZURE_AD_TOKEN": "fake_ad_token",
            "API_VERSION": "2023-12-01-preview",
            "AZURE_ENDPOINT": "https://test-resource.openai.azure.com/",
            "MODEL": "gpt-4",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def mock_azure_config_with_base_url(self):
        """Fixture to create Azure configuration with base_url"""
        return {
            "API_KEY": "fake_azure_api_key",
            "API_VERSION": "2023-12-01-preview",
            "BASE_URL": "https://custom.openai.azure.com/openai/deployments/gpt-4",
            "MODEL": "gpt-4",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

    def test_azure_init_with_deployment(self, mock_azure_config):
        """Test Azure OpenAI initialization with deployment"""
        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=mock_azure_config)
            client_params = provider.get_client_params()

            assert client_params["api_key"] == "fake_azure_api_key"
            assert client_params["azure_endpoint"] == "https://test-resource.openai.azure.com/"
            assert client_params["azure_deployment"] == "gpt-4"
            assert client_params["base_url"] == "https://test-resource.openai.azure.com/openai/deployments/gpt-4"
            assert client_params["default_query"]["api-version"] == "2023-12-01-preview"
            assert client_params["default_headers"]["X-Title"] == provider.APP_NAME
            assert client_params["default_headers"]["HTTP_Referer"] == provider.APP_REFERER

            # Verify Azure client was called with correct params
            mock_client_cls.assert_called_once_with(**client_params)

    def test_azure_init_without_deployment(self, mock_azure_config):
        """Test Azure OpenAI initialization without deployment"""
        mock_azure_config.pop("AZURE_DEPLOYMENT")

        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=mock_azure_config)
            client_params = provider.get_client_params()

            assert client_params["azure_deployment"] is None
            assert client_params["base_url"] == "https://test-resource.openai.azure.com/openai"
            mock_client_cls.assert_called_once_with(**client_params)

    def test_azure_init_with_ad_token(self, mock_azure_config_with_ad_token):
        """Test Azure OpenAI initialization with Azure AD token"""
        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=mock_azure_config_with_ad_token)
            client_params = provider.get_client_params()

            # The Azure provider should prefer the AD token over the API key
            assert client_params["azure_ad_token"] == "fake_ad_token"
            # API key should be taken from config even though AD token is present
            assert client_params["api_key"] == "dummy_api_key"
            mock_client_cls.assert_called_once_with(**client_params)

    def test_azure_init_with_base_url(self, mock_azure_config_with_base_url):
        """Test Azure OpenAI initialization with custom base_url"""
        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=mock_azure_config_with_base_url)
            client_params = provider.get_client_params()

            assert client_params["base_url"] == "https://custom.openai.azure.com/openai/deployments/gpt-4"
            assert client_params["azure_endpoint"] is None
            mock_client_cls.assert_called_once_with(**client_params)

    def test_azure_init_with_default_query(self, mock_azure_config):
        """Test Azure OpenAI initialization with custom default query"""
        mock_azure_config["DEFAULT_QUERY"] = {"custom": "value"}

        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=mock_azure_config)
            client_params = provider.get_client_params()

            expected_query = {"custom": "value", "api-version": "2023-12-01-preview"}
            assert client_params["default_query"] == expected_query
            mock_client_cls.assert_called_once_with(**client_params)

    @patch.dict("os.environ", {"AZURE_OPENAI_API_KEY": "env_api_key"})
    def test_azure_init_from_env_api_key(self):
        """Test Azure OpenAI initialization from environment API key"""
        config = {
            # Don't set API_KEY in config to let Azure provider get from environment
            "API_VERSION": "2023-12-01-preview",
            "AZURE_ENDPOINT": "https://test-resource.openai.azure.com/",
            "MODEL": "gpt-4",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

        # Mock base class init to bypass API_KEY validation
        with (
            patch.object(OpenAIProvider, "__init__", return_value=None),
            patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls,
        ):
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=config)
            # Manually set required attributes since we bypassed base __init__
            provider.config = config
            provider.enable_function = False
            provider.enable_mcp = False
            provider.verbose = False
            provider.console = MagicMock()
            provider._completion_params = None

            client_params = provider.get_client_params()

            # Azure should get API key from environment when not in config
            assert client_params["api_key"] == "env_api_key"
            mock_client_cls.assert_called_once_with(**client_params)

    @patch.dict("os.environ", {"AZURE_OPENAI_AD_TOKEN": "env_ad_token"})
    def test_azure_init_from_env_ad_token(self):
        """Test Azure OpenAI initialization from environment AD token"""
        config = {
            "API_KEY": "dummy_api_key",  # Satisfy base class validation
            "API_VERSION": "2023-12-01-preview",
            "AZURE_ENDPOINT": "https://test-resource.openai.azure.com/",
            "MODEL": "gpt-4",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=config)
            client_params = provider.get_client_params()

            # Azure should get AD token from environment
            assert client_params["azure_ad_token"] == "env_ad_token"
            mock_client_cls.assert_called_once_with(**client_params)

    @patch.dict("os.environ", {"OPENAI_API_VERSION": "env_api_version"})
    def test_azure_init_from_env_api_version(self, mock_azure_config_minimal):
        """Test Azure OpenAI initialization from environment API version"""
        mock_azure_config_minimal.pop("API_VERSION")

        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=mock_azure_config_minimal)
            client_params = provider.get_client_params()

            assert client_params["default_query"]["api-version"] == "env_api_version"
            mock_client_cls.assert_called_once_with(**client_params)

    @patch.dict("os.environ", {"AZURE_OPENAI_ENDPOINT": "https://env-resource.openai.azure.com/"})
    def test_azure_init_from_env_endpoint(self):
        """Test Azure OpenAI initialization from environment endpoint"""
        config = {
            "API_KEY": "fake_azure_api_key",
            "API_VERSION": "2023-12-01-preview",
            "MODEL": "gpt-4",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=config)
            client_params = provider.get_client_params()

            assert client_params["azure_endpoint"] == "https://env-resource.openai.azure.com/"
            mock_client_cls.assert_called_once_with(**client_params)

    def test_azure_error_missing_credentials(self):
        """Test error when no credentials are provided"""
        config = {
            "API_KEY": "dummy_api_key",  # Satisfy base class validation
            "API_VERSION": "2023-12-01-preview",
            "AZURE_ENDPOINT": "https://test-resource.openai.azure.com/",
            "MODEL": "gpt-4",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

        # Mock the get_client_params method to simulate missing credentials scenario
        with patch.object(OpenAIAzure, "get_client_params") as mock_get_params:
            mock_get_params.side_effect = ProviderError("Missing credentials")

            with pytest.raises(ProviderError, match="Missing credentials"):
                provider = OpenAIAzure(config=config)
                provider.get_client_params()  # This should raise the error

    def test_azure_error_missing_api_version(self, mock_azure_config_minimal):
        """Test error when API version is not provided"""
        mock_azure_config_minimal.pop("API_VERSION")

        with pytest.raises(ProviderError, match="Must provide either the `api_version` argument"):
            OpenAIAzure(config=mock_azure_config_minimal)

    def test_azure_error_missing_endpoint(self, mock_azure_config_minimal):
        """Test error when endpoint is not provided"""
        mock_azure_config_minimal.pop("AZURE_ENDPOINT")

        with pytest.raises(ValueError, match="Must provide one of the `base_url` or `azure_endpoint`"):
            OpenAIAzure(config=mock_azure_config_minimal)

    def test_azure_error_conflicting_endpoint_and_base_url(self, mock_azure_config):
        """Test error when both endpoint and base_url are provided"""
        mock_azure_config["BASE_URL"] = "https://custom.openai.azure.com/"

        with pytest.raises(ValueError, match="base_url and azure_endpoint are mutually exclusive"):
            OpenAIAzure(config=mock_azure_config)

    def test_azure_with_token_provider(self):
        """Test Azure OpenAI initialization with token provider"""
        token_provider = lambda: "dynamic_token"
        config = {
            "API_KEY": "dummy_api_key",  # Satisfy base class validation
            "AZURE_AD_TOKEN_PROVIDER": token_provider,
            "API_VERSION": "2023-12-01-preview",
            "AZURE_ENDPOINT": "https://test-resource.openai.azure.com/",
            "MODEL": "gpt-4",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=config)
            client_params = provider.get_client_params()

            assert client_params["azure_ad_token_provider"] == token_provider
            mock_client_cls.assert_called_once_with(**client_params)

    def test_azure_inheritance_completion_params(self, mock_azure_config):
        """Test that Azure provider inherits completion params from base class"""
        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=mock_azure_config)

            completion_params = provider.completion_params
            assert completion_params["model"] == "gpt-4"
            assert completion_params["temperature"] == 0.7
            assert completion_params["top_p"] == 1.0
            assert completion_params["max_completion_tokens"] == 1000
            assert completion_params["timeout"] == 60
            mock_client_cls.assert_called_once()

    def test_azure_with_extra_headers(self, mock_azure_config):
        """Test Azure OpenAI initialization with extra headers"""
        extra_headers = {"X-Custom": "test", "Authorization": "Bearer custom"}
        mock_azure_config["DEFAULT_HEADERS"] = extra_headers

        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            provider = OpenAIAzure(config=mock_azure_config)
            client_params = provider.get_client_params()

            expected_headers = {
                **extra_headers,
                "X-Title": provider.APP_NAME,
                "HTTP_Referer": provider.APP_REFERER,
            }
            assert client_params["default_headers"] == expected_headers
            mock_client_cls.assert_called_once_with(**client_params)

    @patch("yaicli.tools.get_openai_schemas")
    def test_azure_completion_integration(self, mock_get_schemas, mock_azure_config):
        """Test that Azure provider can make completion calls like base OpenAI"""
        mock_get_schemas.return_value = []

        # Setup mock response
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Azure response"
        mock_message.reasoning_content = None
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]

        # Create mock Azure client
        mock_azure_client = MagicMock()
        mock_azure_client.chat.completions.create.return_value = mock_response

        with patch.object(OpenAIAzure, "CLIENT_CLS") as mock_client_cls:
            mock_client_cls.return_value = mock_azure_client

            provider = OpenAIAzure(config=mock_azure_config)

            messages = [ChatMessage(role="user", content="Hello Azure")]
            responses = list(provider.completion(messages, stream=False))

            # Verify API call
            mock_azure_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_azure_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["messages"] == [{"role": "user", "content": "Hello Azure"}]

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "Azure response"
            assert responses[0].finish_reason == "stop"
