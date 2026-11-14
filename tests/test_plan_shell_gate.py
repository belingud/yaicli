"""Tool-layer plan-mode gate tests (v0.24 K23).

Covers the controlled read-only shell in ``execute_tool_call`` (denial JSON + REPL
line + audit, allowed path with the executor mocked), the session-tool dispatch
(``submit_plan`` / ``todo_write`` are not builtin functions), the mode-aware
schema getters, the plans-root write guard and the client-side plan gate.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rich.panel import Panel

from yaicli import const, plan_mode, plan_shell
from yaicli import tools as tools_mod
from yaicli.config import cfg
from yaicli.llms.client import LLMClient
from yaicli.llms.provider import Provider
from yaicli.schemas import ChatMessage, ConfirmToolCall, LLMResponse, ToolCall
from yaicli.tools import (
    execute_tool_call,
    get_anthropic_mcp_tools,
    get_anthropic_schemas,
    get_openai_mcp_tools,
    get_openai_schemas,
    output_history,
    set_plan_tool_mode,
    workspace,
)
from yaicli.tools import function as function_mod


@pytest.fixture(autouse=True)
def plan_state(tmp_path, monkeypatch):
    """Isolate plan state, plans root, audit log, schemas and the tool console."""
    plan_mode.reset_plan_session()
    set_plan_tool_mode(None)
    monkeypatch.setitem(cfg, "PLAN_DIR", str(tmp_path / "plans"))
    monkeypatch.setitem(cfg, "PLAN_ALLOW_READONLY_SHELL", True)
    monkeypatch.setitem(cfg, "TOOL_AUDIT", True)
    monkeypatch.setitem(cfg, "ENABLED_TOOLS", "")
    monkeypatch.setitem(cfg, "SHOW_FUNCTION_OUTPUT", False)
    monkeypatch.setitem(cfg, "SHOW_MCP_OUTPUT", False)
    monkeypatch.setattr(const, "TOOL_AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(tools_mod, "_openai_schemas_cache", None)
    monkeypatch.setattr(tools_mod, "_anthropic_schemas_cache", None)
    monkeypatch.setattr(tools_mod, "_filtered_schemas_cache", {})
    monkeypatch.setattr(tools_mod, "_warned_tool_patterns", set())
    monkeypatch.setattr(function_mod, "_gemini_functions_cache", None)
    monkeypatch.delenv("YAI_WORKSPACE_ROOT", raising=False)
    session = plan_mode.get_plan_session()
    session.configure(plans_root=tmp_path / "plans", cwd=tmp_path, model="test-model", session_id="sess-1")
    yield SimpleNamespace(session=session, tmp_path=tmp_path, audit_path=tmp_path / "audit.jsonl")
    plan_mode.reset_plan_session()
    set_plan_tool_mode(None)


def _audit_lines(audit_path):
    if not os.path.exists(audit_path):
        return []
    return [json.loads(line) for line in open(audit_path, encoding="utf-8").read().splitlines() if line.strip()]


def _plan_records(audit_path):
    return [record for record in _audit_lines(audit_path) if str(record.get("event", "")).startswith("plan.")]


def _tool_records(audit_path):
    return [record for record in _audit_lines(audit_path) if "event" not in record and "tool" in record]


def _plan_payload():
    return {
        "goal": "Add a dry-run flag to fs_write_file",
        "steps": [
            {"title": "Locate the write path", "acceptance": "the code path is known"},
            {"title": "Add the flag", "acceptance": "pytest tests/tools passes"},
        ],
    }


def _approve_plan(session):
    session.enter_researching()
    assert plan_mode.handle_submit_plan(_plan_payload())["success"] is True
    assert plan_mode.approve_new_plan(session)["success"] is True


class TestSessionToolsViaExecuteToolCall:
    """Regression: session tools are not builtin functions (K23 blocker fix)."""

    def test_submit_plan_executes_and_writes_the_draft(self, plan_state, monkeypatch):
        session = plan_state.session
        session.enter_researching()
        set_plan_tool_mode("plan")
        console = MagicMock()
        monkeypatch.setattr(tools_mod, "console", console)
        get_function = MagicMock(side_effect=AssertionError("builtin lookup must not run for session tools"))
        monkeypatch.setattr(tools_mod, "get_function", get_function)
        tool_call = ToolCall(id="call_1", name="submit_plan", arguments=json.dumps(_plan_payload()))
        result, ok = execute_tool_call(tool_call)
        assert ok is True
        payload = json.loads(result)
        assert payload["success"] is True
        assert session.draft_plan is not None
        assert session.draft_plan.path.is_file()
        assert session.mode == "reviewing"
        get_function.assert_not_called()
        # The announce line is still printed for the session tool.
        printed = [str(call.args[0]) for call in console.print.call_args_list]
        assert any("@Function call: submit_plan" in text for text in printed)
        # The result is recorded in the Ctrl+O output history (no output panel).
        recorded = output_history.last_output()
        assert recorded is not None
        assert recorded.name == "submit_plan"
        assert json.loads(recorded.text)["success"] is True
        assert not any(isinstance(call.args[0], Panel) for call in console.print.call_args_list)

    def test_todo_write_executes_and_records(self, plan_state, monkeypatch):
        session = plan_state.session
        _approve_plan(session)
        set_plan_tool_mode("execution")
        console = MagicMock()
        monkeypatch.setattr(tools_mod, "console", console)
        tool_call = ToolCall(
            id="call_2",
            name="todo_write",
            arguments=json.dumps(
                {"items": [{"id": "S1", "status": "completed"}, {"id": "S2", "status": "in_progress"}]}
            ),
        )
        result, ok = execute_tool_call(tool_call)
        assert ok is True
        payload = json.loads(result)
        assert payload["success"] is True
        assert session.todo_snapshot() == (("S1", "completed"), ("S2", "in_progress"))
        recorded = output_history.last_output()
        assert recorded is not None and recorded.name == "todo_write"
        printed = [str(call.args[0]) for call in console.print.call_args_list]
        assert any(text.startswith("[todo 2/2] S2") for text in printed)

    def test_session_tool_error_is_in_band(self, plan_state, monkeypatch):
        """A hard submit_plan call outside plan mode returns JSON, never raises."""
        monkeypatch.setattr(tools_mod, "console", MagicMock())
        set_plan_tool_mode("plan")
        result, ok = execute_tool_call(ToolCall(id="1", name="submit_plan", arguments=json.dumps(_plan_payload())))
        assert ok is True
        assert json.loads(result)["error"] == "plan_not_active"


class TestPlanShellGate:
    def test_metachar_command_is_denied_without_running(self, plan_state, monkeypatch):
        session = plan_state.session
        session.enter_researching()
        set_plan_tool_mode("plan")
        console = MagicMock()
        monkeypatch.setattr(tools_mod, "console", console)
        run_shell = MagicMock(side_effect=AssertionError("denied commands must not run"))
        monkeypatch.setattr(plan_shell, "run_plan_shell", run_shell)
        tool_call = ToolCall(
            id="1",
            name="execute_shell_command",
            arguments=json.dumps({"command": "git status | head -5"}),
        )
        result, ok = execute_tool_call(tool_call)
        assert ok is True
        payload = json.loads(result)
        assert payload["error"] == "plan_shell_denied"
        assert "shell metacharacters are not allowed in plan mode" in payload["reason"]
        assert payload["hint"]
        run_shell.assert_not_called()
        printed = [str(call.args[0]) for call in console.print.call_args_list]
        assert any(text.startswith("✗ plan_shell_denied:") for text in printed)
        records = _plan_records(plan_state.audit_path)
        assert records[-1]["event"] == "plan.shell_denied"
        assert "metacharacters" in records[-1]["reason"]

    def test_not_allowlisted_command_is_denied(self, plan_state, monkeypatch):
        plan_state.session.enter_researching()
        set_plan_tool_mode("plan")
        monkeypatch.setattr(tools_mod, "console", MagicMock())
        result, ok = execute_tool_call(
            ToolCall(id="1", name="execute_shell_command", arguments=json.dumps({"command": "rm -rf build/"}))
        )
        assert ok is True
        payload = json.loads(result)
        assert payload["error"] == "plan_shell_denied"
        assert "`rm` is not in the plan-mode read-only allowlist" in payload["reason"]

    def test_dangerous_flag_is_denied(self, plan_state, monkeypatch):
        plan_state.session.enter_researching()
        set_plan_tool_mode("plan")
        monkeypatch.setattr(tools_mod, "console", MagicMock())
        result, _ok = execute_tool_call(
            ToolCall(id="1", name="execute_shell_command", arguments=json.dumps({"command": "find . -delete"}))
        )
        payload = json.loads(result)
        assert payload["error"] == "plan_shell_denied"
        assert "not allowed in plan mode" in payload["reason"]

    def test_allowed_command_runs_through_plan_shell(self, plan_state, monkeypatch):
        plan_state.session.enter_researching()
        set_plan_tool_mode("plan")
        calls = {}

        def fake_run(argv, *, cwd=None, timeout=None):
            calls.update({"argv": tuple(argv), "cwd": cwd, "timeout": timeout})
            return "Exit code: 0, Output:\noneline"

        monkeypatch.setattr(plan_shell, "run_plan_shell", fake_run)
        tool_call = ToolCall(
            id="1",
            name="execute_shell_command",
            arguments=json.dumps({"command": "git status", "cwd": "sub", "timeout": 5}),
        )
        result, ok = execute_tool_call(tool_call)
        assert ok is True
        assert result == "Exit code: 0, Output:\noneline"
        assert calls == {"argv": ("git", "status"), "cwd": "sub", "timeout": 5}
        records = _plan_records(plan_state.audit_path)
        assert records[-1]["event"] == "plan.shell"
        assert records[-1]["decision"] == "allowed"

    def test_plan_shell_gate_only_applies_while_planning(self, plan_state, monkeypatch):
        """Outside plan mode the normal shell dispatch is untouched."""
        set_plan_tool_mode("plan")
        tool = MagicMock()
        tool.execute.return_value = "normal result"
        monkeypatch.setattr(tools_mod, "console", MagicMock())
        monkeypatch.setattr(tools_mod, "get_function", MagicMock(return_value=tool))
        monkeypatch.setattr(plan_shell, "run_plan_shell", MagicMock(side_effect=AssertionError("not plan mode")))
        result, ok = execute_tool_call(
            ToolCall(id="1", name="execute_shell_command", arguments=json.dumps({"command": "git status | head"}))
        )
        assert ok is True
        assert result == "normal result"
        tool.execute.assert_called_once_with(command="git status | head")


class TestModeAwareSchemas:
    @staticmethod
    def _builtin_names():
        return {name for name in function_mod.get_func_name_map()}

    @staticmethod
    def _openai_names(schemas):
        return [schema["function"]["name"] for schema in schemas]

    def test_normal_schemas_unchanged(self):
        set_plan_tool_mode(None)
        schemas = get_openai_schemas()
        assert len(schemas) == len(self._builtin_names())
        assert schemas is tools_mod._openai_schemas_cache

    def test_plan_mode_schemas_are_the_allowlist_plus_submit_plan(self, plan_state):
        set_plan_tool_mode("plan")
        names = set(self._openai_names(get_openai_schemas()))
        expected = self._builtin_names() & set(plan_mode.plan_tool_allowlist(True))
        expected.add("submit_plan")
        assert names == expected
        assert "fs_write_file" not in names
        assert "todo_write" not in names

    def test_plan_mode_without_readonly_shell(self, plan_state, monkeypatch):
        monkeypatch.setitem(cfg, "PLAN_ALLOW_READONLY_SHELL", False)
        set_plan_tool_mode("plan")
        names = set(self._openai_names(get_openai_schemas()))
        assert "execute_shell_command" not in names
        assert "submit_plan" in names

    def test_execution_mode_appends_todo_write(self):
        set_plan_tool_mode("execution")
        names = set(self._openai_names(get_openai_schemas()))
        assert names == self._builtin_names() | {"todo_write"}

    def test_anthropic_schemas_follow_the_mode(self):
        set_plan_tool_mode("plan")
        names = {schema["name"] for schema in get_anthropic_schemas()}
        assert "submit_plan" in names
        assert "fs_write_file" not in names

    def test_cache_identity_restored_after_plan_mode(self):
        set_plan_tool_mode(None)
        baseline = get_openai_schemas()
        set_plan_tool_mode("plan")
        get_openai_schemas()
        set_plan_tool_mode("execution")
        get_openai_schemas()
        set_plan_tool_mode(None)
        assert get_openai_schemas() is baseline

    def test_enabled_tools_applies_last(self, plan_state, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "fs_read_file,submit_plan")
        set_plan_tool_mode("plan")
        assert set(self._openai_names(get_openai_schemas())) == {"fs_read_file", "submit_plan"}

    def test_mcp_schemas_hidden_in_plan_mode(self):
        set_plan_tool_mode("plan")
        with patch("yaicli.tools.get_mcp_manager", side_effect=AssertionError("must not connect to MCP")):
            assert get_openai_mcp_tools() == []
            assert get_anthropic_mcp_tools() == []

    def test_mcp_schemas_available_in_normal_mode(self):
        set_plan_tool_mode(None)
        manager = MagicMock()
        manager.to_openai_tools.return_value = [{"type": "function", "function": {"name": "_mcp__a"}}]
        with patch("yaicli.tools.get_mcp_manager", return_value=manager):
            assert len(get_openai_mcp_tools()) == 1

    def test_gemini_functions_follow_the_mode(self):
        set_plan_tool_mode("plan")
        names = {function.__name__ for function in function_mod.get_functions_gemini_format()}
        assert "submit_plan" in names
        assert "fs_write_file" not in names
        set_plan_tool_mode("execution")
        names = {function.__name__ for function in function_mod.get_functions_gemini_format()}
        assert "todo_write" in names
        set_plan_tool_mode(None)
        names = {function.__name__ for function in function_mod.get_functions_gemini_format()}
        assert names == self._builtin_names()


class TestPlansRootWriteGuard:
    def test_agent_write_under_plans_root_is_denied(self, plan_state):
        plans_root = plan_state.tmp_path / "plans"
        target = plans_root / "some-project" / "plan.md"
        plan = workspace.prepare_mutation(
            "fs_write_file",
            {"file_path": str(target), "content": "x", "mode": "w"},
            root=plan_state.tmp_path,
        )
        assert plan.allowed is False
        payload = json.loads(plan.denial)
        assert payload["success"] is False
        assert payload["error"] == "protected_path"
        assert payload["reason"] == "plan files are managed by the CLI"

    def test_edit_under_plans_root_is_denied(self, plan_state):
        plans_root = plan_state.tmp_path / "plans"
        target = plans_root / "some-project" / "plan.md"
        plan = workspace.prepare_mutation(
            "fs_edit_file",
            {"file_path": str(target), "old_string": "a", "new_string": "b"},
            root=plan_state.tmp_path,
        )
        assert plan.allowed is False
        assert json.loads(plan.denial)["error"] == "protected_path"

    def test_regular_workspace_path_still_allowed(self, plan_state):
        target = plan_state.tmp_path / "src" / "app.py"
        plan = workspace.prepare_mutation(
            "fs_write_file",
            {"file_path": str(target), "content": "x", "mode": "w"},
            root=plan_state.tmp_path,
        )
        assert plan.allowed is True


# ---------------------------------------------------------------------------
# Client-side plan gate
# ---------------------------------------------------------------------------
class _GateProvider(Provider):
    """Provider whose first round requests one tool, then answers."""

    def __init__(self, tool_name, arguments="{}"):
        self.tool_name = tool_name
        self.arguments = arguments
        self.rounds = 0
        self.config = {"ENABLE_FUNCTIONS": True, "ENABLE_MCP": False}
        self.enable_function = True
        self.enable_mcp = False

    def completion(self, messages, stream=False, tool_policy=None):
        self.rounds += 1
        if self.rounds == 1:
            yield LLMResponse(
                tool_calls=[ToolCall(id="call_1", name=self.tool_name, arguments=self.arguments)],
                finish_reason="tool_calls",
            )
        else:
            yield LLMResponse(content="done", finish_reason="stop")

    def detect_tool_role(self):
        return "tool"


def _run_gate(tool_name, arguments="{}", *, mode=None, interactive=True, config_extra=None):
    provider = _GateProvider(tool_name, arguments)
    config = {
        "ENABLE_FUNCTIONS": True,
        "ENABLE_MCP": False,
        "MAX_TOOL_CALL_DEPTH": 3,
        "TOOL_CONFIRM": True,
        "TOOL_AUDIT": True,
        "TOOL_POLICY": "standard",
        "MODEL": "test-model",
        "PROVIDER": "openai",
        "API_KEY": "fake",
        "PLAN_ALLOW_READONLY_SHELL": True,
    }
    config.update(config_extra or {})
    with patch("yaicli.llms.provider.ProviderFactory.create_provider", return_value=provider):
        client = LLMClient(provider_name="openai", config=config, interactive=interactive)
    client.plan_session = plan_mode.PlanSession(mode=mode) if mode else None
    execute = MagicMock(return_value=("tool-result", True))
    messages = [ChatMessage(role="user", content="go")]
    with patch("yaicli.llms.client.execute_tool_call", execute):
        events = list(client.completion_with_tools(messages, stream=False))
    tool_messages = [message for message in messages if message.role == "tool"]
    return SimpleNamespace(events=events, execute=execute, tool_messages=tool_messages, client=client)


def _prompted(events):
    return any(isinstance(event, ConfirmToolCall) for event in events)


def _last_tool_payload(tool_messages):
    assert tool_messages, "expected a tool result message"
    return json.loads(tool_messages[-1].content)


class TestClientPlanGate:
    def test_write_tool_denied_with_structured_mode_error(self, plan_state):
        run = _run_gate("fs_write_file", '{"file_path": "x"}', mode="researching")
        assert _prompted(run.events) is False
        run.execute.assert_not_called()
        payload = _last_tool_payload(run.tool_messages)
        assert payload["error"] == "tool_not_available_in_mode"
        assert "read-only" in payload["reason"]
        records = _tool_records(plan_state.audit_path)
        assert records[-1]["decision"] == "denied"
        assert records[-1]["source"] == "plan_mode"
        assert records[-1]["risk"] == "write"  # fs_write_file keeps its builtin risk class

    def test_session_tool_audited_as_read(self, plan_state):
        """Session tools are not builtins; the audit records them as read risk."""
        run = _run_gate("todo_write", '{"items": []}', mode="executing")
        run.execute.assert_called_once()
        records = _tool_records(plan_state.audit_path)
        assert records[-1]["tool"] == "todo_write"
        assert records[-1]["risk"] == "read"

    def test_denied_session_tool_audited_as_read(self, plan_state):
        _run_gate("submit_plan", "{}", mode="executing")
        records = _tool_records(plan_state.audit_path)
        assert records[-1]["tool"] == "submit_plan"
        assert records[-1]["risk"] == "read"
        assert records[-1]["decision"] == "denied"

    def test_readonly_tool_runs_without_prompt(self, plan_state):
        run = _run_gate("fs_read_file", '{"file_paths": ["x"]}', mode="researching")
        assert _prompted(run.events) is False
        run.execute.assert_called_once()
        records = _tool_records(plan_state.audit_path)
        assert records[-1]["decision"] == "allowed"
        assert records[-1]["source"] == "plan_mode"

    def test_dangerous_shell_has_no_prompt_in_plan_mode(self, plan_state):
        run = _run_gate(
            "execute_shell_command",
            '{"command": "rm -rf /"}',
            mode="researching",
        )
        # The plan gate runs before the danger classification: no confirmation.
        assert _prompted(run.events) is False
        run.execute.assert_called_once()

    def test_shell_denied_when_readonly_shell_disabled(self, plan_state):
        run = _run_gate(
            "execute_shell_command",
            '{"command": "git status"}',
            mode="researching",
            config_extra={"PLAN_ALLOW_READONLY_SHELL": False},
        )
        run.execute.assert_not_called()
        payload = _last_tool_payload(run.tool_messages)
        assert payload["error"] == "tool_not_available_in_mode"

    def test_plan_branch_wins_before_readonly_policy(self, plan_state):
        run = _run_gate(
            "fs_write_file",
            '{"file_path": "x"}',
            mode="researching",
            config_extra={"TOOL_POLICY": "readonly"},
        )
        payload = _last_tool_payload(run.tool_messages)
        assert payload["error"] == "tool_not_available_in_mode"

    def test_executing_mode_allows_todo_write_without_prompt(self, plan_state):
        run = _run_gate("todo_write", '{"items": []}', mode="executing")
        assert _prompted(run.events) is False
        run.execute.assert_called_once()
        records = _tool_records(plan_state.audit_path)
        assert records[-1]["decision"] == "allowed"
        assert records[-1]["source"] == "plan_mode"

    def test_executing_mode_denies_submit_plan(self, plan_state):
        run = _run_gate("submit_plan", "{}", mode="executing")
        assert _prompted(run.events) is False
        run.execute.assert_not_called()
        assert _last_tool_payload(run.tool_messages)["error"] == "tool_not_available_in_mode"

    def test_session_tools_denied_in_normal_mode(self, plan_state):
        run = _run_gate("submit_plan", "{}", mode=None)
        assert _prompted(run.events) is False
        run.execute.assert_not_called()
        assert _last_tool_payload(run.tool_messages)["error"] == "tool_not_available_in_mode"

    def test_normal_dangerous_shell_still_prompts(self, plan_state):
        run = _run_gate("execute_shell_command", '{"command": "rm -rf /"}', mode=None)
        assert _prompted(run.events) is True

    def test_normal_write_tool_still_prompts(self, plan_state):
        run = _run_gate("fs_write_file", '{"file_path": "x"}', mode=None)
        assert _prompted(run.events) is True

    def test_plan_tool_mode_defaults_to_none(self):
        assert tools_mod.get_plan_tool_mode() is None
        set_plan_tool_mode("plan")
        assert tools_mod.get_plan_tool_mode() == "plan"
        set_plan_tool_mode("execution")
        assert tools_mod.get_plan_tool_mode() == "execution"
        set_plan_tool_mode("bogus")
        assert tools_mod.get_plan_tool_mode() is None
