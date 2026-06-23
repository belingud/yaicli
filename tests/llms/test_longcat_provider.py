from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.anthropic_provider import AnthropicProvider
from yaicli.llms.providers.longcat_provider import (
    LongCatAnthropicProvider,
    LongCatProvider,
    _clean_longcat_reasoning,
    _parse_and_clean_longcat_content,
)
from yaicli.llms.providers.openai_provider import OpenAIProvider
from yaicli.schemas import LLMResponse, ToolCall

LONGCAT_TOOL_CONTENT = (
    "Let me help.\n"
    "<longcat_tool_call>test_function\n"
    "<longcat_arg_key>param1</longcat_arg_key>\n"
    "<longcat_arg_value>value1</longcat_arg_value>\n"
    "</longcat_tool_call>"
)


class TestLongCatProvider:
    """Test the LongCat provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://api.longcat.chat/v1/openai",
            "MODEL": "longcat-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of LongCatProvider"""
        with patch("openai.OpenAI"):
            provider = LongCatProvider(config=mock_config)

            # Check initialization of client params
            assert provider.client_params == {
                "api_key": mock_config["API_KEY"],
                "base_url": mock_config["BASE_URL"],
                "default_headers": {
                    "X-Title": provider.APP_NAME,
                    "HTTP_Referer": provider.APP_REFERER,
                },
            }

            # Check completion params (should use LongCat-specific mapping)
            expected_params = {
                "model": mock_config["MODEL"],
                "temperature": mock_config["TEMPERATURE"],
                "top_p": mock_config["TOP_P"],
                "max_tokens": mock_config["MAX_TOKENS"],
                "timeout": mock_config["TIMEOUT"],
            }
            assert provider.completion_params == expected_params

    def test_parse_longcat_tool_call(self):
        """Test parsing of LongCat tool call format"""
        from yaicli.llms.providers.longcat_provider import (
            _parse_and_clean_longcat_content,
        )

        content = """I'll help you with this task.
<longcat_tool_call>test_function
<longcat_arg_key>param1</longcat_arg_key>
<longcat_arg_value>value1</longcat_arg_value>
<longcat_arg_key>param2</longcat_arg_key>
<longcat_arg_value>value2</longcat_arg_value>
</longcat_tool_call>"""

        tool_call, cleaned_content = _parse_and_clean_longcat_content(content, "resp_123", False, None)

        # Verify tool call was parsed correctly
        assert tool_call is not None
        assert tool_call.name == "test_function"
        assert "param1" in tool_call.arguments
        assert "param2" in tool_call.arguments

        # Verify content was cleaned
        assert "I'll help you with this task." in cleaned_content
        assert "<longcat_tool_call>" not in cleaned_content

    def test_clean_longcat_reasoning(self):
        """Test cleaning LongCat tool call tags from reasoning"""
        from yaicli.llms.providers.longcat_provider import _clean_longcat_reasoning

        reasoning = """Let me think about this.
<longcat_tool_call>test_func
<longcat_arg_key>test</longcat_arg_key>
<longcat_arg_value>data</longcat_arg_value>
</longcat_tool_call>"""

        cleaned = _clean_longcat_reasoning(reasoning)
        assert "Let me think about this." in cleaned
        assert "<longcat_tool_call>" not in cleaned


class TestLongCatAnthropicProvider:
    """Test the LongCat Anthropic provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://api.longcat.chat/anthropic",
            "MODEL": "longcat-claude-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of LongCatAnthropicProvider"""
        with patch("yaicli.llms.providers.anthropic_provider.Anthropic"):
            provider = LongCatAnthropicProvider(config=mock_config)

            # Check that it uses the correct base URL and adds Bearer token
            client_params = provider.get_client_params()
            assert client_params["base_url"] == "https://api.longcat.chat/anthropic"
            assert client_params["default_headers"]["Authorization"] == "Bearer fake_api_key"

    def test_handle_normal_response_with_longcat_tool_call(self, mock_config):
        """Test normal response handling with LongCat tool call"""
        with patch("yaicli.llms.providers.anthropic_provider.Anthropic"):
            provider = LongCatAnthropicProvider(config=mock_config)

            # Create a mock response with LongCat tool call in content
            mock_response = MagicMock()
            mock_response.id = "resp_123"

            # Mock the content block with LongCat tool call
            mock_content_block = MagicMock()
            mock_content_block.type = "text"
            mock_content_block.text = """I'll execute the function for you.
<longcat_tool_call>test_function
<longcat_arg_key>input_data</longcat_arg_key>
<longcat_arg_value>sample data</longcat_arg_value>
</longcat_tool_call>"""

            mock_response.content = [mock_content_block]
            mock_response.stop_reason = "end_turn"

            # Mock the _handle_normal_response method to test the logic
            responses = list(provider._handle_normal_response(mock_response))

            # Verify response - should detect tool call and change finish_reason
            assert len(responses) == 1
            assert "I'll execute the function for you." in responses[0].content
            assert responses[0].finish_reason == "tool_use"
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.name == "test_function"
            assert "input_data" in responses[0].tool_call.arguments


class TestLongCatHelpers:
    """Tests for LongCat parsing helper functions."""

    def test_clean_reasoning_empty(self):
        """Empty reasoning is returned unchanged."""
        assert _clean_longcat_reasoning("") == ""

    def test_parse_empty_content(self):
        """Empty content yields no tool call."""
        assert _parse_and_clean_longcat_content("") == (None, "")

    def test_parse_no_tool_call(self):
        """Content without a tool call tag yields no tool call."""
        tool_call, cleaned = _parse_and_clean_longcat_content("just plain text")
        assert tool_call is None
        assert cleaned == "just plain text"

    def test_parse_tool_call_tag_without_args(self):
        """A tool call tag with no arg key/value pairs yields no tool call."""
        tool_call, _ = _parse_and_clean_longcat_content("<longcat_tool_call>fn</longcat_tool_call>")
        assert tool_call is None

    def test_parse_verbose_prints(self):
        """verbose=True prints the extracted tool call name; response_id is used as id."""
        console = MagicMock()
        tool_call, _ = _parse_and_clean_longcat_content(
            LONGCAT_TOOL_CONTENT, response_id="resp_1", verbose=True, console=console
        )
        assert tool_call is not None
        assert tool_call.id == "resp_1"
        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("Extracted tool call" in t for t in printed)

    def test_parse_generates_id_when_missing(self):
        """Without a response_id, a longcat_-prefixed id is generated."""
        tool_call, _ = _parse_and_clean_longcat_content(LONGCAT_TOOL_CONTENT)
        assert tool_call is not None
        assert tool_call.id.startswith("longcat_")


class TestLongCatProviderHandlers:
    """Tests for LongCatProvider response handling (OpenAI-compatible)."""

    @pytest.fixture
    def mock_config(self):
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://api.longcat.chat/openai",
            "MODEL": "longcat-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def provider(self, mock_config):
        with patch("openai.OpenAI"):
            return LongCatProvider(config=mock_config)

    def test_normal_tool_call_in_reasoning(self, provider):
        """finish_reason=stop with a tool call hidden in reasoning becomes tool_calls."""
        std = LLMResponse(reasoning=LONGCAT_TOOL_CONTENT, content="", finish_reason="stop")
        mock_response = MagicMock()
        mock_response.id = "resp_1"
        with patch.object(OpenAIProvider, "_handle_normal_response", return_value=iter([std])):
            responses = list(provider._handle_normal_response(mock_response))

        assert len(responses) == 1
        assert responses[0].finish_reason == "tool_calls"
        assert responses[0].tool_call.name == "test_function"

    def test_normal_reasoning_without_tool_call(self, provider):
        """finish_reason=stop with reasoning but no tool call yields the std response."""
        std = LLMResponse(reasoning="just thinking", content="answer", finish_reason="stop")
        with patch.object(OpenAIProvider, "_handle_normal_response", return_value=iter([std])):
            responses = list(provider._handle_normal_response(MagicMock()))

        assert responses[0].finish_reason == "stop"
        assert responses[0].tool_call is None

    def test_normal_non_stop_finish(self, provider):
        """A non-stop finish reason yields the std response unchanged."""
        std = LLMResponse(content="hello", finish_reason="length")
        with patch.object(OpenAIProvider, "_handle_normal_response", return_value=iter([std])):
            responses = list(provider._handle_normal_response(MagicMock()))

        assert responses[0].content == "hello"
        assert responses[0].finish_reason == "length"

    def test_stream_tool_call_in_reasoning(self, provider):
        """Streaming: reasoning accumulates a tool call, finish=stop -> tool_calls."""
        chunks = [
            LLMResponse(reasoning=LONGCAT_TOOL_CONTENT, content=""),
            LLMResponse(content="", finish_reason="stop"),
        ]
        mock_response = MagicMock()
        mock_response.id = "resp_1"
        with patch.object(OpenAIProvider, "_handle_stream_response", return_value=iter(chunks)):
            responses = list(provider._handle_stream_response(mock_response))

        tool_responses = [r for r in responses if r.tool_call]
        assert tool_responses
        assert tool_responses[0].finish_reason == "tool_calls"
        assert tool_responses[0].tool_call.name == "test_function"

    def test_stream_passthrough_tool_calls(self, provider):
        """Streaming: a chunk already marked tool_calls passes through."""
        tc = ToolCall(id="t1", name="fn", arguments="{}")
        chunks = [LLMResponse(content="", finish_reason="tool_calls", tool_call=tc)]
        with patch.object(OpenAIProvider, "_handle_stream_response", return_value=iter(chunks)):
            responses = list(provider._handle_stream_response(MagicMock()))

        assert responses[0].finish_reason == "tool_calls"
        assert responses[0].tool_call.id == "t1"

    def test_stream_plain_content(self, provider):
        """Streaming: plain content chunks (no tool call) yield as-is."""
        chunks = [LLMResponse(content="hello "), LLMResponse(content="world", finish_reason="stop")]
        with patch.object(OpenAIProvider, "_handle_stream_response", return_value=iter(chunks)):
            responses = list(provider._handle_stream_response(MagicMock()))

        contents = "".join(r.content for r in responses if r.content)
        assert "hello world" in contents


class TestLongCatAnthropicHandlers:
    """Tests for LongCatAnthropicProvider response handling (Anthropic-compatible)."""

    @pytest.fixture
    def mock_config(self):
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://api.longcat.chat/anthropic",
            "MODEL": "longcat-claude-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def provider(self, mock_config):
        with patch("yaicli.llms.providers.anthropic_provider.Anthropic"):
            return LongCatAnthropicProvider(config=mock_config)

    def test_get_client_params_with_extra_headers(self, mock_config):
        """EXTRA_HEADERS are merged into default_headers alongside the Bearer token."""
        mock_config["EXTRA_HEADERS"] = {"X-Custom": "v"}
        with patch("yaicli.llms.providers.anthropic_provider.Anthropic"):
            provider = LongCatAnthropicProvider(config=mock_config)
            params = provider.get_client_params()

        assert params["default_headers"]["X-Custom"] == "v"
        assert params["default_headers"]["Authorization"] == "Bearer fake_api_key"
        assert params["timeout"] == 60

    def test_normal_passthrough_tool_use(self, provider):
        """A parent-detected tool_use response is yielded as-is."""
        tc = ToolCall(id="t1", name="fn", arguments="{}")
        std = LLMResponse(content="x", finish_reason="tool_use", tool_call=tc)
        with patch.object(AnthropicProvider, "_handle_normal_response", return_value=iter([std])):
            responses = list(provider._handle_normal_response(MagicMock()))

        assert responses[0].finish_reason == "tool_use"
        assert responses[0].tool_call.id == "t1"

    def test_normal_tool_call_in_reasoning(self, provider):
        """end_turn with a tool call embedded in reasoning becomes tool_use."""
        std = LLMResponse(reasoning=LONGCAT_TOOL_CONTENT, content="", finish_reason="end_turn")
        mock_response = MagicMock()
        mock_response.id = "resp_1"
        with patch.object(AnthropicProvider, "_handle_normal_response", return_value=iter([std])):
            responses = list(provider._handle_normal_response(mock_response))

        assert responses[0].finish_reason == "tool_use"
        assert responses[0].tool_call.name == "test_function"

    def test_normal_end_turn_no_tool_call(self, provider):
        """end_turn without any tool call yields the original response."""
        std = LLMResponse(content="plain answer", finish_reason="end_turn")
        with patch.object(AnthropicProvider, "_handle_normal_response", return_value=iter([std])):
            responses = list(provider._handle_normal_response(MagicMock()))

        assert responses[0].content == "plain answer"
        assert responses[0].finish_reason == "end_turn"
        assert responses[0].tool_call is None

    def test_normal_other_finish_reason(self, provider):
        """A finish reason that is neither tool_use nor end_turn passes through."""
        std = LLMResponse(content="partial", finish_reason="max_tokens")
        with patch.object(AnthropicProvider, "_handle_normal_response", return_value=iter([std])):
            responses = list(provider._handle_normal_response(MagicMock()))

        assert responses[0].finish_reason == "max_tokens"

    def test_stream_tool_call_in_content(self, provider):
        """Streaming: tool call accumulates in content, finish=stop -> tool_use."""
        chunks = [
            LLMResponse(content=LONGCAT_TOOL_CONTENT),
            LLMResponse(content="", finish_reason="stop"),
        ]
        mock_response = MagicMock()
        mock_response.id = "resp_1"
        with patch.object(AnthropicProvider, "_handle_stream_response", return_value=iter(chunks)):
            responses = list(provider._handle_stream_response(mock_response))

        tool_responses = [r for r in responses if r.tool_call]
        assert tool_responses
        assert tool_responses[0].finish_reason == "tool_use"
        assert tool_responses[0].tool_call.name == "test_function"

    def test_stream_passthrough_tool_use(self, provider):
        """Streaming: a chunk already marked tool_use passes through."""
        tc = ToolCall(id="t1", name="fn", arguments="{}")
        chunks = [LLMResponse(content="", finish_reason="tool_use", tool_call=tc)]
        with patch.object(AnthropicProvider, "_handle_stream_response", return_value=iter(chunks)):
            responses = list(provider._handle_stream_response(MagicMock()))

        assert responses[0].finish_reason == "tool_use"
        assert responses[0].tool_call.id == "t1"

    def test_stream_plain_content(self, provider):
        """Streaming: plain content yields as-is."""
        chunks = [LLMResponse(content="hello "), LLMResponse(content="world", finish_reason="end_turn")]
        with patch.object(AnthropicProvider, "_handle_stream_response", return_value=iter(chunks)):
            responses = list(provider._handle_stream_response(MagicMock()))

        contents = "".join(r.content for r in responses if r.content)
        assert "hello world" in contents
