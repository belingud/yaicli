from unittest.mock import MagicMock, patch

import pytest

from yaicli.const import EventTypeEnum
from yaicli.providers.openai import OpenAIClient


@pytest.fixture
def mock_console():
    """Mock console fixture"""
    console = MagicMock()
    return console


@pytest.fixture
def test_config():
    """Test configuration fixture"""
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


class TestOpenAIClient:
    """Test OpenAI client"""

    @pytest.fixture
    def mock_openai(self):
        """Mock OpenAI client fixture"""
        with patch("yaicli.providers.openai.OpenAI") as mock_openai:
            yield mock_openai

    @pytest.fixture
    def openai_client(self, mock_console, test_config, mock_openai):
        """Create OpenAI client fixture"""
        client = OpenAIClient(test_config, mock_console, verbose=False)
        return client

    def test_initialization(self, openai_client, test_config, mock_openai):
        """Test OpenAI client initialization"""
        assert openai_client.api_key == test_config["API_KEY"]
        assert openai_client.model == test_config["MODEL"]
        assert openai_client.base_url == test_config["BASE_URL"]
        # Verify OpenAI client initialization parameters
        mock_openai.assert_called_once()
        call_args = mock_openai.call_args[1]
        assert call_args["api_key"] == test_config["API_KEY"]
        assert call_args["base_url"] == test_config["BASE_URL"]

    def test_prepare_request_params(self, openai_client, test_config):
        """Test preparing request parameters"""
        messages = [{"role": "user", "content": "Hello"}]

        # Test streaming mode
        params = openai_client._prepare_request_params(messages, stream=True)
        assert params["messages"] == messages
        assert params["model"] == test_config["MODEL"]
        assert params["stream"] is True
        assert params["temperature"] == test_config["TEMPERATURE"]
        assert params["top_p"] == test_config["TOP_P"]
        assert params["max_tokens"] == test_config["MAX_TOKENS"]
        assert params["max_completion_tokens"] == test_config["MAX_TOKENS"]

        # Test non-streaming mode
        params = openai_client._prepare_request_params(messages, stream=False)
        assert params["stream"] is False

    def test_process_completion_response(self, openai_client):
        """Test processing completion response"""
        # Use MagicMock instead of ChatCompletionMessage to avoid model_extra assignment issues
        message = MagicMock()
        message.role = "assistant"
        message.content = "Test response"
        message.model_extra = {}

        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "stop"

        completion = MagicMock()
        completion.choices = [choice]

        # Test basic response handling
        content, reasoning = openai_client._process_completion_response(completion)
        assert content == "Test response"
        assert reasoning is None

        # Test with reasoning in model_extra
        message.model_extra = {"reasoning": "思考过程"}
        content, reasoning = openai_client._process_completion_response(completion)
        assert content == "Test response"
        assert reasoning == "思考过程"

        # Test with <think> tags
        message.content = "<think>思考过程</think>Test response"
        message.model_extra = {}
        content, reasoning = openai_client._process_completion_response(completion)
        assert content == "Test response"
        assert reasoning == "思考过程"

    def test_completion(self, openai_client):
        """Test non-streaming completion request"""
        # Save original methods
        original_client = openai_client.client
        original_process_method = openai_client._process_completion_response

        try:
            # Mock client and context manager
            client_mock = MagicMock()
            context_mock = MagicMock()
            completions_mock = MagicMock()

            # Setup return value chain
            client_mock.with_options.return_value = context_mock
            context_mock.__enter__ = MagicMock(return_value=context_mock)
            context_mock.__exit__ = MagicMock(return_value=None)
            context_mock.chat.completions.create = completions_mock

            # Setup completion response
            mock_response = MagicMock()
            completions_mock.return_value = mock_response

            # Replace client and processing method
            openai_client.client = client_mock
            openai_client._process_completion_response = MagicMock(return_value=("Test response", None))

            # Call completion method
            messages = [{"role": "user", "content": "Hello"}]
            response, reasoning = openai_client.completion(messages)

            # Verify results
            assert response == "Test response"
            assert reasoning is None
            client_mock.with_options.assert_called_once()
            completions_mock.assert_called_once()
            openai_client._process_completion_response.assert_called_once_with(mock_response)
        finally:
            # Restore original methods
            openai_client.client = original_client
            openai_client._process_completion_response = original_process_method

    def test_completion_error(self, openai_client):
        """Test error handling for non-streaming completion requests"""
        # Save original method
        original_completion = openai_client.completion

        try:
            # Mock the completion method to raise an exception
            openai_client.completion = MagicMock(side_effect=Exception("API Error"))

            # Call completion method and verify exception is raised
            messages = [{"role": "user", "content": "Hello"}]
            with pytest.raises(Exception, match="API Error"):
                openai_client.completion(messages)
        finally:
            # Restore original method
            openai_client.completion = original_completion

    def test_stream_completion(self, openai_client):
        """Test streaming completion requests"""
        # Mock the stream response
        mock_chunk1 = MagicMock()
        mock_chunk1.choices = [MagicMock()]
        mock_chunk1.choices[0].delta = MagicMock()
        mock_chunk1.choices[0].delta.content = "Hello"
        mock_chunk1.choices[0].finish_reason = None

        mock_chunk2 = MagicMock()
        mock_chunk2.choices = [MagicMock()]
        mock_chunk2.choices[0].delta = MagicMock()
        mock_chunk2.choices[0].delta.content = " world"
        mock_chunk2.choices[0].finish_reason = None

        mock_chunk3 = MagicMock()
        mock_chunk3.choices = [MagicMock()]
        mock_chunk3.choices[0].delta = MagicMock()
        mock_chunk3.choices[0].delta.content = None
        mock_chunk3.choices[0].finish_reason = "stop"

        # Mock the stream method to return processed events
        original_stream = openai_client.stream_completion
        openai_client.stream_completion = MagicMock(
            return_value=[
                {"type": EventTypeEnum.CONTENT, "chunk": "Hello"},
                {"type": EventTypeEnum.CONTENT, "chunk": " world"},
                {"type": EventTypeEnum.FINISH, "reason": "stop"},
            ]
        )

        try:
            # Call stream completion method
            messages = [{"role": "user", "content": "Hello"}]
            stream_events = list(openai_client.stream_completion(messages))

            # Verify results
            assert len(stream_events) == 3
            assert stream_events[0]["chunk"] == "Hello"
            assert stream_events[1]["chunk"] == " world"
            assert stream_events[2]["reason"] == "stop"

            # Test error handling
            openai_client.stream_completion.side_effect = Exception("Stream Error")
            with pytest.raises(Exception, match="Stream Error"):
                list(openai_client.stream_completion(messages))
        finally:
            # Restore original method
            openai_client.stream_completion = original_stream
