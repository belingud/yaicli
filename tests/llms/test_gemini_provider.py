import json
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from yaicli.errors import AgentError, ErrorKind
from yaicli.llms.providers.gemini_provider import GeminiProvider
from yaicli.schemas import ChatMessage, ImageData, ToolCall, ToolPolicy
from yaicli.usage import Usage
from yaicli.tools.function import wrap_gemini_function


def _make_text_response(text: str = "ok"):
    """Build a minimal valid Gemini (non-streaming) response."""
    part = MagicMock()
    part.function_call = None
    part.thought = None
    part.text = text
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    candidate.finish_reason = "stop"
    response = MagicMock()
    response.candidates = [candidate]
    return response


class TestGeminiProvider:
    """Tests for Gemini provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration for tests"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,
            "MODEL": "gemini-pro",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "TOP_K": 40,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "PRESENCE_PENALTY": 0.1,
            "FREQUENCY_PENALTY": 0.2,
            "SEED": 42,
            "INCLUDE_THOUGHTS": True,
            "THINKING_BUDGET": 1000,
            "EXTRA_HEADERS": {"X-Custom": "test"},
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def mock_gemini_client(self):
        """Create a mocked Gemini client"""
        client_mock = MagicMock()
        chats_mock = MagicMock()
        client_mock.chats = chats_mock
        return client_mock

    def test_wrap_function(self):
        """Test the wrap_function decorator"""

        def test_func(x, y):
            """Test function docstring"""
            return x + y

        wrapped = wrap_gemini_function(test_func)

        # Check function attributes are preserved
        assert wrapped.__name__ == "test_func"
        assert wrapped.__doc__ == "Test function docstring"

        # Check function behavior is preserved
        assert wrapped(3, 4) == 7

    def test_init(self, mock_config):
        """Test initialization of GeminiProvider"""
        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)

            # Check initialization parameters
            assert provider.client_params["api_key"] == mock_config["API_KEY"]
            assert provider.enable_function == mock_config["ENABLE_FUNCTIONS"]
            assert provider.enable_mcp == mock_config["ENABLE_MCP"]

    def test_get_client_params(self, mock_config):
        """Test get_client_params method returns the expected parameters"""
        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            params = provider.get_client_params()

            assert params == {
                "api_key": mock_config["API_KEY"],
            }

    @patch("yaicli.llms.providers.gemini_provider.types.HttpOptions")
    @patch("yaicli.llms.providers.gemini_provider.types.ThinkingConfig")
    @patch("yaicli.llms.providers.gemini_provider.types.GenerateContentConfig")
    @patch("yaicli.tools.function.get_functions_gemini_format")
    def test_get_chat_config(
        self, mock_get_functions, mock_gen_config, mock_thinking_config, mock_http_options, mock_config
    ):
        """Test get_chat_config method returns the expected configuration"""
        mock_http_options.return_value = MagicMock()
        mock_thinking_config.return_value = MagicMock()
        mock_gen_config.return_value = MagicMock()
        mock_get_functions.return_value = []

        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            provider.get_chat_config()

            # Verify HttpOptions was called with correct parameters
            mock_http_options.assert_called_once_with(
                timeout=mock_config["TIMEOUT"] * 1000,
                headers={
                    **mock_config["EXTRA_HEADERS"],
                    "X-Client": provider.APP_NAME,
                    "Referer": provider.APP_REFERER,
                },
            )

            # Verify ThinkingConfig was called with correct parameters
            mock_thinking_config.assert_called_once_with(
                include_thoughts=mock_config["INCLUDE_THOUGHTS"], thinking_budget=int(mock_config["THINKING_BUDGET"])
            )

            # Verify GenerateContentConfig was called with correct parameters
            mock_gen_config.assert_called_once()
            call_args = mock_gen_config.call_args[1]
            assert call_args["max_output_tokens"] == mock_config["MAX_TOKENS"]
            assert call_args["temperature"] == mock_config["TEMPERATURE"]
            assert call_args["top_p"] == mock_config["TOP_P"]
            assert call_args["top_k"] == mock_config["TOP_K"]
            assert call_args["presence_penalty"] == mock_config["PRESENCE_PENALTY"]
            assert call_args["frequency_penalty"] == mock_config["FREQUENCY_PENALTY"]
            assert call_args["seed"] == mock_config["SEED"]
            assert call_args["thinking_config"] == mock_thinking_config.return_value
            assert call_args["http_options"] == mock_http_options.return_value

    @patch("yaicli.llms.providers.gemini_provider.types.HttpOptions")
    @patch("yaicli.llms.providers.gemini_provider.types.ThinkingConfig")
    @patch("yaicli.llms.providers.gemini_provider.types.GenerateContentConfig")
    @patch("yaicli.tools.function.get_functions_gemini_format")
    def test_get_chat_config_request_tool_policy_disables_tools(
        self, mock_get_functions, mock_gen_config, mock_thinking_config, mock_http_options, mock_config
    ):
        """Test request-scoped policy omits Gemini tool configuration."""
        mock_http_options.return_value = MagicMock()
        mock_thinking_config.return_value = MagicMock()
        mock_gen_config.return_value = MagicMock()
        mock_get_functions.return_value = [MagicMock()]
        mock_config["ENABLE_MCP"] = True

        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            provider.get_chat_config(tool_policy=ToolPolicy(False, False))

            call_args = mock_gen_config.call_args.kwargs
            assert "tools" not in call_args
            assert "automatic_function_calling" not in call_args

    @patch("yaicli.llms.providers.gemini_provider.types.HttpOptions")
    @patch("yaicli.llms.providers.gemini_provider.types.ThinkingConfig")
    @patch("yaicli.llms.providers.gemini_provider.types.GenerateContentConfig")
    def test_get_chat_config_with_base_url(self, mock_gen_config, mock_thinking_config, mock_http_options, mock_config):
        """Test get_chat_config with custom base URL"""
        mock_config["BASE_URL"] = "https://custom-api.example.com"
        mock_config["API_VERSION"] = "v2"

        mock_http_options.return_value = MagicMock()
        mock_thinking_config.return_value = MagicMock()
        mock_gen_config.return_value = MagicMock()

        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            provider.get_chat_config()

            # Verify HttpOptions was called with base_url and api_version
            mock_http_options.assert_called_once()
            call_args = mock_http_options.call_args[1]
            assert call_args["base_url"] == mock_config["BASE_URL"]
            assert call_args["api_version"] == mock_config["API_VERSION"]

    def test_map_role(self, mock_config):
        """Test _map_role method correctly maps roles"""
        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)

            # Test mapping assistant role to model
            assert provider._map_role("assistant") == "model"

            # Test other roles remain unchanged
            assert provider._map_role("user") == "user"
            assert provider._map_role("system") == "system"
            assert provider._map_role("tool") == "tool"

    @patch("yaicli.llms.providers.gemini_provider.types.Part")
    @patch("yaicli.llms.providers.gemini_provider.types.Content")
    def test_convert_messages(self, mock_content, mock_part, mock_config):
        """Test _convert_messages method correctly converts messages"""
        # Setup mocks
        mock_content_instance = MagicMock()
        mock_content.return_value = mock_content_instance

        mock_part_instance = MagicMock()
        mock_part.return_value = mock_part_instance
        mock_part.from_function_response.return_value = mock_part_instance

        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)

            # Create test messages
            messages = [
                ChatMessage(role="system", content="You are a helpful assistant"),
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi there"),
                ChatMessage(role="tool", name="calculate", content="42"),
            ]

            # Convert messages
            converted_messages = provider._convert_messages(messages)

            # Check Content constructor calls
            mock_content.assert_has_calls(
                [
                    # First call for user message
                    call(role="user", parts=[mock_part_instance]),
                    # Second call for assistant message (mapped to model)
                    call(role="model", parts=[mock_part_instance]),
                ],
                any_order=False,
            )

            # For tool message, we have to verify that the role was set to "user" manually
            # and that from_function_response was called
            mock_part.from_function_response.assert_called_once_with(name="calculate", response={"result": "42"})

            # Verify correct number of messages (system message should be skipped)
            assert len(converted_messages) == 3

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    @patch("yaicli.llms.providers.gemini_provider.get_mcp_manager")
    def test_gen_gemini_functions(self, mock_get_mcp_manager, mock_get_functions, mock_config):
        """Test gen_gemini_functions method correctly combines functions"""
        # Setup MCP functions
        mock_mcp_manager = MagicMock()
        mock_mcp_tools = [MagicMock(), MagicMock()]
        mock_mcp_manager.to_gemini_tools.return_value = mock_mcp_tools
        mock_get_mcp_manager.return_value = mock_mcp_manager

        # Setup regular functions
        mock_functions = [MagicMock(), MagicMock()]
        mock_get_functions.return_value = mock_functions

        with patch("google.genai.Client"):
            # Reset config to avoid side effects
            mock_config["ENABLE_FUNCTIONS"] = True
            mock_config["ENABLE_MCP"] = True

            # Test with both functions and MCP enabled
            provider = GeminiProvider(config=mock_config)
            functions = provider.gen_gemini_functions()

            # Should combine both function types
            assert len(functions) == 4  # 2 + 2
            mock_get_functions.assert_called_once()
            mock_get_mcp_manager.assert_called_once()

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_non_streaming(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test non-streaming completion request"""
        # Set up mock functions
        mock_get_functions.return_value = []

        # Set up mock response
        mock_response = MagicMock()
        mock_candidate = MagicMock()
        mock_content = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "Test response"
        mock_part.thought = None
        mock_part.function_call = None
        mock_content.parts = [mock_part]
        mock_candidate.content = mock_content
        mock_response.candidates = [mock_candidate]

        # Mock chat create and send_message
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        # Create provider with mocked client
        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            # Call completion
            messages = [
                ChatMessage(role="system", content="You are a helpful assistant"),
                ChatMessage(role="user", content="Hello"),
            ]
            responses = list(provider.completion(messages, stream=False))

            # Verify chat creation
            mock_gemini_client.chats.create.assert_called_once()
            create_args = mock_gemini_client.chats.create.call_args
            assert create_args[1]["model"] == mock_config["MODEL"]
            assert create_args[1]["config"].system_instruction == "You are a helpful assistant"

            # Verify send_message call
            mock_chat.send_message.assert_called_once_with(message="Hello")

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "Test response"
            assert responses[0].reasoning is None
            assert responses[0].finish_reason == "stop"

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_with_reasoning(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test completion with reasoning/thought part"""
        # Set up mock functions
        mock_get_functions.return_value = []

        # Set up mock response
        mock_response = MagicMock()
        mock_candidate = MagicMock()
        mock_content = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "Let me think about this"
        mock_part.thought = True  # This is a thought/reasoning part
        mock_part.function_call = None
        mock_content.parts = [mock_part]
        mock_candidate.content = mock_content
        mock_response.candidates = [mock_candidate]

        # Mock chat create and send_message
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        # Create provider with mocked client
        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            # Call completion
            messages = [
                ChatMessage(role="system", content="You are a helpful assistant"),
                ChatMessage(role="user", content="Solve this problem"),
            ]
            responses = list(provider.completion(messages, stream=False))

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == ""  # Empty content when there's only reasoning
            assert responses[0].reasoning == "Let me think about this"
            assert responses[0].finish_reason == "stop"

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_streaming(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test streaming completion request"""
        # Set up mock functions
        mock_get_functions.return_value = []

        # Set up mock stream chunks
        chunk1 = MagicMock()
        candidate1 = MagicMock()
        content1 = MagicMock()
        part1 = MagicMock()
        part1.text = "Hello"
        part1.thought = None
        part1.function_call = None
        content1.parts = [part1]
        candidate1.content = content1
        candidate1.finish_reason = None
        chunk1.candidates = [candidate1]

        chunk2 = MagicMock()
        candidate2 = MagicMock()
        content2 = MagicMock()
        part2 = MagicMock()
        part2.text = " world!"
        part2.thought = None
        part2.function_call = None
        content2.parts = [part2]
        candidate2.content = content2
        candidate2.finish_reason = "stop"
        chunk2.candidates = [candidate2]

        # Mock chat create and send_message_stream
        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = [chunk1, chunk2]
        mock_gemini_client.chats.create.return_value = mock_chat

        # Create provider with mocked client
        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            # Call completion with streaming
            messages = [
                ChatMessage(role="system", content="You are a helpful assistant"),
                ChatMessage(role="user", content="Hello"),
            ]
            responses = list(provider.completion(messages, stream=True))

            # Verify chat creation and stream request
            mock_gemini_client.chats.create.assert_called_once()
            mock_chat.send_message_stream.assert_called_once_with(message="Hello")

            # Verify responses
            assert len(responses) == 2
            assert responses[0].content == "Hello"
            assert responses[0].finish_reason is None

            assert responses[1].content == " world!"
            assert responses[1].finish_reason == "stop"

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_empty_response(self, mock_get_functions, mock_config, mock_gemini_client):
        """A response with no candidates raises a classified error instead of assistant text"""
        # Set up mock functions
        mock_get_functions.return_value = []

        # Set up mock empty response
        mock_response = MagicMock()
        mock_response.candidates = []  # Empty candidates list
        mock_response.to_json_dict.return_value = {"error": "No candidates"}

        # Mock chat create and send_message
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        # Create provider with mocked client
        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            # Call completion
            messages = [
                ChatMessage(role="system", content="You are a helpful assistant"),
                ChatMessage(role="user", content="Hello"),
            ]
            with pytest.raises(AgentError) as excinfo:
                list(provider.completion(messages, stream=False))

        assert excinfo.value.kind is ErrorKind.PROVIDER
        assert "Gemini API error" in str(excinfo.value)
        assert "No candidates" in str(excinfo.value)

    def test_detect_tool_role(self, mock_config):
        """Test detect_tool_role returns the expected role"""
        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            # "tool" is required so LLMClient creates ChatMessages that _convert_messages
            # turns into function_response parts (client.py uses detect_tool_role()).
            assert provider.detect_tool_role() == "tool"

    # ---- _normalize_fc_args tests ----

    def test_normalize_fc_args_proxy_format(self):
        """Test unwrapping proxy format: {'arguments': '{"city":"Beijing"}'} -> {'city':'Beijing'}"""
        args = {"arguments": '{"city": "Beijing"}'}
        assert GeminiProvider._normalize_fc_args(args) == {"city": "Beijing"}

    def test_normalize_fc_args_native_format(self):
        """Test native Gemini format is returned unchanged"""
        args = {"city": "Beijing", "unit": "celsius"}
        assert GeminiProvider._normalize_fc_args(args) == {"city": "Beijing", "unit": "celsius"}

    def test_normalize_fc_args_invalid_json(self):
        """Test invalid JSON in arguments key is returned as-is"""
        args = {"arguments": "{invalid json"}
        assert GeminiProvider._normalize_fc_args(args) == {"arguments": "{invalid json"}

    def test_normalize_fc_args_non_dict_json(self):
        """Test non-dict JSON parsed from arguments is returned as-is"""
        args = {"arguments": '"just a string"'}
        assert GeminiProvider._normalize_fc_args(args) == {"arguments": '"just a string"'}

    def test_normalize_fc_args_empty(self):
        """Test empty dict is returned unchanged"""
        assert GeminiProvider._normalize_fc_args({}) == {}

    # ---- _convert_messages with tool_calls tests ----

    @patch("yaicli.llms.providers.gemini_provider.types.FunctionCall")
    @patch("yaicli.llms.providers.gemini_provider.types.Part")
    @patch("yaicli.llms.providers.gemini_provider.types.Content")
    def test_convert_messages_assistant_with_tool_calls(self, mock_content, mock_part, mock_fc, mock_config):
        """Test converting assistant message with tool_calls to FunctionCall parts"""
        mock_content.return_value = MagicMock()
        mock_part.return_value = MagicMock()
        mock_fc.return_value = MagicMock()

        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            messages = [
                ChatMessage(role="system", content="system prompt"),
                ChatMessage(
                    role="assistant",
                    content="Let me check",
                    tool_calls=[
                        ToolCall(id="call_1", name="get_weather", arguments='{"city": "Beijing"}'),
                    ],
                ),
            ]
            result = provider._convert_messages(messages)

            assert len(result) == 1
            # Verify FunctionCall was created with correct args
            mock_fc.assert_called_once_with(name="get_weather", args={"city": "Beijing"})
            # Verify Content was created with role="model"
            mock_content.assert_called_once()
            assert mock_content.call_args[1]["role"] == "model"

    @patch("yaicli.llms.providers.gemini_provider.types.FunctionCall")
    @patch("yaicli.llms.providers.gemini_provider.types.Part")
    @patch("yaicli.llms.providers.gemini_provider.types.Content")
    def test_convert_messages_assistant_tool_calls_no_content(self, mock_content, mock_part, mock_fc, mock_config):
        """Test assistant message with tool_calls but no text content"""
        mock_content.return_value = MagicMock()
        mock_part.return_value = MagicMock()
        mock_fc.return_value = MagicMock()

        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            messages = [
                ChatMessage(role="system", content="system prompt"),
                ChatMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ToolCall(id="call_1", name="search", arguments='{"q": "test"}'),
                    ],
                ),
            ]
            result = provider._convert_messages(messages)

            assert len(result) == 1
            # text Part should NOT be created when content is None
            # Only the function_call Part should exist
            mock_part.assert_called_once()  # Only the function_call Part

    # ---- _handle_normal_response with function call tests ----

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_normal_response_with_function_call(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test non-streaming response containing a function call"""
        mock_get_functions.return_value = []

        # Build mock response with function_call part
        mock_fc = MagicMock()
        mock_fc.name = "get_weather"
        mock_fc.args = {"city": "Beijing"}
        mock_fc.id = "fc_123"

        mock_part = MagicMock()
        mock_part.function_call = mock_fc
        mock_part.thought = None

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="weather?"),
            ]
            responses = list(provider.completion(messages, stream=False))

            assert len(responses) == 1
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.name == "get_weather"
            assert json.loads(responses[0].tool_call.arguments) == {"city": "Beijing"}
            assert responses[0].tool_call.id == "fc_123"
            assert responses[0].finish_reason == "tool_calls"

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_normal_response_with_proxy_format_args(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test non-streaming response with proxy-wrapped arguments"""
        mock_get_functions.return_value = []

        mock_fc = MagicMock()
        mock_fc.name = "get_weather"
        mock_fc.args = {"arguments": '{"city": "Beijing"}'}
        mock_fc.id = None

        mock_part = MagicMock()
        mock_part.function_call = mock_fc
        mock_part.thought = None

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="weather?"),
            ]
            responses = list(provider.completion(messages, stream=False))

            assert responses[0].tool_call is not None
            # Proxy format should be unwrapped
            assert json.loads(responses[0].tool_call.arguments) == {"city": "Beijing"}

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_normal_response_function_call_empty_name_skipped(
        self, mock_get_functions, mock_config, mock_gemini_client
    ):
        """Test that function call parts with empty name are skipped"""
        mock_get_functions.return_value = []

        mock_fc = MagicMock()
        mock_fc.name = ""  # empty name
        mock_fc.args = {"city": "Beijing"}

        mock_part_fc = MagicMock()
        mock_part_fc.function_call = mock_fc
        mock_part_fc.thought = None

        mock_part_text = MagicMock()
        mock_part_text.function_call = None
        mock_part_text.thought = None
        mock_part_text.text = "Hello"

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part_fc, mock_part_text]
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="hi"),
            ]
            responses = list(provider.completion(messages, stream=False))

            # Empty-name fc skipped, only text part yielded
            assert len(responses) == 1
            assert responses[0].tool_call is None
            assert responses[0].content == "Hello"

    # ---- _handle_stream_response function call accumulation tests ----

    def _make_stream_chunk(self, parts, finish_reason=None):
        """Helper to build a mock streaming chunk"""
        chunk = MagicMock()
        candidate = MagicMock()
        content = MagicMock()
        content.parts = parts
        candidate.content = content
        candidate.finish_reason = finish_reason
        chunk.candidates = [candidate]
        return chunk

    def _make_fc_part(self, name, args):
        """Helper to build a mock function_call part"""
        part = MagicMock()
        fc = MagicMock()
        fc.name = name
        fc.args = args
        part.function_call = fc
        part.thought = None
        return part

    def _make_text_part(self, text, thought=None):
        """Helper to build a mock text part"""
        part = MagicMock()
        part.function_call = None
        part.thought = thought
        part.text = text
        return part

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_stream_single_chunk_function_call(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test streaming with a complete function call in a single chunk"""
        mock_get_functions.return_value = []

        fc_part = self._make_fc_part("get_weather", {"city": "Beijing"})
        chunk = self._make_stream_chunk([fc_part], finish_reason="stop")

        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = [chunk]
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="weather?"),
            ]
            responses = list(provider.completion(messages, stream=True))

            assert len(responses) == 1
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.name == "get_weather"
            assert json.loads(responses[0].tool_call.arguments) == {"city": "Beijing"}
            assert responses[0].finish_reason == "tool_calls"

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_stream_multi_chunk_function_call_accumulation(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test streaming accumulates function call args across multiple chunks"""
        mock_get_functions.return_value = []

        # Simulate proxy splitting args across chunks
        chunk1 = self._make_stream_chunk(
            [self._make_fc_part("get_weather", {"arguments": '{"city": "Bei'})],
        )
        chunk2 = self._make_stream_chunk(
            [self._make_fc_part("", {"arguments": 'jing"}'})],  # empty name = continuation
        )

        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = [chunk1, chunk2]
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="weather?"),
            ]
            responses = list(provider.completion(messages, stream=True))

            assert len(responses) == 1
            tc = responses[0].tool_call
            assert tc is not None
            assert tc.name == "get_weather"
            # Accumulated and unwrapped from proxy format
            assert json.loads(tc.arguments) == {"city": "Beijing"}

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_stream_text_then_function_call(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test streaming with text chunks followed by a function call"""
        mock_get_functions.return_value = []

        text_chunk = self._make_stream_chunk(
            [self._make_text_part("Let me check")],
            finish_reason=None,
        )
        fc_chunk = self._make_stream_chunk(
            [self._make_fc_part("get_weather", {"city": "Beijing"})],
            finish_reason="stop",
        )

        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = [text_chunk, fc_chunk]
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="weather?"),
            ]
            responses = list(provider.completion(messages, stream=True))

            # First response is text, second is tool call
            assert len(responses) == 2
            assert responses[0].content == "Let me check"
            assert responses[0].tool_call is None
            assert responses[1].tool_call is not None
            assert responses[1].tool_call.name == "get_weather"

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_stream_multiple_different_function_calls(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test streaming with two different function calls"""
        mock_get_functions.return_value = []

        chunk1 = self._make_stream_chunk(
            [self._make_fc_part("get_weather", {"city": "Beijing"})],
        )
        chunk2 = self._make_stream_chunk(
            [self._make_fc_part("get_time", {"timezone": "UTC"})],
        )

        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = [chunk1, chunk2]
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="weather and time?"),
            ]
            responses = list(provider.completion(messages, stream=True))

            # Both function calls yielded
            assert len(responses) == 2
            assert responses[0].tool_call.name == "get_weather"
            assert responses[1].tool_call.name == "get_time"
            assert json.loads(responses[1].tool_call.arguments) == {"timezone": "UTC"}

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_stream_skips_empty_name_without_current(self, mock_get_functions, mock_config, mock_gemini_client):
        """Test that function_call with empty name and no prior name is skipped"""
        mock_get_functions.return_value = []

        # First chunk has empty name and no prior context — should be skipped
        chunk1 = self._make_stream_chunk(
            [self._make_fc_part("", {"city": "Beijing"})],
        )
        chunk2 = self._make_stream_chunk(
            [self._make_text_part("Hello")],
            finish_reason="stop",
        )

        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = [chunk1, chunk2]
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="hi"),
            ]
            responses = list(provider.completion(messages, stream=True))

            # Only the text response, no tool call
            assert len(responses) == 1
            assert responses[0].content == "Hello"
            assert responses[0].tool_call is None

    # ---- tool-round protocol / last-message de-duplication tests ----

    def test_client_tool_message_converts_to_function_response(self, mock_config):
        """Messages built by LLMClient (role == detect_tool_role()) become function_response parts."""
        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)

        tool_role = provider.detect_tool_role()
        assert tool_role == "tool"

        messages = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="read a.txt"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call_1", name="fs_read_file", arguments='{"path": "a.txt"}')],
            ),
            # exactly what LLMClient._execute_tools_and_continue appends
            ChatMessage(role=tool_role, content="file contents", name="fs_read_file", tool_call_id="call_1"),
        ]

        converted = provider._convert_messages(messages)

        assert [content.role for content in converted] == ["user", "model", "user"]
        function_call = converted[1].parts[0].function_call
        assert function_call is not None
        assert function_call.name == "fs_read_file"
        tool_content = converted[-1]
        assert len(tool_content.parts) == 1
        function_response = tool_content.parts[0].function_response
        assert function_response is not None
        assert function_response.name == "fs_read_file"
        assert function_response.response == {"result": "file contents"}

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_last_user_message_not_duplicated_in_history(
        self, mock_get_functions, mock_config, mock_gemini_client
    ):
        """The final user message is sent exactly once (via send_message), not also in history."""
        mock_get_functions.return_value = []

        mock_response = _make_text_response("ok")

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys prompt"),
                ChatMessage(role="user", content="first question"),
                ChatMessage(role="assistant", content="first answer"),
                ChatMessage(role="user", content="second question"),
            ]
            list(provider.completion(messages, stream=False))

        history = mock_gemini_client.chats.create.call_args[1]["history"]
        assert [content.parts[0].text for content in history] == ["first question", "first answer"]
        assert mock_chat.send_message.call_args[1]["message"] == "second question"

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_streaming_last_user_message_not_duplicated_in_history(
        self, mock_get_functions, mock_config, mock_gemini_client
    ):
        """Streaming path also keeps the final user message out of the history."""
        mock_get_functions.return_value = []

        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = []
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys prompt"),
                ChatMessage(role="user", content="first question"),
                ChatMessage(role="assistant", content="first answer"),
                ChatMessage(role="user", content="second question"),
            ]
            list(provider.completion(messages, stream=True))

        history = mock_gemini_client.chats.create.call_args[1]["history"]
        assert [content.parts[0].text for content in history] == ["first question", "first answer"]
        assert mock_chat.send_message_stream.call_args[1]["message"] == "second question"

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_tool_round_sends_function_response_parts(
        self, mock_get_functions, mock_config, mock_gemini_client
    ):
        """A tool round sends the tool result as function_response parts, not plain user text."""
        mock_get_functions.return_value = []

        mock_response = _make_text_response("ok")

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys prompt"),
                ChatMessage(role="user", content="read a.txt"),
                ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="call_1", name="fs_read_file", arguments='{"path": "a.txt"}')],
                ),
                ChatMessage(
                    role=provider.detect_tool_role(),
                    content="file contents",
                    name="fs_read_file",
                    tool_call_id="call_1",
                ),
            ]
            list(provider.completion(messages, stream=False))

        # The tool result turn is not part of history; only user prompt + model function_call are.
        history = mock_gemini_client.chats.create.call_args[1]["history"]
        assert [content.role for content in history] == ["user", "model"]
        assert history[1].parts[0].function_call.name == "fs_read_file"

        message = mock_chat.send_message.call_args[1]["message"]
        assert isinstance(message, list)
        assert len(message) == 1
        function_response = message[0].function_response
        assert function_response is not None
        assert function_response.name == "fs_read_file"
        assert function_response.response == {"result": "file contents"}

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_streaming_tool_round_sends_function_response_parts(
        self, mock_get_functions, mock_config, mock_gemini_client
    ):
        """Streaming tool round also sends function_response parts (not plain user text)."""
        mock_get_functions.return_value = []

        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = []
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys prompt"),
                ChatMessage(role="user", content="read a.txt"),
                ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="call_1", name="fs_read_file", arguments='{"path": "a.txt"}')],
                ),
                ChatMessage(
                    role=provider.detect_tool_role(),
                    content="file contents",
                    name="fs_read_file",
                    tool_call_id="call_1",
                ),
            ]
            list(provider.completion(messages, stream=True))

        history = mock_gemini_client.chats.create.call_args[1]["history"]
        assert [content.role for content in history] == ["user", "model"]

        message = mock_chat.send_message_stream.call_args[1]["message"]
        assert isinstance(message, list)
        assert message[0].function_response.name == "fs_read_file"
        assert message[0].function_response.response == {"result": "file contents"}

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_last_message_with_images_sends_parts(self, mock_get_functions, mock_config, mock_gemini_client):
        """De-duplication must not drop image parts of the final user message."""
        mock_get_functions.return_value = []

        mock_response = _make_text_response("ok")

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys prompt"),
                ChatMessage(
                    role="user",
                    content="describe the image",
                    images=[ImageData(data="aGVsbG8=", media_type="image/png", is_url=False)],
                ),
            ]
            list(provider.completion(messages, stream=False))

        history = mock_gemini_client.chats.create.call_args[1]["history"]
        assert history == []
        message = mock_chat.send_message.call_args[1]["message"]
        assert isinstance(message, list)
        assert message[0].inline_data is not None
        assert message[0].inline_data.mime_type == "image/png"
        assert message[1].text == "describe the image"

    # ---- parallel tool responses (grouped into one function_response turn) ----

    @staticmethod
    def _parallel_tool_round_messages(tool_role="tool"):
        """Messages exactly as LLMClient builds them after executing two parallel tools."""
        return [
            ChatMessage(role="system", content="sys prompt"),
            ChatMessage(role="user", content="read a.txt and b.txt"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(id="call_a", name="fs_read_file", arguments='{"path": "a.txt"}'),
                    ToolCall(id="call_b", name="fs_read_file", arguments='{"path": "b.txt"}'),
                ],
            ),
            ChatMessage(role=tool_role, content="contents A", name="fs_read_file", tool_call_id="call_a"),
            ChatMessage(role=tool_role, content="contents B", name="fs_read_file", tool_call_id="call_b"),
        ]

    def test_convert_messages_groups_consecutive_tool_responses(self, mock_config):
        """Consecutive tool messages become one user Content with all function_response parts."""
        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)

        converted = provider._convert_messages(self._parallel_tool_round_messages())

        assert [content.role for content in converted] == ["user", "model", "user"]
        # both function calls stay in the same model turn
        assert len(converted[1].parts) == 2
        assert [part.function_call.name for part in converted[1].parts] == ["fs_read_file", "fs_read_file"]
        # both tool results are grouped into a single user turn
        tool_turn = converted[-1]
        assert len(tool_turn.parts) == 2
        assert [part.function_response.name for part in tool_turn.parts] == ["fs_read_file", "fs_read_file"]
        assert [part.function_response.response for part in tool_turn.parts] == [
            {"result": "contents A"},
            {"result": "contents B"},
        ]

    def test_convert_messages_does_not_merge_non_consecutive_tool_responses(self, mock_config):
        """Tool messages separated by another message form separate user Contents."""
        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)

        messages = [
            ChatMessage(role="tool", content="first", name="fs_read_file", tool_call_id="call_a"),
            ChatMessage(role="assistant", content="in between"),
            ChatMessage(role="tool", content="second", name="fs_read_file", tool_call_id="call_b"),
        ]

        converted = provider._convert_messages(messages)

        assert [content.role for content in converted] == ["user", "model", "user"]
        assert len(converted[0].parts) == 1
        assert converted[0].parts[0].function_response.response == {"result": "first"}
        assert len(converted[2].parts) == 1
        assert converted[2].parts[0].function_response.response == {"result": "second"}

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_parallel_tool_followup_sends_one_function_response_turn(
        self, mock_get_functions, mock_config, mock_gemini_client
    ):
        """Two parallel calls: history excludes the grouped tool turn, send carries both parts."""
        mock_get_functions.return_value = []

        mock_response = _make_text_response("ok")

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = self._parallel_tool_round_messages(tool_role=provider.detect_tool_role())
            list(provider.completion(messages, stream=False))

        history = mock_gemini_client.chats.create.call_args[1]["history"]
        assert [content.role for content in history] == ["user", "model"]
        # the grouped tool turn is sent as the new message, not left in history
        assert all(part.function_response is None for content in history for part in content.parts)

        message = mock_chat.send_message.call_args[1]["message"]
        assert isinstance(message, list)
        assert len(message) == 2
        assert [part.function_response.name for part in message] == ["fs_read_file", "fs_read_file"]
        assert [part.function_response.response for part in message] == [
            {"result": "contents A"},
            {"result": "contents B"},
        ]

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")
    def test_completion_streaming_parallel_tool_followup_sends_one_function_response_turn(
        self, mock_get_functions, mock_config, mock_gemini_client
    ):
        """Streaming variant of the parallel tool-response grouping."""
        mock_get_functions.return_value = []

        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = []
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = self._parallel_tool_round_messages(tool_role=provider.detect_tool_role())
            list(provider.completion(messages, stream=True))

        history = mock_gemini_client.chats.create.call_args[1]["history"]
        assert [content.role for content in history] == ["user", "model"]
        assert all(part.function_response is None for content in history for part in content.parts)

        message = mock_chat.send_message_stream.call_args[1]["message"]
        assert isinstance(message, list)
        assert len(message) == 2
        assert [part.function_response.response for part in message] == [
            {"result": "contents A"},
            {"result": "contents B"},
        ]

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format", return_value=[])
    def test_completion_api_error_raises_classified(self, mock_get_functions, mock_config, mock_gemini_client):
        """A Gemini request failure raises a classified AgentError, never assistant text."""
        mock_chat = MagicMock()
        mock_chat.send_message.side_effect = httpx.ConnectError("connection refused")
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="Hello"),
            ]
            with pytest.raises(AgentError) as excinfo:
                list(provider.completion(messages, stream=False))

        assert excinfo.value.kind is ErrorKind.NETWORK
        assert excinfo.value.retryable is True
        assert "Gemini API error" in str(excinfo.value)

    @patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format", return_value=[])
    def test_completion_stream_midstream_error_raises_classified(
        self, mock_get_functions, mock_config, mock_gemini_client
    ):
        """A stream that breaks mid-iteration raises a classified error, not an empty success."""
        good_part = MagicMock()
        good_part.function_call = None
        good_part.thought = None
        good_part.text = "partial"
        good_content = MagicMock()
        good_content.parts = [good_part]
        good_candidate = MagicMock()
        good_candidate.content = good_content
        good_candidate.finish_reason = "STOP"
        good_chunk = MagicMock()
        good_chunk.candidates = [good_candidate]

        def broken_stream():
            yield good_chunk
            raise httpx.ReadTimeout("read timed out")

        mock_chat = MagicMock()
        mock_chat.send_message_stream.return_value = broken_stream()
        mock_gemini_client.chats.create.return_value = mock_chat

        with patch("google.genai.Client", return_value=mock_gemini_client):
            provider = GeminiProvider(config=mock_config)
            provider.client = mock_gemini_client

            messages = [
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="Hello"),
            ]
            collected = []
            with pytest.raises(AgentError) as excinfo:
                for response in provider.completion(messages, stream=True):
                    collected.append(response)

        assert [r.content for r in collected] == ["partial"]
        assert excinfo.value.kind is ErrorKind.TIMEOUT
        assert excinfo.value.retryable is True


class TestGeminiUsage:
    """v0.22 K17: ``usage_metadata`` reaches LLMResponse."""

    @pytest.fixture
    def mock_config(self):
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,
            "MODEL": "gemini-2.5-flash",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "TOP_K": 40,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "PRESENCE_PENALTY": 0.0,
            "FREQUENCY_PENALTY": 0.0,
            "SEED": None,
            "INCLUDE_THOUGHTS": True,
            "EXTRA_HEADERS": {},
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

    def _provider(self, config):
        with patch("google.genai.Client", return_value=MagicMock()):
            return GeminiProvider(config=config)

    @staticmethod
    def _text_part(text):
        part = MagicMock()
        part.text = text
        part.thought = None
        part.function_call = None
        return part

    @staticmethod
    def _usage_metadata(prompt=7, completion=3, total=10, cached=1, thoughts=2):
        metadata = MagicMock()
        metadata.prompt_token_count = prompt
        metadata.candidates_token_count = completion
        metadata.total_token_count = total
        metadata.cached_content_token_count = cached
        metadata.thoughts_token_count = thoughts
        return metadata

    def test_non_stream_usage_attached(self, mock_config):
        provider = self._provider(mock_config)
        response = MagicMock()
        content = MagicMock()
        content.parts = [self._text_part("hello")]
        candidate = MagicMock()
        candidate.content = content
        response.candidates = [candidate]
        response.usage_metadata = self._usage_metadata()

        responses = list(provider._handle_normal_response(response))

        assert len(responses) == 1
        assert responses[0].content == "hello"
        assert responses[0].usage == Usage(
            prompt_tokens=7, completion_tokens=3, total_tokens=10, cached_tokens=1, reasoning_tokens=2
        )

    def test_non_stream_parallel_calls_attach_usage_to_first_only(self, mock_config):
        provider = self._provider(mock_config)
        parts = []
        for index in range(2):
            part = MagicMock()
            part.function_call.name = f"fs_read_file_{index}"
            part.function_call.args = {"path": "a.txt"}
            part.function_call.id = f"call_{index}"
            parts.append(part)
        response = MagicMock()
        content = MagicMock()
        content.parts = parts
        candidate = MagicMock()
        candidate.content = content
        response.candidates = [candidate]
        response.usage_metadata = self._usage_metadata()

        responses = list(provider._handle_normal_response(response))

        assert len(responses) == 2
        assert responses[0].usage is not None
        assert responses[1].usage is None

    def test_stream_usage_terminal_response(self, mock_config):
        provider = self._provider(mock_config)
        chunks = []
        for text, finish_reason in (("Hello", None), (" world", "stop")):
            chunk = MagicMock()
            content = MagicMock()
            content.parts = [self._text_part(text)]
            candidate = MagicMock()
            candidate.content = content
            candidate.finish_reason = finish_reason
            chunk.candidates = [candidate]
            chunks.append(chunk)
        chunks[-1].usage_metadata = self._usage_metadata()

        responses = list(provider._handle_stream_response(chunks))

        assert [response.content for response in responses] == ["Hello", " world", ""]
        assert responses[-1].usage == Usage(
            prompt_tokens=7, completion_tokens=3, total_tokens=10, cached_tokens=1, reasoning_tokens=2
        )
        # Usage is attached to one terminal response only.
        assert sum(1 for response in responses if response.usage is not None) == 1


# ---------------------------------------------------------------------------
# v0.23 K22: provider metadata hook
# ---------------------------------------------------------------------------


class TestGeminiModelLimits:
    """``GeminiProvider.model_limits`` maps ``models.get`` limits to ModelLimits."""

    @pytest.fixture
    def provider(self):
        with patch("yaicli.llms.providers.gemini_provider.genai.Client") as client_cls:
            mock_client = MagicMock()
            client_cls.return_value = mock_client
            provider = GeminiProvider(
                config={
                    "API_KEY": "fake_api_key",
                    "BASE_URL": None,
                    "MODEL": "gemini-2.5-pro",
                    "ENABLE_FUNCTIONS": False,
                    "ENABLE_MCP": False,
                }
            )
        return provider

    @staticmethod
    def _info(input_token_limit=1_048_576, output_token_limit=65_536):
        return MagicMock(input_token_limit=input_token_limit, output_token_limit=output_token_limit)

    def test_returns_metadata_limits(self, provider):
        provider.client.models.get.return_value = self._info()

        limits = provider.model_limits("gemini-2.5-pro")

        assert limits is not None
        assert limits.window == 1_048_576
        assert limits.max_output == 65_536
        assert limits.source == "metadata"
        assert limits.detail == "gemini models.get"
        provider.client.models.get.assert_called_once_with(model="models/gemini-2.5-pro")

    def test_falls_back_to_bare_model_id_when_prefixed_lookup_fails(self, provider):
        provider.client.models.get.side_effect = [RuntimeError("404 model not found"), self._info()]

        limits = provider.model_limits("gemini-2.5-pro")

        assert limits is not None and limits.window == 1_048_576
        assert provider.client.models.get.call_args_list == [
            call(model="models/gemini-2.5-pro"),
            call(model="gemini-2.5-pro"),
        ]

    def test_both_lookups_failing_returns_none_silently(self, provider, capsys):
        provider.client.models.get.side_effect = RuntimeError("quota exceeded")

        assert provider.model_limits("gemini-2.5-pro") is None
        assert capsys.readouterr().err == ""

    def test_info_without_token_limits_returns_none(self, provider):
        provider.client.models.get.return_value = self._info(input_token_limit=None, output_token_limit=None)

        assert provider.model_limits("gemini-2.5-pro") is None

    def test_empty_model_returns_none_without_probe(self, provider):
        assert provider.model_limits("") is None
        provider.client.models.get.assert_not_called()

    def test_no_provider_side_caching(self, provider):
        provider.client.models.get.return_value = self._info()

        first = provider.model_limits("gemini-2.5-pro")
        second = provider.model_limits("gemini-2.5-pro")

        assert first == second
        assert provider.client.models.get.call_count == 2
