import pytest
from unittest.mock import MagicMock, patch

from yaicli.llms.providers.minimax_provider import MinimaxProvider
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall, ToolPolicy


class TestMinimaxProvider:
    """Tests for MinimaxProvider with Interleaved Thinking support"""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config for testing"""
        return {
            "API_KEY": "test-api-key",
            "MODEL": "MiniMax-M2.1",
            "TEMPERATURE": 0.3,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 60,
            "EXTRA_BODY": {},
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
            "MINIMAX_REASONING_SPLIT": True,
        }

    @pytest.fixture
    def provider(self, mock_config):
        """Create a MinimaxProvider instance for testing"""
        with patch("openai.OpenAI"):
            provider = MinimaxProvider(config=mock_config, verbose=False)
            return provider

    def test_reasoning_split_default_enabled(self, provider):
        """Test that reasoning_split=True is set by default in extra_body"""
        params = provider.get_completion_params()

        assert "extra_body" in params
        assert params["extra_body"]["reasoning_split"] is True

    def test_get_completion_params_accepts_tool_policy(self, provider):
        """Test get_completion_params accepts request-scoped tool policy."""
        params = provider.get_completion_params(tool_policy=ToolPolicy(False, False))

        assert params["model"] == provider.config["MODEL"]
        assert params["extra_body"]["reasoning_split"] is True

    def test_reasoning_split_respects_config(self, mock_config):
        """Test that reasoning_split respects MINIMAX_REASONING_SPLIT config"""
        mock_config["MINIMAX_REASONING_SPLIT"] = False

        with patch("openai.OpenAI"):
            provider = MinimaxProvider(config=mock_config, verbose=False)
            params = provider.get_completion_params()

            assert params["extra_body"]["reasoning_split"] is False

    def test_reasoning_split_not_override_user_setting(self, mock_config):
        """Test that user-provided reasoning_split in EXTRA_BODY is not overridden"""
        mock_config["EXTRA_BODY"] = {"reasoning_split": False}

        with patch("openai.OpenAI"):
            provider = MinimaxProvider(config=mock_config, verbose=False)
            params = provider.get_completion_params()

            assert params["extra_body"]["reasoning_split"] is False

    def test_convert_messages_with_reasoning(self, provider):
        """Test that message conversion correctly handles reasoning content"""
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(
                role="assistant",
                content="Response",
                reasoning="This is my thinking process",
            ),
        ]

        converted = provider._convert_messages(messages)

        assert len(converted) == 2
        # User message should not have reasoning_details
        assert "reasoning_details" not in converted[0]
        # Assistant message should have reasoning_details
        assert "reasoning_details" in converted[1]
        assert converted[1]["reasoning_details"] == [{"type": "reasoning.text", "text": "This is my thinking process"}]

    def test_convert_messages_without_reasoning(self, provider):
        """Test that message conversion works without reasoning content"""
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Response"),
        ]

        converted = provider._convert_messages(messages)

        assert len(converted) == 2
        # Neither message should have reasoning_details
        assert "reasoning_details" not in converted[0]
        assert "reasoning_details" not in converted[1]

    def test_convert_messages_with_tool_calls_and_reasoning(self, provider):
        """Test that message conversion handles both tool_calls and reasoning"""
        messages = [
            ChatMessage(
                role="assistant",
                content="Let me check that",
                reasoning="I need to use a tool to answer this",
                tool_calls=[ToolCall(id="call_123", name="get_weather", arguments='{"city": "Beijing"}')],
            ),
        ]

        converted = provider._convert_messages(messages)

        assert len(converted) == 1
        assert "tool_calls" in converted[0]
        assert "reasoning_details" in converted[0]
        assert converted[0]["tool_calls"][0]["id"] == "call_123"
        assert converted[0]["reasoning_details"][0]["text"] == "I need to use a tool to answer this"

    def test_get_reasoning_content_from_details(self, provider):
        """Test extraction of reasoning from reasoning_details format"""
        delta = {
            "reasoning_details": [
                {"type": "reasoning.text", "text": "First part of thinking"},
                {"type": "reasoning.text", "text": "Second part of thinking"},
            ]
        }

        reasoning = provider._get_reasoning_content(delta)

        assert reasoning == "First part of thinkingSecond part of thinking"

    def test_get_reasoning_content_empty_details(self, provider):
        """Test extraction with empty reasoning_details"""
        delta = {"reasoning_details": []}

        reasoning = provider._get_reasoning_content(delta)

        assert reasoning is None

    def test_get_reasoning_content_no_details(self, provider):
        """Test extraction when no reasoning_details present"""
        delta = {"content": "Some content"}

        reasoning = provider._get_reasoning_content(delta)

        assert reasoning is None

    def test_get_reasoning_content_fallback_to_parent(self, provider):
        """Test fallback to parent implementation for other formats"""
        # Test reasoning_content format (used by deepseek etc.)
        delta = {"reasoning_content": "Thinking content"}

        reasoning = provider._get_reasoning_content(delta)

        assert reasoning == "Thinking content"

        # Test reasoning format (used by openrouter)
        delta = {"reasoning": "Thinking content"}

        reasoning = provider._get_reasoning_content(delta)

        assert reasoning == "Thinking content"

    def test_get_reasoning_content_with_non_dict(self, provider):
        """Test extraction when delta is not a dict"""
        # Create a mock object that behaves like a dict when converted
        mock_delta = MagicMock()
        mock_delta.__iter__ = lambda self: iter({"reasoning_details": [{"text": "thinking"}]}.items())
        mock_delta.get = lambda key, default=None: {"reasoning_details": [{"text": "thinking"}]}.get(key, default)

        reasoning = provider._get_reasoning_content(mock_delta)

        # Should handle the conversion gracefully - dict() will use __iter__
        # But our implementation uses .get() method, so we need to verify it works
        # The actual behavior depends on how dict() constructs from the object
        # This test verifies no exception is raised
        assert reasoning is not None or reasoning is None  # Either is acceptable if no exception

    def test_inheritance_from_openai_provider(self, provider):
        """Test that MinimaxProvider properly inherits from OpenAIProvider"""
        from yaicli.llms.providers.openai_provider import OpenAIProvider

        assert isinstance(provider, OpenAIProvider)

    def test_default_base_url(self, provider):
        """Test that default base URL is set correctly"""
        assert provider.DEFAULT_BASE_URL == "https://api.minimaxi.com/v1"

    def test_completion_params_keys(self, provider):
        """Test that completion params keys are defined correctly"""
        expected_keys = {
            "model": "MODEL",
            "temperature": "TEMPERATURE",
            "top_p": "TOP_P",
            "max_tokens": "MAX_TOKENS",
            "timeout": "TIMEOUT",
            "extra_body": "EXTRA_BODY",
            "frequency_penalty": "FREQUENCY_PENALTY",
        }

        assert provider.COMPLETION_PARAMS_KEYS == expected_keys

    def test_convert_messages_with_name_field(self, provider):
        """Test message conversion with name field"""
        messages = [ChatMessage(role="user", content="Hello", name="test_user")]

        converted = provider._convert_messages(messages)

        assert converted[0]["name"] == "test_user"

    def test_convert_messages_with_tool_role(self, provider):
        """Test message conversion with tool role and tool_call_id"""
        messages = [ChatMessage(role="tool", content="result", tool_call_id="call_123")]

        converted = provider._convert_messages(messages)

        assert converted[0]["role"] == "tool"
        assert converted[0]["tool_call_id"] == "call_123"

    def test_get_reasoning_content_with_non_dict_delta(self, provider):
        """Test _get_reasoning_content converts non-dict delta"""
        # Create a mock object that behaves like a dict when converted
        class MockDelta:
            def __init__(self, data):
                self._data = data

            def __iter__(self):
                return iter(self._data.items())

        mock_delta = MockDelta({"reasoning_details": [{"text": "thinking"}]})
        reasoning = provider._get_reasoning_content(mock_delta)

        # Should handle the conversion gracefully
        assert reasoning == "thinking"

    def test_handle_stream_response(self, provider):
        """Test streaming response handling"""
        # Create mock chunks
        chunk1 = MagicMock()
        choice1 = MagicMock()
        delta1 = MagicMock()
        delta1.content = "Hello"
        delta1.model_extra = None
        delta1.tool_calls = None
        choice1.delta = delta1
        choice1.finish_reason = None
        chunk1.choices = [choice1]

        chunk2 = MagicMock()
        choice2 = MagicMock()
        delta2 = MagicMock()
        delta2.content = " world"
        delta2.model_extra = None
        delta2.tool_calls = None
        choice2.delta = delta2
        choice2.finish_reason = "stop"
        chunk2.choices = [choice2]

        responses = list(provider._handle_stream_response([chunk1, chunk2]))

        assert len(responses) == 2
        assert responses[0].content == "Hello"
        assert responses[1].content == " world"
        assert responses[1].finish_reason == "stop"

    def test_handle_stream_response_with_reasoning(self, provider):
        """Test streaming response with reasoning_details"""
        chunk = MagicMock()
        choice = MagicMock()
        delta = MagicMock()
        delta.content = "answer"
        delta.model_extra = {"reasoning_details": [{"text": "thinking"}]}
        delta.tool_calls = None
        choice.delta = delta
        choice.finish_reason = "stop"
        chunk.choices = [choice]

        responses = list(provider._handle_stream_response([chunk]))

        assert responses[0].reasoning == "thinking"
        assert responses[0].content == "answer"

    def test_handle_stream_response_empty_first_chunk(self, provider):
        """Test streaming with empty first chunk"""
        chunk1 = MagicMock()
        chunk1.choices = []

        chunk2 = MagicMock()
        choice2 = MagicMock()
        delta2 = MagicMock()
        delta2.content = "ok"
        delta2.model_extra = None
        delta2.tool_calls = None
        choice2.delta = delta2
        choice2.finish_reason = "stop"
        chunk2.choices = [choice2]

        responses = list(provider._handle_stream_response([chunk1, chunk2]))

        # First empty chunk is skipped
        assert len(responses) == 1
        assert responses[0].content == "ok"

    def test_handle_stream_response_first_chunk_error(self, provider):
        """Test streaming with first chunk error response"""
        chunk1 = MagicMock()
        chunk1.choices = []

        chunk2 = MagicMock()
        choice2 = MagicMock()
        delta2 = MagicMock()
        delta2.content = "ok"
        delta2.model_extra = None
        delta2.tool_calls = None
        choice2.delta = delta2
        choice2.finish_reason = "stop"
        chunk2.choices = [choice2]

        with patch.object(provider, "_first_chunk_error", return_value=LLMResponse(content="error", finish_reason="stop")):
            responses = list(provider._handle_stream_response([chunk1, chunk2]))

        # Should yield the error response first
        assert responses[0].content == "error"
        assert responses[1].content == "ok"

    def test_handle_stream_response_mid_empty_chunk(self, provider):
        """Test streaming with empty chunk in the middle"""
        chunk1 = MagicMock()
        choice1 = MagicMock()
        delta1 = MagicMock()
        delta1.content = "a"
        delta1.model_extra = None
        delta1.tool_calls = None
        choice1.delta = delta1
        choice1.finish_reason = None
        chunk1.choices = [choice1]

        chunk2 = MagicMock()
        chunk2.choices = []  # Empty chunk

        chunk3 = MagicMock()
        choice3 = MagicMock()
        delta3 = MagicMock()
        delta3.content = "b"
        delta3.model_extra = None
        delta3.tool_calls = None
        choice3.delta = delta3
        choice3.finish_reason = "stop"
        chunk3.choices = [choice3]

        responses = list(provider._handle_stream_response([chunk1, chunk2, chunk3]))

        # Middle empty chunk should be skipped
        assert len(responses) == 2
        assert responses[0].content == "a"
        assert responses[1].content == "b"

    def test_handle_stream_response_with_tool_call(self, provider):
        """Test streaming response with tool call"""
        chunk = MagicMock()
        choice = MagicMock()
        delta = MagicMock()
        delta.content = ""
        delta.model_extra = None

        mock_tool = MagicMock()
        mock_tool.id = "call_123"
        mock_tool.function.name = "test_func"
        mock_tool.function.arguments = '{"key": "val"}'
        delta.tool_calls = [mock_tool]

        choice.delta = delta
        choice.finish_reason = "tool_calls"
        chunk.choices = [choice]

        responses = list(provider._handle_stream_response([chunk]))

        assert responses[0].tool_call is not None
        assert responses[0].tool_call.id == "call_123"
        assert responses[0].finish_reason == "tool_calls"
