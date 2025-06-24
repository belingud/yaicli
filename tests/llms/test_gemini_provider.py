import json
from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.gemini_provider import GeminiProvider, wrap_function
from yaicli.schemas import ChatMessage


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

        wrapped = wrap_function(test_func)

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

    def test_get_client_params(self, mock_config):
        """Test get_client_params method returns the expected parameters"""
        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            params = provider.get_client_params()

            assert params == {
                "api_key": mock_config["API_KEY"],
            }

    def test_get_chat_config(self, mock_config):
        """Test get_chat_config method returns the expected configuration"""
        with patch("google.genai.Client"), patch("yaicli.tools.get_func_name_map", return_value={}):
            provider = GeminiProvider(config=mock_config)
            config = provider.get_chat_config()

            # Check basic parameters
            assert config.temperature == mock_config["TEMPERATURE"]
            assert config.top_p == mock_config["TOP_P"]
            assert config.top_k == mock_config["TOP_K"]
            assert config.max_output_tokens == mock_config["MAX_TOKENS"]
            assert config.presence_penalty == mock_config["PRESENCE_PENALTY"]
            assert config.frequency_penalty == mock_config["FREQUENCY_PENALTY"]
            assert config.seed == mock_config["SEED"]

            # Check HTTP options
            assert config.http_options.timeout == mock_config["TIMEOUT"] * 1000
            assert "X-Custom" in config.http_options.headers
            assert "X-Client" in config.http_options.headers
            assert "Referer" in config.http_options.headers

            # Check thinking config
            assert config.thinking_config.include_thoughts == mock_config["INCLUDE_THOUGHTS"]
            assert config.thinking_config.thinking_budget == mock_config["THINKING_BUDGET"]

    def test_get_chat_config_with_base_url(self, mock_config):
        """Test get_chat_config with custom base URL"""
        mock_config["BASE_URL"] = "https://custom-api.example.com"
        mock_config["API_VERSION"] = "v2"

        with patch("google.genai.Client"), patch("yaicli.tools.get_func_name_map", return_value={}):
            provider = GeminiProvider(config=mock_config)
            config = provider.get_chat_config()

            # Check custom base URL
            assert config.http_options.base_url == mock_config["BASE_URL"]
            assert config.http_options.api_version == mock_config["API_VERSION"]

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

    def test_convert_messages(self, mock_config):
        """Test _convert_messages method correctly converts messages"""
        with patch("google.genai.Client"), patch("yaicli.tools.get_func_name_map", return_value={}):
            provider = GeminiProvider(config=mock_config)

            # Create test messages
            messages = [
                ChatMessage(role="system", content="You are a helpful assistant"),
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi there"),
                ChatMessage(role="tool", name="calculate", content="42"),
            ]

            # Convert messages
            converted = provider._convert_messages(messages)

            # Check conversion results
            assert len(converted) == 3  # System message should be skipped

            # Check user message
            assert converted[0].role == "user"
            assert converted[0].parts[0].text == "Hello"

            # Check assistant message (mapped to "model")
            assert converted[1].role == "model"
            assert converted[1].parts[0].text == "Hi there"

            # Check tool message (mapped to user with special parts)
            assert converted[2].role == "user"
            assert len(converted[2].parts) == 1
            # Since Part.from_function_response returns a complex type, just verify it exists

    @patch("yaicli.llms.providers.gemini_provider.get_func_name_map")
    def test_gen_gemini_functions(self, mock_get_func_name_map, mock_config):
        """Test gen_gemini_functions method correctly wraps functions"""
        # Create mock function
        mock_func = MagicMock()
        mock_func.execute = MagicMock(return_value="result")

        # Set up mock return value
        mock_get_func_name_map.return_value = {"test_function": mock_func}

        with patch("google.genai.Client"):
            provider = GeminiProvider(config=mock_config)
            functions = provider.gen_gemini_functions()

            # Check function was wrapped correctly
            assert len(functions) == 1
            # Check if the function is callable
            assert callable(functions[0])

    @patch("yaicli.tools.get_func_name_map")
    def test_completion_non_streaming(self, mock_get_func_name_map, mock_config, mock_gemini_client):
        """Test non-streaming completion request"""
        # Set up mock functions
        mock_get_func_name_map.return_value = {}

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
            assert len(create_args[1]["history"]) == 1  # Only user message (system is set separately)
            assert create_args[1]["config"].system_instruction == "You are a helpful assistant"

            # Verify send_message call
            mock_chat.send_message.assert_called_once_with(message="Hello")

            # Verify response
            assert len(responses) == 1
            assert responses[0].content == "Test response"
            assert responses[0].reasoning is None
            assert responses[0].finish_reason == "stop"

    @patch("yaicli.tools.get_func_name_map")
    def test_completion_with_reasoning(self, mock_get_func_name_map, mock_config, mock_gemini_client):
        """Test completion with reasoning/thought part"""
        # Set up mock functions
        mock_get_func_name_map.return_value = {}

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
            assert responses[0].content == ""
            assert responses[0].reasoning == "Let me think about this"
            assert responses[0].finish_reason == "stop"

    @patch("yaicli.tools.get_func_name_map")
    def test_completion_streaming(self, mock_get_func_name_map, mock_config, mock_gemini_client):
        """Test streaming completion request"""
        # Set up mock functions
        mock_get_func_name_map.return_value = {}

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

    @patch("yaicli.tools.get_func_name_map")
    def test_completion_empty_response(self, mock_get_func_name_map, mock_config, mock_gemini_client):
        """Test handling of empty/invalid response"""
        # Set up mock functions
        mock_get_func_name_map.return_value = {}

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
