from unittest.mock import patch

import pytest

from yaicli.llms.providers.bailian_provider import (
    BailianIntlProvider,
    BailianProvider,
)


class TestBailianProvider:
    """Tests for the Bailian provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "MODEL": "qwen-plus",
            "TEMPERATURE": 0.8,
            "TOP_P": 0.85,
            "MAX_TOKENS": 2048,
            "TIMEOUT": 20,
            "BASE_URL": None,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of BailianProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = BailianProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == BailianProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == mock_config["API_KEY"]
            assert provider.completion_params["model"] == mock_config["MODEL"]
            assert provider.completion_params["temperature"] == mock_config["TEMPERATURE"]
            assert provider.completion_params["top_p"] == mock_config["TOP_P"]
            assert provider.completion_params["max_tokens"] == mock_config["MAX_TOKENS"]

    def test_init_with_custom_base_url(self, mock_config):
        """Test initialization with a custom base URL"""
        custom_url = "https://custom.bailian.com/v1"
        mock_config["BASE_URL"] = custom_url
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = BailianProvider(config=mock_config)
            assert provider.client_params["base_url"] == custom_url


class TestBailianIntlProvider:
    """Tests for the BailianIntl provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "MODEL": "qwen-intl",
            "TEMPERATURE": 0.8,
            "TOP_P": 0.85,
            "MAX_TOKENS": 2048,
            "TIMEOUT": 20,
            "BASE_URL": None,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of BailianIntlProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = BailianIntlProvider(config=mock_config)

            # Check that the international base URL is used
            assert provider.client_params["base_url"] == BailianIntlProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == mock_config["API_KEY"]
            assert provider.completion_params["model"] == mock_config["MODEL"]
