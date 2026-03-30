import json
from unittest.mock import MagicMock, call, patch

import pytest

from yaicli.llms.providers.gemini_provider import GeminiProvider
from yaicli.schemas import ChatMessage, ToolCall, ToolPolicy
from yaicli.tools.function import wrap_gemini_function


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
        """Test handling of empty/invalid response"""
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
            responses = list(provider.completion(messages, stream=False))

            # Verify response handling
            assert len(responses) == 1
            assert responses[0].content == json.dumps({"error": "No candidates"})
            assert responses[0].finish_reason == "stop"

    def test_detect_tool_role(self, mock_config):
        """Test detect_tool_role returns the expected role"""
        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            assert provider.detect_tool_role() == "user"

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
