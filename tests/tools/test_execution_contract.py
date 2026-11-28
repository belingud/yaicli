"""Behavioral seams kept intact when the tool entry point is split into modules."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yaicli import const
from yaicli.config import cfg
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
from yaicli.tools import execute_tool_call, output_history, workspace
from yaicli.tools.approval import ToolApprovalManager


class WritingProvider:
    """Repeat a real file-write request followed by a final answer, without an SDK."""

    def __init__(self, target):
        self.target = target
        self.requests = []

    def resolve_tool_policy(self, tool_policy):
        return tool_policy or ToolPolicy(True, False)

    def detect_tool_role(self):
        return "tool"

    def completion(self, messages, stream=False, tool_policy=None):
        self.requests.append(list(messages))
        if len(self.requests) % 2:
            yield LLMResponse(
                tool_call=ToolCall(
                    id="write-1",
                    name="fs_write_file",
                    arguments=json.dumps({"file_path": str(self.target), "content": "approved bytes\n"}),
                ),
                finish_reason="tool_calls",
            )
        else:
            yield LLMResponse(content="done", finish_reason="stop")


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    settings = {
        "ENABLE_FUNCTIONS": True,
        "ENABLE_MCP": False,
        "MAX_TOOL_CALL_DEPTH": 8,
        "TOOL_CONFIRM": True,
        "TOOL_POLICY": "standard",
        "TOOL_AUDIT": True,
        "ENABLED_TOOLS": "",
        "SHOW_FUNCTION_OUTPUT": False,
        "SHOW_MCP_OUTPUT": False,
        "WORKSPACE_ROOT": str(tmp_path),
        "TOOL_TIMEOUT": 120,
        "TOOL_ENV_INHERIT": True,
        "TOOL_OUTPUT_MAX_CHARS": 32000,
    }
    for key, value in settings.items():
        monkeypatch.setitem(cfg, key, value)
    for key in ("TOOL_TIMEOUT", "TOOL_ENV_INHERIT", "WORKSPACE_ROOT", "TOOL_OUTPUT_MAX_CHARS"):
        monkeypatch.setenv(
            "YAI_" + key, str(settings[key]).lower() if isinstance(settings[key], bool) else str(settings[key])
        )
    monkeypatch.setattr(const, "TOOL_AUDIT_PATH", tmp_path / "audit.jsonl")
    output_history.reset()
    workspace.reset_undo()
    target = tmp_path / "result.txt"
    provider = WritingProvider(target)
    manager = ToolApprovalManager(permissions_path=tmp_path / "permissions.json")
    with patch.object(ProviderFactory, "create_provider", return_value=provider):
        client = LLMClient("openai", config=settings, approval=manager)
    client.console = MagicMock()
    yield client, provider, manager, target
    output_history.reset()
    workspace.reset_undo()


def run_turn(client, decision):
    messages = [ChatMessage(role="user", content="write the file")]
    generator = client.completion_with_tools(messages, tool_policy=ToolPolicy(True, False))
    confirms = []
    response = None
    while True:
        try:
            item = generator.send(response) if response is not None else next(generator)
        except StopIteration:
            return messages, confirms
        response = None
        if isinstance(item, ConfirmToolCall):
            confirms.append(item.tool_call)
            response = decision


@pytest.mark.parametrize("decision", [ToolConfirmDecision.ONCE, ToolConfirmDecision.DENY])
def test_confirmed_or_denied_call_reaches_real_dispatch_contract(runtime, decision):
    client, provider, _, target = runtime
    console = MagicMock()
    with patch("yaicli.tools.console", console):
        messages, confirms = run_turn(client, decision)
    assert len(confirms) == 1
    assert len(provider.requests) == 2
    tool_message = next(message for message in messages if message.role == "tool")
    assert tool_message.tool_call_id == "write-1"
    assert tool_message.name == "fs_write_file"
    assert provider.requests[1][-1] is tool_message
    audit = [json.loads(line) for line in const.TOOL_AUDIT_PATH.read_text().splitlines()]
    assert len(audit) == 1
    assert audit[0]["source"] == "prompt"
    assert audit[0]["tool"] == "fs_write_file"
    if decision == ToolConfirmDecision.ONCE:
        assert target.read_bytes() == b"approved bytes\n"
        assert json.loads(tool_message.content)["success"] is True
        assert audit[0]["decision"] == "allowed"
        assert len(output_history.all_outputs()) == 1
    else:
        assert not target.exists()
        assert json.loads(tool_message.content)["error"] == "tool_denied"
        assert audit[0]["decision"] == "denied"
        assert output_history.all_outputs() == []
    assert not any("@Function call" in str(call) for call in console.print.call_args_list)


def test_persist_failure_still_executes_and_only_grants_current_session(runtime):
    client, provider, manager, target = runtime
    with patch.object(manager, "allow_persist", side_effect=OSError("read-only permission file")):
        first_messages, first_confirms = run_turn(client, ToolConfirmDecision.PERSIST)
    second_messages, second_confirms = run_turn(client, ToolConfirmDecision.DENY)
    assert len(first_confirms) == 1
    assert second_confirms == []
    assert len(provider.requests) == 4
    assert target.read_bytes() == b"approved bytes\n"
    for messages in (first_messages, second_messages):
        result = next(message for message in messages if message.role == "tool")
        assert result.tool_call_id == "write-1"
        assert json.loads(result.content)["success"] is True
    assert manager.is_allowed("fs_write_file")
    reloaded = ToolApprovalManager(permissions_path=manager.permissions_path)
    assert not reloaded.is_allowed("fs_write_file")
    client.console.print.assert_called_once_with(
        "Could not persist approval for 'fs_write_file'; allowed for this session only.", style="yellow"
    )


def test_dispatch_truncates_once_and_keeps_original_spill_and_single_history_entry(tmp_path, monkeypatch):
    original = "a complete output line\n" * 500
    config = {
        "TOOL_OUTPUT_DIR": str(tmp_path),
        "TOOL_OUTPUT_MAX_CHARS": 400,
        "SHOW_FUNCTION_OUTPUT": False,
        "SHOW_MCP_OUTPUT": False,
    }
    tool = MagicMock()
    tool.execute.return_value = original
    output_history.reset()
    try:
        with (
            patch("yaicli.tools.executor.get_function", return_value=tool),
            patch("yaicli.tools.cfg", config),
            patch("yaicli.tools.console", MagicMock()),
        ):
            model_text, ok = execute_tool_call(ToolCall(id="large", name="large_output", arguments="{}"))
        assert ok is True
        entries = output_history.all_outputs()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.total_chars == len(original)
        assert entry.truncated is True
        assert entry.text == model_text
        assert len(model_text) <= 400
        assert Path(entry.spill_path).read_text() == original
        assert list(tmp_path.glob("*.txt")) == [Path(entry.spill_path)]
        tool.execute.assert_called_once_with()
    finally:
        output_history.reset()
