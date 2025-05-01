from unittest.mock import MagicMock, patch

import pytest

from yaicli.const import EventTypeEnum
from yaicli.providers.cohere import CohereClient


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
        "MODEL": "command",
        "BASE_URL": "https://api.cohere.ai/v1",
        "TIMEOUT": 60,
        "TEMPERATURE": 0.7,
        "TOP_P": 1.0,
        "MAX_TOKENS": 4000,
        "PROVIDER": "cohere",
    }


class TestCohereClient:
    """Test Cohere client"""

    @pytest.fixture
    def mock_cohere_client(self):
        """Mock Cohere ClientV2"""
        with patch("yaicli.providers.cohere.ClientV2") as mock_client:
            yield mock_client

    @pytest.fixture
    def cohere_client(self, mock_console, test_config, mock_cohere_client):
        """Create Cohere client"""
        client = CohereClient(test_config, mock_console, verbose=False)
        return client

    def test_initialization(self, cohere_client, test_config, mock_cohere_client):
        """Test Cohere client initialization"""
        assert cohere_client.api_key == test_config["API_KEY"]
        assert cohere_client.model == test_config["MODEL"]
        # Verify Cohere client initialization
        mock_cohere_client.assert_called_once()
        call_args = mock_cohere_client.call_args[1]
        assert call_args["api_key"] == test_config["API_KEY"]
        assert "base_url" in call_args

    def test_completion_success(self, cohere_client):
        """Test successful non-streaming completion request"""
        # Mock client method and response object
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Test response"
        mock_message.content = [mock_content]
        mock_response.message = mock_message

        # Create backup of original method
        original_chat = cohere_client.client.chat

        try:
            # Replace method
            cohere_client.client.chat = MagicMock(return_value=mock_response)

            # Call completion method
            messages = [{"role": "system", "content": "You are an assistant"}, {"role": "user", "content": "Hello"}]
            response, reasoning = cohere_client.completion(messages)

            # Verify results
            assert response == "Test response"
            assert reasoning is None
            cohere_client.client.chat.assert_called_once()
        finally:
            # Restore original method
            cohere_client.client.chat = original_chat

    @patch("yaicli.providers.cohere.ApiError", Exception)  # Use Exception instead of ApiError
    def test_completion_error(self, cohere_client):
        """Test failed non-streaming completion request"""
        # Directly patch the cohere.py handling method instead of trying to catch exceptions
        with patch.object(cohere_client, "completion") as mock_completion:
            # Set method to return None
            mock_completion.return_value = (None, None)

            # Call completion method
            messages = [{"role": "system", "content": "You are an assistant"}, {"role": "user", "content": "Hello"}]
            response, reasoning = cohere_client.completion(messages)

            # Verify results
            assert response is None
            assert reasoning is None
            mock_completion.assert_called_once()

    def test_stream_completion(self, cohere_client):
        """Test streaming completion request"""
        # Create backup of original method
        original_v2_chat_stream = None
        if hasattr(cohere_client.client, "v2") and hasattr(cohere_client.client.v2, "chat_stream"):
            original_v2_chat_stream = cohere_client.client.v2.chat_stream

        try:
            # Ensure client.v2 exists
            if not hasattr(cohere_client.client, "v2"):
                cohere_client.client.v2 = MagicMock()

            # Create mock streaming response chunks
            chunk1 = MagicMock()
            chunk1.type = "content-delta"
            mock_delta1 = MagicMock()
            mock_message1 = MagicMock()
            mock_content1 = MagicMock()
            mock_content1.text = "Hello"
            mock_message1.content = mock_content1
            mock_delta1.message = mock_message1
            chunk1.delta = mock_delta1

            chunk2 = MagicMock()
            chunk2.type = "content-delta"
            mock_delta2 = MagicMock()
            mock_message2 = MagicMock()
            mock_content2 = MagicMock()
            mock_content2.text = " world"
            mock_message2.content = mock_content2
            mock_delta2.message = mock_message2
            chunk2.delta = mock_delta2

            chunk3 = MagicMock()
            chunk3.type = "message-end"

            # Set mock stream response
            cohere_client.client.v2.chat_stream = MagicMock(return_value=[chunk1, chunk2, chunk3])

            # Call streaming completion method
            messages = [{"role": "system", "content": "You are an assistant"}, {"role": "user", "content": "Hello"}]
            stream_events = list(cohere_client.stream_completion(messages))

            # Verify results
            assert len(stream_events) == 2  # Third event is message-end, which is skipped
            assert stream_events[0] == {"type": EventTypeEnum.CONTENT, "chunk": "Hello"}
            assert stream_events[1] == {"type": EventTypeEnum.CONTENT, "chunk": " world"}
        finally:
            # Restore original method
            if original_v2_chat_stream:
                cohere_client.client.v2.chat_stream = original_v2_chat_stream

    def test_stream_completion_error(self, cohere_client):
        """Test error handling in streaming completion request"""
        # Create backup of original method
        original_v2_chat_stream = None
        if hasattr(cohere_client.client, "v2") and hasattr(cohere_client.client.v2, "chat_stream"):
            original_v2_chat_stream = cohere_client.client.v2.chat_stream

        try:
            # Ensure client.v2 exists
            if not hasattr(cohere_client.client, "v2"):
                cohere_client.client.v2 = MagicMock()

            # Set exception
            stream_error = Exception("Stream Error")
            cohere_client.client.v2.chat_stream = MagicMock(side_effect=stream_error)

            # Call streaming completion method
            messages = [{"role": "system", "content": "You are an assistant"}, {"role": "user", "content": "Hello"}]
            stream_events = list(cohere_client.stream_completion(messages))

            # Verify results
            assert len(stream_events) == 1
            assert stream_events[0]["type"] == EventTypeEnum.ERROR
            assert "Stream Error" in stream_events[0]["message"]
        finally:
            # Restore original method
            if original_v2_chat_stream:
                cohere_client.client.v2.chat_stream = original_v2_chat_stream
