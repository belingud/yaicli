import json
from unittest.mock import MagicMock, call, patch

import pytest

from yaicli.llms.providers.gemini_provider import GeminiProvider
from yaicli.schemas import ChatMessage
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
