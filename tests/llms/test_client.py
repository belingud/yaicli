# type: ignore
from unittest.mock import MagicMock, patch

import pytest
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from yaicli.errors import AgentError, ErrorKind
from yaicli.llms.client import LLMClient
from yaicli.llms.provider import Provider
from yaicli.llms.providers.openai_provider import OpenAIProvider
from yaicli.model_limits import ModelLimits, get_context_limits
from yaicli.schemas import ChatMessage, LLMResponse, RefreshLive, ToolCall, ToolPolicy
from yaicli.usage import Usage


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
            # These tests exercise the silent tool-execution path; confirmation has
            # its own coverage in tests/llms/test_tool_confirmation.py.
            "TOOL_CONFIRM": False,
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

    @patch("yaicli.llms.client.execute_tool_call")
    def test_completion_with_parallel_tool_calls_executes_all(self, mock_execute_tool, mock_config):
        """End-to-end: a provider emitting two parallel tool calls executes both of them.

        Uses the real OpenAI provider (no mocked factory) so the provider parsing and the
        client collection/execution loop are exercised together.
        """
        first_response = ChatCompletion.model_validate(
            {
                "id": "chatcmpl-multi",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "Reading both files",
                            "tool_calls": [
                                {
                                    "id": "call_a",
                                    "type": "function",
                                    "function": {"name": "fs_read_file", "arguments": '{"path": "a.txt"}'},
                                },
                                {
                                    "id": "call_b",
                                    "type": "function",
                                    "function": {"name": "fs_read_file", "arguments": '{"path": "b.txt"}'},
                                },
                            ],
                        },
                    }
                ],
            }
        )
        second_response = ChatCompletion.model_validate(
            {
                "id": "chatcmpl-final",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Both files read"},
                    }
                ],
            }
        )
        mock_config["ENABLE_FUNCTIONS"] = True
        with patch.object(OpenAIProvider, "CLIENT_CLS"):
            client = LLMClient(provider_name="openai", config=mock_config)

        client.provider.client = MagicMock()
        client.provider.client.chat.completions.create.side_effect = [first_response, second_response]
        mock_execute_tool.side_effect = lambda tool_call, announce=True: (f"result-{tool_call.id}", True)

        messages = [ChatMessage(role="user", content="read a.txt and b.txt")]
        responses = list(client.completion_with_tools(messages, stream=False))

        # both tool calls executed, in index order
        assert mock_execute_tool.call_count == 2
        assert [call.args[0].id for call in mock_execute_tool.call_args_list] == ["call_a", "call_b"]
        assert [call.args[0].name for call in mock_execute_tool.call_args_list] == [
            "fs_read_file",
            "fs_read_file",
        ]

        # assistant message keeps both calls; history has one tool result per call
        assistant_messages = [message for message in messages if message.role == "assistant"]
        assert [tool.id for tool in assistant_messages[0].tool_calls] == ["call_a", "call_b"]
        tool_messages = [message for message in messages if message.role == "tool"]
        assert [message.tool_call_id for message in tool_messages] == ["call_a", "call_b"]
        assert [message.content for message in tool_messages] == ["result-call_a", "result-call_b"]

        # final answer was still received
        assert any(getattr(response, "content", None) == "Both files read" for response in responses)

    @patch("yaicli.llms.client.execute_tool_call")
    def test_completion_with_parallel_tool_calls_streaming_executes_all(self, mock_execute_tool, mock_config):
        """Streaming end-to-end: interleaved parallel tool call chunks are all executed."""

        def chunk(choices):
            return ChatCompletionChunk.model_validate(
                {
                    "id": "chatcmpl-stream",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "gpt-4",
                    "choices": choices,
                }
            )

        first_stream = [
            chunk([{"index": 0, "delta": {"role": "assistant", "content": "Reading both"}, "finish_reason": None}]),
            chunk(
                [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_a",
                                    "type": "function",
                                    "function": {"name": "fs_read_file", "arguments": ""},
                                },
                                {
                                    "index": 1,
                                    "id": "call_b",
                                    "type": "function",
                                    "function": {"name": "fs_read_file", "arguments": ""},
                                },
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            ),
            chunk(
                [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 1, "function": {"arguments": '{"path": "b.txt"}'}},
                                {"index": 0, "function": {"arguments": '{"path": "a.txt"}'}},
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            ),
            chunk([{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]),
        ]
        second_stream = [
            chunk([{"index": 0, "delta": {"role": "assistant", "content": "Both files read"}, "finish_reason": None}]),
            chunk([{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}]),
        ]

        mock_config["ENABLE_FUNCTIONS"] = True
        with patch.object(OpenAIProvider, "CLIENT_CLS"):
            client = LLMClient(provider_name="openai", config=mock_config)

        client.provider.client = MagicMock()
        client.provider.client.chat.completions.create.side_effect = [first_stream, second_stream]
        mock_execute_tool.side_effect = lambda tool_call, announce=True: (f"result-{tool_call.id}", True)

        messages = [ChatMessage(role="user", content="read a.txt and b.txt")]
        responses = list(client.completion_with_tools(messages, stream=True))

        assert mock_execute_tool.call_count == 2
        assert [call.args[0].id for call in mock_execute_tool.call_args_list] == ["call_a", "call_b"]
        assert [call.args[0].arguments for call in mock_execute_tool.call_args_list] == [
            '{"path": "a.txt"}',
            '{"path": "b.txt"}',
        ]
        tool_messages = [message for message in messages if message.role == "tool"]
        assert [message.tool_call_id for message in tool_messages] == ["call_a", "call_b"]
        assert any(getattr(response, "content", None) == "Both files read" for response in responses)


class TestLLMClientUsage:
    """v0.22 K17: the client accumulates usage/tool metrics exactly once per round."""

    @pytest.fixture
    def mock_config(self):
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://fake-api.openai.com/v1",
            "MODEL": "gpt-4o-mini",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "PROVIDER": "openai",
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            "MAX_TOOL_CALL_DEPTH": 5,
            "TOOL_CONFIRM": False,
        }

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_records_provider_usage_once(self, mock_factory, mock_config):
        provider = MockProvider(
            responses=[
                LLMResponse(content="a", usage=Usage(10, 5, 15)),
                LLMResponse(content="b"),
            ]
        )
        mock_factory.return_value = provider
        client = LLMClient(provider_name="mock_provider", config=mock_config)

        list(client.completion_with_tools([ChatMessage(role="user", content="hi")]))

        assert client.session_usage == Usage(10, 5, 15)
        assert client.last_usage == Usage(10, 5, 15)
        assert client.usage_tracker.requests == 1
        assert client.usage_tracker.by_model["gpt-4o-mini"] == Usage(10, 5, 15)

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_duplicate_usage_snapshots_are_not_double_counted(self, mock_factory, mock_config):
        duplicate = Usage(10, 5, 15)
        provider = MockProvider(
            responses=[LLMResponse(content="a", usage=duplicate), LLMResponse(content="b", usage=duplicate)]
        )
        mock_factory.return_value = provider
        client = LLMClient(provider_name="mock_provider", config=mock_config)

        list(client.completion_with_tools([ChatMessage(role="user", content="hi")]))

        assert client.session_usage == duplicate
        assert client.usage_tracker.requests == 1

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_estimates_usage_when_provider_reports_none(self, mock_factory, mock_config):
        provider = MockProvider(responses=[LLMResponse(content="a fairly long answer")])
        mock_factory.return_value = provider
        client = LLMClient(provider_name="mock_provider", config=mock_config)

        list(client.completion_with_tools([ChatMessage(role="user", content="hi")]))

        usage = client.session_usage
        assert usage.estimated is True
        assert usage.prompt_tokens > 0
        assert usage.completion_tokens > 0
        assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
        assert client.last_usage is not None
        assert client.last_usage.estimated is True

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_finish_reason_length_sets_output_truncated(self, mock_factory, mock_config):
        provider = MagicMock(spec=Provider)
        mock_factory.return_value = provider
        provider.detect_tool_role.return_value = "tool"
        provider.resolve_tool_policy.return_value = ToolPolicy(enable_functions=True, enable_mcp=False)
        provider.completion.side_effect = [
            iter([LLMResponse(content="partial", finish_reason="length")]),
            iter([LLMResponse(content="complete", finish_reason="stop")]),
        ]
        client = LLMClient(provider_name="mock_provider", config=mock_config)
        messages = [ChatMessage(role="user", content="hi")]

        list(client.completion_with_tools(messages))
        assert client.output_truncated is True
        assert client.last_finish_reason == "length"

        # A new turn resets the per-turn truncation flag.
        list(client.completion_with_tools(messages))
        assert client.output_truncated is False
        assert client.last_finish_reason == "stop"

    @patch("yaicli.llms.client.execute_tool_call")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_multi_round_usage_and_tool_metrics(self, mock_factory, mock_execute_tool, mock_config):
        mock_execute_tool.return_value = ('{"ok": true}', True)
        tool_call = ToolCall(id="call_1", name="fs_list_directory", arguments="{}")
        provider = MagicMock(spec=Provider)
        mock_factory.return_value = provider
        provider.detect_tool_role.return_value = "tool"
        provider.resolve_tool_policy.return_value = ToolPolicy(enable_functions=True, enable_mcp=False)
        provider.completion.side_effect = [
            iter([LLMResponse(content="", finish_reason="tool_calls", tool_call=tool_call, usage=Usage(10, 5, 15))]),
            iter([LLMResponse(content="done", finish_reason="stop", usage=Usage(20, 10, 30))]),
        ]
        client = LLMClient(provider_name="mock_provider", config=mock_config)

        list(client.completion_with_tools([ChatMessage(role="user", content="list")]))

        assert client.session_usage == Usage(30, 15, 45)
        assert client.usage_tracker.requests == 2
        tool_metrics = client.usage_tracker.snapshot()["tools"]
        assert tool_metrics["count"] == 1
        assert tool_metrics["result_chars"] == len('{"ok": true}')
        assert tool_metrics["duration_ms"] >= 0

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_usage_snapshot_includes_cost_and_models(self, mock_factory, mock_config):
        mock_factory.return_value = MockProvider(responses=[LLMResponse(content="hi")])
        client = LLMClient(provider_name="mock_provider", config=mock_config)
        client.usage_tracker.record(Usage(1_000_000, 1_000_000, 2_000_000), "gpt-4o-mini")

        snapshot = client.usage_snapshot()

        assert snapshot["prompt_tokens"] == 1_000_000
        assert snapshot["cost_usd"] == pytest.approx(0.75)
        assert snapshot["estimated"] is False
        assert snapshot["models"]["gpt-4o-mini"]["cost_usd"] == pytest.approx(0.75)
        assert snapshot["tools"] == {"count": 0, "duration_ms": 0.0, "result_chars": 0}


# ---------------------------------------------------------------------------
# v0.23 K22: context-limit resolution, unknown-window warning, limit learning
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_model_limit_cache(tmp_path):
    """Keep resolved/learned limits out of the developer's real config dir.

    Learned values are written through ``yaicli.model_limits``; without this
    override a self-heal test would touch ``<config-dir>/cache/model_limits.json``
    (R12: tests must not read/write the real ``~/.config/yaicli``).
    """
    from yaicli import model_limits as model_limits_module

    model_limits_module.clear_limit_cache()
    previous = model_limits_module.CACHE_PATH_OVERRIDE
    model_limits_module.CACHE_PATH_OVERRIDE = tmp_path / "cache" / "model_limits.json"
    try:
        yield
    finally:
        model_limits_module.CACHE_PATH_OVERRIDE = previous
        model_limits_module.clear_limit_cache()


def _limits_config(**overrides):
    """Complete config for LLMClient with K22 keys (metadata on, cache off in tmp)."""
    config = {
        "API_KEY": "fake_api_key",
        "BASE_URL": "",
        "MODEL": "gpt-4o",
        "TEMPERATURE": 0.7,
        "TOP_P": 1.0,
        "MAX_TOKENS": 1024,
        "CONTEXT_SAFETY_TOKENS": 1024,
        "CONTEXT_BUDGET_TOKENS": 0,
        "ENABLE_MODEL_METADATA": True,
        "ENABLE_MODEL_LIMITS_CACHE": False,
        "TIMEOUT": 60,
        "PROVIDER": "openai",
        "ENABLE_FUNCTIONS": False,
        "ENABLE_MCP": False,
        "MAX_TOOL_CALL_DEPTH": 4,
        "TOOL_CONFIRM": False,
        "RETRY_ENABLED": True,
        "RETRY_MAX": 2,
        "RETRY_BASE_DELAY": 0.0,
        "RETRY_MAX_DELAY": 0.0,
    }
    config.update(overrides)
    return config


class ContextLengthError(Exception):
    """Provider-style 400 context rejection carrying the real limit."""

    status_code = 400

    def __init__(self, limit: int = 200_000):
        super().__init__(
            f"This model's maximum context length is {limit} tokens. Please reduce the length of the messages."
        )


class ScriptedLimitsProvider(Provider):
    """Provider that relays a scripted completion and optionally advertises limits."""

    def __init__(self, script, *, limits=None):
        self.script = list(script)
        self.calls = 0
        self.snapshots = []
        self.enable_function = False
        self.enable_mcp = False
        self._limits = limits
        self.config = {
            "BASE_URL": "https://gateway.example/v1",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
        }

    def completion(self, messages, stream=False, tool_policy=None):
        self.snapshots.append(list(messages))
        effect = self.script[self.calls]
        self.calls += 1
        if isinstance(effect, BaseException):
            raise effect
        yield from effect

    def detect_tool_role(self):
        return "tool"

    def model_limits(self, model):
        return self._limits


def _make_limits_client(provider, config):
    with patch("yaicli.llms.provider.ProviderFactory.create_provider", return_value=provider):
        client = LLMClient(provider_name="openai", config=config)
    client.provider = provider
    return client


def _two_group_history():
    return [
        ChatMessage(role="user", content="first question"),
        ChatMessage(role="assistant", content="first answer"),
        ChatMessage(role="user", content="second question"),
    ]


class TestUnknownContextWindowWarning:
    """PRD Feature example 3: unknown window warning once per client session."""

    @patch("yaicli.llms.client.get_error_console")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_unknown_model_warns_once_per_client_with_override_hint(self, mock_factory, mock_error_console):
        provider = MockProvider(responses=[LLMResponse(content="ok")])
        mock_factory.return_value = provider
        error_console = MagicMock()
        mock_error_console.return_value = error_console
        client = LLMClient(provider_name="openai", config=_limits_config(MODEL="my-gateway-model"))

        list(client.completion_with_tools([ChatMessage(role="user", content="hi")]))
        list(client.completion_with_tools([ChatMessage(role="user", content="again")]))

        assert error_console.print.call_count == 1
        message = error_console.print.call_args.args[0]
        assert message.splitlines() == [
            'Context window for model "my-gateway-model" is unknown; assuming 128,000 tokens (source: default).',
            'Set MODEL_CONTEXT_WINDOWS={"my-gateway-model": 200000} or CONTEXT_BUDGET_TOKENS to override.',
        ]
        assert error_console.print.call_args.kwargs["style"] == "dim yellow"

    @patch("yaicli.llms.client.get_error_console")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_known_model_does_not_warn(self, mock_factory, mock_error_console):
        mock_factory.return_value = MockProvider(responses=[LLMResponse(content="ok")])
        error_console = MagicMock()
        mock_error_console.return_value = error_console
        client = LLMClient(provider_name="openai", config=_limits_config(MODEL="gpt-4o"))

        list(client.completion_with_tools([ChatMessage(role="user", content="hi")]))

        assert client.last_context_limits is not None
        assert client.last_context_limits.source in ("catalog", "heuristic")
        error_console.print.assert_not_called()

    @patch("yaicli.llms.client.get_error_console")
    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_empty_model_does_not_warn(self, mock_factory, mock_error_console):
        mock_factory.return_value = MockProvider(responses=[LLMResponse(content="ok")])
        error_console = MagicMock()
        mock_error_console.return_value = error_console
        client = LLMClient(provider_name="openai", config=_limits_config(MODEL=""))

        list(client.completion_with_tools([ChatMessage(role="user", content="hi")]))

        assert client.last_context_budget > 0
        error_console.print.assert_not_called()

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_provider_metadata_hook_supplies_limits_without_warning(self, mock_factory):
        provider = ScriptedLimitsProvider(
            [[LLMResponse(content="ok")]],
            limits=ModelLimits(window=777_000, max_output=12_345, source="metadata", detail="test /models"),
        )
        mock_factory.return_value = provider
        client = LLMClient(provider_name="openai", config=_limits_config(MODEL="my-gateway-model"))

        list(client.completion_with_tools([ChatMessage(role="user", content="hi")]))

        assert client.last_context_limits is not None
        assert client.last_context_limits.source == "metadata"
        assert client.last_context_limits.window == 777_000
        assert client.last_context_budget == 777_000 - 1024 - 1024

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_provider_key_is_normalized(self, mock_factory):
        mock_factory.return_value = MockProvider(responses=[LLMResponse(content="ok")])
        client = LLMClient(provider_name="OpenAI", config=_limits_config())

        assert client.provider_key == "openai"
        assert client.last_context_limits is None
        assert client._limits_warned is False
        mock_factory.assert_called_once()
        assert mock_factory.call_args.args[0] == "openai"


class TestContextLengthSelfHealLearning:
    """PRD Feature example 4: learn the real limit, recompute the budget, retry once."""

    @patch("yaicli.llms.client.get_error_console")
    def test_learns_real_limit_and_retries_once(self, mock_error_console):
        error_console = MagicMock()
        mock_error_console.return_value = error_console
        provider = ScriptedLimitsProvider(
            [ContextLengthError(200_000), [LLMResponse(content="recovered", finish_reason="stop")]]
        )
        client = _make_limits_client(provider, _limits_config(MODEL="gateway-learned-model"))

        responses = list(client.completion_with_tools(_two_group_history()))

        assert [response.content for response in responses if isinstance(response, LLMResponse)] == ["recovered"]
        assert provider.calls == 2
        # The oldest turn group was dropped before the retry.
        assert [message.content for message in provider.snapshots[1]] == ["second question"]
        # The learned limit was applied immediately: budget recomputed from 200k.
        assert client.last_context_limits is not None
        assert client.last_context_limits.source == "learned"
        assert client.last_context_limits.window == 200_000
        assert client.last_context_budget == 200_000 - 1024 - 1024
        printed = "\n".join(str(call.args[0]) for call in error_console.print.call_args_list)
        assert "Provider rejected the request as too long; learned the real context limit (200,000 tokens)" in printed
        assert "retrying once" in printed

        # A later request reuses the learned value instead of the 128k default.
        provider.script.append([LLMResponse(content="next", finish_reason="stop")])
        list(client.completion_with_tools([ChatMessage(role="user", content="third")]))
        assert client.last_context_limits.source == "learned"
        assert client.last_context_limits.window == 200_000

    @patch("yaicli.llms.client.get_error_console")
    def test_second_context_error_never_retries_again(self, mock_error_console):
        mock_error_console.return_value = MagicMock()
        provider = ScriptedLimitsProvider([ContextLengthError(8192), ContextLengthError(8192)])
        client = _make_limits_client(provider, _limits_config(MODEL="gateway-learned-model-2"))

        with pytest.raises(AgentError) as excinfo:
            list(client.completion_with_tools(_two_group_history()))

        assert excinfo.value.kind is ErrorKind.CONTEXT_LENGTH
        assert provider.calls == 2

    @patch("yaicli.llms.client.get_error_console")
    def test_single_turn_context_error_learns_without_retry(self, mock_error_console):
        mock_error_console.return_value = MagicMock()
        provider = ScriptedLimitsProvider([ContextLengthError(4096)])
        config = _limits_config(MODEL="gateway-single-turn")
        client = _make_limits_client(provider, config)

        with pytest.raises(AgentError) as excinfo:
            list(client.completion_with_tools([ChatMessage(role="user", content="only turn")]))

        assert excinfo.value.kind is ErrorKind.CONTEXT_LENGTH
        assert provider.calls == 1  # no group to drop -> actionable error, no retry
        # The learned value is recorded even though the retry could not happen.
        learned = get_context_limits(
            client.provider_key,
            "gateway-single-turn",
            config,
            base_url=client.provider.base_url,
        )
        assert learned.source == "learned"
        assert learned.window == 4096

    @patch("yaicli.llms.client.get_error_console")
    def test_context_budget_override_still_wins_after_learning(self, mock_error_console):
        mock_error_console.return_value = MagicMock()
        provider = ScriptedLimitsProvider(
            [ContextLengthError(200_000), [LLMResponse(content="recovered", finish_reason="stop")]]
        )
        config = _limits_config(MODEL="gateway-override-model", CONTEXT_BUDGET_TOKENS=5000)
        client = _make_limits_client(provider, config)

        list(client.completion_with_tools(_two_group_history()))

        assert client.last_context_limits.window == 200_000
        assert client.last_context_budget == 5000


class TestOversizedMaxTokensClamp:
    """A MAX_TOKENS near/above the context window must not starve the input budget.

    Regression: ``MAX_TOKENS=128000`` with the default (unknown) 128k window left a
    budget of 1 token, so the client trimmed the whole conversation on every request:
    a ``/load``-ed session looked like a fresh conversation to the model although
    ``/his`` showed the history.
    """

    @pytest.fixture
    def max_config(self):
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://fake-api.openai.com/v1",
            "MODEL": "z-ai/glm-5.3-flash",  # unknown to the catalog -> default 128k window
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 128_000,
            "TIMEOUT": 60,
            "PROVIDER": "openai",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
            "MAX_TOOL_CALL_DEPTH": 5,
            "TOOL_CONFIRM": False,
            "CONTEXT_SAFETY_TOKENS": 1024,
            "MODEL_CONTEXT_WINDOWS": {},
            "ENABLE_MODEL_METADATA": False,
            "ENABLE_MODEL_LIMITS_CACHE": False,
        }

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_max_tokens_is_clamped_and_history_survives(self, mock_factory, max_config, capsys):
        mock_factory.return_value = MockProvider(responses=[LLMResponse(content="ok")])
        config = max_config
        client = LLMClient(provider_name="openai", config=config)
        messages = [ChatMessage(role="system", content="system prompt")]
        for index in range(40):
            messages.append(ChatMessage(role="user", content=f"question {index}"))
            messages.append(ChatMessage(role="assistant", content="answer " * 20))

        list(client.completion_with_tools(messages))

        half_window = 128_000 // 2
        assert config["MAX_TOKENS"] == half_window - 1024
        assert client.last_context_budget == half_window
        assert client.context_trimmed is False
        assert len([message for message in messages if message.role == "user"]) == 40
        error_output = capsys.readouterr().err
        assert "MAX_TOKENS=128,000" in error_output
        assert f"using MAX_TOKENS={half_window - 1024:,}" in error_output

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_clamp_warning_and_value_are_applied_once(self, mock_factory, max_config, capsys):
        mock_factory.return_value = MockProvider(responses=[LLMResponse(content="ok")])
        config = max_config
        client = LLMClient(provider_name="openai", config=config)
        messages = [ChatMessage(role="user", content="hi")]

        list(client.completion_with_tools(messages))
        list(client.completion_with_tools(messages))

        assert config["MAX_TOKENS"] == 128_000 // 2 - 1024
        assert capsys.readouterr().err.count("leaves no room for input") == 1

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_explicit_context_budget_override_is_respected(self, mock_factory, max_config):
        mock_factory.return_value = MockProvider(responses=[LLMResponse(content="ok")])
        config = dict(max_config)
        config.update({"CONTEXT_BUDGET_TOKENS": 2000})
        client = LLMClient(provider_name="openai", config=config)

        list(client.completion_with_tools([ChatMessage(role="user", content="hi")]))

        assert config["MAX_TOKENS"] == 128_000  # explicit override disables the clamp
        assert client.last_context_budget == 2000
