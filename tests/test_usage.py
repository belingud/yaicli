"""v0.22 K17 observability: usage normalization, cost table, tracker and CLI output.

Locks the K17 contract:

* provider usage shapes (OpenAI/Anthropic/Gemini/Mistral/Ollama, dict or SDK
  object or mock) normalize to one frozen :class:`Usage`;
* ``estimate_usage`` is the heuristic fallback (``estimated=True``);
* ``estimate_cost`` honours the built-in prefix table, longest-prefix matching
  and ``MODEL_PRICING`` overrides, and returns ``None`` for unknown models;
* :class:`UsageTracker` accumulates requests/models/tool metrics;
* ``--output-format json`` reports real usage + ``finish_reason``;
* ``--output-format stream-json`` emits one real ``usage`` event;
* ``finish_reason == "length"`` produces one stderr warning;
* the interactive per-turn usage line degrades gracefully.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from yaicli.cli import CLI
from yaicli.entry import app
from yaicli.schemas import LLMResponse
from yaicli.usage import (
    Usage,
    UsageTracker,
    estimate_cost,
    estimate_usage,
    usage_from_anthropic,
    usage_from_gemini,
    usage_from_mistral,
    usage_from_ollama,
    usage_from_openai,
)

runner = CliRunner()

#: A representative snapshot as produced by ``LLMClient.usage_snapshot()``.
USAGE_SNAPSHOT = {
    "prompt_tokens": 1234,
    "completion_tokens": 567,
    "total_tokens": 1801,
    "cached_tokens": 12,
    "reasoning_tokens": 0,
    "estimated": False,
    "requests": 2,
    "cost_usd": 0.0021,
    "models": {
        "gpt-4o-mini": {
            "prompt_tokens": 1234,
            "completion_tokens": 567,
            "total_tokens": 1801,
            "estimated": False,
            "cost_usd": 0.0021,
        }
    },
    "tools": {"count": 1, "duration_ms": 12.5, "result_chars": 100},
}


# ---------------------------------------------------------------------------
# Usage value object
# ---------------------------------------------------------------------------
class TestUsageDataclass:
    def test_add_sums_fields_and_ors_estimated(self):
        left = Usage(10, 5, 15, cached_tokens=2, reasoning_tokens=1)
        right = Usage(20, 7, 27, cached_tokens=3, reasoning_tokens=4, estimated=True)

        total = left + right

        assert total == Usage(30, 12, 42, cached_tokens=5, reasoning_tokens=5, estimated=True)

    def test_sum_and_radd(self):
        usages = [Usage(1, 2, 3), Usage(4, 5, 9)]
        assert sum(usages) == Usage(5, 7, 12)
        assert 0 + Usage(1, 2, 3) == Usage(1, 2, 3)

    def test_to_dict(self):
        usage = Usage(1, 2, 3, cached_tokens=4, reasoning_tokens=5, estimated=True)
        assert usage.to_dict() == {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
            "cached_tokens": 4,
            "reasoning_tokens": 5,
            "estimated": True,
        }


# ---------------------------------------------------------------------------
# Provider conversions
# ---------------------------------------------------------------------------
class TestOpenAIUsageConversion:
    def test_dict_with_details(self):
        payload = {
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 4,
                "total_tokens": 15,
                "prompt_tokens_details": {"cached_tokens": 3},
                "completion_tokens_details": {"reasoning_tokens": 2},
            }
        }
        assert usage_from_openai(payload) == Usage(11, 4, 15, cached_tokens=3, reasoning_tokens=2)

    def test_object_minimal(self):
        obj = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
        assert usage_from_openai(obj) == Usage(10, 5, 15)

    def test_absent_or_mock_returns_none(self):
        assert usage_from_openai(SimpleNamespace(usage=None)) is None
        assert usage_from_openai({}) is None
        assert usage_from_openai(MagicMock()) is None


class TestAnthropicUsageConversion:
    def test_message_usage(self):
        message = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=40))
        assert usage_from_anthropic(message) == Usage(100, 20, 120, cached_tokens=40)

    def test_message_start_nested_usage(self):
        event = SimpleNamespace(
            type="message_start", message=SimpleNamespace(usage=SimpleNamespace(input_tokens=80, output_tokens=1))
        )
        assert usage_from_anthropic(event) == Usage(80, 1, 81)

    def test_message_delta_output_only(self):
        event = SimpleNamespace(type="message_delta", usage=SimpleNamespace(output_tokens=50))
        assert usage_from_anthropic(event) == Usage(0, 50, 50)

    def test_absent_returns_none(self):
        assert usage_from_anthropic(SimpleNamespace(usage=None)) is None
        assert usage_from_anthropic(MagicMock()) is None


class TestGeminiUsageConversion:
    def test_usage_metadata(self):
        response = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=7,
                candidates_token_count=3,
                total_token_count=10,
                cached_content_token_count=1,
                thoughts_token_count=2,
            )
        )
        assert usage_from_gemini(response) == Usage(7, 3, 10, cached_tokens=1, reasoning_tokens=2)

    def test_absent_returns_none(self):
        assert usage_from_gemini(SimpleNamespace(usage_metadata=None)) is None
        assert usage_from_gemini(MagicMock()) is None


class TestMistralUsageConversion:
    def test_response_usage(self):
        response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=8, completion_tokens=2, total_tokens=10))
        assert usage_from_mistral(response) == Usage(8, 2, 10)

    def test_stream_event_data_usage(self):
        event = SimpleNamespace(data=SimpleNamespace(usage=SimpleNamespace(prompt_tokens=4, completion_tokens=6)))
        assert usage_from_mistral(event) == Usage(4, 6, 10)

    def test_absent_returns_none(self):
        assert usage_from_mistral(SimpleNamespace(data=SimpleNamespace(usage=None))) is None
        assert usage_from_mistral(MagicMock()) is None


class TestOllamaUsageConversion:
    def test_object_counts(self):
        assert usage_from_ollama(SimpleNamespace(prompt_eval_count=9, eval_count=4)) == Usage(9, 4, 13)

    def test_dict_counts(self):
        assert usage_from_ollama({"prompt_eval_count": 3, "eval_count": 2}) == Usage(3, 2, 5)

    def test_absent_returns_none(self):
        assert usage_from_ollama(SimpleNamespace(prompt_eval_count=None, eval_count=None)) is None
        assert usage_from_ollama(MagicMock()) is None


class TestEstimateUsage:
    def test_estimated_from_messages_and_completion(self):
        usage = estimate_usage([{"role": "user", "content": "hello world"}], "a short answer")

        assert usage.estimated is True
        assert usage.prompt_tokens > 0
        assert usage.completion_tokens > 0
        assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens

    def test_empty_inputs(self):
        usage = estimate_usage(None, "")
        assert usage == Usage(0, 0, 0, estimated=True)


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------
class TestEstimateCost:
    def test_known_model_builtin_prices(self):
        usage = Usage(1_000_000, 1_000_000, 2_000_000)
        # gpt-4o-mini: 0.15 input + 0.60 output (USD / 1M tokens)
        assert estimate_cost("gpt-4o-mini", usage) == pytest.approx(0.75)

    def test_longest_prefix_wins(self):
        usage = Usage(1_000_000, 1_000_000, 2_000_000)
        assert estimate_cost("gpt-4o", usage) == pytest.approx(12.50)
        assert estimate_cost("gpt-4o-mini-2024-07-18", usage) == pytest.approx(0.75)

    def test_default_repo_model_is_priced(self):
        # The shipped DEFAULT_MODEL should show a cost out of the box.
        from yaicli.const import DEFAULT_MODEL

        assert estimate_cost(DEFAULT_MODEL, Usage(1_000_000, 1_000_000, 2_000_000)) is not None

    def test_slash_qualified_model_name_matches_substring(self):
        usage = Usage(1_000_000, 0, 1_000_000)
        assert estimate_cost("openrouter/anthropic/claude-sonnet-4", usage) == pytest.approx(3.00)

    def test_model_pricing_override(self):
        usage = Usage(1_000_000, 1_000_000, 2_000_000)
        config = {"MODEL_PRICING": {"gpt-4o-mini": {"input": 1.0, "output": 2.0}}}
        assert estimate_cost("gpt-4o-mini", usage, config) == pytest.approx(3.0)

    def test_model_pricing_as_json_string(self):
        usage = Usage(1_000_000, 0, 1_000_000)
        config = {"MODEL_PRICING": '{"custom-model": {"input": 2.5, "output": 10}}'}
        assert estimate_cost("custom-model-v1", usage, config) == pytest.approx(2.5)

    def test_model_pricing_malformed_falls_back_to_builtin(self):
        usage = Usage(1_000_000, 0, 1_000_000)
        config = {"MODEL_PRICING": "not-json", "MODEL": "gpt-4o-mini"}
        assert estimate_cost("gpt-4o-mini", usage, config) == pytest.approx(0.15)

    def test_model_pricing_invalid_entries_ignored(self):
        usage = Usage(1_000_000, 0, 1_000_000)
        config = {"MODEL_PRICING": {"gpt-4o-mini": {"input": "oops"}, "broken": 3}}
        assert estimate_cost("gpt-4o-mini", usage, config) == pytest.approx(0.15)

    def test_unknown_model_returns_none(self):
        assert estimate_cost("totally-unknown-model", Usage(1, 1, 2)) is None

    def test_none_usage_returns_none(self):
        assert estimate_cost("gpt-4o-mini", None) is None

    def test_global_config_fallback(self):
        usage = Usage(1_000_000, 0, 1_000_000)
        with patch("yaicli.config.cfg", {"MODEL_PRICING": {"gpt-4o-mini": {"input": 9.0, "output": 0}}}):
            assert estimate_cost("gpt-4o-mini", usage) == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------
class TestUsageTracker:
    def test_record_accumulates_total_and_per_model(self):
        tracker = UsageTracker()
        tracker.record(Usage(10, 5, 15), "gpt-4o-mini")
        tracker.record(Usage(20, 7, 27, estimated=True), "gpt-4o-mini")
        tracker.record(Usage(1, 1, 2), "claude-sonnet")

        assert tracker.total == Usage(31, 13, 44, estimated=True)
        assert tracker.request_count == 2 + 1
        assert tracker.requests == 3
        assert tracker.by_model["gpt-4o-mini"] == Usage(30, 12, 42, estimated=True)
        assert tracker.by_model["claude-sonnet"] == Usage(1, 1, 2)

    def test_record_none_is_ignored(self):
        tracker = UsageTracker()
        tracker.record(None, "gpt-4o-mini")
        assert tracker.request_count == 0
        assert tracker.total == Usage(0, 0, 0)

    def test_record_tool_metrics(self):
        tracker = UsageTracker()
        tracker.record_tool(12.5, 100)
        tracker.record_tool(7.5, 50)

        assert tracker.tool_calls == 2
        assert tracker.tool_duration_ms == pytest.approx(20.0)
        assert tracker.tool_result_chars == 150

    def test_snapshot_shape_and_cost(self):
        tracker = UsageTracker({"MODEL_PRICING": {}})
        tracker.record(Usage(1_000_000, 1_000_000, 2_000_000), "gpt-4o-mini")
        tracker.record_tool(10.0, 42)

        snapshot = tracker.snapshot()

        assert snapshot["prompt_tokens"] == 1_000_000
        assert snapshot["completion_tokens"] == 1_000_000
        assert snapshot["total_tokens"] == 2_000_000
        assert snapshot["requests"] == 1
        assert snapshot["cost_usd"] == pytest.approx(0.75)
        assert snapshot["models"]["gpt-4o-mini"]["cost_usd"] == pytest.approx(0.75)
        assert snapshot["tools"] == {"count": 1, "duration_ms": 10.0, "result_chars": 42}

    def test_snapshot_unknown_pricing(self):
        tracker = UsageTracker()
        tracker.record(Usage(10, 5, 15), "totally-unknown-model")
        snapshot = tracker.snapshot()
        assert snapshot["cost_usd"] is None
        assert snapshot["models"]["totally-unknown-model"]["cost_usd"] is None

    def test_reset(self):
        tracker = UsageTracker()
        tracker.record(Usage(10, 5, 15), "gpt-4o-mini")
        tracker.record_tool(1.0, 2)
        tracker.reset()

        assert tracker.total == Usage(0, 0, 0)
        assert tracker.by_model == {}
        assert tracker.request_count == 0
        assert tracker.tool_calls == 0
        assert tracker.tool_duration_ms == 0.0
        assert tracker.tool_result_chars == 0


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------
def make_client(chunks, usage_snapshot=None, finish_reason=None, output_truncated=False):
    """A mocked LLMClient whose completion_with_tools() yields ``chunks``."""
    client = MagicMock()
    items = list(chunks)

    def completion(messages, **kwargs):
        return iter(items)

    client.completion_with_tools = MagicMock(side_effect=completion)
    if usage_snapshot is not None:
        client.usage_snapshot = MagicMock(return_value=usage_snapshot)
    if finish_reason is not None:
        client.last_finish_reason = finish_reason
    client.output_truncated = output_truncated
    return client


def invoke_real_cli(client, args):
    with patch("yaicli.cli.LLMClient", return_value=client):
        return runner.invoke(app, args)


class TestCliJsonUsage:
    def test_json_reports_real_usage_and_finish_reason(self):
        client = make_client([LLMResponse(content="hello")], usage_snapshot=dict(USAGE_SNAPSHOT), finish_reason="stop")
        result = invoke_real_cli(client, ["-p", "--output-format", "json", "hi"])

        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        usage = payload["usage"]
        # Backward-compatible top-level counters plus the rich K17 fields.
        assert usage["prompt_tokens"] == 1234
        assert usage["completion_tokens"] == 567
        assert usage["total_tokens"] == 1801
        assert usage["cost_usd"] == pytest.approx(0.0021)
        assert usage["estimated"] is False
        assert usage["requests"] == 2
        assert usage["tools"] == {"count": 1, "duration_ms": 12.5, "result_chars": 100}
        assert usage["models"]["gpt-4o-mini"]["prompt_tokens"] == 1234
        assert payload["finish_reason"] == "stop"

    def test_json_finish_reason_length_warns_on_stderr(self):
        client = make_client(
            [LLMResponse(content="partial", finish_reason="length")],
            usage_snapshot=dict(USAGE_SNAPSHOT),
            finish_reason="length",
            output_truncated=True,
        )
        result = invoke_real_cli(client, ["-p", "--output-format", "json", "hi"])

        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["finish_reason"] == "length"
        assert "MAX_TOKENS" in result.stderr

    def test_stream_json_usage_event_carries_real_numbers(self):
        client = make_client([LLMResponse(content="hello")], usage_snapshot=dict(USAGE_SNAPSHOT), finish_reason="stop")
        result = invoke_real_cli(client, ["-p", "--output-format", "stream-json", "hi"])

        assert result.exit_code == 0, result.stderr
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        usage_events = [event for event in events if event["type"] == "usage"]
        assert len(usage_events) == 1
        usage_event = usage_events[0]
        assert usage_event["prompt_tokens"] == 1234
        assert usage_event["completion_tokens"] == 567
        assert usage_event["total_tokens"] == 1801
        assert usage_event["cost_usd"] == pytest.approx(0.0021)
        assert usage_event["requests"] == 2
        assert usage_event["finish_reason"] == "stop"
        assert events[-1]["type"] == "done"


class TestCliUsageLine:
    def test_format_usage_line(self):
        cli = CLI()
        with patch("yaicli.cli.cfg", {"MODEL": "gpt-4o-mini", "MODEL_PRICING": {}}):
            line = cli._format_usage_line(
                {"prompt_tokens": 100, "completion_tokens": 10},
                {"prompt_tokens": 1334, "completion_tokens": 577},
                1.234,
                "stop",
            )

        assert line is not None
        assert "tokens 1,234 in / 567 out" in line
        assert line.startswith("gpt-4o-mini · tokens ")
        assert " · " in line
        assert "1.2s" in line
        assert line.endswith("stop")
        assert "$" in line

    def test_format_usage_line_includes_model_and_context(self):
        cli = CLI()
        cli._context_percent = 12.6
        with patch("yaicli.cli.cfg", {"MODEL": "openai/gpt-4o", "MODEL_PRICING": {}}):
            line = cli._format_usage_line(None, {"prompt_tokens": 10, "completion_tokens": 5}, 0.5, "stop")

        assert line is not None
        assert line.startswith("gpt-4o · context 13% · tokens 10 in / 5 out")

    def test_format_usage_line_unknown_pricing_omits_cost(self):
        cli = CLI()
        with patch("yaicli.cli.cfg", {"MODEL": "totally-unknown-model", "MODEL_PRICING": {}}):
            line = cli._format_usage_line(None, {"prompt_tokens": 10, "completion_tokens": 5}, 0.5, "stop")

        assert line is not None
        assert "$" not in line
        assert "tokens 10 in / 5 out" in line

    def test_format_usage_line_degrades_without_usage(self):
        cli = CLI()
        assert cli._format_usage_line(None, None, 1.0, None) is None
        line = cli._format_usage_line(None, {"prompt_tokens": 0, "completion_tokens": 0}, 1.0, "length")
        assert line is not None
        assert "tokens n/a" in line
        assert line.endswith("length")

    def test_process_user_input_prints_dim_usage_line(self):
        cli = CLI()
        cli.machine_output = False
        cli.console = MagicMock()
        cli._client = MagicMock()
        cli._client.usage_snapshot = MagicMock(
            side_effect=[
                {"prompt_tokens": 100, "completion_tokens": 10},
                {"prompt_tokens": 1100, "completion_tokens": 510},
            ]
        )
        cli._client.last_finish_reason = "stop"
        cli._client.output_truncated = False

        with patch.object(CLI, "_handle_llm_response", return_value=("hello", [])):
            assert cli._process_user_input("hi") is True

        dim_lines = [
            call.args[0] for call in cli.console.print.call_args_list if call.kwargs.get("style") == "dim" and call.args
        ]
        assert any("tokens 1,000 in / 500 out" in line for line in dim_lines)

    def test_process_user_input_usage_line_disabled_by_config(self):
        cli = CLI()
        cli.machine_output = False
        cli.console = MagicMock()
        cli._client = MagicMock()
        cli._client.usage_snapshot = MagicMock(return_value={"prompt_tokens": 10, "completion_tokens": 5})
        cli._client.last_finish_reason = "stop"
        cli._client.output_truncated = False

        with (
            patch("yaicli.cli.cfg", {"SHOW_USAGE": False}),
            patch.object(CLI, "_handle_llm_response", return_value=("hello", [])),
        ):
            assert cli._process_user_input("hi") is True

        dim_lines = [
            call.args[0] for call in cli.console.print.call_args_list if call.kwargs.get("style") == "dim" and call.args
        ]
        assert not dim_lines

    def test_process_user_input_warns_on_max_tokens(self):
        cli = CLI()
        cli.machine_output = True
        cli.console = MagicMock()
        cli._client = MagicMock()
        cli._client.usage_snapshot = MagicMock(return_value={"prompt_tokens": 5, "completion_tokens": 0})
        cli._client.last_finish_reason = "length"
        cli._client.output_truncated = True

        with (
            patch.object(CLI, "_handle_llm_response", return_value=("partial", [])),
            patch("yaicli.cli.get_error_console") as mock_error_console,
        ):
            assert cli._process_user_input("hi") is True

        printed = [str(call.args[0]) for call in mock_error_console.return_value.print.call_args_list if call.args]
        assert any("MAX_TOKENS" in line for line in printed)

    def test_usage_payload_fallback_without_client(self):
        cli = CLI()
        cli._client = None
        payload = cli._usage_payload()

        assert payload["prompt_tokens"] == 0
        assert payload["completion_tokens"] == 0
        assert payload["total_tokens"] == 0
        assert payload["requests"] == 0
        assert payload["cost_usd"] is None
        assert payload["tools"] == {"count": 0, "duration_ms": 0.0, "result_chars": 0}


class TestEndToEndUsage:
    """One real ``LLMClient`` round: provider usage -> tracker -> CLI JSON."""

    def test_real_client_usage_reaches_build_result(self):
        from yaicli.config import cfg as real_cfg
        from yaicli.llms.client import LLMClient
        from yaicli.llms.provider import Provider

        class UsageProvider(Provider):
            def __init__(self):
                self.config = {}
                self.enable_function = False
                self.enable_mcp = False

            def completion(self, messages, stream=False, tool_policy=None):
                yield LLMResponse(content="hello", usage=Usage(321, 45, 366), finish_reason="stop")

            def detect_tool_role(self):
                return "tool"

        with patch("yaicli.llms.provider.ProviderFactory.create_provider", return_value=UsageProvider()):
            client = LLMClient(provider_name="openai", config=real_cfg)
            cli = CLI(print_mode=True, output_format="json")
            cli.client = client
            cli.configure_headless(print_mode=True, output_format="json")
            assert cli._process_user_input("hi") is True
            payload = cli._build_result()

        assert payload["usage"]["prompt_tokens"] == 321
        assert payload["usage"]["completion_tokens"] == 45
        assert payload["usage"]["total_tokens"] == 366
        assert payload["usage"]["requests"] == 1
        assert payload["usage"]["cost_usd"] is not None
        assert payload["finish_reason"] == "stop"
        assert client.session_usage == Usage(321, 45, 366)
