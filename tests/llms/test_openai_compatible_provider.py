from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.openai_compatible_provider import OpenAICompatibleProvider
from yaicli.schemas import ChatMessage, LLMResponse


def make_tool_call(tc_id=None, name=None, arguments=""):
    """Build a mock streaming tool-call delta entry"""
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def make_chunk(content="", finish_reason=None, tool_calls=None, model_extra=None, choices_empty=False):
    """Build a mock streaming chunk"""
    chunk = MagicMock()
    if choices_empty:
        chunk.choices = []
        return chunk
    choice = MagicMock()
    delta = MagicMock()
    delta.content = content
    delta.model_extra = model_extra
    delta.tool_calls = tool_calls
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk.choices = [choice]
    return chunk


class TestOpenAICompatibleProvider:
    """Tests for OpenAICompatibleProvider streaming logic (complete-JSON detection)"""

    @pytest.fixture
    def mock_config(self):
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://fake-compatible.example.com/v1",
            "MODEL": "compatible-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def _make_provider(self, mock_config, chunks):
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = OpenAICompatibleProvider(config=mock_config)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = chunks
        provider.client = mock_client
        return provider

    @patch("yaicli.tools.get_openai_schemas", return_value=[])
    def test_streaming_plain_text(self, _schemas, mock_config):
        """Plain text streaming yields one response per chunk with no tool call"""
        chunks = [
            make_chunk(content="Hello", finish_reason=None, tool_calls=None),
            make_chunk(content=" world", finish_reason=None, tool_calls=None),
            make_chunk(content="!", finish_reason="stop", tool_calls=None),
        ]
        provider = self._make_provider(mock_config, chunks)
        responses = list(provider.completion([ChatMessage(role="user", content="hi")], stream=True))

        assert [r.content for r in responses] == ["Hello", " world", "!"]
        assert responses[-1].finish_reason == "stop"
        assert all(r.tool_call is None for r in responses)

    @patch("yaicli.tools.get_openai_schemas", return_value=[])
    def test_streaming_reasoning_content(self, _schemas, mock_config):
        """Reasoning content in model_extra is surfaced on the response"""
        chunks = [
            make_chunk(
                content="answer",
                finish_reason="stop",
                tool_calls=None,
                model_extra={"reasoning_content": "thinking hard"},
            ),
        ]
        provider = self._make_provider(mock_config, chunks)
        responses = list(provider.completion([ChatMessage(role="user", content="hi")], stream=True))

        assert responses[0].reasoning == "thinking hard"
        assert responses[0].content == "answer"

    @patch("yaicli.tools.get_openai_schemas", return_value=[])
    def test_tool_call_returned_early_on_complete_json(self, _schemas, mock_config):
        """A single chunk carrying complete JSON args returns the tool call even without finish_reason"""
        chunks = [
            make_chunk(
                content="",
                finish_reason=None,
                tool_calls=[make_tool_call("call_1", "get_weather", '{"location": "NYC"}')],
            ),
        ]
        provider = self._make_provider(mock_config, chunks)
        responses = list(provider.completion([ChatMessage(role="user", content="weather?")], stream=True))

        assert responses[0].tool_call is not None
        assert responses[0].tool_call.id == "call_1"
        assert responses[0].tool_call.name == "get_weather"
        assert responses[0].tool_call.arguments == '{"location": "NYC"}'
        # finish_reason is synthesized as tool_calls even though the chunk had none
        assert responses[0].finish_reason == "tool_calls"

    @patch("yaicli.tools.get_openai_schemas", return_value=[])
    def test_tool_call_incomplete_json_then_complete(self, _schemas, mock_config):
        """Partial JSON args do not return a tool call until the JSON parses"""
        chunks = [
            make_chunk(content="", finish_reason=None, tool_calls=[make_tool_call("call_1", "f", '{"x": ')]),
            make_chunk(content="", finish_reason="tool_calls", tool_calls=[make_tool_call(None, None, "1}")]),
        ]
        provider = self._make_provider(mock_config, chunks)
        responses = list(provider.completion([ChatMessage(role="user", content="go")], stream=True))

        # First chunk: JSON not yet valid -> no tool call surfaced
        assert responses[0].tool_call is None
        # Second chunk: JSON complete and finish_reason set -> tool call surfaced
        assert responses[1].tool_call is not None
        assert responses[1].tool_call.arguments == '{"x": 1}'
        assert responses[1].finish_reason == "tool_calls"

    @patch("yaicli.tools.get_openai_schemas", return_value=[])
    def test_first_chunk_without_choices_is_skipped(self, _schemas, mock_config):
        """An error-shaped first chunk with no choices is skipped, not yielded"""
        chunks = [
            make_chunk(choices_empty=True),
            make_chunk(content="hi", finish_reason="stop", tool_calls=None),
        ]
        provider = self._make_provider(mock_config, chunks)
        responses = list(provider.completion([ChatMessage(role="user", content="hi")], stream=True))

        assert len(responses) == 1
        assert responses[0].content == "hi"

    @patch("yaicli.tools.get_openai_schemas", return_value=[])
    def test_first_chunk_error_response_is_yielded(self, _schemas, mock_config):
        """When _first_chunk_error returns a response, it is yielded before the stream proper"""
        chunks = [
            make_chunk(choices_empty=True),
            make_chunk(content="ok", finish_reason="stop", tool_calls=None),
        ]
        provider = self._make_provider(mock_config, chunks)
        with patch.object(
            provider, "_first_chunk_error", return_value=LLMResponse(content="err", finish_reason="stop")
        ):
            responses = list(provider.completion([ChatMessage(role="user", content="hi")], stream=True))

        assert responses[0].content == "err"
        assert responses[1].content == "ok"

    @patch("yaicli.tools.get_openai_schemas", return_value=[])
    def test_mid_stream_chunk_without_choices_is_skipped(self, _schemas, mock_config):
        """A no-choices chunk in the middle of the stream is skipped"""
        chunks = [
            make_chunk(content="a", finish_reason=None, tool_calls=None),
            make_chunk(choices_empty=True),
            make_chunk(content="b", finish_reason="stop", tool_calls=None),
        ]
        provider = self._make_provider(mock_config, chunks)
        responses = list(provider.completion([ChatMessage(role="user", content="hi")], stream=True))

        assert [r.content for r in responses] == ["a", "b"]
