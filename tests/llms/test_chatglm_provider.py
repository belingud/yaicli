from unittest.mock import MagicMock, patch

import pytest
from openai.types.chat.chat_completion import (
    ChatCompletion,
)
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, ChoiceDelta

from yaicli.llms.providers.chatglm_provider import ChatglmProvider
from yaicli.schemas import ChatMessage


class TestChatglmProvider:
    """Tests for the Chatglm provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://open.bigmodel.cn/api/paas/v4/",
            "MODEL": "glm-4",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            "LITE_TRANSPORT": False,
        }

    @pytest.fixture
    def mock_client(self):
        """Fixture to create a mock OpenAI client"""
        with patch("openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            yield mock_client

    def test_init(self, mock_config):
        """Test initialization of ChatglmProvider"""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["base_url"] == mock_config["BASE_URL"]
            assert provider.completion_params["model"] == mock_config["MODEL"]
            assert provider.completion_params["temperature"] == mock_config["TEMPERATURE"]
            assert provider.enable_function == mock_config["ENABLE_FUNCTIONS"]

    def test_timeout_is_forwarded_to_request(self, mock_config):
        """ChatGLM used to ignore config TIMEOUT; it must be sent with the request."""
        mock_client = MagicMock()
        with patch.object(ChatglmProvider, "CLIENT_CLS", MagicMock(return_value=mock_client)):
            provider = ChatglmProvider(config=mock_config)

        assert provider.completion_params["timeout"] == mock_config["TIMEOUT"]
        provider.client.chat.completions.create.return_value = MagicMock()

        with patch.object(provider, "_handle_normal_response", return_value=[]):
            list(provider.completion([ChatMessage(role="user", content="hi")], stream=False))

        call_kwargs = provider.client.chat.completions.create.call_args.kwargs
        assert call_kwargs["timeout"] == mock_config["TIMEOUT"]

    def test_handle_normal_response_with_content(self, mock_config):
        """Test handling of normal response with content"""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

            # Create a mock response with content
            message = MagicMock()
            message.content = "This is a test response."
            message.reasoning_content = None
            message.model_extra = None

            choice = MagicMock()
            choice.message = message
            choice.finish_reason = "stop"

            mock_response = MagicMock(spec=ChatCompletion)
            mock_response.choices = [choice]

            # Process response
            responses = list(provider._handle_normal_response(mock_response))

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "This is a test response."
            assert responses[0].reasoning is None
            assert responses[0].tool_call is None

    def test_handle_normal_response_with_think_tag(self, mock_config):
        """Test handling of normal response with <think> tags"""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

            # Create a mock response with <think> tags
            message = MagicMock()
            message.content = "<think>This is my reasoning process</think>This is the actual response."
            message.reasoning_content = None
            message.model_extra = None

            choice = MagicMock()
            choice.message = message
            choice.finish_reason = "stop"

            mock_response = MagicMock(spec=ChatCompletion)
            mock_response.choices = [choice]

            # Process response
            responses = list(provider._handle_normal_response(mock_response))

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "This is the actual response."
            assert responses[0].reasoning == "This is my reasoning process"
            assert responses[0].tool_call is None

    def test_handle_normal_response_with_model_extra(self, mock_config):
        """Test handling of normal response with model_extra reasoning content"""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

            # Mock the _get_reasoning_content method
            provider._get_reasoning_content = MagicMock(return_value="Reasoning from model_extra")

            # Create a mock response with model_extra
            message = MagicMock()
            message.content = "This is a test response."
            message.reasoning_content = None
            message.model_extra = {"reasoning": "Reasoning from model_extra"}

            choice = MagicMock()
            choice.message = message
            choice.finish_reason = "stop"

            mock_response = MagicMock(spec=ChatCompletion)
            mock_response.choices = [choice]

            # Process response
            responses = list(provider._handle_normal_response(mock_response))

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "This is a test response."
            assert responses[0].reasoning == "Reasoning from model_extra"
            assert responses[0].tool_call is None

    def test_handle_normal_response_with_tool_call(self, mock_config):
        """Test handling of normal response with tool call"""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

            # Create a mock tool call
            tool_call = MagicMock()
            tool_call.id = "call_123"
            tool_call.function.name = "get_weather"
            tool_call.function.arguments = '{"location": "New York"}'

            # Create a mock response with tool call
            message = MagicMock()
            message.content = "Let me check the weather."
            message.reasoning_content = None
            message.model_extra = None
            message.tool_calls = [tool_call]

            choice = MagicMock()
            choice.message = message
            choice.finish_reason = "tool_calls"

            mock_response = MagicMock(spec=ChatCompletion)
            mock_response.choices = [choice]

            # Process response
            responses = list(provider._handle_normal_response(mock_response))

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "Let me check the weather."
            assert responses[0].finish_reason == "tool_calls"
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.id == "call_123"
            assert responses[0].tool_call.name == "get_weather"
            assert responses[0].tool_call.arguments == '{"location": "New York"}'

    def test_handle_normal_response_with_tool_call_in_content(self, mock_config):
        """Test handling of normal response with tool call in content"""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

            # Create content with tool call JSON
            tool_content = '{"index": 0, "tool_call_id": "call_123", "function": {"name": "get_weather", "arguments": "{\\"location\\": \\"New York\\"}"}}'

            # Create a mock response with tool call in content
            message = MagicMock()
            message.content = f"Let me check the weather.\n{tool_content}"
            message.reasoning_content = None
            message.model_extra = None
            message.tool_calls = []

            choice = MagicMock()
            choice.message = message
            choice.finish_reason = "tool_calls"

            mock_response = MagicMock(spec=ChatCompletion)
            mock_response.choices = [choice]

            # Mock parse_choice_from_content method
            mock_choice = MagicMock()
            mock_message = MagicMock()
            mock_tool_call = MagicMock()
            mock_tool_call.id = "call_123"
            mock_tool_call.function.name = "get_weather"
            mock_tool_call.function.arguments = '{"location": "New York"}'
            mock_message.tool_calls = [mock_tool_call]
            mock_choice.message = mock_message
            provider.parse_choice_from_content = MagicMock(return_value=mock_choice)

            # Process response
            responses = list(provider._handle_normal_response(mock_response))

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == f"Let me check the weather.\n{tool_content}"
            assert responses[0].finish_reason == "tool_calls"
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.id == "call_123"
            assert responses[0].tool_call.name == "get_weather"

    def test_handle_stream_response(self, mock_config):
        """Test handling of streaming response"""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

            # Mock the _get_reasoning_content method
            provider._get_reasoning_content = MagicMock(side_effect=["Thinking", "", ""])

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
            choice2.finish_reason = None
            chunk2.choices = [choice2]

            chunk3 = MagicMock(spec=ChatCompletionChunk)
            delta3 = MagicMock(spec=ChoiceDelta)
            delta3.content = "!"
            delta3.tool_calls = None
            choice3 = MagicMock()
            choice3.delta = delta3
            choice3.finish_reason = "stop"
            chunk3.choices = [choice3]

            # Process events
            responses = list(provider._handle_stream_response([chunk1, chunk2, chunk3]))

            # Verify responses
            assert len(responses) == 3
            assert responses[0].content == "Hello"
            assert responses[0].reasoning == "Thinking"
            assert responses[1].content == " world"
            assert responses[2].content == "!"
            assert responses[2].finish_reason == "stop"

    def test_handle_stream_response_with_tool_call(self, mock_config):
        """Test handling of streaming response with tool call"""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

            # Mock the _get_reasoning_content method
            provider._get_reasoning_content = MagicMock(return_value="")

            # Create mock stream chunks
            chunk1 = MagicMock(spec=ChatCompletionChunk)
            delta1 = MagicMock(spec=ChoiceDelta)
            delta1.content = "I'll check the weather"
            delta1.tool_calls = None
            choice1 = MagicMock()
            choice1.delta = delta1
            choice1.finish_reason = None
            chunk1.choices = [choice1]

            # Create chunk with tool call
            chunk2 = MagicMock(spec=ChatCompletionChunk)
            delta2 = MagicMock(spec=ChoiceDelta)
            delta2.content = ""

            tool_call = MagicMock()
            tool_call.id = "call_123"
            tool_call.function = MagicMock()
            tool_call.function.name = "get_weather"
            tool_call.function.arguments = '{"location": '
            delta2.tool_calls = [tool_call]

            choice2 = MagicMock()
            choice2.delta = delta2
            choice2.finish_reason = None
            chunk2.choices = [choice2]

            # Continue tool call arguments
            chunk3 = MagicMock(spec=ChatCompletionChunk)
            delta3 = MagicMock(spec=ChoiceDelta)
            delta3.content = ""

            tool_call3 = MagicMock()
            tool_call3.id = None
            tool_call3.function = MagicMock()
            tool_call3.function.name = None
            tool_call3.function.arguments = '"New York"}'
            delta3.tool_calls = [tool_call3]

            choice3 = MagicMock()
            choice3.delta = delta3
            choice3.finish_reason = "tool_calls"
            chunk3.choices = [choice3]

            # Process events
            responses = list(provider._handle_stream_response([chunk1, chunk2, chunk3]))

            # Content chunks are streamed as before, but partial tool calls are
            # never surfaced: the client must never execute truncated arguments.
            assert responses[0].content == "I'll check the weather"
            assert [response for response in responses[:-1] if response.tool_call] == []

            # The complete call is emitted once, after the stream finished.
            tool_responses = [response for response in responses if response.tool_call]
            assert len(tool_responses) == 1
            assert tool_responses[0].tool_call.id == "call_123"
            assert tool_responses[0].tool_call.name == "get_weather"
            assert tool_responses[0].tool_call.arguments == '{"location": "New York"}'
            assert tool_responses[0].finish_reason == "tool_calls"

    def test_parse_choice_from_content(self, mock_config):
        """Test parsing choice from content"""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

            # Valid content
            valid_content = (
                '{"index": 0, "message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}'
            )

            # Mock Choice.model_validate
            mock_choice = MagicMock()
            with patch("openai.types.chat.chat_completion.Choice.model_validate", return_value=mock_choice):
                result = provider.parse_choice_from_content(valid_content)
                assert result == mock_choice

            # Invalid JSON content
            invalid_content = "not a valid json"
            with pytest.raises(ValueError, match="Invalid message from LLM"):
                provider.parse_choice_from_content(invalid_content)

            # Valid JSON but invalid model content
            with patch(
                "openai.types.chat.chat_completion.Choice.model_validate", side_effect=Exception("Invalid model")
            ):
                with pytest.raises(ValueError, match="Invalid message from LLM"):
                    provider.parse_choice_from_content(valid_content)

    def test_handle_normal_response_without_reasoning_content_attribute(self, mock_config):
        """A plain OpenAI-schema message with no reasoning_content field must not crash.

        Regression test for HuggingFace's ``ChatCompletionOutputMessage`` (and non-thinking
        ChatGLM responses), which do not expose a ``reasoning_content`` attribute at all.
        """
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

        response = ChatCompletion.model_validate(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1,
                "model": "glm-4",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "plain answer"},
                    }
                ],
            }
        )
        # The SDK model only exposes reasoning_content when the API actually returned it.
        assert not hasattr(response.choices[0].message, "reasoning_content")

        responses = list(provider._handle_normal_response(response))

        assert len(responses) == 1
        assert responses[0].content == "plain answer"
        assert responses[0].reasoning is None
        assert responses[0].tool_call is None

    def test_handle_normal_response_keeps_reasoning_content(self, mock_config):
        """When reasoning_content is present it is still returned as reasoning."""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

        message = MagicMock()
        message.content = "actual answer"
        message.reasoning_content = "thinking process"
        message.model_extra = None

        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "stop"

        mock_response = MagicMock(spec=ChatCompletion)
        mock_response.choices = [choice]

        responses = list(provider._handle_normal_response(mock_response))

        assert len(responses) == 1
        assert responses[0].content == "actual answer"
        assert responses[0].reasoning == "thinking process"

    def test_handle_stream_response_without_reasoning_content_attribute(self, mock_config):
        """Streaming deltas without a reasoning_content attribute must not crash."""
        with patch("openai.OpenAI"):
            provider = ChatglmProvider(config=mock_config)

        chunk = ChatCompletionChunk.model_validate(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "glm-4",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "streamed answer"},
                        "finish_reason": None,
                    }
                ],
            }
        )
        assert not hasattr(chunk.choices[0].delta, "reasoning_content")

        responses = list(provider._handle_stream_response([chunk]))

        assert len(responses) == 1
        assert responses[0].content == "streamed answer"
        assert responses[0].reasoning is None
        assert responses[0].tool_call is None
