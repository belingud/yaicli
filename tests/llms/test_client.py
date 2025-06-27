from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.client import LLMClient
from yaicli.llms.provider import Provider
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall


class MockProvider(Provider):
    """Mock provider for testing"""

    def __init__(self, responses=None):
        """Initialize with predefined responses"""
        self.responses = responses or [LLMResponse(content="Test response")]
        self.completion_called = False

    def completion(self, messages, stream=False):
        """Return predefined responses"""
        self.completion_called = True
        self.messages = messages
        self.stream = stream

        # Directly return predefined responses
        for response in self.responses:
            yield response

    def detect_tool_role(self):
        """Return tool role"""
        return "tool"


class TestLLMClient:
    """Tests for the LLMClient class"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://fake-api.openai.com/v1",
            "MODEL": "gpt-4",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "PROVIDER": "openai",
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            "MAX_RECURSION_DEPTH": 5,
        }

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_init_with_provider_name(self, mock_factory, mock_config):
        """Test initialization with provider name"""
        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        client = LLMClient(provider_name="openai", config=mock_config)

        mock_factory.assert_called_once_with("openai", config=mock_config, verbose=False)
        assert client.provider == mock_provider

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_init_with_default_provider(self, mock_factory, mock_config):
        """Test initialization with default provider from config"""
        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        client = LLMClient(config=mock_config)

        mock_factory.assert_called_once_with("openai", config=mock_config, verbose=False)
        assert client.provider == mock_provider

    def test_completion_without_tools(self, mock_config):
        """Test completion without tool calls"""
        # Create a mock provider with simple responses
        responses = [LLMResponse(content="Hello"), LLMResponse(content=" world!")]
        provider = MockProvider(responses=responses)

        # Create client with our mock provider
        client = LLMClient(provider=provider, config=mock_config)

        # Call completion
        messages = [ChatMessage(role="user", content="Say hello")]
        responses = list(client.completion_with_tools(messages))

        # Verify provider was called
        assert provider.completion_called
        assert provider.messages == messages

        # Verify responses were forwarded
        assert len(responses) == 2
        assert responses[0].content == "Hello"
        assert responses[1].content == " world!"

    @patch("yaicli.llms.client.execute_tool_call")
    def test_completion_with_tool_call(self, mock_execute_tool, mock_config):
        """Test completion with a tool call that gets executed"""
        # Setup tool call
        tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')

        # Setup mock tool execution result - Return successful result
        mock_execute_tool.return_value = ("Sunny and 75°F", True)

        # Create client with a custom mock provider that we'll control manually
        mock_provider = MagicMock(spec=Provider)

        # Set the return value for detect_tool_role
        mock_provider.detect_tool_role.return_value = "tool"

        # First call returns response with tool calls
        first_call_responses = [
            LLMResponse(content="Let me check the weather", finish_reason="tool_calls", tool_call=tool_call)
        ]

        # Second call returns regular text response
        second_call_responses = [LLMResponse(content="It's sunny in New York", finish_reason="stop")]

        # Set side_effect for the completion method
        mock_provider.completion.side_effect = [
            iter(first_call_responses),  # First call
            iter(second_call_responses),  # Second call (recursive)
        ]

        # Create client using our mock provider
        client = LLMClient(provider=mock_provider, config=mock_config)

        # Initial messages
        messages = [ChatMessage(role="user", content="What's the weather in New York?")]

        # Execute test
        responses = list(client.completion_with_tools(messages))

        # Verify provider.completion was called twice (original + recursive)
        assert mock_provider.completion.call_count == 2

        # Verify tool was executed
        mock_execute_tool.assert_called_once()
        args = mock_execute_tool.call_args[0]
        assert args[0].id == tool_call.id
        assert args[0].name == tool_call.name

        # Check responses - original response + RefreshLive + recursive response
        assert len(responses) == 3
        assert responses[0].content == "Let me check the weather"
        assert responses[2].content == "It's sunny in New York"

    @patch("yaicli.tools.execute_tool_call")
    def test_recursion_depth_limit(self, mock_execute_tool, mock_config):
        """Test that recursion depth is limited"""
        # Set a low recursion limit
        mock_config["MAX_RECURSION_DEPTH"] = 2

        # Setup tool call that will keep recursing
        tool_call = ToolCall(id="call_123", name="recursive_function", arguments="{}")

        # Use MagicMock instead of MockProvider
        mock_provider = MagicMock(spec=Provider)

        # Set return value for detect_tool_role
        mock_provider.detect_tool_role.return_value = "tool"

        # Configure completion method to always return responses with tool calls
        mock_provider.completion.side_effect = lambda *args, **kwargs: iter(
            [LLMResponse(content="Calling function", finish_reason="tool_calls", tool_call=tool_call)]
        )

        # Setup mock tool execution result
        mock_execute_tool.return_value = ("Function called", True)

        # Create client
        client = LLMClient(provider=mock_provider, config=mock_config)

        # Initial messages
        messages = [ChatMessage(role="user", content="Start recursion")]

        # Call with recursive provider
        list(client.completion_with_tools(messages))

        # Should have been called only up to MAX_RECURSION_DEPTH times
        assert mock_execute_tool.call_count <= mock_config["MAX_RECURSION_DEPTH"]

        # Check that provider.completion has been called at least once
        assert mock_provider.completion.called

    @patch("yaicli.tools.execute_tool_call")
    def test_functions_disabled(self, mock_execute_tool, mock_config):
        """Test that tool calls are not executed when functions are disabled"""
        # Disable functions
        mock_config["ENABLE_FUNCTIONS"] = False

        # Setup tool call
        tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')

        # Use responses that directly include tool calls
        responses = [LLMResponse(content="Let me check the weather", finish_reason="tool_calls", tool_call=tool_call)]

        # Set up mock provider
        provider = MockProvider(responses=responses)

        # Create client
        client = LLMClient(provider=provider, config=mock_config)

        # Initial messages
        messages = [ChatMessage(role="user", content="What's the weather in New York?")]

        # Call completion
        responses = list(client.completion_with_tools(messages))

        # Verify tool was NOT executed
        mock_execute_tool.assert_not_called()

        # Should only include the initial response
        assert len(responses) == 1
        assert responses[0].content == "Let me check the weather"
