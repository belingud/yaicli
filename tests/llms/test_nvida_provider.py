from unittest.mock import patch

import pytest

from yaicli.llms.providers.nvida_provider import NvidiaProvider


class TestNvidiaProvider:
    """Tests for the Nvidia provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "MODEL": "nvidia/llama3-8b",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "BASE_URL": None,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of NvidiaProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = NvidiaProvider(config=mock_config)

            # Check that the default base URL is used
            assert provider.client_params["base_url"] == NvidiaProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == mock_config["API_KEY"]

    def test_init_with_custom_base_url(self, mock_config):
        """Test initialization with a custom base URL"""
        custom_url = "https://custom.nvidia.com/v1"
        mock_config["BASE_URL"] = custom_url
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = NvidiaProvider(config=mock_config)
            assert provider.client_params["base_url"] == custom_url

    def test_get_completion_params_no_extra_body(self, mock_config):
        """Test get_completion_params when EXTRA_BODY is not set"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = NvidiaProvider(config=mock_config)
            params = provider.get_completion_params()
            assert "extra_body" not in params

    def test_get_completion_params_with_extra_body(self, mock_config):
        """Test that chat_template_kwargs is added to extra_body"""
        extra_body_content = {"some_key": "some_value"}
        mock_config["EXTRA_BODY"] = extra_body_content.copy()

        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = NvidiaProvider(config=mock_config)
            params = provider.get_completion_params()

            assert "extra_body" in params
            assert params["extra_body"]["some_key"] == "some_value"
            assert "chat_template_kwargs" in params["extra_body"]
            assert params["extra_body"]["chat_template_kwargs"] == extra_body_content

    def test_get_completion_params_with_existing_chat_template_kwargs(self, mock_config):
        """Test that existing chat_template_kwargs is not overwritten"""
        original_kwargs = {"preset_key": "preset_value"}
        mock_config["EXTRA_BODY"] = {
            "chat_template_kwargs": original_kwargs,
            "other_key": "value2",
        }

        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = NvidiaProvider(config=mock_config)
            params = provider.get_completion_params()

            assert "extra_body" in params
            # Verify that the original chat_template_kwargs is preserved
            assert params["extra_body"]["chat_template_kwargs"] == original_kwargs
            assert params["extra_body"]["other_key"] == "value2"
