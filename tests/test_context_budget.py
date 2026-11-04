"""Tests for the v0.19 K02 context-economy layer.

Covers:

* the stdlib token estimator (monotonic, CJK-aware) and the model window/budget table;
* turn-group-aware trimming (500 randomized tool-heavy sessions -> zero orphans);
* tool-output truncation + spill-to-disk (8 MB result -> capped + payload < 64 KB);
* the client token budget, context-length self-heal, retry policy and depth limit;
* the ``/context`` usage summary and the new ``/compact`` REPL command.
"""

import json
import os
import random
import re
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import yaicli.tools as tools_module
import yaicli.tools.limits as limits_module
from yaicli.cmd_handler import CMD_COMPACT, CmdHandler
from yaicli.errors import AgentError, ErrorKind
from yaicli.llms.client import LLMClient
from yaicli.llms.provider import ProviderFactory
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall, ToolPolicy
from yaicli.tokens import (
    DEFAULT_CONTEXT_WINDOW,
    OLLAMA_DEFAULT_CONTEXT_WINDOW,
    estimate_context_usage,
    estimate_messages_tokens,
    estimate_tokens,
    get_context_window,
    repair_tool_pairing,
    resolve_context_budget,
    split_turn_groups,
    trim_messages_to_budget,
    trim_oldest_group,
    validate_tool_pairing,
)
from yaicli.tools import execute_tool_call
from yaicli.tools.limits import resolve_output_cap, truncate_tool_output

SHELL_ENV_KEYS = ("YAI_TOOL_TIMEOUT", "YAI_TOOL_ENV_INHERIT", "YAI_WORKSPACE_ROOT", "YAI_TOOL_OUTPUT_MAX_CHARS")


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
def make_config(**overrides):
    config = {
        "ENABLE_FUNCTIONS": True,
        "ENABLE_MCP": False,
        "MAX_TOOL_CALL_DEPTH": 4,
        "TOOL_CONFIRM": False,
        "MODEL": "gpt-4o",
        "PROVIDER": "openai",
        "CONTEXT_BUDGET_TOKENS": 0,
        "RETRY_ENABLED": True,
        "RETRY_MAX": 2,
        "RETRY_BASE_DELAY": 0.0,
        "RETRY_MAX_DELAY": 0.0,
    }
    config.update(overrides)
    return config


class DenyApproval:
    """Minimal approval stub: nothing is pre-approved, nothing persists."""

    permissions_path = "<test>"

    def is_allowed(self, name):
        return False

    def allow_session(self, name):
        pass

    def allow_persist(self, name):
        pass


class ScriptedProvider:
    """Provider that replays a script, recording each request's messages snapshot.

    A script entry may be a list of ``LLMResponse`` objects, an exception instance
    (raised when the provider is called) or a zero-argument callable returning an
    iterator (used to model a stream that breaks after partial content).
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.snapshots = []

    def resolve_tool_policy(self, tool_policy):
        return tool_policy or ToolPolicy(enable_functions=True, enable_mcp=False)

    def detect_tool_role(self):
        return "tool"

    def completion(self, messages, stream=False, tool_policy=None):
        self.snapshots.append(list(messages))
        effect = self.script[self.calls]
        self.calls += 1
        if isinstance(effect, BaseException):
            raise effect
        if callable(effect):
            yield from effect()
        else:
            yield from effect


def make_client(provider, config, **kwargs):
    kwargs.setdefault("approval", DenyApproval())
    with patch.object(ProviderFactory, "create_provider", return_value=provider):
        client = LLMClient(provider_name="openai", config=config, **kwargs)
    client.provider = provider
    return client


class ContextLengthError(Exception):
    """Provider-style 400 context-length rejection (duck-typed like an SDK error)."""

    status_code = 400

    def __init__(self, message=None):
        super().__init__(
            message or "This model's maximum context length is 128000 tokens. Please reduce the length of the messages."
        )


class RateLimitError(Exception):
    status_code = 429

    def __init__(self):
        super().__init__("Rate limit reached for requests")


class AuthError(Exception):
    status_code = 401

    def __init__(self):
        super().__init__("Incorrect API key provided")


class NetworkError(Exception):
    def __init__(self):
        super().__init__("connection reset by peer")


def assistant_tool_turn(group_index, tool_contents=None, answer="done"):
    """Build one complete turn group: user -> assistant(tool_calls) -> tool results -> answer."""
    contents = list(tool_contents or ["tool output"])
    calls = [
        ToolCall(id=f"c{group_index}_{index}", name="fs_read_file", arguments=f'{{"file_paths": ["file{index}"]}}')
        for index in range(len(contents))
    ]
    messages = [ChatMessage(role="user", content=f"question {group_index}")]
    messages.append(ChatMessage(role="assistant", content="", tool_calls=calls))
    for call, content in zip(calls, contents):
        messages.append(ChatMessage(role="tool", content=content, name=call.name, tool_call_id=call.id))
    messages.append(ChatMessage(role="assistant", content=answer))
    return messages


def make_cmd_cli(history=None):
    """A lightweight CLI stand-in for CmdHandler tests (no REPL/prompt_toolkit)."""
    cli = SimpleNamespace(
        console=MagicMock(),
        chat=SimpleNamespace(history=list(history or [])),
        role=SimpleNamespace(prompt="You are YAICLI, a terminal agent."),
        context_manager=MagicMock(),
        verbose=False,
        init_role="DEFAULT",
        current_mode="chat",
    )
    return cli


def printed_text(console):
    return "\n".join(str(call.args[0]) if call.args else "" for call in console.print.call_args_list)


@pytest.fixture
def tool_output_config(tmp_path, monkeypatch):
    """Point tool-output spills at a temp dir; restore config afterwards."""
    monkeypatch.setitem(limits_module.cfg, "TOOL_OUTPUT_DIR", str(tmp_path / "tool-outputs"))
    monkeypatch.setitem(limits_module.cfg, "TOOL_OUTPUT_MAX_CHARS", 32000)
    return tmp_path / "tool-outputs"


@pytest.fixture
def clean_shell_env(monkeypatch):
    """Ensure shell guardrail env vars start unset and are restored afterwards.

    The code under test writes ``os.environ`` directly, which ``monkeypatch`` does
    not track for keys that were absent; restore them explicitly.
    """
    originals = {key: os.environ.get(key) for key in SHELL_ENV_KEYS}
    for key in SHELL_ENV_KEYS:
        os.environ.pop(key, None)
    yield monkeypatch
    for key, value in originals.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# 1. Estimator + model windows / budget
# ---------------------------------------------------------------------------
class TestTokenEstimator:
    def test_empty_values(self):
        assert estimate_tokens(None) == 0
        assert estimate_tokens("") == 0
        assert estimate_messages_tokens([]) == 0

    def test_latin_heuristic_and_monotonicity(self):
        assert estimate_tokens("a" * 350) == 100
        short = estimate_tokens("hello world")
        long = estimate_tokens("hello world " * 100)
        heavier = estimate_tokens("hello world " * 200)
        assert short < long < heavier
        # Every message carries a fixed framing overhead.
        assert estimate_messages_tokens([ChatMessage(role="user", content="hi")]) > estimate_tokens("hi")

    def test_cjk_is_denser_than_latin(self):
        assert estimate_tokens("中" * 100) == 100
        assert estimate_tokens("中" * 100) > estimate_tokens("a" * 100)
        assert estimate_tokens("测试中文内容") >= len("测试中文内容")

    def test_message_counts_tool_calls_and_reasoning(self):
        plain = ChatMessage(role="assistant", content="hi")
        with_tools = ChatMessage(
            role="assistant",
            content="hi",
            tool_calls=[ToolCall(id="c1", name="fs_read_file", arguments='{"file_paths": ["a.txt"]}')],
        )
        with_reasoning = ChatMessage(role="assistant", content="hi", reasoning="thinking " * 50)
        assert estimate_messages_tokens([with_tools]) > estimate_messages_tokens([plain])
        assert estimate_messages_tokens([with_reasoning]) > estimate_messages_tokens([plain])

    def test_image_message_is_charged(self):
        from yaicli.schemas import ImageData

        text_only = ChatMessage(role="user", content="see this")
        with_image = ChatMessage(
            role="user",
            content="see this",
            images=[ImageData(data="A" * 10000, media_type="image/png", is_url=False)],
        )
        assert estimate_messages_tokens([with_image]) > estimate_messages_tokens([text_only]) + 850


class TestModelWindowAndBudget:
    def test_context_window_table(self):
        assert get_context_window("gpt-4o") == 128000
        assert get_context_window("gpt-4.1") == 1047576
        assert get_context_window("gpt-5.2") == 400000
        assert get_context_window("claude-sonnet-4") == 200000
        assert get_context_window("gemini-2.5-pro") == 1048576
        assert get_context_window("deepseek-chat") == 128000
        assert get_context_window("totally-unknown-model") == DEFAULT_CONTEXT_WINDOW
        assert get_context_window("llama3:8b", provider="ollama") == OLLAMA_DEFAULT_CONTEXT_WINDOW

    def test_resolve_context_budget(self):
        assert resolve_context_budget({"MODEL": "gpt-4o"}, "gpt-4o") == int(128000 * 0.70)
        # Explicit configuration always wins.
        assert resolve_context_budget({"MODEL": "gpt-4o", "CONTEXT_BUDGET_TOKENS": 5000}) == 5000
        # Model defaults from config; provider enables the Ollama fallback.
        assert resolve_context_budget({"MODEL": "llama3", "PROVIDER": "ollama"}) == int(
            OLLAMA_DEFAULT_CONTEXT_WINDOW * 0.70
        )

    def test_estimate_context_usage_breakdown(self):
        messages = [
            ChatMessage(role="user", content="q" * 350),
            ChatMessage(
                role="assistant", content="", tool_calls=[ToolCall(id="c1", name="fs_read_file", arguments="{}")]
            ),
            ChatMessage(role="tool", content="t" * 700, name="fs_read_file", tool_call_id="c1"),
        ]
        usage = estimate_context_usage(messages, config={"MODEL": "gpt-4o"}, system_text="system prompt")
        assert usage.message_count == 3
        assert usage.system_tokens > 0
        assert usage.history_tokens > 0
        assert usage.tool_output_tokens > 0
        assert usage.total_tokens == usage.system_tokens + usage.history_tokens + 3
        assert usage.budget_tokens == int(128000 * 0.70)
        assert usage.remaining_tokens == usage.budget_tokens - usage.total_tokens
        assert 0 < usage.used_percent < 100


# ---------------------------------------------------------------------------
# 2. Turn-group trimming + pairing invariant
# ---------------------------------------------------------------------------
class TestTurnGroupTrim:
    def test_split_keeps_system_prefix_and_groups_at_user_boundaries(self):
        messages = [ChatMessage(role="system", content="sys")]
        messages += assistant_tool_turn(0)
        messages += assistant_tool_turn(1)
        prefix, groups = split_turn_groups(messages)
        assert prefix == [messages[0]]
        assert len(groups) == 2
        assert groups[0][0].role == "user"
        assert [message.role for message in groups[1]] == ["user", "assistant", "tool", "assistant"]

    def test_trimming_drops_whole_groups_and_keeps_pairing(self):
        messages = [ChatMessage(role="system", content="sys")]
        for index in range(4):
            messages += assistant_tool_turn(index)
        # Budget: fits the system prefix + roughly the last turn group.
        last_group_tokens = estimate_messages_tokens(assistant_tool_turn(3))
        budget = estimate_messages_tokens([messages[0]]) + last_group_tokens

        result = trim_messages_to_budget(messages, budget)

        assert result.removed_messages
        assert validate_tool_pairing(result.messages) == []
        assert result.messages[0].role == "system"
        assert result.messages[1].role == "user"
        # Only complete turn groups were removed: the newest user turn survives.
        assert result.messages[1].content == "question 3"
        assert result.tokens_after <= result.tokens_before
        # A tool_call message is never kept without its matching tool result.
        assert [message.role for message in result.messages[1:]] == ["user", "assistant", "tool", "assistant"]

    def test_trimming_never_splits_a_parallel_tool_group(self):
        tool_contents = ["a" * 500, "b" * 500, "c" * 500]
        messages = [ChatMessage(role="system", content="sys")]
        messages += assistant_tool_turn(0, tool_contents=tool_contents)
        messages += assistant_tool_turn(1)
        result = trim_messages_to_budget(messages, budget=1)  # keep only the newest group

        assert validate_tool_pairing(result.messages) == []
        assert len([message for message in result.messages if message.role == "tool"]) == 1
        assert result.messages[1].content == "question 1"

    def test_keep_recent_groups_ignores_budget(self):
        messages = []
        for index in range(6):
            messages += assistant_tool_turn(index)
        result = trim_messages_to_budget(messages, budget=0, keep_recent_groups=2)
        users = [message.content for message in result.messages if message.role == "user"]
        assert users == ["question 4", "question 5"]
        assert validate_tool_pairing(result.messages) == []

    def test_trim_oldest_group(self):
        messages = [ChatMessage(role="system", content="sys")]
        for index in range(3):
            messages += assistant_tool_turn(index)
        result = trim_oldest_group(messages)
        users = [message.content for message in result.messages if message.role == "user"]
        assert users == ["question 1", "question 2"]
        assert validate_tool_pairing(result.messages) == []

        single = [ChatMessage(role="user", content="only")]
        assert trim_oldest_group(single).removed_messages == []

    def test_repair_fixes_orphans_and_unanswered_calls(self):
        broken = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="tool", content="orphan", tool_call_id="nope"),
            ChatMessage(role="user", content="q"),
            ChatMessage(role="assistant", content="", tool_calls=[ToolCall(id="c1", name="x", arguments="{}")]),
            ChatMessage(role="assistant", content="final"),
        ]
        repaired = repair_tool_pairing(broken)
        assert not any(message.role == "tool" for message in repaired)
        calls = [call for message in repaired for tool_call in message.tool_calls for call in [tool_call]]
        assert calls == []
        assert validate_tool_pairing(repaired) == []

    def test_randomized_sessions_never_orphan_tool_messages(self):
        """500 tool-heavy sessions, trimmed after every turn: pairing stays valid."""
        rng = random.Random(20261104)
        for _ in range(500):
            messages = [ChatMessage(role="system", content="system prompt")]
            groups = rng.randint(1, 12)
            for group_index in range(groups):
                if rng.random() < 0.75:
                    tool_contents = ["x" * rng.randint(20, 5000) for _ in range(rng.randint(1, 3))]
                    messages += assistant_tool_turn(group_index, tool_contents=tool_contents)
                else:
                    messages += [
                        ChatMessage(role="user", content=f"q{group_index}" * rng.randint(1, 10)),
                        ChatMessage(role="assistant", content="y" * rng.randint(10, 800)),
                    ]
                # Trim repeatedly with varying budgets (as the REPL would per turn).
                if rng.random() < 0.6:
                    total = estimate_messages_tokens(messages)
                    budget = rng.randint(1, max(2, total))
                    trimmed = trim_messages_to_budget(messages, budget)
                    messages = trimmed.messages
                    assert validate_tool_pairing(messages) == []
                    assert trimmed.tokens_after <= trimmed.tokens_before
                    if len(messages) > 1:
                        assert messages[1].role == "user"
                    assert trimmed.removed_messages or len(messages) > 1

    def test_trim_preserves_system_prefix_even_when_over_budget(self):
        messages = [ChatMessage(role="system", content="s" * 3500)]
        messages += assistant_tool_turn(0)
        result = trim_messages_to_budget(messages, budget=100)
        assert result.messages[0].role == "system"
        assert validate_tool_pairing(result.messages) == []


# ---------------------------------------------------------------------------
# 3. Tool output truncation + spill
# ---------------------------------------------------------------------------
class TestToolOutputLimits:
    def test_per_tool_caps(self):
        assert resolve_output_cap("execute_shell_command") == 32000
        assert resolve_output_cap("fs_read_file") == 64000
        assert resolve_output_cap("fs_search_files") == 48000
        assert resolve_output_cap("fs_list_directory") == 48000
        assert resolve_output_cap("fetch_webpage") == 100000
        assert resolve_output_cap("unknown_tool") == 32000

    def test_short_output_is_unchanged(self, tool_output_config):
        assert truncate_tool_output("small output", "execute_shell_command") == "small output"

    def test_8mb_output_is_capped_spilled_and_mentions_path(self, tool_output_config):
        big = "A" * 8_000_000
        result = truncate_tool_output(big, "execute_shell_command")

        assert len(result) <= 32000
        assert "...[truncated " in result
        assert "full output saved to" in result
        assert "use fs_read_file with offset/limit to read more" in result

        match = re.search(r"full output saved to (.*?); use fs_read_file", result)
        assert match is not None
        spill_path = match.group(1)
        spilled = open(spill_path, encoding="utf-8").read()
        assert spilled == big

    def test_spill_file_is_private(self, tool_output_config):
        """Spilled tool output may contain secrets: create it with mode 0600."""
        result = truncate_tool_output("S" * 100_000, "execute_shell_command")
        match = re.search(r"full output saved to (.*?); use fs_read_file", result)
        assert match is not None
        spill_path = Path(match.group(1))
        assert spill_path.exists()
        if os.name != "posix":  # pragma: no cover - Windows chmod semantics differ
            return
        assert (spill_path.stat().st_mode & 0o777) == 0o600

    def test_truncated_output_can_be_paged_with_fs_read_file(self, tmp_path, tool_output_config, monkeypatch):
        """Manual-probe flow: a huge fs_read_file result is truncated, then pageable.

        The truncation marker tells the model to "use fs_read_file with offset/limit
        to read more"; this test proves that call actually works (on the spilled full
        output *and* on the original file) instead of erroring on unknown arguments.
        """
        from yaicli.functions.buildin.fs_read_file import Function as FSReadFileFunction
        from yaicli.tools.function import Function as ToolFunction

        big_path = tmp_path / "big.log"
        content = ("0123456789abcdef" * (8 * 1024 * 1024 // 16))[: 8 * 1024 * 1024]
        big_path.write_text(content)
        monkeypatch.setitem(tools_module.cfg, "SHOW_FUNCTION_OUTPUT", False)
        monkeypatch.setitem(tools_module.cfg, "SHOW_MCP_OUTPUT", False)

        tool = ToolFunction(function=FSReadFileFunction)
        tool_call = ToolCall(
            id="c-big",
            name="fs_read_file",
            arguments=json.dumps({"file_paths": [str(big_path)]}),
        )
        with patch("yaicli.tools.get_function", return_value=tool):
            result, ok = execute_tool_call(tool_call)

        # 1. The model-facing result is capped and points at the spilled full text.
        assert ok is True
        assert len(result) <= 64000
        assert "full output saved to" in result
        match = re.search(r"full output saved to (.*?); use fs_read_file", result)
        assert match is not None
        spill_path = match.group(1)

        # 2. Paging the spilled full output returns exactly the requested window.
        spilled_text = Path(spill_path).read_text(encoding="utf-8")
        paged_spill = json.loads(FSReadFileFunction.execute(spill_path, offset=100, limit=500))
        assert paged_spill["success"] is True
        assert paged_spill["content"] == spilled_text[100:600]
        assert paged_spill["truncated"] is True

        # 3. Paging the original file works too - no "unknown argument" failure.
        paged_original = json.loads(FSReadFileFunction.execute(str(big_path), offset=123456, limit=100))
        assert paged_original["success"] is True
        assert paged_original["error"] is None
        assert paged_original["content"] == content[123456:123556]
        assert paged_original["total_chars"] == len(content)
        assert paged_original["returned_chars"] == 100

    def test_per_tool_caps_apply_to_large_outputs(self, tool_output_config):
        payload = "B" * 500_000
        assert len(truncate_tool_output(payload, "fs_read_file")) <= 64000
        assert len(truncate_tool_output(payload, "fs_search_files")) <= 48000
        assert len(truncate_tool_output(payload, "fetch_webpage")) <= 100000
        # Small caps are allowed to cut much more aggressively.
        assert len(truncate_tool_output(payload, "execute_shell_command", max_chars=1000)) <= 1000

    def test_configured_cap_overrides_per_tool_caps(self, monkeypatch, tool_output_config):
        monkeypatch.setitem(limits_module.cfg, "TOOL_OUTPUT_MAX_CHARS", 5000)
        payload = "C" * 200_000
        assert len(truncate_tool_output(payload, "fetch_webpage")) <= 5000
        assert len(truncate_tool_output(payload, "execute_shell_command")) <= 5000

    def test_zero_disables_truncation(self, monkeypatch, tool_output_config):
        monkeypatch.setitem(limits_module.cfg, "TOOL_OUTPUT_MAX_CHARS", 0)
        payload = "D" * 100_000
        assert truncate_tool_output(payload, "execute_shell_command") == payload

    def test_spill_failure_degrades_to_plain_truncation(self, tmp_path, monkeypatch):
        blocker = tmp_path / "a-file"
        blocker.write_text("not a directory")
        monkeypatch.setitem(limits_module.cfg, "TOOL_OUTPUT_DIR", str(blocker / "sub"))
        monkeypatch.setitem(limits_module.cfg, "TOOL_OUTPUT_MAX_CHARS", 32000)

        result = truncate_tool_output("E" * 100_000, "execute_shell_command")
        assert len(result) <= 32000
        assert "truncated" in result
        assert "full output saved to" not in result

    def test_execute_tool_call_truncates_model_result_and_panel(self, tool_output_config, monkeypatch):
        tool = MagicMock()
        tool.execute.return_value = "Z" * 200_000
        tool_call = ToolCall(id="c1", name="fs_read_file", arguments='{"file_paths": ["big.txt"]}')
        monkeypatch.setitem(tools_module.cfg, "SHOW_FUNCTION_OUTPUT", True)
        monkeypatch.setitem(tools_module.cfg, "SHOW_MCP_OUTPUT", False)

        console = MagicMock()
        with (
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", console),
        ):
            result, ok = execute_tool_call(tool_call)

        assert ok is True
        assert len(result) <= 64000
        panels = [call.args[0] for call in console.print.call_args_list if hasattr(call.args[0], "renderable")]
        assert panels, "the SHOW_FUNCTION_OUTPUT panel must still be printed"
        assert len(panels[0].renderable.plain) <= 64000


# ---------------------------------------------------------------------------
# 4. Client integration: budget, 8MB tool result, self-heal, retry, depth
# ---------------------------------------------------------------------------
class TestClientContextBudget:
    def test_8mb_tool_result_keeps_next_request_payload_small(self, tool_output_config, clean_shell_env, monkeypatch):
        big_output = "Q" * 8_000_000
        tool = MagicMock()
        tool.execute.return_value = big_output
        monkeypatch.setitem(tools_module.cfg, "SHOW_FUNCTION_OUTPUT", False)
        monkeypatch.setitem(tools_module.cfg, "SHOW_MCP_OUTPUT", False)

        tool_turn = [
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                tool_call=ToolCall(
                    id="call_big",
                    name="execute_shell_command",
                    arguments='{"shell_command": "cat big.log"}',
                ),
            )
        ]
        provider = ScriptedProvider([tool_turn, [LLMResponse(content="done", finish_reason="stop")]])
        config = make_config(ENABLE_FUNCTIONS=True, MAX_TOOL_CALL_DEPTH=3, CONTEXT_BUDGET_TOKENS=100000)
        client = make_client(provider, config)

        messages = [ChatMessage(role="user", content="cat the big log")]
        with patch("yaicli.tools.get_function", return_value=tool):
            responses = list(client.completion_with_tools(messages, stream=False))

        assert any(getattr(response, "content", None) == "done" for response in responses)
        tool_messages = [message for message in provider.snapshots[1] if message.role == "tool"]
        assert tool_messages and len(tool_messages[0].content) <= 32000

        payload = json.dumps([asdict(message) for message in provider.snapshots[1]], default=str)
        assert len(payload.encode("utf-8")) < 64 * 1024

    def test_over_budget_history_is_trimmed_in_place_with_stderr_notice(self, capsys):
        old_turns = []
        for index in range(6):
            old_turns += assistant_tool_turn(index, tool_contents=["O" * 3000])
        provider = ScriptedProvider([[LLMResponse(content="ok", finish_reason="stop")]])
        # Tiny explicit budget forces a trim on the very first request.
        config = make_config(CONTEXT_BUDGET_TOKENS=400)
        client = make_client(provider, config)

        messages = [ChatMessage(role="system", content="system")] + old_turns + [ChatMessage(role="user", content="go")]
        list(client.completion_with_tools(messages, stream=False))  # noqa: F841 - generator consumed

        assert client.context_trimmed is True
        assert len(messages) < 1 + len(old_turns) + 1
        assert validate_tool_pairing(messages) == []
        assert any(message.content == "go" for message in messages)
        assert messages[-1].role == "assistant" and messages[-1].content == "ok"
        assert client.last_context_budget == 400
        assert client.last_tokens_estimate <= 400
        captured = capsys.readouterr()
        assert "Context over budget" in captured.err
        assert "Context over budget" not in captured.out

    def test_context_length_400_trims_one_extra_group_and_retries_once(self):
        history = [ChatMessage(role="system", content="system")]
        for index in range(3):
            history += assistant_tool_turn(index, tool_contents=["H" * 2000])
        provider = ScriptedProvider([ContextLengthError(), [LLMResponse(content="recovered", finish_reason="stop")]])
        config = make_config(CONTEXT_BUDGET_TOKENS=100000)
        client = make_client(provider, config)

        responses = list(
            client.completion_with_tools(history + [ChatMessage(role="user", content="continue")], stream=False)
        )

        assert any(getattr(response, "content", None) == "recovered" for response in responses)
        assert provider.calls == 2
        assert client.context_trimmed is True
        # The retried request lost exactly one turn group (the oldest one).
        retried = provider.snapshots[1]
        assert retried[0].role == "system"
        assert retried[1].content != "question 0"
        assert validate_tool_pairing(retried) == []

    def test_context_length_failure_after_retry_raises_actionable_agent_error(self):
        history = assistant_tool_turn(0)
        history += [ChatMessage(role="user", content="first")]
        provider = ScriptedProvider([ContextLengthError(), ContextLengthError()])
        config = make_config(CONTEXT_BUDGET_TOKENS=100000)
        client = make_client(provider, config)

        with pytest.raises(AgentError) as excinfo:
            list(client.completion_with_tools(history, stream=False))

        assert excinfo.value.kind is ErrorKind.CONTEXT_LENGTH
        message = str(excinfo.value)
        assert "/clear" in message and "/compact" in message
        assert provider.calls == 2  # initial + exactly one self-heal retry

    def test_context_length_with_a_single_turn_raises_actionable_error(self):
        provider = ScriptedProvider([ContextLengthError()])
        client = make_client(provider, make_config())
        with pytest.raises(AgentError) as excinfo:
            list(client.completion_with_tools([ChatMessage(role="user", content="one turn")], stream=False))
        assert excinfo.value.kind is ErrorKind.CONTEXT_LENGTH
        assert "single" in str(excinfo.value).lower() or "/clear" in str(excinfo.value)


class TestClientRetryPolicy:
    def test_rate_limit_error_is_retried_then_succeeds(self):
        provider = ScriptedProvider([RateLimitError(), [LLMResponse(content="after retry", finish_reason="stop")]])
        client = make_client(provider, make_config())
        responses = list(client.completion_with_tools([ChatMessage(role="user", content="hi")], stream=False))
        assert any(response.content == "after retry" for response in responses if isinstance(response, LLMResponse))
        assert provider.calls == 2

    def test_retry_can_be_disabled(self):
        provider = ScriptedProvider([RateLimitError(), [LLMResponse(content="nope")]])
        client = make_client(provider, make_config(RETRY_ENABLED=False))
        with pytest.raises(RateLimitError):
            list(client.completion_with_tools([ChatMessage(role="user", content="hi")], stream=False))
        assert provider.calls == 1

    def test_auth_error_is_not_retried(self):
        provider = ScriptedProvider([AuthError(), [LLMResponse(content="unreachable")]])
        client = make_client(provider, make_config())
        with pytest.raises(AuthError):
            list(client.completion_with_tools([ChatMessage(role="user", content="hi")], stream=False))
        assert provider.calls == 1

    def test_stream_break_after_content_raises_clear_error_without_retry(self):
        def broken_stream():
            yield LLMResponse(content="partial answer")
            raise NetworkError()

        provider = ScriptedProvider([broken_stream])
        client = make_client(provider, make_config())
        with pytest.raises(AgentError) as excinfo:
            list(client.completion_with_tools([ChatMessage(role="user", content="hi")], stream=True))
        assert "partial content" in str(excinfo.value)
        assert provider.calls == 1


class TestClientDepthLimit:
    def test_depth_limit_sets_flags_and_yields_finish_reason(self):
        tool_call = ToolCall(id="call_loop", name="fs_read_file", arguments='{"file_paths": ["x"]}')
        always_tool = [LLMResponse(content="", finish_reason="tool_calls", tool_call=tool_call)]
        provider = ScriptedProvider([always_tool, always_tool, always_tool, always_tool])
        config = make_config(MAX_TOOL_CALL_DEPTH=2)
        client = make_client(provider, config)

        with patch("yaicli.llms.client.execute_tool_call", return_value=("result", True)) as mock_execute:
            responses = list(client.completion_with_tools([ChatMessage(role="user", content="loop")], stream=False))

        assert client.depth_limit_reached is True
        assert client.last_finish_reason == "depth_limit"
        assert mock_execute.call_count == 2  # exactly the two allowed tool rounds
        depth_responses = [
            response
            for response in responses
            if isinstance(response, LLMResponse) and response.finish_reason == "depth_limit"
        ]
        assert len(depth_responses) == 1
        assert depth_responses[0].content == ""

    def test_tool_denied_flag_is_set(self):
        tool_call = ToolCall(id="call_denied", name="fs_read_file", arguments='{"file_paths": ["x"]}')
        provider = ScriptedProvider(
            [
                [LLMResponse(content="", finish_reason="tool_calls", tool_call=tool_call)],
                [LLMResponse(content="final", finish_reason="stop")],
            ]
        )
        config = make_config(TOOL_CONFIRM=True, MAX_TOOL_CALL_DEPTH=4)
        client = make_client(provider, config, interactive=False)

        list(client.completion_with_tools([ChatMessage(role="user", content="read x")], stream=False))

        assert client.tool_denied is True
        tool_messages = [message for message in provider.snapshots[1] if message.role == "tool"]
        assert tool_messages and "declined" in tool_messages[0].content.lower()


# ---------------------------------------------------------------------------
# 5. Shell guardrail config -> env propagation (K03 integration)
# ---------------------------------------------------------------------------
class TestShellGuardrailPropagation:
    def test_config_values_are_exported_for_the_shell_tool(self, clean_shell_env):
        tool = MagicMock()
        tool.execute.return_value = "ok"
        tool_call = ToolCall(id="c1", name="execute_shell_command", arguments='{"shell_command": "ls"}')
        fake_cfg = {
            "SHOW_FUNCTION_OUTPUT": False,
            "SHOW_MCP_OUTPUT": False,
            "TOOL_TIMEOUT": 7,
            "TOOL_ENV_INHERIT": True,
            "WORKSPACE_ROOT": "/tmp/workspace",
            "TOOL_OUTPUT_MAX_CHARS": 1234,
        }
        with (
            patch("yaicli.tools.cfg", fake_cfg),
            patch("yaicli.tools.get_function", return_value=tool),
        ):
            result, ok = execute_tool_call(tool_call)

        assert ok is True
        assert os.environ["YAI_TOOL_TIMEOUT"] == "7"
        assert os.environ["YAI_TOOL_ENV_INHERIT"] == "true"
        assert os.environ["YAI_WORKSPACE_ROOT"] == "/tmp/workspace"
        assert os.environ["YAI_TOOL_OUTPUT_MAX_CHARS"] == "1234"

    def test_exported_env_value_is_consistent_with_config(self, clean_shell_env):
        """cfg is env-first, so an exported value is written back unchanged."""
        clean_shell_env.setenv("YAI_TOOL_TIMEOUT", "99")
        tool = MagicMock()
        tool.execute.return_value = "ok"
        tool_call = ToolCall(id="c1", name="execute_shell_command", arguments='{"shell_command": "ls"}')
        fake_cfg = {"SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False, "TOOL_TIMEOUT": 99}
        with (
            patch("yaicli.tools.cfg", fake_cfg),
            patch("yaicli.tools.get_function", return_value=tool),
        ):
            execute_tool_call(tool_call)

        assert os.environ["YAI_TOOL_TIMEOUT"] == "99"

    def test_config_wins_over_stale_env_workspace_root(self, clean_shell_env):
        """--cwd sets cfg["WORKSPACE_ROOT"] after config load; it must win over env.

        Regression for the gap where an exported ``YAI_WORKSPACE_ROOT`` made
        ``--cwd`` silently ignored: entry._apply_cwd() writes the resolved directory
        to cfg, and the propagation step now exports the *config* value.
        """
        clean_shell_env.setenv("YAI_WORKSPACE_ROOT", "/old/exported/root")
        clean_shell_env.setenv("YAI_TOOL_TIMEOUT", "99")
        tool = MagicMock()
        tool.execute.return_value = "ok"
        tool_call = ToolCall(id="c1", name="execute_shell_command", arguments='{"shell_command": "ls"}')
        fake_cfg = {
            "SHOW_FUNCTION_OUTPUT": False,
            "SHOW_MCP_OUTPUT": False,
            "TOOL_TIMEOUT": 7,
            "WORKSPACE_ROOT": "/tmp/new-cwd-root",
            "TOOL_ENV_INHERIT": False,
        }
        with (
            patch("yaicli.tools.cfg", fake_cfg),
            patch("yaicli.tools.get_function", return_value=tool),
        ):
            execute_tool_call(tool_call)

        assert os.environ["YAI_WORKSPACE_ROOT"] == "/tmp/new-cwd-root"
        assert os.environ["YAI_TOOL_TIMEOUT"] == "7"

    def test_empty_config_values_are_not_exported(self, clean_shell_env):
        """Unset/empty config values keep the tool's built-in defaults."""
        tool = MagicMock()
        tool.execute.return_value = "ok"
        tool_call = ToolCall(id="c1", name="execute_shell_command", arguments='{"shell_command": "ls"}')
        fake_cfg = {"SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False, "WORKSPACE_ROOT": ""}
        with (
            patch("yaicli.tools.cfg", fake_cfg),
            patch("yaicli.tools.get_function", return_value=tool),
        ):
            execute_tool_call(tool_call)

        assert "YAI_WORKSPACE_ROOT" not in os.environ

    def test_non_shell_tools_do_not_touch_the_env(self, clean_shell_env):
        tool = MagicMock()
        tool.execute.return_value = "ok"
        tool_call = ToolCall(id="c1", name="get_weather", arguments='{"city": "NYC"}')
        fake_cfg = {"SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False, "TOOL_TIMEOUT": 7}
        with (
            patch("yaicli.tools.cfg", fake_cfg),
            patch("yaicli.tools.get_function", return_value=tool),
        ):
            execute_tool_call(tool_call)

        assert "YAI_TOOL_TIMEOUT" not in os.environ


# ---------------------------------------------------------------------------
# 6. /context and /compact REPL commands
# ---------------------------------------------------------------------------
class TestContextAndCompactCommands:
    def test_bare_context_prints_usage_and_still_lists_context(self):
        cli = make_cmd_cli()
        handler = CmdHandler(cli)

        assert handler.handle_context("/context") is True

        output = printed_text(cli.console)
        assert "Context usage (estimated)" in output
        assert "system prompt" in output
        assert "history" in output
        assert "budget" in output.lower()
        assert "remaining" in output
        cli.context_manager.list_items.assert_called_once()

    def test_context_budget_subcommand_prints_usage_only(self):
        cli = make_cmd_cli()
        handler = CmdHandler(cli)

        for subcommand in ("/context budget", "/context stats"):
            cli.console.print.reset_mock()
            assert handler.handle_context(subcommand) is True
            output = printed_text(cli.console)
            assert "Context usage (estimated)" in output
            cli.context_manager.list_items.assert_not_called()

    def test_existing_context_subcommands_still_work(self):
        cli = make_cmd_cli()
        handler = CmdHandler(cli)

        handler.handle_context("/context list")
        cli.context_manager.list_items.assert_called_once()
        handler.handle_context("/context clear")
        cli.context_manager.clear.assert_called_once()
        handler.handle_context("/context add f.txt")
        cli.context_manager.add.assert_called_once_with("f.txt")
        handler.handle_context("/context remove f.txt")
        cli.context_manager.remove.assert_called_once_with("f.txt")

    def test_context_is_registered_in_command_handler(self):
        cli = make_cmd_cli()
        handler = CmdHandler(cli)

        assert handler.handle_command("/context budget") is True
        assert "Context usage (estimated)" in printed_text(cli.console)

    def test_compact_keeps_last_turn_groups_and_reports_tokens(self):
        history = []
        for index in range(6):
            history += assistant_tool_turn(index, tool_contents=["T" * 1000])
        cli = make_cmd_cli(history=history)
        handler = CmdHandler(cli)

        assert handler.handle_command(f"{CMD_COMPACT} 2") is True

        compacted = cli.chat.history
        users = [message.content for message in compacted if message.role == "user"]
        assert users == ["question 4", "question 5"]
        assert validate_tool_pairing(compacted) == []
        output = printed_text(cli.console)
        assert "Compacted context" in output
        assert "estimated tokens" in output
        cli.context_manager.list_items.assert_not_called()

    def test_compact_default_keeps_five_groups(self):
        history = []
        for index in range(8):
            history += assistant_tool_turn(index)
        cli = make_cmd_cli(history=history)
        handler = CmdHandler(cli)

        assert handler.handle_command(CMD_COMPACT) is True

        users = [message.content for message in cli.chat.history if message.role == "user"]
        assert users == [f"question {index}" for index in range(3, 8)]

    def test_compact_with_nothing_to_do(self):
        cli = make_cmd_cli(history=assistant_tool_turn(0))
        handler = CmdHandler(cli)

        assert handler.handle_command(CMD_COMPACT) is True
        output = printed_text(cli.console)
        assert "Nothing to compact" in output

    def test_compact_with_empty_history(self):
        cli = make_cmd_cli()
        handler = CmdHandler(cli)

        assert handler.handle_command(CMD_COMPACT) is True
        assert "empty" in printed_text(cli.console).lower()

    def test_compact_rejects_invalid_keep_rounds(self):
        cli = make_cmd_cli(history=assistant_tool_turn(0))
        handler = CmdHandler(cli)

        assert handler.handle_command(f"{CMD_COMPACT} not-a-number") is True
        assert "Usage: /compact" in printed_text(cli.console)
        cli.console.print.reset_mock()
        assert handler.handle_command(f"{CMD_COMPACT} 0") is True
        assert "Usage: /compact" in printed_text(cli.console)


class TestCliErrorActionability:
    def test_handle_llm_response_prints_classified_hint(self):
        """K05: a 401 surfaces as an actionable classified message (not raw SDK text)."""
        from yaicli.cli import CLI
        from yaicli.errors import wrap_provider_exception

        class ProviderAuthError(Exception):
            status_code = 401

            def __init__(self):
                super().__init__("Incorrect API key provided")

        cli = CLI.__new__(CLI)
        cli.console = MagicMock()
        cli.verbose = False
        cli.machine_output = True
        cli.output_format = "text"
        cli.had_error = False
        cli.error_kind = ErrorKind.UNKNOWN
        cli.error_message = None
        cli.role = SimpleNamespace(prompt="system", name="DEFAULT")
        cli.current_mode = "chat"
        cli.chat = SimpleNamespace(history=[])
        cli.context_manager = MagicMock()
        cli.context_manager.get_context_messages.return_value = []
        cli.context_manager.parse_at_references.return_value = ("", "hi", [])
        cli.client = MagicMock()
        cli.client.completion_with_tools.side_effect = wrap_provider_exception(ProviderAuthError(), "OpenAI")

        content, messages = cli._handle_llm_response("hi")

        assert content is None
        output = printed_text(cli.console)
        assert "Error processing LLM response:" in output
        assert "auth" in output.lower()
        assert "Hint:" in output
        assert cli.had_error is True
        assert cli.error_kind is ErrorKind.AUTH


class TestCliHistoryTrim:
    def test_check_history_len_is_group_aware(self):
        from yaicli.cli import CLI

        cli = CLI.__new__(CLI)
        cli.console = MagicMock()
        cli.verbose = True
        cli.interactive_round = 2  # max 4 messages
        history = []
        for index in range(4):
            history += assistant_tool_turn(index)
        cli.chat = SimpleNamespace(history=history)

        cli._check_history_len()

        assert len(cli.chat.history) <= 4
        assert validate_tool_pairing(cli.chat.history) == []
        assert cli.chat.history[0].role == "user"
        assert "trimmed" in printed_text(cli.console).lower()

    def test_cli_persists_a_trim_after_a_context_length_error(self):
        from yaicli.cli import CLI

        cli = CLI.__new__(CLI)
        cli.console = MagicMock()
        history = []
        for index in range(3):
            history += assistant_tool_turn(index)
        cli.chat = SimpleNamespace(history=history)

        cli._recover_persisted_context_on_overflow(AgentError("context length exceeded", kind=ErrorKind.CONTEXT_LENGTH))

        assert len(cli.chat.history) < len(history)
        assert cli.chat.history[0].role == "user"
        assert validate_tool_pairing(cli.chat.history) == []

    def test_cli_does_not_touch_history_for_other_error_kinds(self):
        from yaicli.cli import CLI

        cli = CLI.__new__(CLI)
        cli.console = MagicMock()
        history = assistant_tool_turn(0)
        cli.chat = SimpleNamespace(history=history)

        cli._recover_persisted_context_on_overflow(AuthError())

        assert cli.chat.history is history
