from unittest.mock import MagicMock, patch

import pytest
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, ChoiceDelta

from yaicli.llms.providers.ai21_provider import AI21Provider
from yaicli.schemas import ToolCall


class TestAI21Provider:
    """Tests for the AI21 provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://api.ai21.com/studio/v1",
            "MODEL": "j2-mid",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
        }

    def test_init(self, mock_config):
        """Test initialization of AI21Provider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = AI21Provider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == mock_config["BASE_URL"]
            assert provider.completion_params["model"] == mock_config["MODEL"]
            assert provider.completion_params["temperature"] == mock_config["TEMPERATURE"]
            assert provider.enable_function == mock_config["ENABLE_FUNCTIONS"]

            # Check max_tokens parameter renamed from max_completion_tokens
            assert "max_completion_tokens" not in provider.completion_params
            assert "max_tokens" in provider.completion_params
            assert provider.completion_params["max_tokens"] == mock_config["MAX_TOKENS"]

    def test_handle_stream_response(self, mock_config):
        """Test handling of streaming response"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = AI21Provider(config=mock_config)

            # Mock the _get_reasoning_content method
            provider._get_reasoning_content = MagicMock(return_value="")

            # Create mock stream chunks
            chunk1 = MagicMock(spec=ChatCompletionChunk)
            delta1 = MagicMock(spec=ChoiceDelta)
            delta1.content = "Hello"
            delta1.tool_calls = None
            choice1 = MagicMock()
            choice1.delta = delta1
            choice1.finish_reason = None
            chunk1.choices = [choice1]

            chunk2 = MagicMock(spec=ChatCompletionChunk)
            delta2 = MagicMock(spec=ChoiceDelta)
            delta2.content = " world"
            delta2.tool_calls = None
            choice2 = MagicMock()
            choice2.delta = delta2
            choice2.finish_reason = "stop"
            chunk2.choices = [choice2]

            # Process events
            responses = list(provider._handle_stream_response([chunk1, chunk2]))

            # Verify responses
            assert len(responses) == 2
            assert responses[0].content == "Hello"
            assert responses[1].content == " world"
            assert responses[1].finish_reason == "stop"

    def test_handle_stream_response_with_tool_call(self, mock_config):
        """Test handling of streaming response with tool call"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = AI21Provider(config=mock_config)

            # Mock the _get_reasoning_content method
            provider._get_reasoning_content = MagicMock(return_value="")

            # Mock the _process_tool_call_chunk method
            tool_call = ToolCall(id="tc_123", name="get_weather", arguments='{"location": "New York"}')
            provider._process_tool_call_chunk = MagicMock(return_value=tool_call)

            # Create chunk with tool call
            chunk = MagicMock(spec=ChatCompletionChunk)
            delta = MagicMock(spec=ChoiceDelta)
            delta.content = ""  # AI21 specific: content must not be empty for tool calls
            delta.tool_calls = [MagicMock()]  # Just need something non-empty
            choice = MagicMock()
            choice.delta = delta
            choice.finish_reason = "tool_calls"
            chunk.choices = [choice]

            # Process events
            responses = list(provider._handle_stream_response([chunk]))

            # Verify responses - AI21 should set content to tool_call.id when empty
            assert len(responses) == 1
            assert responses[0].content == tool_call.id
            assert responses[0].finish_reason == "tool_calls"
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.id == "tc_123"
            assert responses[0].tool_call.name == "get_weather"
            assert responses[0].tool_call.arguments == '{"location": "New York"}'
