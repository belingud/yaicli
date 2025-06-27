from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.doubao_provider import DoubaoProvider


class TestDoubaoProvider:
    """Tests for the Doubao provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://ark.cn-beijing.volces.com/api/v3",
            "MODEL": "doubao-4k",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": {"User-Agent": "Test-Agent"},
            "EXTRA_BODY": {"custom_param": "test_value"},
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            "AK": "test_access_key",
            "SK": "test_secret_key",
            "REGION": "cn-beijing",
        }

    def test_init_with_api_key(self, mock_config):
        """Test initialization of DoubaoProvider with API key"""
        # Create a mock client
        mock_client = MagicMock()

        # Create a provider with client initialization patched
        with patch.object(DoubaoProvider, "CLIENT_CLS") as mock_cls:
            # Configure the mock class to return our mock client
            mock_cls.return_value = mock_client

            # Create provider
            provider = DoubaoProvider(config=mock_config)

            # Verify client parameters
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args.kwargs

            # Verify API Key is set
            assert call_kwargs["api_key"] == mock_config["API_KEY"]
            assert call_kwargs["base_url"] == mock_config["BASE_URL"]
            assert call_kwargs["ak"] == mock_config["AK"]
            assert call_kwargs["sk"] == mock_config["SK"]
            assert call_kwargs["region"] == mock_config["REGION"]

            # Verify completion parameters
            assert provider.completion_params["model"] == mock_config["MODEL"]
            assert provider.completion_params["temperature"] == mock_config["TEMPERATURE"]
            assert provider.completion_params["top_p"] == mock_config["TOP_P"]
            assert provider.completion_params["max_tokens"] == mock_config["MAX_TOKENS"]
            assert provider.completion_params["timeout"] == mock_config["TIMEOUT"]

            # Check extra parameters
            assert provider.completion_params.get("extra_body") == mock_config["EXTRA_BODY"]

    def test_init_without_optional_params(self):
        """Test initialization of DoubaoProvider without optional parameters"""
        minimal_config = {
            "API_KEY": "minimal_api_key",  # Need at least API_KEY
            "MODEL": "doubao-4k",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

        # Create a mock client
        mock_client = MagicMock()

        # Create a provider with client initialization patched
        with patch.object(DoubaoProvider, "CLIENT_CLS") as mock_cls:
            # Configure the mock class to return our mock client
            mock_cls.return_value = mock_client

            # Create provider
            provider = DoubaoProvider(config=minimal_config)

            # Verify client parameters
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args.kwargs

            # Verify default URL is used
            assert call_kwargs["base_url"] == DoubaoProvider.DEFAULT_BASE_URL
            assert call_kwargs["api_key"] == "minimal_api_key"
            assert "ak" not in call_kwargs
            assert "sk" not in call_kwargs
            assert "region" not in call_kwargs

            # Verify completion parameters
            assert provider.completion_params["model"] == minimal_config["MODEL"]
            assert "extra_body" not in provider.completion_params
