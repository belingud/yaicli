from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.deepseek_provider import DeepSeekProvider
from yaicli.schemas import ChatMessage, ToolCall


class TestDeepSeekProvider:
    """Tests for DeepSeek thinking mode compatibility."""

    @pytest.fixture
    def mock_config(self):
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "",
            "MODEL": "deepseek-v4-pro",
            "TEMPERATURE": 0.3,
            "FREQUENCY_PENALTY": 0.0,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": {},
            "REASONING_EFFORT": None,
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def provider(self, mock_config):
        with patch.object(DeepSeekProvider, "CLIENT_CLS"):
            return DeepSeekProvider(config=mock_config)

    @pytest.fixture
    def mock_client(self):
        chat_mock = MagicMock()
        completions_mock = MagicMock()
        completions_mock.create = MagicMock()
        chat_mock.completions = completions_mock

        client_mock = MagicMock()
        client_mock.chat = chat_mock
        return client_mock

    def _mock_response(self, content="OK", reasoning_content=None, finish_reason="stop"):
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = content
        mock_message.reasoning_content = reasoning_content
        mock_message.model_extra = None
        mock_message.tool_calls = None
        mock_choice.message = mock_message
        mock_choice.finish_reason = finish_reason
        mock_response.choices = [mock_choice]
        return mock_response

    def test_completion_forwards_enabled_thinking_extra_body(self, mock_config, mock_client):
        mock_config["EXTRA_BODY"] = {"thinking": {"type": "enabled"}}

        with patch.object(DeepSeekProvider, "CLIENT_CLS"):
            provider = DeepSeekProvider(config=mock_config)
        provider.client = mock_client
        mock_client.chat.completions.create.return_value = self._mock_response()

        list(provider.completion([ChatMessage(role="user", content="Hello")]))

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}

    def test_completion_preserves_disabled_thinking_extra_body(self, mock_config, mock_client):
        mock_config["EXTRA_BODY"] = {"thinking": {"type": "disabled"}}

        with patch.object(DeepSeekProvider, "CLIENT_CLS"):
            provider = DeepSeekProvider(config=mock_config)
        provider.client = mock_client
        mock_client.chat.completions.create.return_value = self._mock_response()

        list(provider.completion([ChatMessage(role="user", content="Hello")]))

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_completion_forwards_reasoning_effort(self, mock_config, mock_client):
        mock_config["REASONING_EFFORT"] = "high"

        with patch.object(DeepSeekProvider, "CLIENT_CLS"):
            provider = DeepSeekProvider(config=mock_config)
        provider.client = mock_client
        mock_client.chat.completions.create.return_value = self._mock_response()

        list(provider.completion([ChatMessage(role="user", content="Hello")]))

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning_effort"] == "high"

    def test_convert_messages_uses_reasoning_content_for_assistant_reasoning(self, provider):
        messages = [ChatMessage(role="assistant", content="Final answer", reasoning="Thinking content")]

        converted = provider._convert_messages(messages)

        assert converted == [{"role": "assistant", "content": "Final answer", "reasoning_content": "Thinking content"}]

    def test_convert_messages_preserves_tool_calls_with_reasoning_content(self, provider):
        tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"city": "Beijing"}')
        messages = [
            ChatMessage(
                role="assistant",
                content="Let me check",
                reasoning="I need weather data",
                tool_calls=[tool_call],
            )
        ]

        converted = provider._convert_messages(messages)

        assert converted[0]["reasoning_content"] == "I need weather data"
        assert "reasoning" not in converted[0]
        assert converted[0]["tool_calls"] == [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Beijing"}'},
            }
        ]

    def test_convert_messages_preserves_tool_response_call_id(self, provider):
        messages = [
            ChatMessage(role="tool", content="Cloudy", name="get_weather", tool_call_id="call_123"),
        ]

        converted = provider._convert_messages(messages)

        assert converted == [
            {"role": "tool", "content": "Cloudy", "name": "get_weather", "tool_call_id": "call_123"}
        ]

    def test_completion_maps_reasoning_content_to_reasoning(self, provider, mock_client):
        provider.client = mock_client
        mock_client.chat.completions.create.return_value = self._mock_response(
            content="Final answer",
            reasoning_content="Thinking content",
        )

        responses = list(provider.completion([ChatMessage(role="user", content="Question")]))

        assert responses[0].reasoning == "Thinking content"

    def test_stream_completion_maps_reasoning_content_to_reasoning(self, provider, mock_client):
        provider.client = mock_client
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = ""
        chunk.choices[0].delta.model_extra = {"reasoning_content": "Thinking chunk"}
        chunk.choices[0].delta.tool_calls = None
        chunk.choices[0].finish_reason = None
        mock_client.chat.completions.create.return_value = [chunk]

        responses = list(provider.completion([ChatMessage(role="user", content="Question")], stream=True))

        assert responses[0].reasoning == "Thinking chunk"
