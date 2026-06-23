from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.cohere_provider import (
    CohereBadrockProvider,
    CohereProvider,
    CohereSagemakerProvider,
)
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall, ToolPolicy


class TestCohereProvider:
    """Tests for the Cohere provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://fake-api.cohere.com/v2",
            "MODEL": "command-r-plus",
            "TEMPERATURE": 0.7,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def mock_client(self):
        """Fixture to create a mock Cohere client"""
        with patch("yaicli.llms.providers.cohere_provider.ClientV2") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            yield mock_client

    def test_init(self, mock_config, mock_client):
        """Test initialization of CohereProvider"""
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

            # Check client parameters
            assert provider.client_params == {
                "api_key": mock_config["API_KEY"],
                "timeout": mock_config["TIMEOUT"],
                "base_url": mock_config["BASE_URL"],
            }

    def test_detect_tool_role(self, mock_config, mock_client):
        """Test detect_tool_role method"""
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)
            assert provider.detect_tool_role() == "tool"

    def test_convert_messages(self, mock_config, mock_client):
        """Test message conversion for Cohere format"""
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

            # Test basic message conversion
            messages = [
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi there"),
            ]

            converted = provider._convert_messages(messages)
            assert len(converted) == 2
            assert converted[0]["role"] == "user"
            assert converted[0]["content"] == "Hello"
            assert converted[1]["role"] == "assistant"
            assert converted[1]["content"] == "Hi there"

            # Test with tool calls
            tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')
            messages = [ChatMessage(role="assistant", content=None, tool_calls=[tool_call])]

            converted = provider._convert_messages(messages)
            assert len(converted) == 1
            assert converted[0]["role"] == "assistant"
            assert "tool_calls" in converted[0]
            assert len(converted[0]["tool_calls"]) == 1
            assert converted[0]["tool_calls"][0].id == "call_123"
            assert converted[0]["tool_calls"][0].function.name == "get_weather"
            assert converted[0]["tool_calls"][0].function.arguments == '{"location": "New York"}'

            # Test tool response
            messages = [ChatMessage(role="tool", content="Sunny, 25°C", tool_call_id="call_123")]

            converted = provider._convert_messages(messages)
            assert len(converted) == 1
            assert converted[0]["role"] == "tool"
            assert converted[0]["tool_call_id"] == "call_123"
            # Check content is formatted as document for tool messages
            assert converted[0]["content"][0]["type"] == "document"
            assert converted[0]["content"][0]["document"]["data"] == "Sunny, 25°C"

    @patch("yaicli.tools.get_openai_schemas")
    def test_prepare_tools(self, mock_get_schemas, mock_config, mock_client):
        """Test tool preparation"""
        # Force mock to return exact value we want to test against
        mock_tools = [{"type": "function", "function": {"name": "test_func"}}]
        mock_get_schemas.return_value = mock_tools

        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)
            # Mock the _prepare_tools method to return our controlled value
            with patch.object(provider, "_prepare_tools", return_value=mock_tools):
                tools = provider._prepare_tools()

                assert tools == mock_tools

                # Test with functions disabled
                mock_config["ENABLE_FUNCTIONS"] = False
                provider = CohereProvider(config=mock_config)
                with patch.object(provider, "_prepare_tools", return_value=None):
                    tools = provider._prepare_tools()
                    assert tools is None

    @patch("yaicli.tools.get_openai_schemas")
    def test_prepare_tools_request_tool_policy_disables_functions(self, mock_get_schemas, mock_config, mock_client):
        """Test request-scoped policy suppresses Cohere tools for a single request."""
        mock_get_schemas.return_value = [{"type": "function", "function": {"name": "test_func"}}]

        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)
            assert provider._prepare_tools(tool_policy=ToolPolicy(False, False)) is None

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_non_streaming(self, mock_get_schemas, mock_config, mock_client):
        """Test non-streaming completion request"""
        # Setup mock tools
        mock_tools = [{"type": "function", "function": {"name": "test_func"}}]
        mock_get_schemas.return_value = mock_tools

        # Setup mock response
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_content_item = MagicMock()
        mock_content_item.text = "Test response"
        mock_message.content = [mock_content_item]
        mock_message.tool_calls = []
        mock_response.message = mock_message

        # Ensure the mock client's chat method is properly set up
        mock_client.chat = MagicMock(return_value=mock_response)

        # Create provider and call completion
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

            # Mock _prepare_tools to return our controlled value
            with patch.object(provider, "_prepare_tools", return_value=mock_tools):
                with patch.object(
                    provider, "_handle_normal_response", return_value=[LLMResponse(content="Test response")]
                ):
                    messages = [ChatMessage(role="user", content="Hello")]
                    responses = list(provider.completion(messages, stream=False))

                    # Verify response
                    assert len(responses) == 1
                    assert responses[0].content == "Test response"

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_with_tool_call(self, mock_get_schemas, mock_config, mock_client):
        """Test completion with tool call response"""
        # Setup mock tools
        mock_tools = [{"type": "function", "function": {"name": "get_weather"}}]
        mock_get_schemas.return_value = mock_tools

        # Setup mock response with tool call
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_content_item = MagicMock()
        mock_content_item.text = "Let me check the weather"
        mock_message.content = [mock_content_item]
        mock_message.tool_plan = "I'll use get_weather to check the weather"

        # Mock tool call
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "get_weather"
        mock_tool_call.function.arguments = '{"location": "New York"}'
        mock_message.tool_calls = [mock_tool_call]

        mock_response.message = mock_message

        # Ensure the mock client's chat method is properly set up
        mock_client.chat = MagicMock(return_value=mock_response)

        # Create provider and call completion
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

            # Mock relevant methods to ensure test isolation
            with patch.object(provider, "_prepare_tools", return_value=mock_tools):
                with patch.object(
                    provider,
                    "_handle_normal_response",
                    return_value=[
                        LLMResponse(content="Let me check the weather"),
                        LLMResponse(content="I'll use get_weather to check the weather"),
                        LLMResponse(
                            tool_call=ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')
                        ),
                    ],
                ):
                    messages = [ChatMessage(role="user", content="What's the weather in New York?")]
                    responses = list(provider.completion(messages, stream=False))

                    # Verify responses - should get content and tool call
                    assert len(responses) == 3
                    assert responses[0].content == "Let me check the weather"
                    assert responses[1].content == "I'll use get_weather to check the weather"
                    assert responses[2].tool_call is not None
                    assert responses[2].tool_call.id == "call_123"
                    assert responses[2].tool_call.name == "get_weather"
                    assert responses[2].tool_call.arguments == '{"location": "New York"}'

    @patch("yaicli.tools.get_openai_schemas")
    def test_handle_streaming_content(self, mock_get_schemas, mock_config, mock_client):
        """Test handling of streaming content chunks"""
        # Create provider
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

            # Create mock content_delta events
            event1 = MagicMock()
            event1.type = "content-delta"
            event1.delta.message.content.text = "Hello"

            event2 = MagicMock()
            event2.type = "content-delta"
            event2.delta.message.content.text = " world"

            # Process events
            responses = list(provider._handle_streaming_response([event1, event2]))

            # Verify responses
            assert len(responses) == 2
            assert responses[0].content == "Hello"
            assert responses[1].content == " world"

    @patch("yaicli.tools.get_openai_schemas")
    def test_handle_streaming_tool_call(self, mock_get_schemas, mock_config, mock_client):
        """Test handling of streaming tool call chunks"""
        # Create provider
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

            # Create mock tool call events
            tool_start_event = MagicMock()
            tool_start_event.type = "tool-call-start"
            tool_start_event.delta.message.tool_calls = MagicMock()
            tool_start_event.delta.message.tool_calls.id = "call_123"
            tool_start_event.delta.message.tool_calls.function.name = "get_weather"
            tool_start_event.delta.message.tool_calls.function.arguments = '{"location": '

            tool_delta_event = MagicMock()
            tool_delta_event.type = "tool-call-delta"
            tool_delta_event.delta.message.tool_calls = MagicMock()
            tool_delta_event.delta.message.tool_calls.function.arguments = '"New York"}'

            tool_end_event = MagicMock()
            tool_end_event.type = "tool-call-end"

            # Process events
            responses = list(provider._handle_streaming_response([tool_start_event, tool_delta_event, tool_end_event]))

            # Verify responses
            assert len(responses) == 1
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.id == "call_123"
            assert responses[0].tool_call.name == "get_weather"
            assert responses[0].tool_call.arguments == '{"location": "New York"}'


class TestCohereBadrockProvider:
    """Tests for the CohereBadrock provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Add BASE_URL with None value
            "MODEL": "cohere.command-r-plus-v1",
            "REGION": "us-east-1",
            "TEMPERATURE": 0.7,
            "TIMEOUT": 60,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            # Add required AWS credentials
            "AWS_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": "fake-access-key",
            "AWS_SECRET_ACCESS_KEY": "fake-secret-key",
            "AWS_SESSION_TOKEN": "fake-session-token",
        }

    def test_init_and_client_creation(self, mock_config):
        """CohereBadrockProvider builds a real BedrockClientV2 from AWS credentials."""
        from cohere import BedrockClientV2

        provider = CohereBadrockProvider(config=mock_config)

        # A real Bedrock client was constructed (not mocked)
        assert isinstance(provider.client, BedrockClientV2)
        # AWS credentials were mapped into client_params; the Cohere api_key was dropped
        assert provider.client_params["aws_region"] == mock_config["AWS_REGION"]
        assert provider.client_params["aws_access_key"] == mock_config["AWS_ACCESS_KEY_ID"]
        assert "api_key" not in provider.client_params


class TestCohereSagemakerProvider:
    """Tests for the CohereSagemaker provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Add BASE_URL with None value
            "MODEL": "cohere.command-r-plus-v1",
            "ENDPOINT_URL": "https://example-sagemaker-endpoint.com",
            "REGION": "us-east-1",
            "TEMPERATURE": 0.7,
            "TIMEOUT": 60,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            # Add required AWS credentials
            "AWS_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": "fake-access-key",
            "AWS_SECRET_ACCESS_KEY": "fake-secret-key",
            "AWS_SESSION_TOKEN": "fake-session-token",
        }

    def test_init_and_client_creation(self, mock_config):
        """CohereSagemakerProvider builds a real SagemakerClientV2 from AWS credentials."""
        from cohere import SagemakerClientV2

        provider = CohereSagemakerProvider(config=mock_config)

        # A real Sagemaker client was constructed (not mocked)
        assert isinstance(provider.client, SagemakerClientV2)
        assert provider.client_params["aws_region"] == mock_config["AWS_REGION"]
        assert "api_key" not in provider.client_params


class TestCohereProviderMissingBranches:
    """Tests for missing coverage branches in CohereProvider"""

    @pytest.fixture
    def mock_config(self):
        return {
            "API_KEY": "test_cohere_key",
            "MODEL": "command-r-plus",
            "TEMPERATURE": 0.7,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 60,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    @pytest.fixture
    def mock_client(self):
        return MagicMock()

    def test_create_client_with_environment(self, mock_config):
        """create_client propagates ENVIRONMENT into client_params and builds a real ClientV2.

        cohere's ClientV2 derives its base URL from the environment enum (it reads
        ``environment.value``), so we pass a real ``ClientEnvironment`` and let the client
        be constructed for real rather than mocking it away.
        """
        from cohere import ClientEnvironment, ClientV2

        mock_config["ENVIRONMENT"] = ClientEnvironment.PRODUCTION

        provider = CohereProvider(config=mock_config)

        # Source: ENVIRONMENT from config is written into client_params
        assert provider.client_params["environment"] == ClientEnvironment.PRODUCTION
        # A real ClientV2 instance was created (not a mock)
        assert isinstance(provider.client, ClientV2)

    def test_prepare_tools_empty_with_verbose(self, mock_config, mock_client):
        """Test _prepare_tools with no tools and verbose=True"""
        mock_console = MagicMock()

        with (
            patch("yaicli.llms.providers.cohere_provider.get_openai_schemas", return_value=[]),
            patch.object(CohereProvider, "create_client", return_value=mock_client),
            patch("yaicli.llms.providers.cohere_provider.get_console", return_value=mock_console),
        ):
            provider = CohereProvider(config=mock_config, verbose=True)
            tools = provider._prepare_tools()

        assert tools == []
        mock_console.print.assert_any_call("No tools available", style="yellow")

    def test_streaming_with_none_chunk(self, mock_config, mock_client):
        """Test _handle_streaming_response skips None chunks"""
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

        chunk1 = MagicMock()
        chunk1.type = "content-delta"
        chunk1.delta.message.content.text = "hello"

        chunks = [None, chunk1, None]
        responses = list(provider._handle_streaming_response(chunks))

        # Only one response from the valid chunk
        assert len(responses) == 1
        assert responses[0].content == "hello"

    def test_streaming_tool_plan_delta(self, mock_config, mock_client):
        """Test _handle_streaming_response with tool-plan-delta event"""
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

        chunk = MagicMock()
        chunk.type = "tool-plan-delta"
        chunk.delta.message.tool_plan = "Planning to call function X"

        responses = list(provider._handle_streaming_response([chunk]))

        assert len(responses) == 1
        assert responses[0].content == "Planning to call function X"

    def test_streaming_tool_call_delta_without_tool_call(self, mock_config, mock_client):
        """Test tool-call-delta without prior tool-call-start is skipped"""
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

        chunk = MagicMock()
        chunk.type = "tool-call-delta"
        chunk.delta.message.tool_calls.function.arguments = '{"key": "val"}'

        responses = list(provider._handle_streaming_response([chunk]))

        # Should be skipped
        assert len(responses) == 0

    def test_normal_response_with_content(self, mock_config, mock_client):
        """Test _handle_normal_response with content items"""
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Response text"
        mock_response.message.content = [mock_content]
        mock_response.message.tool_calls = None

        responses = list(provider._handle_normal_response(mock_response))

        assert len(responses) == 1
        assert responses[0].content == "Response text"

    def test_normal_response_with_tool_calls(self, mock_config, mock_client):
        """Test _handle_normal_response with tool calls"""
        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)

        mock_response = MagicMock()
        mock_response.message.content = []
        mock_response.message.tool_plan = "Using tool X"
        mock_tool = MagicMock()
        mock_tool.id = "call_123"
        mock_tool.function.name = "test_func"
        mock_tool.function.arguments = '{"key": "val"}'
        mock_response.message.tool_calls = [mock_tool]

        responses = list(provider._handle_normal_response(mock_response))

        # Should yield tool plan + tool call
        assert len(responses) == 2
        assert responses[0].content == "Using tool X"
        assert responses[1].tool_call.id == "call_123"

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_verbose_prints_messages(self, mock_get_schemas, mock_config, mock_client):
        """Test completion with verbose=True prints messages"""
        mock_get_schemas.return_value = []
        mock_console = MagicMock()
        mock_response = MagicMock()
        mock_response.message.content = []
        mock_response.message.tool_calls = None
        mock_client.chat.return_value = mock_response

        with (
            patch.object(CohereProvider, "create_client", return_value=mock_client),
            patch("yaicli.llms.providers.cohere_provider.get_console", return_value=mock_console),
        ):
            provider = CohereProvider(config=mock_config, verbose=True)
            list(provider.completion([ChatMessage(role="user", content="hi")], stream=False))

        # Verify verbose output
        printed_texts = [str(call.args[0]) for call in mock_console.print.call_args_list]
        assert any("Messages:" in text for text in printed_texts)

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_stream_mode(self, mock_get_schemas, mock_config, mock_client):
        """Test completion with stream=True"""
        mock_get_schemas.return_value = []

        chunk = MagicMock()
        chunk.type = "content-delta"
        chunk.delta.message.content.text = "stream"
        mock_client.chat_stream.return_value = [chunk]

        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)
            responses = list(provider.completion([ChatMessage(role="user", content="hi")], stream=True))

        assert mock_client.chat_stream.called
        assert len(responses) == 1
        assert responses[0].content == "stream"

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_exception_handling(self, mock_get_schemas, mock_config, mock_client):
        """Test completion exception is caught and yields error response"""
        mock_get_schemas.return_value = []
        mock_client.chat.side_effect = RuntimeError("API error")

        with patch.object(CohereProvider, "create_client", return_value=mock_client):
            provider = CohereProvider(config=mock_config)
            responses = list(provider.completion([ChatMessage(role="user", content="hi")], stream=False))

        assert len(responses) == 1
        assert "Error in Cohere API call" in responses[0].content

    @patch("yaicli.tools.get_openai_schemas")
    def test_completion_exception_handling_verbose(self, mock_get_schemas, mock_config, mock_client):
        """Test completion exception with verbose=True prints traceback"""
        mock_get_schemas.return_value = []
        mock_client.chat.side_effect = RuntimeError("API error")
        mock_console = MagicMock()

        with (
            patch.object(CohereProvider, "create_client", return_value=mock_client),
            patch("yaicli.llms.providers.cohere_provider.get_console", return_value=mock_console),
        ):
            provider = CohereProvider(config=mock_config, verbose=True)
            responses = list(provider.completion([ChatMessage(role="user", content="hi")], stream=False))

        assert "Error in Cohere API call" in responses[0].content
        # Verify verbose error output
        printed = [str(call.args[0]) for call in mock_console.print.call_args_list]
        assert any("Error in Cohere completion" in text for text in printed)

    @pytest.fixture
    def bedrock_config(self):
        return {
            "API_KEY": "bedrock_key",
            "MODEL": "cohere.command-r-plus-v1:0",
            "TEMPERATURE": 0.7,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 60,
            "AWS_REGION": "us-east-1",
            "AWS_ACCESS_KEY": "access_key",
            "AWS_SECRET_KEY": "secret_key",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

    @patch("yaicli.tools.get_openai_schemas", return_value=[])
    @patch("yaicli.llms.providers.cohere_provider.BedrockClientV2")
    def test_bedrock_create_client_missing_key(self, mock_bedrock_cls, mock_get_schemas, bedrock_config):
        """Test CohereBadrockProvider.create_client raises on missing key"""
        bedrock_config.pop("AWS_REGION")

        with pytest.raises(ValueError, match="AWS_REGION"):
            CohereBadrockProvider(config=bedrock_config)
