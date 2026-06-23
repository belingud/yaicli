import sys
from unittest.mock import MagicMock, patch

import pytest

from yaicli.exceptions import ConfigMissingError, MCPToolsError
from yaicli.llms.providers.anthropic_provider import (
    AnthropicBedrockProvider,
    AnthropicProvider,
    AnthropicVertexProvider,
)
from yaicli.schemas import ChatMessage, ImageData, ToolPolicy


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

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    @patch("yaicli.tools.get_anthropic_mcp_tools", return_value=[{"name": "_mcp__clock"}])
    @patch("yaicli.tools.get_anthropic_schemas", return_value=[{"name": "test_function"}])
    def test_request_tool_policy_disables_tools(
        self, mock_get_schemas, mock_get_mcp_tools, mock_anthropic_cls, mock_config
    ):
        """Test request-scoped policy omits Anthropic tools and tool choice."""
        real_cls = AnthropicProvider.CLIENT_CLS
        try:
            mock_config["ENABLE_MCP"] = True
            AnthropicProvider.CLIENT_CLS = mock_anthropic_cls

            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client

            mock_text_block = MagicMock()
            mock_text_block.type = "text"
            mock_text_block.text = "ls -la"

            mock_response = MagicMock()
            mock_response.content = [mock_text_block]
            mock_response.stop_reason = "stop"
            mock_client.messages.create.return_value = mock_response

            provider = AnthropicProvider(config=mock_config)
            messages = [ChatMessage(role="user", content="List files")]
            list(provider.completion(messages, tool_policy=ToolPolicy(False, False)))

            call_kwargs = mock_client.messages.create.call_args.kwargs
            assert "tools" not in call_kwargs
            assert "tool_choice" not in call_kwargs
        finally:
            AnthropicProvider.CLIENT_CLS = real_cls

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    @patch("yaicli.tools.get_anthropic_schemas", return_value=[{"name": "test_function"}])
    def test_completion_with_thinking_blocks(self, mock_get_schemas, mock_anthropic_cls, mock_config):
        """Test completion with thinking blocks (reasoning content)"""
        real_cls = AnthropicProvider.CLIENT_CLS
        try:
            AnthropicProvider.CLIENT_CLS = mock_anthropic_cls

            # Set up mock client
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client

            # Create thinking block
            mock_thinking_block = MagicMock()
            mock_thinking_block.type = "thinking"
            mock_thinking_block.thinking = "Let me analyze this step by step..."

            # Create text block
            mock_text_block = MagicMock()
            mock_text_block.type = "text"
            mock_text_block.text = "Here's my analysis: The answer is 42."

            mock_response = MagicMock()
            mock_response.content = [mock_thinking_block, mock_text_block]
            mock_response.stop_reason = "stop"

            mock_client.messages.create.return_value = mock_response

            provider = AnthropicProvider(config=mock_config)
            messages = [ChatMessage(role="user", content="What's the answer to life, universe, and everything?")]
            responses = list(provider.completion(messages))

            # Verify response includes reasoning content
            assert len(responses) == 1
            assert responses[0].content == "Here's my analysis: The answer is 42."
            assert responses[0].reasoning == "Let me analyze this step by step..."
            assert responses[0].finish_reason == "stop"
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
                    tool_calls=[ToolCall(id="tool_1", name="get_weather", arguments='{"location": "New York"}')],
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


class TestAnthropicProviderCoverage:
    """Additional tests covering uncovered branches in anthropic_provider."""

    @pytest.fixture
    def mock_config(self):
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

    def _make_text_response(self):
        block = MagicMock()
        block.type = "text"
        block.text = "ok"
        resp = MagicMock()
        resp.content = [block]
        resp.stop_reason = "stop"
        return resp

    def test_init_missing_api_key_raises(self, mock_config):
        """__init__ raises ValueError when API_KEY is missing."""
        mock_config["API_KEY"] = ""
        with pytest.raises(ValueError, match="API_KEY is required"):
            AnthropicProvider(config=mock_config)

    def test_get_client_params_merges_extra_headers(self, mock_config):
        """EXTRA_HEADERS are merged into default_headers, with timeout and base_url applied."""
        mock_config["EXTRA_HEADERS"] = {"X-Custom": "abc"}
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config)
        params = provider.get_client_params()
        assert params["default_headers"]["X-Custom"] == "abc"
        assert params["timeout"] == 60
        assert params["base_url"] == "https://api.anthropic.com"

    def test_completion_extracts_system_prompt(self, mock_config):
        """System message is extracted into params['system'] and removed from messages."""
        mock_config["ENABLE_FUNCTIONS"] = False
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config)
            provider.client.messages.create.return_value = self._make_text_response()
            messages = [
                ChatMessage(role="system", content="You are helpful"),
                ChatMessage(role="user", content="hi"),
            ]
            list(provider.completion(messages))

        call_kwargs = provider.client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are helpful"
        roles = [m["role"] for m in call_kwargs["messages"]]
        assert "system" not in roles

    def test_completion_schemas_import_error(self, mock_config):
        """ImportError while loading function schemas is caught and reported."""
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config)
            provider.client.messages.create.return_value = self._make_text_response()
            mock_console = MagicMock()
            provider.console = mock_console
            with patch("yaicli.tools.get_anthropic_schemas", side_effect=ImportError):
                list(provider.completion([ChatMessage(role="user", content="hi")]))

        printed = [str(c.args[0]) for c in mock_console.print.call_args_list]
        assert any("Function tools not available" in t for t in printed)

    def test_completion_with_mcp_tools(self, mock_config):
        """MCP tools are appended when enable_mcp is set."""
        mock_config["ENABLE_MCP"] = True
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config)
            provider.client.messages.create.return_value = self._make_text_response()
            with (
                patch("yaicli.tools.get_anthropic_schemas", return_value=[{"name": "fn"}]),
                patch("yaicli.tools.get_anthropic_mcp_tools", return_value=[{"name": "mcp_fn"}]),
            ):
                list(provider.completion([ChatMessage(role="user", content="hi")]))

        call_kwargs = provider.client.messages.create.call_args.kwargs
        tool_names = [t["name"] for t in call_kwargs["tools"]]
        assert "mcp_fn" in tool_names

    def test_completion_mcp_tools_error(self, mock_config):
        """Errors loading MCP tools are caught and reported."""
        mock_config["ENABLE_MCP"] = True
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config)
            provider.client.messages.create.return_value = self._make_text_response()
            mock_console = MagicMock()
            provider.console = mock_console
            with (
                patch("yaicli.tools.get_anthropic_schemas", return_value=[]),
                patch("yaicli.tools.get_anthropic_mcp_tools", side_effect=MCPToolsError("boom")),
            ):
                list(provider.completion([ChatMessage(role="user", content="hi")]))

        printed = [str(c.args[0]) for c in mock_console.print.call_args_list]
        assert any("Failed to load MCP tools" in t for t in printed)

    def test_completion_verbose_prints(self, mock_config):
        """verbose=True prints system prompt, messages, tools, tool choice and extra body."""
        mock_config["EXTRA_BODY"] = {"foo": "bar"}
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config, verbose=True)
            provider.client.messages.create.return_value = self._make_text_response()
            mock_console = MagicMock()
            provider.console = mock_console
            with patch("yaicli.tools.get_anthropic_schemas", return_value=[{"name": "fn"}]):
                messages = [
                    ChatMessage(role="system", content="sys"),
                    ChatMessage(role="user", content="hi"),
                ]
                list(provider.completion(messages))

        printed = [str(c.args[0]) for c in mock_console.print.call_args_list]
        assert any("System prompt:" in t for t in printed)
        assert any("Tools:" in t for t in printed)
        assert any("Extra body:" in t for t in printed)

    def test_completion_api_error_raises(self, mock_config):
        """API errors are printed and re-raised."""
        mock_config["ENABLE_FUNCTIONS"] = False
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config)
            provider.client.messages.create.side_effect = RuntimeError("api down")
            mock_console = MagicMock()
            provider.console = mock_console
            with pytest.raises(RuntimeError, match="api down"):
                list(provider.completion([ChatMessage(role="user", content="hi")]))

        printed = [str(c.args[0]) for c in mock_console.print.call_args_list]
        assert any("Error:" in t for t in printed)

    def test_normal_response_empty_content(self, mock_config):
        """_handle_normal_response yields a serialized dump when content is empty."""
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config)

        resp = MagicMock()
        resp.content = []
        resp.model_dump.return_value = {"id": "msg_1"}
        responses = list(provider._handle_normal_response(resp))

        assert len(responses) == 1
        assert responses[0].finish_reason == "stop"
        assert "msg_1" in responses[0].content

    def test_stream_tool_use_full_flow(self, mock_config):
        """Streaming tool_use: message_start, block_start, partial_json deltas, stop, message_delta, message_stop."""
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config)

        c_start = MagicMock()
        c_start.type = "message_start"

        c_block_start = MagicMock()
        c_block_start.type = "content_block_start"
        c_block_start.content_block.type = "tool_use"
        c_block_start.content_block.id = "tool_1"
        c_block_start.content_block.name = "get_weather"

        c_delta1 = MagicMock()
        c_delta1.type = "content_block_delta"
        c_delta1.delta = MagicMock(spec=["partial_json"])
        c_delta1.delta.partial_json = '{"location":'

        c_delta2 = MagicMock()
        c_delta2.type = "content_block_delta"
        c_delta2.delta = MagicMock(spec=["partial_json"])
        c_delta2.delta.partial_json = ' "NYC"}'

        c_block_stop = MagicMock()
        c_block_stop.type = "content_block_stop"

        c_msg_delta = MagicMock()
        c_msg_delta.type = "message_delta"
        c_msg_delta.delta = MagicMock(spec=["stop_reason"])
        c_msg_delta.delta.stop_reason = "tool_use"

        c_msg_stop = MagicMock()
        c_msg_stop.type = "message_stop"

        chunks = [c_start, c_block_start, c_delta1, c_delta2, c_block_stop, c_msg_delta, c_msg_stop]
        responses = list(provider._handle_stream_response(chunks))

        tool_responses = [r for r in responses if r.tool_call is not None]
        assert tool_responses
        tc = tool_responses[0].tool_call
        assert tc.id == "tool_1"
        assert tc.name == "get_weather"
        assert "NYC" in tc.arguments

        reasons = [r.finish_reason for r in responses]
        assert "tool_use" in reasons
        assert "stop" in reasons

    def test_convert_messages_with_images(self, mock_config):
        """_convert_messages encodes url and base64 images plus a trailing text block."""
        with patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicProvider(config=mock_config)

        messages = [
            ChatMessage(
                role="user",
                content="describe these",
                images=[
                    ImageData(data="https://example.com/a.png", media_type="image/png", is_url=True),
                    ImageData(data="b64data", media_type="image/jpeg", is_url=False),
                ],
            )
        ]
        converted = provider._convert_messages(messages)

        content = converted[0]["content"]
        assert content[0] == {"type": "image", "source": {"type": "url", "url": "https://example.com/a.png"}}
        assert content[1]["source"]["type"] == "base64"
        assert content[1]["source"]["media_type"] == "image/jpeg"
        assert content[1]["source"]["data"] == "b64data"
        assert content[-1] == {"type": "text", "text": "describe these"}


class TestAnthropicBedrockProvider:
    """Tests for AnthropicBedrockProvider.get_client_params."""

    @pytest.fixture
    def bedrock_config(self):
        return {
            "API_KEY": "fake",
            "BASE_URL": None,
            "MODEL": "claude-3",
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
            "AWS_ACCESS_KEY_ID": "akid",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "AWS_SESSION_TOKEN": "token",
            "AWS_REGION": "us-east-1",
        }

    def test_get_client_params_from_config(self, bedrock_config):
        """AWS credentials from config are mapped into client params."""
        with patch.object(AnthropicBedrockProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicBedrockProvider(config=bedrock_config)
            params = provider.get_client_params()

        assert params["aws_access_key"] == "akid"
        assert params["aws_secret_key"] == "secret"
        assert params["aws_session_token"] == "token"
        assert params["aws_region"] == "us-east-1"

    def test_missing_aws_credential_raises(self, bedrock_config, monkeypatch):
        """Missing AWS credential (absent from config and env) raises ConfigMissingError."""
        bedrock_config.pop("AWS_REGION")
        monkeypatch.delenv("AWS_REGION", raising=False)
        with patch.object(AnthropicBedrockProvider, "CLIENT_CLS", MagicMock()):
            with pytest.raises(ConfigMissingError, match="AWS_REGION"):
                AnthropicBedrockProvider(config=bedrock_config)

    def test_missing_aws_credential_from_env(self, bedrock_config, monkeypatch):
        """A missing config credential is filled from the environment."""
        bedrock_config.pop("AWS_SESSION_TOKEN")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "env-token")
        with patch.object(AnthropicBedrockProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicBedrockProvider(config=bedrock_config)

        assert provider.config["AWS_SESSION_TOKEN"] == "env-token"


class TestAnthropicVertexProvider:
    """Tests for AnthropicVertexProvider.get_client_params."""

    @pytest.fixture
    def vertex_config(self):
        return {
            "API_KEY": "fake",
            "BASE_URL": None,
            "MODEL": "claude-3",
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
            "PROJECT_ID": "my-project",
            "CLOUD_ML_REGION": "us-central1",
        }

    def test_get_client_params_from_config(self, vertex_config):
        """PROJECT_ID and CLOUD_ML_REGION from config are mapped into client params."""
        with patch.object(AnthropicVertexProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicVertexProvider(config=vertex_config)
            params = provider.get_client_params()

        assert params["project_id"] == "my-project"
        assert params["region"] == "us-central1"

    def test_missing_project_id_raises(self, vertex_config, monkeypatch):
        """Missing PROJECT_ID (absent from config and env) raises ConfigMissingError."""
        vertex_config.pop("PROJECT_ID")
        monkeypatch.delenv("PROJECT_ID", raising=False)
        with patch.object(AnthropicVertexProvider, "CLIENT_CLS", MagicMock()):
            with pytest.raises(ConfigMissingError, match="PROJECT_ID"):
                AnthropicVertexProvider(config=vertex_config)

    def test_missing_region_from_env(self, vertex_config, monkeypatch):
        """A missing CLOUD_ML_REGION is filled from the environment."""
        vertex_config.pop("CLOUD_ML_REGION")
        monkeypatch.setenv("CLOUD_ML_REGION", "europe-west1")
        with patch.object(AnthropicVertexProvider, "CLIENT_CLS", MagicMock()):
            provider = AnthropicVertexProvider(config=vertex_config)

        assert provider.config["CLOUD_ML_REGION"] == "europe-west1"
