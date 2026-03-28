# type: ignore
from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.client import LLMClient
from yaicli.llms.provider import Provider
from yaicli.schemas import ChatMessage, LLMResponse, RefreshLive, ToolCall, ToolPolicy


class MockProvider(Provider):
    """Mock provider for testing"""

    def __init__(self, responses=None, enable_functions=True, enable_mcp=False):
        """Initialize with predefined responses"""
        self.responses = responses or [LLMResponse(content="Test response")]
        self.completion_called = False
        self.enable_function = enable_functions
        self.enable_mcp = enable_mcp
        self.config = {"ENABLE_FUNCTIONS": enable_functions, "ENABLE_MCP": enable_mcp}

    def completion(self, messages, stream=False, tool_policy=None):
        """Return predefined responses"""
        self.completion_called = True
        self.messages = messages
        self.stream = stream
        self.tool_policy = tool_policy

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
            "MAX_TOOL_CALL_DEPTH": 5,
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

        client = LLMClient(provider_name="openai", config=mock_config)

        mock_factory.assert_called_once_with("openai", config=mock_config, verbose=False)
        assert client.provider == mock_provider

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_completion_without_tools(self, mock_factory, mock_config):
        """Test completion without tool calls"""
        # Create a mock provider with simple responses
        responses = [LLMResponse(content="Hello"), LLMResponse(content=" world!")]
        provider = MockProvider(responses=responses, enable_functions=True, enable_mcp=False)
        mock_factory.return_value = provider

        # Create client with our mock provider
        client = LLMClient(provider_name="mock_provider", config=mock_config)

        # Call completion
        messages = [ChatMessage(role="user", content="Say hello")]
        responses = list(client.completion_with_tools(messages))

        # Verify provider was called
        assert provider.completion_called
        assert provider.messages == messages
        assert provider.tool_policy == ToolPolicy(enable_functions=True, enable_mcp=False)

        # Verify responses were forwarded
        assert len(responses) == 2
        assert responses[0].content == "Hello"
        assert responses[1].content == " world!"

    @patch("yaicli.llms.client.execute_tool_call")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_completion_with_tool_call(self, mock_factory, mock_execute_tool, mock_config):
        """Test completion with a tool call that gets executed"""
        # Setup tool call
        tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')

        # Setup mock tool execution result - Return successful result
        mock_execute_tool.return_value = ("Sunny and 75°F", True)

        # Create client with a custom mock provider that we'll control manually
        mock_provider = MagicMock(spec=Provider)
        mock_factory.return_value = mock_provider

        # Set the return value for detect_tool_role
        mock_provider.detect_tool_role.return_value = "tool"
        mock_provider.resolve_tool_policy.return_value = ToolPolicy(enable_functions=True, enable_mcp=False)

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
        client = LLMClient(provider_name="mock_provider", config=mock_config)

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
        assert isinstance(responses[0], LLMResponse)
        assert responses[0].content == "Let me check the weather"
        assert isinstance(responses[1], RefreshLive)
        assert isinstance(responses[2], LLMResponse)
        assert responses[2].content == "It's sunny in New York"

    @patch("yaicli.llms.client.execute_tool_call")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_recursion_depth_limit(self, mock_factory, mock_execute_tool, mock_config):
        """Test that recursion depth is limited"""
        # Set a low recursion limit
        mock_config["MAX_TOOL_CALL_DEPTH"] = 2

        # Setup tool call that will keep recursing
        tool_call = ToolCall(id="call_123", name="recursive_function", arguments="{}")

        # Use MagicMock instead of MockProvider
        mock_provider = MagicMock(spec=Provider)
        mock_factory.return_value = mock_provider

        # Set return value for detect_tool_role
        mock_provider.detect_tool_role.return_value = "tool"
        mock_provider.resolve_tool_policy.return_value = ToolPolicy(enable_functions=True, enable_mcp=False)

        # Configure completion method to always return responses with tool calls
        mock_provider.completion.side_effect = lambda *args, **kwargs: iter(
            [LLMResponse(content="Calling function", finish_reason="tool_calls", tool_call=tool_call)]
        )

        # Setup mock tool execution result
        mock_execute_tool.return_value = ("Function called", True)

        # Create client
        client = LLMClient(provider_name="mock_provider", config=mock_config)

        # Initial messages
        messages = [ChatMessage(role="user", content="Start recursion")]

        # Call with recursive provider
        list(client.completion_with_tools(messages))

        # Should have been called only up to MAX_TOOL_CALL_DEPTH times
        assert mock_execute_tool.call_count <= mock_config["MAX_TOOL_CALL_DEPTH"]

        # Check that provider.completion has been called at least once
        assert mock_provider.completion.called

    @patch("yaicli.llms.client.execute_tool_call")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_functions_disabled(self, mock_factory, mock_execute_tool, mock_config):
        """Test that tool calls are not executed when functions are disabled"""
        # Disable functions
        mock_config["ENABLE_FUNCTIONS"] = False

        # Setup tool call
        tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')

        # Use responses that directly include tool calls
        responses = [LLMResponse(content="Let me check the weather", finish_reason="tool_calls", tool_call=tool_call)]

        # Set up mock provider
        provider = MockProvider(responses=responses, enable_functions=False, enable_mcp=False)
        mock_factory.return_value = provider

        # Create client
        client = LLMClient(provider_name="mock_provider", config=mock_config)

        # Initial messages
        messages = [ChatMessage(role="user", content="What's the weather in New York?")]

        # Call completion
        responses = list(client.completion_with_tools(messages))

        # Verify tool was NOT executed
        mock_execute_tool.assert_not_called()

        # Should only include the initial response
        assert len(responses) == 1
        assert isinstance(responses[0], LLMResponse)
        assert responses[0].content == "Let me check the weather"
        assert messages[-1].tool_calls == []

    @patch("yaicli.llms.client.execute_tool_call")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_request_tool_policy_drops_disallowed_tool_calls(self, mock_factory, mock_execute_tool, mock_config):
        """Test request-scoped policy drops disallowed tool calls from execution and history."""
        tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')
        provider = MockProvider(
            responses=[LLMResponse(content="Tool attempt", finish_reason="tool_calls", tool_call=tool_call)]
        )
        mock_factory.return_value = provider

        client = LLMClient(provider_name="mock_provider", config=mock_config)
        messages = [ChatMessage(role="user", content="What's the weather?")]

        responses = list(
            client.completion_with_tools(
                messages,
                tool_policy=ToolPolicy(enable_functions=False, enable_mcp=False),
            )
        )

        mock_execute_tool.assert_not_called()
        assert len(responses) == 1
        assert responses[0].content == "Tool attempt"
        assert messages[-1].tool_calls == []

    @patch("yaicli.llms.client.execute_tool_call")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_request_tool_policy_keeps_allowed_mcp_tool_calls(self, mock_factory, mock_execute_tool, mock_config):
        """Test request-scoped policy can allow MCP calls while filtering function calls."""
        function_tool_call = ToolCall(id="call_123", name="get_weather", arguments='{"location": "New York"}')
        mcp_tool_call = ToolCall(id="call_456", name="_mcp__clock", arguments='{"timezone": "UTC"}')
        provider = MagicMock(spec=Provider)
        mock_factory.return_value = provider
        mock_execute_tool.return_value = ("12:00 UTC", True)
        provider.detect_tool_role.return_value = "tool"
        provider.resolve_tool_policy.return_value = ToolPolicy(enable_functions=False, enable_mcp=True)
        provider.completion.side_effect = [
            iter(
                [
                    LLMResponse(content="", finish_reason=None, tool_call=function_tool_call),
                    LLMResponse(content="Using MCP instead", finish_reason="tool_calls", tool_call=mcp_tool_call),
                ]
            ),
            iter([LLMResponse(content="MCP complete", finish_reason="stop")]),
        ]

        client = LLMClient(provider_name="mock_provider", config=mock_config)
        messages = [ChatMessage(role="user", content="What time is it?")]

        responses = list(
            client.completion_with_tools(
                messages,
                tool_policy=ToolPolicy(enable_functions=False, enable_mcp=True),
            )
        )

        mock_execute_tool.assert_called_once()
        assert mock_execute_tool.call_args[0][0].name == "_mcp__clock"
        assert any(isinstance(response, RefreshLive) for response in responses)
        assert messages[-3].tool_calls == [mcp_tool_call]
