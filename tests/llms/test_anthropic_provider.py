import sys
from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.anthropic_provider import AnthropicProvider
from yaicli.schemas import ChatMessage


class TestAnthropicProvider:
    """Tests for the Anthropic provider"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://api.anthropic.com",
            "MODEL": "claude-3-sonnet-20240229",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    def test_init(self, mock_anthropic_cls, mock_config):
        """Test initialization of AnthropicProvider"""
        real_cls = AnthropicProvider.CLIENT_CLS
        try:
            AnthropicProvider.CLIENT_CLS = mock_anthropic_cls

            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client

            provider = AnthropicProvider(config=mock_config)
            assert provider.client == mock_client
            assert provider.config == mock_config
            assert provider.enable_function is True
            assert provider.enable_mcp is False
        finally:
            AnthropicProvider.CLIENT_CLS = real_cls

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    def test_client_params(self, mock_anthropic_cls, mock_config):
        """Test client parameters construction"""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        provider = AnthropicProvider(config=mock_config)

        client_params = provider.get_client_params()
        assert client_params["api_key"] == "fake_api_key"
        assert "default_headers" in client_params

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    def test_completion_params(self, mock_anthropic_cls, mock_config):
        """Test completion parameters construction"""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        provider = AnthropicProvider(config=mock_config)

        params = provider.get_completion_params()
        assert params["model"] == "claude-3-sonnet-20240229"
        assert params["temperature"] == 0.7
        assert params["top_p"] == 1.0
        assert params["max_tokens"] == 1000

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    @patch("yaicli.tools.get_anthropic_schemas", return_value=[{"name": "test_function"}])
    def test_completion_with_tools(self, mock_get_schemas, mock_anthropic_cls, mock_config):
        """Test completion with tools enabled"""
        real_cls = AnthropicProvider.CLIENT_CLS
        try:
            AnthropicProvider.CLIENT_CLS = mock_anthropic_cls

            # Setup mock client and schemas
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client

            # Create mock content block
            mock_content_block = MagicMock()
            mock_content_block.type = "text"
            mock_content_block.text = "Hello, world"

            mock_response = MagicMock()
            mock_response.content = [mock_content_block]
            mock_response.stop_reason = "stop"
            mock_client.messages.create.return_value = mock_response

            provider = AnthropicProvider(config=mock_config)
            messages = [ChatMessage(role="user", content="Hello")]
            responses = list(provider.completion(messages))

            # Verify client call
            mock_client.messages.create.assert_called_once()
            call_args = mock_client.messages.create.call_args
            assert call_args[1]["messages"] == [{"role": "user", "content": "Hello"}]
            assert "tools" in call_args[1]

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "Hello, world"
            assert responses[0].finish_reason == "stop"
        finally:
            AnthropicProvider.CLIENT_CLS = real_cls

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    def test_streaming_response(self, mock_anthropic_cls, mock_config):
        """Test streaming response handling"""
        real_cls = AnthropicProvider.CLIENT_CLS
        try:
            AnthropicProvider.CLIENT_CLS = mock_anthropic_cls

            # Set up mock client and stream
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client

            # Create mock chunks for streaming
            chunk1 = MagicMock()
            chunk1.type = "content_block_delta"
            chunk1.delta = MagicMock()
            chunk1.delta.text = "Hello"

            chunk2 = MagicMock()
            chunk2.type = "content_block_delta"
            chunk2.delta = MagicMock()
            chunk2.delta.text = " world"

            chunk3 = MagicMock()
            chunk3.type = "message_stop"
            chunk3.stop_reason = "stop"

            mock_client.messages.create.return_value = [chunk1, chunk2, chunk3]

            with patch.dict(sys.modules, {"yaicli.llms.providers.anthropic_provider": MagicMock()}):
                provider = AnthropicProvider(config=mock_config)
                provider.enable_function = False
                provider.enable_mcp = False

                messages = [ChatMessage(role="user", content="Hello")]
                responses = list(provider.completion(messages, stream=True))

                # Verify client call
                mock_client.messages.create.assert_called_once()
                call_args = mock_client.messages.create.call_args
                assert call_args[1]["stream"] is True

                # Verify response
                assert len(responses) == 3
                assert responses[0].content == "Hello"
                assert responses[1].content == " world"
                assert responses[2].content == ""
                assert responses[2].finish_reason == "stop"
        finally:
            AnthropicProvider.CLIENT_CLS = real_cls

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    @patch("yaicli.tools.get_anthropic_schemas", return_value=[{"name": "test_function"}])
    def test_tool_calls(self, mock_get_schemas, mock_anthropic_cls, mock_config):
        """Test tool call handling"""
        real_cls = AnthropicProvider.CLIENT_CLS
        try:
            AnthropicProvider.CLIENT_CLS = mock_anthropic_cls

            # Set up mock client
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client

            # Create a simulated response with tool calls
            mock_tool_use = MagicMock()
            mock_tool_use.type = "tool_use"
            mock_tool_use.id = "tool_1"
            mock_tool_use.name = "get_weather"
            mock_tool_use.input = {"location": "New York"}

            mock_content_block = MagicMock()
            mock_content_block.type = "text"
            mock_content_block.text = ""

            mock_response = MagicMock()
            mock_response.content = [mock_content_block, mock_tool_use]
            mock_response.stop_reason = "tool_calls"

            mock_client.messages.create.return_value = mock_response

            provider = AnthropicProvider(config=mock_config)
            messages = [ChatMessage(role="user", content="What's the weather?")]
            responses = list(provider.completion(messages))

            # Verify tool call in response
            assert len(responses) == 1
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.id == "tool_1"
            assert responses[0].tool_call.name == "get_weather"
            assert "New York" in responses[0].tool_call.arguments
        finally:
            AnthropicProvider.CLIENT_CLS = real_cls

    def test_detect_tool_role(self, mock_config):
        """Test detect_tool_role returns the correct role"""
        with patch("yaicli.llms.providers.anthropic_provider.Anthropic"):
            provider = AnthropicProvider(config=mock_config)
            assert provider.detect_tool_role() == "tool"

    def test_convert_messages_with_tool_results(self, mock_config):
        """Test _convert_messages properly handles tool results"""
        with patch("yaicli.llms.providers.anthropic_provider.Anthropic"):
            provider = AnthropicProvider(config=mock_config)
            
            from yaicli.schemas import ToolCall
            
            # Create messages with tool calls and results
            messages = [
                ChatMessage(role="user", content="What's the weather?"),
                ChatMessage(
                    role="assistant", 
                    content="I'll check the weather for you.",
                    tool_calls=[ToolCall(id="tool_1", name="get_weather", arguments='{"location": "New York"}')]
                ),
                ChatMessage(role="tool", content="15 degrees", tool_call_id="tool_1"),
            ]
            
            converted = provider._convert_messages(messages)
            
            # Check user message
            assert converted[0]["role"] == "user"
            assert converted[0]["content"] == "What's the weather?"
            
            # Check assistant message with tool call
            assert converted[1]["role"] == "assistant"
            assert isinstance(converted[1]["content"], list)
            assert len(converted[1]["content"]) == 2
            assert converted[1]["content"][0]["type"] == "text"
            assert converted[1]["content"][0]["text"] == "I'll check the weather for you."
            assert converted[1]["content"][1]["type"] == "tool_use"
            assert converted[1]["content"][1]["id"] == "tool_1"
            assert converted[1]["content"][1]["name"] == "get_weather"
            assert converted[1]["content"][1]["input"] == {"location": "New York"}
            
            # Check tool result as user message
            assert converted[2]["role"] == "user"
            assert isinstance(converted[2]["content"], list)
            assert len(converted[2]["content"]) == 1
            assert converted[2]["content"][0]["type"] == "tool_result"
            assert converted[2]["content"][0]["tool_use_id"] == "tool_1"
            assert converted[2]["content"][0]["content"] == "15 degrees"
