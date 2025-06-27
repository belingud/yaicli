from unittest.mock import patch

import pytest

from yaicli.llms.providers.vertexai_provider import VertexAIProvider


class TestVertexAIProvider:
    """Tests for VertexAI provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration for tests"""
        return {
            "PROJECT": "my-gcp-project",
            "LOCATION": "us-central1",
            "MODEL": "gemini-pro",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": {"X-Custom": "test"},
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of VertexAIProvider"""
        with patch("google.genai.Client"):
            provider = VertexAIProvider(config=mock_config)

            # Check that initialization succeeded (no exception was raised)
            assert provider is not None
            assert provider.config == mock_config

    def test_get_client_params(self, mock_config):
        """Test get_client_params method returns the expected parameters"""
        with patch("google.genai.Client"):
            provider = VertexAIProvider(config=mock_config)
            params = provider.get_client_params()

            # Check Vertex AI specific parameters
            assert params["vertexai"] is True
            assert params["project"] == mock_config["PROJECT"]
            assert params["location"] == mock_config["LOCATION"]

            # Check API_KEY is not used
            assert "api_key" not in params

    def test_missing_required_params(self):
        """Test that missing PROJECT or LOCATION raises ValueError"""
        # Test missing PROJECT
        config_missing_project = {
            "LOCATION": "us-central1",
            "MODEL": "gemini-pro",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": {},
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

        with pytest.raises(ValueError, match="PROJECT and LOCATION are required"), patch("google.genai.Client"):
            VertexAIProvider(config=config_missing_project)

        # Test missing LOCATION
        config_missing_location = {
            "PROJECT": "my-gcp-project",
            "MODEL": "gemini-pro",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": {},
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

        with pytest.raises(ValueError, match="PROJECT and LOCATION are required"), patch("google.genai.Client"):
            VertexAIProvider(config=config_missing_location)

    def test_inheritance(self, mock_config):
        """Test that VertexAIProvider inherits functionality from GeminiProvider"""
        with patch("google.genai.Client"):
            provider = VertexAIProvider(config=mock_config)

            # Test that inherited methods are available
            assert hasattr(provider, "completion")
            assert hasattr(provider, "_convert_messages")
            assert hasattr(provider, "_map_role")
            assert hasattr(provider, "detect_tool_role")

            # Test detect_tool_role (a simple inherited method)
            assert provider.detect_tool_role() == "user"
