# type: ignore
from unittest.mock import MagicMock, patch

import pytest
from mistralai.models import ChatCompletionResponse
from mistralai.utils.eventstreaming import EventStream

from yaicli.exceptions import MCPToolsError
from yaicli.llms.providers.mistral_provider import MistralProvider
from yaicli.schemas import ChatMessage, ToolCall


class TestMistralProvider:
    """Tests for Mistral provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration for tests"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,
            "SERVER": None,
            "MODEL": "mistral-large-latest",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 30,
            "EXTRA_HEADERS": None,
            "STREAM": True,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def mock_mistral_client(self):
        """Create a mocked Mistral client"""
        client_mock = MagicMock()
        chat_mock = MagicMock()
        client_mock.chat = chat_mock
        return client_mock

    @pytest.fixture
    def patched_provider(self, mock_config):
        """Fixture that returns a patched MistralProvider instance to avoid repeated patching"""
        with patch("mistralai.Mistral"), patch("warnings.filterwarnings"):
            provider = MistralProvider(config=mock_config)
            yield provider

    def test_init(self, mock_config):
        """Test initialization of MistralProvider"""
        with patch("mistralai.Mistral"), patch("warnings.filterwarnings"):
            provider = MistralProvider(config=mock_config)

            # Check initialization parameters
            assert provider.config == mock_config
            assert provider.enable_functions == mock_config["ENABLE_FUNCTIONS"]
            assert provider.enable_mcp == mock_config["ENABLE_MCP"]

    def test_get_client_params(self, patched_provider, mock_config):
        """Test get_client_params method returns the expected parameters"""
        params = patched_provider.get_client_params()

        assert params == {
            "api_key": mock_config["API_KEY"],
            "timeout_ms": mock_config["TIMEOUT"] * 1000,
        }

    def test_get_client_params_with_base_url(self, mock_config):
        """Test get_client_params with custom base URL"""
        mock_config["BASE_URL"] = "https://custom-api.mistral.ai/v1"
        mock_config["SERVER"] = "custom-server"

        with patch("mistralai.Mistral"), patch("warnings.filterwarnings"):
            provider = MistralProvider(config=mock_config)
            params = provider.get_client_params()

            assert params == {
                "api_key": mock_config["API_KEY"],
                "timeout_ms": mock_config["TIMEOUT"] * 1000,
                "server_url": mock_config["BASE_URL"],
                "server": mock_config["SERVER"],
            }

    def test_get_completion_params(self, patched_provider, mock_config):
        """Test get_completion_params method returns the expected parameters"""
        params = patched_provider.get_completion_params()

        # Verify basic parameters
        assert params["model"] == mock_config["MODEL"]
        assert params["temperature"] == mock_config["TEMPERATURE"]
        assert params["top_p"] == mock_config["TOP_P"]
        assert params["max_tokens"] == mock_config["MAX_TOKENS"]
        assert params["stream"] == mock_config["STREAM"]
        assert params["http_headers"] == {
            "X-Title": patched_provider.APP_NAME,
            "HTTP_Referer": patched_provider.APP_REFERER,
        }

    def test_get_completion_params_with_extra_headers(self, mock_config):
        """Test get_completion_params with extra headers"""
        mock_config["EXTRA_HEADERS"] = {"X-Custom": "test"}

        with patch("mistralai.Mistral"), patch("warnings.filterwarnings"):
            provider = MistralProvider(config=mock_config)
            params = provider.get_completion_params()

            # Verify headers are combined correctly
            assert "X-Custom" in params["http_headers"]
            assert params["http_headers"]["X-Custom"] == "test"
            assert "X-Title" in params["http_headers"]

    @patch("yaicli.llms.providers.mistral_provider.get_openai_schemas")
    def test_get_completion_params_with_functions(self, mock_get_schemas, patched_provider):
        """Test get_completion_params with functions enabled"""
        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "test_func"}}]

        params = patched_provider.get_completion_params()

        # Verify functions are included
        assert "tools" in params
        assert params["tool_choice"] == "auto"
        assert params["parallel_tool_calls"] is False
        assert len(params["tools"]) == 1

    @patch("yaicli.llms.providers.mistral_provider.get_openai_schemas")
    @patch("yaicli.llms.providers.mistral_provider.get_openai_mcp_tools")
    def test_get_completion_params_with_mcp(self, mock_get_mcp_tools, mock_get_schemas, mock_config):
        """Test get_completion_params with MCP tools enabled"""
        mock_config["ENABLE_MCP"] = True

        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "test_func"}}]
        mock_get_mcp_tools.return_value = [{"type": "function", "function": {"name": "mcp_func"}}]

        with patch("mistralai.Mistral"), patch("warnings.filterwarnings"):
            provider = MistralProvider(config=mock_config)
            params = provider.get_completion_params()

            # Verify both function types are included
            assert "tools" in params
            assert len(params["tools"]) == 2

    @patch("yaicli.llms.providers.mistral_provider.get_openai_schemas")
    @patch("yaicli.llms.providers.mistral_provider.get_openai_mcp_tools")
    def test_get_completion_params_mcp_error(self, mock_get_mcp_tools, mock_get_schemas, mock_config):
        """Test error handling when MCP tools raise an error"""
        mock_config["ENABLE_MCP"] = True
        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "regular_func"}}]
        mock_get_mcp_tools.side_effect = MCPToolsError("Error loading MCP tools")

        with patch("mistralai.Mistral"), patch("warnings.filterwarnings"):
            provider = MistralProvider(config=mock_config)
            params = provider.get_completion_params()

            # Should still return valid parameters, just without MCP tools
            assert "tools" in params
            assert len(params["tools"]) == 1
            assert params["tools"][0]["function"]["name"] == "regular_func"

    # 创建通用的响应模拟辅助方法
    def _create_mock_normal_response(self, content="Test response", finish_reason="stop", tool_calls=None):
        """Helper method to create mock normal responses"""
        mock_response = MagicMock(spec=ChatCompletionResponse)
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = content

        if tool_calls:
            mock_message.tool_calls = tool_calls

        mock_choice.message = mock_message
        mock_choice.finish_reason = finish_reason
        mock_response.choices = [mock_choice]
        return mock_response

    def test_handle_normal_response(self, patched_provider):
        """Test _handle_normal_response method correctly processes a response"""
        # Create a mock response using helper method
        mock_response = self._create_mock_normal_response()

        # Process the response
        responses = list(patched_provider._handle_normal_response(mock_response))

        # Verify response handling
        assert len(responses) == 1
        assert responses[0].content == "Test response"
        assert responses[0].finish_reason == "stop"
        assert responses[0].tool_call is None

    def test_handle_normal_response_with_tool_calls(self, patched_provider):
        """Test _handle_normal_response with tool calls"""
        # Create a mock tool call
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_function = MagicMock()
        mock_function.name = "test_function"
        mock_function.arguments = '{"param": "value"}'
        mock_tool_call.function = mock_function

        # Create a mock response with tool call using helper method
        mock_response = self._create_mock_normal_response(
            content="Let me check something", finish_reason="tool_calls", tool_calls=[mock_tool_call]
        )

        # Process the response
        responses = list(patched_provider._handle_normal_response(mock_response))

        # Verify response handling
        assert len(responses) == 1
        assert responses[0].content == "Let me check something"
        assert responses[0].finish_reason == "tool_calls"
        assert responses[0].tool_call is not None
        assert responses[0].tool_call.name == "test_function"
        assert responses[0].tool_call.arguments == '{"param": "value"}'

    def test_process_tool_call_chunk(self, patched_provider):
        """Test _process_tool_call_chunk method correctly processes tool call data"""
        # Create mock tool calls
        mock_tool_call = MagicMock()
        mock_function = MagicMock()
        mock_function.name = "weather_function"
        mock_function.arguments = '{"location"'  # Partial JSON
        mock_tool_call.function = mock_function
        mock_tool_call.id = "call_123"

        # Process first chunk
        result = patched_provider._process_tool_call_chunk([mock_tool_call])

        assert result.id == "call_123"
        assert result.name == "weather_function"
        assert result.arguments == '{"location"'

        # Process second chunk with continuation of arguments
        mock_tool_call2 = MagicMock()
        mock_function2 = MagicMock()
        mock_function2.arguments = ': "New York"}'
        mock_tool_call2.function = mock_function2

        # Continue processing with existing tool call
        result = patched_provider._process_tool_call_chunk([mock_tool_call2], result)

        assert result.arguments == '{"location": "New York"}'

    def test_get_content_from_delta_content_string(self, patched_provider):
        """Test get_content_from_delta_content with string input"""
        content = patched_provider.get_content_from_delta_content("Hello world")
        assert content == "Hello world"

    @patch("yaicli.llms.providers.mistral_provider.MistralProvider.extract_contents_list")
    def test_get_content_from_delta_content_list(self, mock_extract_contents, patched_provider):
        """Test get_content_from_delta_content with ContentChunk list"""
        # Mock the extract_contents_list method return value
        mock_extract_contents.return_value = "Processed content"

        # Create a list that would be passed as ContentChunk list
        chunks = []

        # Call the method with our list
        content = patched_provider.get_content_from_delta_content(chunks)

        # Check if extract_contents_list was called with our list
        mock_extract_contents.assert_called_once_with(chunks)
        assert content == "Processed content"

    def test_extract_contents_list(self, patched_provider):
        """Test extract_contents_list method"""
        # Create mocks for different content chunk types
        text_chunk = MagicMock()
        text_chunk.type = "text"
        text_chunk.text = "Hello "

        image_chunk = MagicMock()
        image_chunk.type = "image_url"
        image_chunk.image_url = "http://example.com/image.png"

        image_chunk_obj = MagicMock()
        image_chunk_obj.type = "image_url"
        image_chunk_obj.image_url = MagicMock()
        image_chunk_obj.image_url.url = "http://example.com/image2.png"

        document_chunk = MagicMock()
        document_chunk.type = "document_url"
        document_chunk.document_url = "http://example.com/doc.pdf"
        document_chunk.document_name = "Document"

        reference_chunk = MagicMock()
        reference_chunk.type = "reference"
        reference_chunk.reference_ids = ["ref1", "ref2"]

        # Call the method with our mocked chunks
        chunks = [text_chunk, image_chunk, image_chunk_obj, document_chunk, reference_chunk]
        content = patched_provider.extract_contents_list(chunks)

        # Verify output contains expected content from each chunk type
        assert "Hello " in content
        assert "http://example.com/image.png" in content
        assert "http://example.com/image2.png" in content
        assert "[Document](http://example.com/doc.pdf)" in content
        assert "Reference IDs" in content
        assert "ref1" in content
        assert "ref2" in content

    def test_detect_tool_role(self, patched_provider):
        """Test detect_tool_role returns the expected role"""
        assert patched_provider.detect_tool_role() == "tool"

    def test_completion_non_streaming(self, patched_provider):
        """Test completion method with non-streaming response"""
        # Mock _convert_messages method
        patched_provider._convert_messages = MagicMock(return_value=[{"role": "user", "content": "Hello"}])

        # Create mock response using helper method
        mock_response = self._create_mock_normal_response()
        patched_provider.client.chat.complete = MagicMock(return_value=mock_response)

        # Create test messages
        messages = [ChatMessage(role="user", content="Hello")]

        # Call the completion method with streaming=False
        responses = list(patched_provider.completion(messages, stream=False))

        # Verify _convert_messages was called
        patched_provider._convert_messages.assert_called_once_with(messages)

        # Verify complete method was called with correct parameters
        patched_provider.client.chat.complete.assert_called_once()

        # Verify response
        assert len(responses) == 1
        assert responses[0].content == "Test response"
        assert responses[0].finish_reason == "stop"

    def test_completion_streaming(self, mock_config):
        """Test completion method with streaming response"""
        with patch("mistralai.Mistral"):
            with patch("warnings.filterwarnings"):
                # Set up mocks
                provider = MistralProvider(config=mock_config)

                # Mock _convert_messages method
                provider._convert_messages = MagicMock(return_value=[{"role": "user", "content": "Hello"}])

                # Create mock for stream response
                mock_event_stream = MagicMock(spec=EventStream)

                # Create mock for stream chunks
                mock_chunk1 = MagicMock()
                mock_choice1 = MagicMock()
                mock_delta1 = MagicMock()
                mock_delta1.content = "Hello"
                mock_choice1.delta = mock_delta1
                mock_choice1.finish_reason = None
                mock_chunk1.data.choices = [mock_choice1]

                mock_chunk2 = MagicMock()
                mock_choice2 = MagicMock()
                mock_delta2 = MagicMock()
                mock_delta2.content = " world"
                mock_choice2.delta = mock_delta2
                mock_choice2.finish_reason = "stop"
                mock_chunk2.data.choices = [mock_choice2]

                # Set up the mock event stream to yield our chunks
                mock_event_stream.__iter__ = MagicMock(return_value=iter([mock_chunk1, mock_chunk2]))

                # Mock client.chat.stream method
                provider.client.chat.stream = MagicMock(return_value=mock_event_stream)

                # Create test messages
                messages = [ChatMessage(role="user", content="Hello")]

                # Call the completion method with streaming=True
                responses = list(provider.completion(messages, stream=True))

                # Verify _convert_messages was called
                provider._convert_messages.assert_called_once_with(messages)

                # Verify stream method was called with correct parameters
                provider.client.chat.stream.assert_called_once()

                # Verify responses
                assert len(responses) == 2
                assert responses[0].content == "Hello"
                assert responses[0].finish_reason is None
                assert responses[1].content == " world"
                assert responses[1].finish_reason == "stop"

    def test_handle_stream_response_with_tool_calls(self, mock_config):
        """Test _handle_stream_response with tool calls"""
        with patch("mistralai.Mistral"):
            with patch("warnings.filterwarnings"):
                provider = MistralProvider(config=mock_config)

                # Create mock for stream response
                mock_event_stream = MagicMock(spec=EventStream)

                # Create first chunk with tool call start
                mock_chunk1 = MagicMock()
                mock_choice1 = MagicMock()
                mock_delta1 = MagicMock()
                mock_delta1.content = "Let me check"

                # Create mock tool call for first chunk
                mock_tool_call1 = MagicMock()
                mock_function1 = MagicMock()
                mock_function1.name = "get_weather"
                mock_function1.arguments = '{"location"'
                mock_tool_call1.function = mock_function1
                mock_tool_call1.id = "call_abc123"
                mock_delta1.tool_calls = [mock_tool_call1]

                mock_choice1.delta = mock_delta1
                mock_choice1.finish_reason = None
                mock_chunk1.data.choices = [mock_choice1]

                # Create second chunk with tool call completion
                mock_chunk2 = MagicMock()
                mock_choice2 = MagicMock()
                mock_delta2 = MagicMock()
                mock_delta2.content = ""

                # Create mock tool call for second chunk
                mock_tool_call2 = MagicMock()
                mock_function2 = MagicMock()
                mock_function2.arguments = ': "New York"}'
                mock_tool_call2.function = mock_function2
                mock_delta2.tool_calls = [mock_tool_call2]

                mock_choice2.delta = mock_delta2
                mock_choice2.finish_reason = "tool_calls"
                mock_chunk2.data.choices = [mock_choice2]

                # Set up the mock event stream to yield our chunks
                mock_event_stream.__iter__ = MagicMock(return_value=iter([mock_chunk1, mock_chunk2]))

                # Process the stream
                responses = list(provider._handle_stream_response(mock_event_stream))

                # Verify responses
                assert len(responses) == 2
                assert responses[0].content == "Let me check"
                assert responses[0].tool_call is None

                assert responses[1].content == ""
                assert responses[1].finish_reason == "tool_calls"
                assert responses[1].tool_call is not None
                assert responses[1].tool_call.arguments == '{"location": "New York"}'

    def test_handle_normal_response_edge_case(self, mock_config):
        """Test _handle_normal_response method with empty or invalid response"""
        with patch("mistralai.Mistral"):
            with patch("warnings.filterwarnings"):
                provider = MistralProvider(config=mock_config)

                # Create a mock response with no choices
                mock_response = MagicMock(spec=ChatCompletionResponse)
                mock_response.choices = []
                mock_response.model_dump_json = MagicMock(return_value='{"error": "no choices"}')

                # Process the response
                responses = list(provider._handle_normal_response(mock_response))

                # Verify response handling for edge case
                assert len(responses) == 1
                assert responses[0].content == '{"error": "no choices"}'
                assert responses[0].finish_reason == "stop"

    def test_completion_with_verbose(self, mock_config):
        """Test completion method with verbose flag enabled"""
        with patch("mistralai.Mistral"):
            with patch("warnings.filterwarnings"):
                # Enable verbose mode
                provider = MistralProvider(config=mock_config, verbose=True)

                # Mock console
                provider.console = MagicMock()

                # Mock _convert_messages method
                provider._convert_messages = MagicMock(return_value=[{"role": "user", "content": "Hello"}])

                # Mock client.chat.complete method
                mock_response = MagicMock(spec=ChatCompletionResponse)
                mock_choice = MagicMock()
                mock_message = MagicMock()
                mock_message.content = "Test response"
                mock_choice.message = mock_message
                mock_choice.finish_reason = "stop"
                mock_response.choices = [mock_choice]

                provider.client.chat.complete = MagicMock(return_value=mock_response)

                # Create test messages
                messages = [ChatMessage(role="user", content="Hello")]

                # Call the completion method with streaming=False
                list(provider.completion(messages, stream=False))

                # Verify console.print was called for verbose output
                provider.console.print.assert_any_call("Messages:")
                provider.console.print.assert_any_call([{"role": "user", "content": "Hello"}])

    def test_process_tool_call_chunk_with_dict_arguments(self, mock_config):
        """Test _process_tool_call_chunk with dictionary arguments instead of string"""
        with patch("mistralai.Mistral"):
            with patch("warnings.filterwarnings"):
                provider = MistralProvider(config=mock_config)

                # Create mock tool calls with dict arguments instead of string
                mock_tool_call = MagicMock()
                mock_function = MagicMock()
                mock_function.name = "weather_function"
                # Use a dict instead of a string for arguments
                mock_function.arguments = {"location": "New York"}
                mock_tool_call.function = mock_function
                mock_tool_call.id = "call_123"

                # Process the tool call
                result = provider._process_tool_call_chunk([mock_tool_call])

                # Verify arguments were converted to JSON string
                assert result.id == "call_123"
                assert result.name == "weather_function"
                assert result.arguments == '{"location": "New York"}'

    def test_process_tool_call_chunk_with_no_function(self, mock_config):
        """Test _process_tool_call_chunk with tool that has no function"""
        with patch("mistralai.Mistral"):
            with patch("warnings.filterwarnings"):
                provider = MistralProvider(config=mock_config)

                # Create a tool call with a missing function
                mock_tool_call = MagicMock()
                mock_tool_call.id = "call_456"
                mock_tool_call.function = None

                # Create a valid tool call
                mock_tool_call2 = MagicMock()
                mock_function = MagicMock()
                mock_function.name = "valid_function"
                mock_function.arguments = '{"valid": true}'
                mock_tool_call2.function = mock_function
                mock_tool_call2.id = "call_123"

                # Process both tool calls
                existing_tool_call = ToolCall("call_123", "valid_function", "")
                result = provider._process_tool_call_chunk([mock_tool_call, mock_tool_call2], existing_tool_call)

                # Verify valid function was processed and invalid one was skipped
                assert result.id == "call_123"
                assert result.name == "valid_function"
                assert result.arguments == '{"valid": true}'
