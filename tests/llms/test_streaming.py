from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.openai_provider import OpenAIProvider
from yaicli.schemas import ChatMessage


class TestStreamingResponses:
    """Tests for streaming responses from providers"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://fake-api.openai.com/v1",
            "MODEL": "gpt-4",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    @patch("yaicli.tools.get_openai_schemas")
    @patch("openai.OpenAI")
    def test_openai_streaming_text(self, mock_openai_cls, mock_get_schemas, mock_config):
        """Test streaming text response from OpenAI provider"""
        # Setup mock OpenAI client
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # Setup mock stream response
        mock_get_schemas.return_value = []

        # Create mock chunks for streaming response
        mock_chunks = []

        # First chunk
        chunk1 = MagicMock()
        choice1 = MagicMock()
        delta1 = MagicMock()
        delta1.content = "Hello"
        delta1.model_extra = None
        choice1.delta = delta1
        choice1.finish_reason = None
        chunk1.choices = [choice1]
        mock_chunks.append(chunk1)

        # Second chunk
        chunk2 = MagicMock()
        choice2 = MagicMock()
        delta2 = MagicMock()
        delta2.content = " world"
        delta2.model_extra = None
        choice2.delta = delta2
        choice2.finish_reason = None
        chunk2.choices = [choice2]
        mock_chunks.append(chunk2)

        # Final chunk
        chunk3 = MagicMock()
        choice3 = MagicMock()
        delta3 = MagicMock()
        delta3.content = "!"
        delta3.model_extra = None
        choice3.delta = delta3
        choice3.finish_reason = "stop"
        chunk3.choices = [choice3]
        mock_chunks.append(chunk3)

        # Set mock response
        mock_client.chat.completions.create.return_value = mock_chunks

        # Create provider and call completion
        provider = OpenAIProvider(config=mock_config)
        # Manually set the provider's client to our mock to prevent real API calls
        provider.client = mock_client
        messages = [ChatMessage(role="user", content="Say hello")]

        # Collect responses
        responses = list(provider.completion(messages, stream=True))

        # Verify API call
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"] == [{"role": "user", "content": "Say hello"}]
        assert call_kwargs["stream"] is True

        # Verify responses
        assert len(responses) == 3
        assert responses[0].content == "Hello"
        assert responses[1].content == " world"
        assert responses[2].content == "!"
        assert responses[2].finish_reason == "stop"

    @patch("yaicli.tools.get_openai_schemas")
    @patch("openai.OpenAI")
    def test_openai_streaming_with_reasoning(self, mock_openai_cls, mock_get_schemas, mock_config):
        """Test streaming response with reasoning content"""
        # Setup mock OpenAI client
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # Setup mock stream response
        mock_get_schemas.return_value = []

        # Create mock chunks for streaming response
        mock_chunks = []

        # First chunk with reasoning
        chunk1 = MagicMock()
        choice1 = MagicMock()
        delta1 = MagicMock()
        delta1.content = "Let me"
        # Add reasoning in model_extra
        delta1.model_extra = {"reasoning_content": "I need to think about this"}
        choice1.delta = delta1
        choice1.finish_reason = None
        chunk1.choices = [choice1]
        mock_chunks.append(chunk1)

        # Second chunk
        chunk2 = MagicMock()
        choice2 = MagicMock()
        delta2 = MagicMock()
        delta2.content = " calculate"
        delta2.model_extra = None
        choice2.delta = delta2
        choice2.finish_reason = None
        chunk2.choices = [choice2]
        mock_chunks.append(chunk2)

        # Final chunk
        chunk3 = MagicMock()
        choice3 = MagicMock()
        delta3 = MagicMock()
        delta3.content = " the answer"
        delta3.model_extra = None
        choice3.delta = delta3
        choice3.finish_reason = "stop"
        chunk3.choices = [choice3]
        mock_chunks.append(chunk3)

        # Set mock response
        mock_client.chat.completions.create.return_value = mock_chunks

        # Create provider and call completion
        provider = OpenAIProvider(config=mock_config)
        # Manually set the provider's client to our mock to prevent real API calls
        provider.client = mock_client
        messages = [ChatMessage(role="user", content="What is 2+2?")]

        # Collect responses
        responses = list(provider.completion(messages, stream=True))

        # Verify responses
        assert len(responses) == 3
        assert responses[0].content == "Let me"
        assert responses[0].reasoning == "I need to think about this"
        assert responses[1].content == " calculate"
        assert responses[1].reasoning is None
        assert responses[2].content == " the answer"
        assert responses[2].finish_reason == "stop"

    @patch("yaicli.tools.get_openai_schemas")
    @patch("openai.OpenAI")
    def test_openai_streaming_tool_call(self, mock_openai_cls, mock_get_schemas, mock_config):
        """Test streaming response with a tool call"""
        # Setup mock OpenAI client
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # Setup mock stream response
        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "get_weather"}}]

        # Create mock chunks for streaming response
        mock_chunks = []

        # First chunk with content
        chunk1 = MagicMock()
        choice1 = MagicMock()
        delta1 = MagicMock()
        delta1.content = "Let me check"
        delta1.model_extra = None
        delta1.tool_calls = None
        choice1.delta = delta1
        choice1.finish_reason = None
        chunk1.choices = [choice1]
        mock_chunks.append(chunk1)

        # Second chunk starts tool call
        chunk2 = MagicMock()
        choice2 = MagicMock()
        delta2 = MagicMock()
        delta2.content = " the weather"

        # First part of tool call
        mock_tool_call1 = MagicMock()
        mock_tool_call1.id = "call_123"
        mock_tool_call1.function.name = "get_weather"
        mock_tool_call1.function.arguments = '{"location": '
        delta2.tool_calls = [mock_tool_call1]

        choice2.delta = delta2
        choice2.finish_reason = None
        chunk2.choices = [choice2]
        mock_chunks.append(chunk2)

        # Final chunk
        chunk3 = MagicMock()
        choice3 = MagicMock()
        delta3 = MagicMock()
        delta3.content = ""

        # Second part of tool call
        mock_tool_call2 = MagicMock()
        mock_tool_call2.id = None
        mock_tool_call2.function.name = None
        mock_tool_call2.function.arguments = '"New York"}'
        delta3.tool_calls = [mock_tool_call2]

        choice3.delta = delta3
        choice3.finish_reason = "tool_calls"
        chunk3.choices = [choice3]
        mock_chunks.append(chunk3)

        # Set mock response
        mock_client.chat.completions.create.return_value = mock_chunks

        # Create provider and call completion
        provider = OpenAIProvider(config=mock_config)
        # Manually set the provider's client to our mock to prevent real API calls
        provider.client = mock_client
        messages = [ChatMessage(role="user", content="What's the weather in New York?")]

        # Collect responses
        responses = list(provider.completion(messages, stream=True))

        # Verify responses
        assert len(responses) == 3
        assert responses[0].content == "Let me check"
        assert responses[0].tool_call is None

        assert responses[1].content == " the weather"
        # Tool call is still accumulating, so should be None until finished
        assert responses[1].tool_call is None

        assert responses[2].content == ""
        assert responses[2].finish_reason == "tool_calls"
        # Final response should have complete tool call
        assert responses[2].tool_call is not None
        assert responses[2].tool_call.id == "call_123"
        assert responses[2].tool_call.name == "get_weather"
        assert responses[2].tool_call.arguments == '{"location": "New York"}'
