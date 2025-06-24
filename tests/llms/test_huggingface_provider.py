from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.huggingface_provider import HuggingFaceProvider


class TestHuggingFaceProvider:
    """Tests for the HuggingFace provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://api-inference.huggingface.co/models/meta-llama/Llama-2-70b-chat-hf",
            "MODEL": "meta-llama/Llama-2-70b-chat-hf",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 30,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": False,
            "HF_PROVIDER": "hf-inference",
            "BILL_TO": "organization-123",
        }

    @pytest.fixture
    def mock_client(self):
        """Fixture to create a mock InferenceClient"""
        with patch("huggingface_hub.InferenceClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            yield mock_client

    def test_init(self, mock_config):
        """Test initialization of HuggingFaceProvider"""
        with patch("huggingface_hub.InferenceClient"):
            provider = HuggingFaceProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["api_key"] == mock_config["API_KEY"]
            assert provider.client_params["base_url"] == mock_config["BASE_URL"]
            assert provider.client_params["timeout"] == mock_config["TIMEOUT"]
            assert provider.client_params["provider"] == mock_config["HF_PROVIDER"]
            assert provider.client_params["bill_to"] == mock_config["BILL_TO"]
            assert provider.completion_params["model"] == mock_config["MODEL"]
            assert provider.completion_params["temperature"] == mock_config["TEMPERATURE"]
            assert provider.completion_params["top_p"] == mock_config["TOP_P"]
            assert provider.completion_params["max_tokens"] == mock_config["MAX_TOKENS"]

    def test_get_client_params_with_default_provider(self, mock_config):
        """Test using default provider when HF_PROVIDER is not specified"""
        config = mock_config.copy()
        del config["HF_PROVIDER"]

        with patch("huggingface_hub.InferenceClient"):
            provider = HuggingFaceProvider(config=config)

            # Check that default provider is used
            assert provider.client_params["provider"] == provider.DEFAULT_PROVIDER

    def test_get_client_params_with_extra_headers(self, mock_config):
        """Test handling of extra headers"""
        config = mock_config.copy()
        config["EXTRA_HEADERS"] = {"Custom-Header": "custom-value"}

        with patch("huggingface_hub.InferenceClient"):
            provider = HuggingFaceProvider(config=config)

            # Check that extra headers are properly merged
            assert "Custom-Header" in provider.client_params["headers"]
            assert provider.client_params["headers"]["Custom-Header"] == "custom-value"
            assert "X-Title" in provider.client_params["headers"]
            assert provider.client_params["headers"]["X-Title"] == provider.APP_NAME
            assert "HTTP-Referer" in provider.client_params["headers"]
            assert provider.client_params["headers"]["HTTP-Referer"] == provider.APP_REFERER

    def test_get_client_params_without_base_url(self, mock_config):
        """Test behavior when BASE_URL is not provided"""
        config = mock_config.copy()
        config["BASE_URL"] = None

        with patch("huggingface_hub.InferenceClient"):
            provider = HuggingFaceProvider(config=config)

            # Check that base_url is not in client_params
            assert "base_url" not in provider.client_params

    def test_get_client_params_without_bill_to(self, mock_config):
        """Test behavior when BILL_TO is not provided"""
        config = mock_config.copy()
        del config["BILL_TO"]

        with patch("huggingface_hub.InferenceClient"):
            provider = HuggingFaceProvider(config=config)

            # Check that bill_to is not in client_params
            assert "bill_to" not in provider.client_params

    def test_completion_integration(self, mock_config, mock_client):
        """Test the completion method integration (with mocked parent methods since it inherits from ChatglmProvider)"""
        from yaicli.schemas import ChatMessage

        with patch("huggingface_hub.InferenceClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            provider = HuggingFaceProvider(config=mock_config)

            # Mock the parent class methods to avoid actual API calls
            with patch.object(provider, "_convert_messages", return_value=MagicMock()):
                with patch.object(provider, "_handle_normal_response") as mock_handle:
                    mock_handle.return_value = [MagicMock()]

                    # Mock OpenAI client
                    with patch.object(provider, "client") as mock_provider_client:
                        # Create a mock that mimics OpenAI client structure
                        mock_create = MagicMock()
                        # Set up the mock hierarchy
                        mock_provider_client.chat.completions.create = mock_create

                        # Call completion
                        messages = [ChatMessage(role="user", content="Hello")]
                        list(provider.completion(messages))

                        # Check that the create method was called
                        mock_create.assert_called_once()
