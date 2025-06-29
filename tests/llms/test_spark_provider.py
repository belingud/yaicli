from unittest.mock import patch

import pytest

from yaicli.llms.providers.spark_provider import SparkProvider


class TestSparkProvider:
    """Tests for the Spark provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "APP_ID": "fake_app_id",
            "API_KEY": "fake_api_key",
            "API_SECRET": "fake_api_secret",
            "MODEL": "spark-v3.5",
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
        """Test initialization of SparkProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = SparkProvider(config=mock_config)

            expected_api_key = f"{mock_config['API_KEY']}:{mock_config['API_SECRET']}"

            # Check initialization parameters
            assert provider.client_params["base_url"] == SparkProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == expected_api_key
            assert provider.completion_params["model"] == mock_config["MODEL"]
            assert provider.completion_params["temperature"] == mock_config["TEMPERATURE"]
            assert provider.completion_params["top_p"] == mock_config["TOP_P"]
            assert provider.completion_params["max_tokens"] == mock_config["MAX_TOKENS"]

            # Spark provider specific checks
            assert "extra_body" in provider.completion_params
            assert provider.completion_params["extra_body"]["uid"] == mock_config["APP_ID"]

    def test_init_with_custom_base_url(self, mock_config):
        """Test initialization with a custom base URL"""
        custom_url = "https://custom.spark.com/v1"
        mock_config["BASE_URL"] = custom_url
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = SparkProvider(config=mock_config)
            assert provider.client_params["base_url"] == custom_url

    def test_init_missing_credentials(self):
        """Test initialization fails with missing credentials"""
        # Missing API_KEY
        config_no_key = {"API_SECRET": "secret", "APP_ID": "id"}
        with pytest.raises(ValueError, match="API_KEY and API_SECRET are required for Spark provider"):
            SparkProvider(config=config_no_key)

        # Missing API_SECRET
        config_no_secret = {"API_KEY": "key", "APP_ID": "id"}
        with pytest.raises(ValueError, match="API_KEY and API_SECRET are required for Spark provider"):
            SparkProvider(config=config_no_secret)

    def test_init_with_existing_extra_body(self, mock_config):
        """Test that APP_ID is added to an existing extra_body"""
        mock_config["EXTRA_BODY"] = {"existing_param": "value"}
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = SparkProvider(config=mock_config)
            assert "extra_body" in provider.completion_params
            assert provider.completion_params["extra_body"]["uid"] == mock_config["APP_ID"]
            assert provider.completion_params["extra_body"]["existing_param"] == "value"
