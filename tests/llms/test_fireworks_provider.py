from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.fireworks_provider import FireworksProvider


class TestFireworksProvider:
    """Test the Fireworks provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "llama-v3p1-70b-instruct",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "ACCOUNT": "fireworks",
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "REASONING_EFFORT": 0.5,
            "FREQUENCY_PENALTY": 0.3,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }
    
    @pytest.fixture
    def mock_fireworks_client(self):
        """Create a mock Fireworks client"""
        chat_mock = MagicMock()
        completions_mock = MagicMock()
        completions_mock.create = MagicMock()
        chat_mock.completions = completions_mock

        client_mock = MagicMock()
        client_mock.chat = chat_mock
        
        return client_mock

    def test_init(self, mock_config):
        """Test initialization of FireworksProvider"""
        # Create a mock for the OpenAI client class
        mock_fireworks_cls = MagicMock()
        mock_client_instance = MagicMock()
        mock_fireworks_cls.return_value = mock_client_instance
        
        # Patch the CLIENT_CLS that gets called in __init__
        with patch.object(FireworksProvider, 'CLIENT_CLS', mock_fireworks_cls):
            provider = FireworksProvider(config=mock_config)
            
            # Verify client was created with correct parameters
            mock_fireworks_cls.assert_called_once()
            
            # Check initialization parameters
            assert provider.client_params["base_url"] == FireworksProvider.DEFAULT_BASE_URL
            assert provider.client_params["base_url"] == "https://api.fireworks.ai/inference/v1"
            assert provider.client_params["api_key"] == mock_config["API_KEY"]

            # Check Fireworks specific parameters
            assert "account" in provider.client_params
            assert provider.client_params["account"] == "fireworks"
            assert "timeout" in provider.client_params
            assert provider.client_params["timeout"] == mock_config["TIMEOUT"]
            assert "extra_headers" in provider.client_params
            assert "default_headers" not in provider.client_params

    def test_init_with_extra_headers(self, mock_config):
        """Test initialization with extra headers"""
        extra_headers = {"X-Custom": "test"}
        mock_config["EXTRA_HEADERS"] = extra_headers
        
        # Mock client class
        mock_fireworks_cls = MagicMock()
        mock_client_instance = MagicMock()
        mock_fireworks_cls.return_value = mock_client_instance
        
        # Patch the CLIENT_CLS
        with patch.object(FireworksProvider, 'CLIENT_CLS', mock_fireworks_cls):
            provider = FireworksProvider(config=mock_config)

            # Check headers were properly set
            assert provider.client_params["extra_headers"] == {
                **extra_headers,
                "X-Title": provider.APP_NAME,
                "HTTP_Referer": provider.APP_REFERER,
            }

    def test_get_client_params(self, mock_config):
        """Test get_client_params method"""
        # Mock client class
        mock_fireworks_cls = MagicMock()
        mock_client_instance = MagicMock()
        mock_fireworks_cls.return_value = mock_client_instance
        
        # Patch the CLIENT_CLS
        with patch.object(FireworksProvider, 'CLIENT_CLS', mock_fireworks_cls):
            provider = FireworksProvider(config=mock_config)

            # Directly test the get_client_params method
            client_params = provider.get_client_params()

            assert "extra_headers" in client_params
            assert "default_headers" not in client_params
            assert client_params["account"] == "fireworks"
            assert client_params["timeout"] == mock_config["TIMEOUT"]

    def test_get_client_params_custom_account(self, mock_config):
        """Test get_client_params with custom account"""
        # Set a custom account
        mock_config["ACCOUNT"] = "fireworks-dev"
        
        # Mock client class
        mock_fireworks_cls = MagicMock()
        mock_client_instance = MagicMock()
        mock_fireworks_cls.return_value = mock_client_instance
        
        # Patch the CLIENT_CLS
        with patch.object(FireworksProvider, 'CLIENT_CLS', mock_fireworks_cls):
            provider = FireworksProvider(config=mock_config)

            # Directly test the get_client_params method
            client_params = provider.get_client_params()

            # Check that the custom account was used
            assert client_params["account"] == "fireworks-dev"

    def test_detect_tool_role(self, mock_config):
        """Test the detect_tool_role method"""
        # Mock client class
        mock_fireworks_cls = MagicMock()
        mock_client_instance = MagicMock()
        mock_fireworks_cls.return_value = mock_client_instance
        
        # Patch the CLIENT_CLS
        with patch.object(FireworksProvider, 'CLIENT_CLS', mock_fireworks_cls):
            provider = FireworksProvider(config=mock_config)

            # Check that the method returns the expected value
            assert provider.detect_tool_role() == "tool"

    @patch("yaicli.llms.providers.openai_provider.OpenAIProvider.completion")
    def test_completion_params(self, mock_completion, mock_config):
        """Test that the completion parameters are correctly set"""
        # Mock client class
        mock_fireworks_cls = MagicMock()
        mock_client_instance = MagicMock()
        mock_fireworks_cls.return_value = mock_client_instance
        
        # Patch the CLIENT_CLS
        with patch.object(FireworksProvider, 'CLIENT_CLS', mock_fireworks_cls):
            provider = FireworksProvider(config=mock_config)

            # Set up the mock to return an empty list
            mock_completion.return_value = []

            # Call completion
            list(provider.completion([], stream=False))

            # Check that the completion method was called with the right parameters
            mock_completion.assert_called_once()

            # Check that the provider's completion_params contain the Fireworks specific parameters
            assert "model" in provider.completion_params
            assert provider.completion_params["model"] == mock_config["MODEL"]
            assert "temperature" in provider.completion_params
            assert provider.completion_params["temperature"] == mock_config["TEMPERATURE"]
            assert "top_p" in provider.completion_params
            assert provider.completion_params["top_p"] == mock_config["TOP_P"]
            assert "max_tokens" in provider.completion_params
            assert provider.completion_params["max_tokens"] == mock_config["MAX_TOKENS"]
            assert "reasoning_effort" in provider.completion_params
            assert provider.completion_params["reasoning_effort"] == mock_config["REASONING_EFFORT"]
            assert "frequency_penalty" in provider.completion_params
            assert provider.completion_params["frequency_penalty"] == mock_config["FREQUENCY_PENALTY"]
