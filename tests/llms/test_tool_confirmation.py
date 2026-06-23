from unittest.mock import patch

from yaicli.llms.client import LLMClient
from yaicli.llms.provider import ProviderFactory
from yaicli.schemas import (
    ChatMessage,
    ConfirmToolCall,
    LLMResponse,
    ToolCall,
    ToolConfirmDecision,
    ToolPolicy,
)
from yaicli.tools.approval import ToolApprovalManager


class FakeProvider:
    """Minimal provider that replays scripted LLMResponse batches, one per completion() call."""

    def __init__(self, scripted):
        self._scripted = scripted
        self.calls = 0

    def resolve_tool_policy(self, tool_policy):
        return tool_policy or ToolPolicy(enable_functions=True, enable_mcp=True)

    def completion(self, messages, stream=False, tool_policy=None):
        batch = self._scripted[self.calls]
        self.calls += 1
        yield from batch

    def detect_tool_role(self):
        return "tool"


def make_client(scripted, approval, *, interactive=True, tool_confirm=True):
    config = {
        "ENABLE_FUNCTIONS": True,
        "ENABLE_MCP": True,
        "MAX_TOOL_CALL_DEPTH": 8,
        "TOOL_CONFIRM": tool_confirm,
    }
    fake = FakeProvider(scripted)
    with patch.object(ProviderFactory, "create_provider", return_value=fake):
        client = LLMClient(provider_name="openai", config=config, approval=approval, interactive=interactive)
    client.provider = fake
    return client


def drive(gen, decisions):
    """Pump a completion_with_tools generator, answering ConfirmToolCall with queued decisions.

    Returns (collected_items, num_confirms).
    """
    decisions = list(decisions)
    items = []
    send_value = None
    confirms = 0
    while True:
        try:
            item = gen.send(send_value) if send_value is not None else next(gen)
        except StopIteration:
            break
        send_value = None
        items.append(item)
        if isinstance(item, ConfirmToolCall):
            confirms += 1
            send_value = decisions.pop(0)
    return items, confirms


def _tool_then_done(tc):
    """Script: first turn returns a tool call, recursion returns final content."""
    return [
        [LLMResponse(tool_call=tc, finish_reason="tool_calls")],
        [LLMResponse(content="done", finish_reason="stop")],
    ]


def _tool_messages(messages):
    return [m for m in messages if m.role == "tool"]


def test_approve_once_executes_but_is_not_remembered(tmp_path):
    approval = ToolApprovalManager(permissions_path=tmp_path / "p.json")
    tc = ToolCall(id="c1", name="get_weather", arguments="{}")
    client = make_client(_tool_then_done(tc), approval)
    messages = [ChatMessage(role="user", content="weather?")]

    with patch("yaicli.llms.client.execute_tool_call", return_value=("ok", True)) as ex:
        gen = client.completion_with_tools(messages, tool_policy=ToolPolicy(True, True))
        _, confirms = drive(gen, [ToolConfirmDecision.ONCE])

    assert confirms == 1
    ex.assert_called_once()
    # "once" must not be remembered
    assert approval.is_allowed("get_weather") is False
    tool_msgs = _tool_messages(messages)
    assert len(tool_msgs) == 1 and tool_msgs[0].tool_call_id == "c1"


def test_session_approval_skips_later_prompts(tmp_path):
    approval = ToolApprovalManager(permissions_path=tmp_path / "p.json")

    # Turn 1: approve for the session
    tc1 = ToolCall(id="c1", name="get_weather", arguments="{}")
    client1 = make_client(_tool_then_done(tc1), approval)
    with patch("yaicli.llms.client.execute_tool_call", return_value=("ok", True)):
        gen1 = client1.completion_with_tools([ChatMessage(role="user", content="x")], tool_policy=ToolPolicy(True, True))
        _, confirms1 = drive(gen1, [ToolConfirmDecision.SESSION])
    assert confirms1 == 1
    assert approval.is_allowed("get_weather") is True

    # Turn 2: same tool, same approval manager -> no prompt
    tc2 = ToolCall(id="c2", name="get_weather", arguments="{}")
    client2 = make_client(_tool_then_done(tc2), approval)
    with patch("yaicli.llms.client.execute_tool_call", return_value=("ok", True)) as ex2:
        gen2 = client2.completion_with_tools([ChatMessage(role="user", content="y")], tool_policy=ToolPolicy(True, True))
        _, confirms2 = drive(gen2, [])
    assert confirms2 == 0
    ex2.assert_called_once()


def test_persist_decision_writes_allowlist(tmp_path):
    path = tmp_path / "p.json"
    approval = ToolApprovalManager(permissions_path=path)
    tc = ToolCall(id="c1", name="get_weather", arguments="{}")
    client = make_client(_tool_then_done(tc), approval)

    with patch("yaicli.llms.client.execute_tool_call", return_value=("ok", True)):
        gen = client.completion_with_tools([ChatMessage(role="user", content="x")], tool_policy=ToolPolicy(True, True))
        drive(gen, [ToolConfirmDecision.PERSIST])

    # Persisted and honored by a fresh manager loaded from disk
    assert ToolApprovalManager(permissions_path=path).is_allowed("get_weather") is True


def test_deny_appends_refusal_and_does_not_execute(tmp_path):
    approval = ToolApprovalManager(permissions_path=tmp_path / "p.json")
    tc = ToolCall(id="c1", name="get_weather", arguments="{}")
    client = make_client(_tool_then_done(tc), approval)
    messages = [ChatMessage(role="user", content="x")]

    with patch("yaicli.llms.client.execute_tool_call") as ex:
        gen = client.completion_with_tools(messages, tool_policy=ToolPolicy(True, True))
        drive(gen, [ToolConfirmDecision.DENY])

    ex.assert_not_called()
    tool_msgs = _tool_messages(messages)
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "c1"
    assert "declined" in (tool_msgs[0].content or "").lower()


def test_deny_mcp_tool_result_name_is_deprefixed(tmp_path):
    approval = ToolApprovalManager(permissions_path=tmp_path / "p.json")
    tc = ToolCall(id="c1", name="_mcp__clock", arguments="{}")
    scripted = [
        [LLMResponse(tool_call=tc, finish_reason="tool_calls")],
        [LLMResponse(content="done", finish_reason="stop")],
    ]
    client = make_client(scripted, approval)
    messages = [ChatMessage(role="user", content="x")]

    with patch("yaicli.llms.client.execute_tool_call") as ex:
        gen = client.completion_with_tools(messages, tool_policy=ToolPolicy(True, True))
        drive(gen, [ToolConfirmDecision.DENY])

    ex.assert_not_called()
    tool_msgs = _tool_messages(messages)
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "c1"
    # MCP prefix stripped, matching the executed path
    assert tool_msgs[0].name == "clock"


def test_multi_tool_turn_denies_one_executes_other(tmp_path):
    approval = ToolApprovalManager(permissions_path=tmp_path / "p.json")
    tc1 = ToolCall(id="c1", name="danger", arguments="{}")
    tc2 = ToolCall(id="c2", name="safe", arguments="{}")
    scripted = [
        [
            LLMResponse(tool_call=tc1, finish_reason="tool_calls"),
            LLMResponse(tool_call=tc2, finish_reason="tool_calls"),
        ],
        [LLMResponse(content="done", finish_reason="stop")],
    ]
    client = make_client(scripted, approval)
    messages = [ChatMessage(role="user", content="x")]

    with patch("yaicli.llms.client.execute_tool_call", return_value=("ok", True)) as ex:
        gen = client.completion_with_tools(messages, tool_policy=ToolPolicy(True, True))
        _, confirms = drive(gen, [ToolConfirmDecision.DENY, ToolConfirmDecision.ONCE])

    assert confirms == 2
    assert ex.call_count == 1  # only the approved call executed
    # Every tool call has a matching result (so the next request stays valid)
    assert {m.tool_call_id for m in _tool_messages(messages)} == {"c1", "c2"}


def test_non_interactive_denies_unapproved(tmp_path):
    approval = ToolApprovalManager(permissions_path=tmp_path / "p.json")
    tc = ToolCall(id="c1", name="get_weather", arguments="{}")
    client = make_client(_tool_then_done(tc), approval, interactive=False)
    messages = [ChatMessage(role="user", content="x")]

    with patch("yaicli.llms.client.execute_tool_call") as ex:
        gen = client.completion_with_tools(messages, tool_policy=ToolPolicy(True, True))
        _, confirms = drive(gen, [])

    assert confirms == 0  # never prompts without a TTY
    ex.assert_not_called()
    tool_msgs = _tool_messages(messages)
    assert tool_msgs and tool_msgs[0].tool_call_id == "c1"


def test_non_interactive_allowlisted_runs(tmp_path):
    approval = ToolApprovalManager(permissions_path=tmp_path / "p.json")
    approval.allow_session("get_weather")
    tc = ToolCall(id="c1", name="get_weather", arguments="{}")
    client = make_client(_tool_then_done(tc), approval, interactive=False)

    with patch("yaicli.llms.client.execute_tool_call", return_value=("ok", True)) as ex:
        gen = client.completion_with_tools([ChatMessage(role="user", content="x")], tool_policy=ToolPolicy(True, True))
        _, confirms = drive(gen, [])

    assert confirms == 0
    ex.assert_called_once()


def test_master_switch_off_executes_without_prompt(tmp_path):
    approval = ToolApprovalManager(permissions_path=tmp_path / "p.json")
    tc = ToolCall(id="c1", name="get_weather", arguments="{}")
    client = make_client(_tool_then_done(tc), approval, tool_confirm=False)

    with patch("yaicli.llms.client.execute_tool_call", return_value=("ok", True)) as ex:
        gen = client.completion_with_tools([ChatMessage(role="user", content="x")], tool_policy=ToolPolicy(True, True))
        _, confirms = drive(gen, [])

    assert confirms == 0
    ex.assert_called_once()
