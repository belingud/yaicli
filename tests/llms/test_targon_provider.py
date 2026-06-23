from unittest.mock import patch

import pytest

from yaicli.llms.providers.targon_provider import TargonProvider
from yaicli.schemas import ToolPolicy


class TestTargonProvider:
    """Tests for Targon provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "targon-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "FREQUENCY_PENALTY": 0.0,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of TargonProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = TargonProvider(config=mock_config)

            assert provider.client_params["base_url"] == TargonProvider.DEFAULT_BASE_URL
            assert provider.client_params["base_url"] == "https://api.targon.com/v1"
            assert provider.client_params["api_key"] == mock_config["API_KEY"]

    def test_custom_base_url(self, mock_config):
        """Test Targon provider with a custom base URL"""
        mock_config["BASE_URL"] = "https://custom.targon.example.com"
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = TargonProvider(config=mock_config)
            assert provider.client_params["base_url"] == "https://custom.targon.example.com"

    def test_completion_params_mapping(self, mock_config):
        """Test that Targon maps frequency_penalty and uses max_tokens, not max_completion_tokens"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = TargonProvider(config=mock_config)
            params = provider.get_completion_params(tool_policy=ToolPolicy(True, False))

            assert params["model"] == mock_config["MODEL"]
            assert params["max_tokens"] == mock_config["MAX_TOKENS"]
            assert "max_completion_tokens" not in params
            assert params["frequency_penalty"] == mock_config["FREQUENCY_PENALTY"]
