from unittest.mock import MagicMock

import pytest

from yaicli.providers.base import BaseClient


@pytest.fixture
def mock_console():
    """Mock console"""
    console = MagicMock()
    return console


@pytest.fixture
def test_config():
    """Test configuration"""
    return {
        "API_KEY": "test-api-key",
        "MODEL": "gpt-3.5-turbo",
        "BASE_URL": "https://api.openai.com/v1",
        "TIMEOUT": 60,
        "TEMPERATURE": 0.7,
        "TOP_P": 1.0,
        "MAX_TOKENS": 4000,
        "PROVIDER": "openai",
    }


class TestBaseClient:
    """Test BaseClient class"""

    def test_initialization(self, mock_console, test_config):
        """Test base class initialization"""

        # Create a concrete implementation of BaseClient
        class TestClient(BaseClient):
            def completion(self, messages):
                return "Test response", None

            def stream_completion(self, messages):
                yield {"type": "content", "chunk": "Test"}

        client = TestClient(test_config, mock_console, verbose=False)
        assert client.config == test_config
        assert client.console == mock_console
        assert client.verbose is False
        assert client.timeout == test_config["TIMEOUT"]

    def test_get_reasoning_content(self, mock_console, test_config):
        """Test method for getting reasoning content"""

        class TestClient(BaseClient):
            def completion(self, messages):
                return "Test response", None

            def stream_completion(self, messages):
                yield {"type": "content", "chunk": "Test"}

        client = TestClient(test_config, mock_console, verbose=False)

        # Test case with no reasoning content
        assert client._get_reasoning_content({}) is None
        # Don't pass None, as parameter expects dict type
        # assert client._get_reasoning_content(None) is None
        assert client._get_reasoning_content({"other_key": "value"}) is None

        # Test case with reasoning_content
        assert client._get_reasoning_content({"reasoning_content": "thinking process"}) == "thinking process"

        # Test case with reasoning
        assert client._get_reasoning_content({"reasoning": "thinking process"}) == "thinking process"

        # Test case with non-string value
        assert client._get_reasoning_content({"reasoning": 123}) is None
        assert client._get_reasoning_content({"reasoning": ""}) is None
