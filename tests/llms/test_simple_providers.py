from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.chutes_provider import ChutesProvider
from yaicli.llms.providers.deepseek_provider import DeepSeekProvider
from yaicli.llms.providers.groq_provider import GroqProvider
from yaicli.llms.providers.infiniai_provider import InfiniAIProvider
from yaicli.llms.providers.modelscope_provider import ModelScopeProvider
from yaicli.llms.providers.openrouter_provider import OpenRouterProvider
from yaicli.llms.providers.siliconflow_provider import SiliconFlowProvider
from yaicli.llms.providers.xai_provider import XaiProvider
from yaicli.llms.providers.yi_provider import YiProvider


class TestYiProvider:
    """Tests for Yi provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "yi-large",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of YiProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = YiProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == YiProvider.DEFAULT_BASE_URL
            assert provider.client_params["base_url"] == "https://api.lingyiwanwu.com/v1"
            assert provider.client_params["api_key"] == mock_config["API_KEY"]


class TestChutesProvider:
    """Tests for Chutes provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "chutes-7b",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of ChutesProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = ChutesProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == ChutesProvider.DEFAULT_BASE_URL
            assert provider.client_params["base_url"] == "https://llm.chutes.ai/v1"
            assert provider.client_params["api_key"] == mock_config["API_KEY"]


class TestDeepSeekProvider:
    """Tests for DeepSeek provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "deepseek-chat",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of DeepSeekProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = DeepSeekProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == DeepSeekProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == mock_config["API_KEY"]

            # Check max_tokens parameter renamed from max_completion_tokens
            assert "max_completion_tokens" not in provider.completion_params
            assert "max_tokens" in provider.completion_params
            assert provider.completion_params["max_tokens"] == mock_config["MAX_TOKENS"]


class TestGroqProvider:
    """Tests for Groq provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "llama3-8b-8192",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": {"N": 2},  # Add EXTRA_BODY with N parameter
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of GroqProvider"""
        # Mock console before creating provider
        mock_console = MagicMock()

        with (
            patch("yaicli.llms.providers.openai_provider.openai.OpenAI"),
            patch("yaicli.llms.providers.openai_provider.get_console", return_value=mock_console),
        ):
            provider = GroqProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == GroqProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == mock_config["API_KEY"]

            # Check that extra_body contains the N parameter set to 1
            assert "extra_body" in provider.completion_params
            assert provider.completion_params["extra_body"]["N"] == 1
            mock_console.print.assert_called_once_with(
                "Groq does not support N parameter, setting N to 1 as Groq default", style="yellow"
            )


class TestInfiniAIProvider:
    """Tests for InfiniAI provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "infiniai-7b",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of InfiniAIProvider"""
        # Mock console before creating provider
        mock_console = MagicMock()

        with (
            patch("yaicli.llms.providers.openai_provider.openai.OpenAI"),
            patch("yaicli.llms.providers.openai_provider.get_console", return_value=mock_console),
        ):
            provider = InfiniAIProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == InfiniAIProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == mock_config["API_KEY"]

            # Check max_tokens parameter renamed from max_completion_tokens
            assert "max_completion_tokens" not in provider.completion_params
            assert "max_tokens" in provider.completion_params
            assert provider.completion_params["max_tokens"] == mock_config["MAX_TOKENS"]

            # Check functions are disabled for InfiniAI
            assert provider.enable_function is False
            # Verify warning message was printed
            mock_console.print.assert_called_once_with("InfiniAI does not support functions, disabled", style="yellow")


class TestModelScopeProvider:
    """Tests for ModelScope provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "modelscope-llama",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of ModelScopeProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = ModelScopeProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == ModelScopeProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == mock_config["API_KEY"]


class TestOpenRouterProvider:
    """Tests for OpenRouter provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "openrouter/model",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of OpenRouterProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = OpenRouterProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == OpenRouterProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == mock_config["API_KEY"]


class TestSiliconFlowProvider:
    """Tests for SiliconFlow provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "siliconflow-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of SiliconFlowProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = SiliconFlowProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == SiliconFlowProvider.DEFAULT_BASE_URL
            assert provider.client_params["api_key"] == mock_config["API_KEY"]


class TestXaiProvider:
    """Tests for Xai provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "xai-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of XaiProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = XaiProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == XaiProvider.DEFAULT_BASE_URL
            assert provider.client_params["base_url"] == "https://api.xai.com/v1"
            assert provider.client_params["api_key"] == mock_config["API_KEY"]


class TestCustomBaseURL:
    """Test custom base URL for providers"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration with custom base URL"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://custom.api.example.com",
            "MODEL": "test-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_custom_base_url(self, mock_config):
        """Test providers with custom base URL"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            # Test with Yi provider
            provider = YiProvider(config=mock_config)
            assert provider.client_params["base_url"] == mock_config["BASE_URL"]

            # Test with Chutes provider
            provider = ChutesProvider(config=mock_config)
            assert provider.client_params["base_url"] == mock_config["BASE_URL"]

            # Test with Xai provider
            provider = XaiProvider(config=mock_config)
            assert provider.client_params["base_url"] == mock_config["BASE_URL"]
