"""Tests for the ``todo_write`` session tool (v0.24 K23).

The todo list must stay 1:1 with the current plan revision, contain at most one
``in_progress`` entry, carry a reason for blocked steps and be written back into
the plan Markdown checkboxes.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from yaicli import const, plan_mode
from yaicli.config import cfg
from yaicli.tools import session_tools, set_plan_tool_mode


@pytest.fixture(autouse=True)
def plan_state(tmp_path, monkeypatch):
    """Isolate the global plan session, plans root, audit log and tool console."""
    plan_mode.reset_plan_session()
    set_plan_tool_mode(None)
    monkeypatch.setitem(cfg, "PLAN_DIR", str(tmp_path / "plans"))
    monkeypatch.setitem(cfg, "PLAN_ALLOW_READONLY_SHELL", True)
    monkeypatch.setitem(cfg, "TOOL_AUDIT", True)
    audit_path = tmp_path / "plan_audit.jsonl"
    monkeypatch.setattr(const, "TOOL_AUDIT_PATH", audit_path)
    session = plan_mode.get_plan_session()
    session.configure(plans_root=tmp_path / "plans", cwd=tmp_path, model="test-model", session_id="sess-1")
    yield SimpleNamespace(session=session, tmp_path=tmp_path, audit_path=audit_path)
    plan_mode.reset_plan_session()
    set_plan_tool_mode(None)


def _valid_plan():
    return {
        "goal": "Add a dry-run flag to fs_write_file",
        "steps": [
            {"title": "Locate the write path", "acceptance": "the code path is known"},
            {"title": "Add the flag", "acceptance": "pytest tests/tools passes"},
        ],
    }


def _executing_session(session):
    session.enter_researching()
    submitted = plan_mode.handle_submit_plan(_valid_plan())
    assert submitted["success"] is True
    approved = plan_mode.approve_new_plan(session)
    assert approved["success"] is True
    assert session.mode == "executing"
    return submitted


def _payload(*statuses):
    """Build an items payload from ``(id, status[, reason])`` tuples."""
    items = []
    for entry in statuses:
        item = {"id": entry[0], "status": entry[1]}
        if len(entry) > 2:
            item["reason"] = entry[2]
        items.append(item)
    return {"items": items}


def _audit_events(audit_path):
    if not os.path.exists(audit_path):
        return []
    return [json.loads(line) for line in open(audit_path, encoding="utf-8").read().splitlines() if line.strip()]


class TestTodoWriteSuccess:
    def test_advances_the_todo_list(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = plan_mode.handle_todo_write(_payload(("S1", "completed"), ("S2", "in_progress")))
        assert result["success"] is True
        assert (result["completed"], result["total"], result["blocked"]) == (1, 2, 0)
        assert result["in_progress"] == "S2"
        assert result["current"] == {
            "index": 2,
            "total": 2,
            "id": "S2",
            "title": "Add the flag",
            "status": "in_progress",
        }
        assert session.todo_snapshot() == (("S1", "completed"), ("S2", "in_progress"))

    def test_result_is_reported_in_plan_todo_order(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        # Submit the items out of order: they are stored in step order.
        result = plan_mode.handle_todo_write(_payload(("S2", "pending"), ("S1", "completed")))
        assert result["success"] is True
        assert session.todo_snapshot() == (("S1", "completed"), ("S2", "pending"))

    def test_checkboxes_written_back_to_plan_md(self, plan_state):
        session = plan_state.session
        submitted = _executing_session(session)
        plan_mode.handle_todo_write(_payload(("S1", "completed"), ("S2", "in_progress")))
        text = open(submitted["path"], encoding="utf-8").read()
        assert "- [x] **S1** Locate the write path" in text
        assert "- [ ] **S2** Add the flag" in text
        # Acceptance/detail lines survive the write-back.
        assert "- acceptance: the code path is known" in text

    def test_blocked_status_written_with_reason(self, plan_state):
        session = plan_state.session
        submitted = _executing_session(session)
        result = plan_mode.handle_todo_write(_payload(("S1", "blocked", "waiting for review"), ("S2", "pending")))
        assert result["success"] is True
        assert result["blocked"] == 1
        assert result["current"]["status"] == "blocked"
        text = open(submitted["path"], encoding="utf-8").read()
        assert "- [ ] **S1** Locate the write path (blocked: waiting for review)" in text

    def test_completed_last_step(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = plan_mode.handle_todo_write(_payload(("S1", "completed"), ("S2", "completed")))
        assert result["success"] is True
        assert session.all_todos_completed() is True
        # Both steps changed to completed; the first changed step is reported.
        assert result["current"]["id"] == "S1"

    def test_audit_todo_update(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        plan_mode.handle_todo_write(_payload(("S1", "completed"), ("S2", "in_progress")))
        events = _audit_events(plan_state.audit_path)
        assert events[-1]["event"] == "plan.todo.update"
        assert events[-1]["completed"] == 1
        assert events[-1]["total"] == 2
        assert events[-1]["in_progress"] == "S2"

    def test_session_dict_persists_todos(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        plan_mode.handle_todo_write(_payload(("S1", "completed"), ("S2", "in_progress")))
        data = session.to_session_dict()
        assert data["todos"] == [
            {"id": "S1", "content": "Locate the write path", "status": "completed", "reason": ""},
            {"id": "S2", "content": "Add the flag", "status": "in_progress", "reason": ""},
        ]

    def test_no_status_change_has_no_current(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        first = plan_mode.handle_todo_write(_payload(("S1", "completed"), ("S2", "in_progress")))
        assert first["current"] is not None
        again = plan_mode.handle_todo_write(_payload(("S1", "completed"), ("S2", "in_progress")))
        assert again["success"] is True
        assert again["current"] is None


class TestTodoWriteValidation:
    def _error(self, plan_state, payload):
        result = plan_mode.handle_todo_write(payload)
        assert result.get("success") is not True
        assert result["error"] == "invalid_todo"
        return result

    def test_requires_every_step(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = self._error(plan_state, _payload(("S1", "in_progress")))
        assert "missing: S2" in result["reason"]

    def test_rejects_unknown_step_id(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = self._error(plan_state, _payload(("S1", "in_progress"), ("S2", "pending"), ("S3", "pending")))
        assert "S3" in result["reason"]
        assert "cannot add or remove steps" in result["hint"]

    def test_rejects_duplicate_ids(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = self._error(plan_state, _payload(("S1", "in_progress"), ("S1", "pending"), ("S2", "pending")))
        assert "duplicate" in result["reason"]

    def test_rejects_changed_content(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        payload = {
            "items": [
                {"id": "S1", "content": "a different title", "status": "in_progress"},
                {"id": "S2", "status": "pending"},
            ]
        }
        result = self._error(plan_state, payload)
        assert "content cannot be changed" in result["reason"]

    def test_at_most_one_in_progress(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = self._error(plan_state, _payload(("S1", "in_progress"), ("S2", "in_progress")))
        assert "at most one" in result["reason"]

    def test_blocked_requires_a_reason(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = self._error(plan_state, _payload(("S1", "blocked"), ("S2", "pending")))
        assert "needs a reason" in result["reason"]

    def test_blocked_reason_length_cap(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = self._error(plan_state, _payload(("S1", "blocked", "x" * 501)))
        assert "500" in result["reason"]

    def test_invalid_status(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = self._error(plan_state, _payload(("S1", "done-ish"), ("S2", "pending")))
        assert "status must be one of" in result["reason"]

    def test_items_must_be_a_list(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        result = self._error(plan_state, {"items": "S1"})
        assert "list" in result["reason"]

    def test_invalid_mode_is_rejected(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        result = plan_mode.handle_todo_write(_payload(("S1", "in_progress")))
        assert result["success"] is False
        assert result["error"] == "todo_write_not_available"

    def test_no_active_plan(self, plan_state):
        result = plan_mode.handle_todo_write(_payload(("S1", "in_progress")))
        assert result["success"] is False
        assert result["error"] == "todo_write_not_available"

    def test_state_is_unchanged_after_an_invalid_write(self, plan_state):
        session = plan_state.session
        _executing_session(session)
        before = session.todo_snapshot()
        plan_mode.handle_todo_write(_payload(("S1", "in_progress"), ("S2", "in_progress")))
        assert session.todo_snapshot() == before


class TestTodoProgressLine:
    def test_progress_line_printed_once_per_change(self, plan_state, monkeypatch):
        session = plan_state.session
        _executing_session(session)
        console = MagicMock()
        monkeypatch.setattr("yaicli.tools.console", console)
        raw = session_tools.execute_session_tool(
            "todo_write",
            {"items": [{"id": "S1", "status": "completed"}, {"id": "S2", "status": "in_progress"}]},
        )
        payload = json.loads(raw)
        assert payload["success"] is True
        console.print.assert_called_once()
        printed = str(console.print.call_args.args[0])
        assert printed == "[todo 2/2] S2 Add the flag"

    def test_no_line_without_a_status_change(self, plan_state, monkeypatch):
        session = plan_state.session
        _executing_session(session)
        session_tools.execute_session_tool("todo_write", _payload(("S1", "completed"), ("S2", "in_progress")))
        console = MagicMock()
        monkeypatch.setattr("yaicli.tools.console", console)
        raw = session_tools.execute_session_tool("todo_write", _payload(("S1", "completed"), ("S2", "in_progress")))
        assert json.loads(raw)["success"] is True
        console.print.assert_not_called()

    def test_no_line_for_invalid_write(self, plan_state, monkeypatch):
        session = plan_state.session
        _executing_session(session)
        console = MagicMock()
        monkeypatch.setattr("yaicli.tools.console", console)
        raw = session_tools.execute_session_tool("todo_write", {"items": []})
        assert json.loads(raw).get("success") is not True
        console.print.assert_not_called()


class TestSessionToolDispatch:
    def test_openai_schemas_per_mode(self):
        plan_names = [item["function"]["name"] for item in session_tools.openai_schemas("plan")]
        execution_names = [item["function"]["name"] for item in session_tools.openai_schemas("execution")]
        assert plan_names == ["submit_plan"]
        assert execution_names == ["todo_write"]
        assert session_tools.openai_schemas("normal") == []

    def test_anthropic_schemas_per_mode(self):
        assert [item["name"] for item in session_tools.anthropic_schemas("plan")] == ["submit_plan"]
        assert [item["name"] for item in session_tools.anthropic_schemas("execution")] == ["todo_write"]

    @pytest.mark.parametrize("mode,name", [("plan", "submit_plan"), ("execution", "todo_write")])
    def test_gemini_functions_per_mode(self, mode, name):
        functions = session_tools.gemini_functions(mode)
        assert [function.__name__ for function in functions] == [name]

    def test_schema_contract(self):
        schema = session_tools.openai_schemas("plan")[0]["function"]
        assert schema["name"] == "submit_plan"
        parameters = schema["parameters"]
        assert set(parameters["required"]) == {"goal", "steps"}
        properties = parameters["properties"]
        assert properties["steps"]["type"] == "array"
        assert "anyOf" not in json.dumps(properties)
        todo_schema = session_tools.openai_schemas("execution")[0]["function"]
        assert todo_schema["name"] == "todo_write"
        assert todo_schema["parameters"]["required"] == ["items"]

    def test_session_tool_available(self):
        assert session_tools.session_tool_available("submit_plan", "plan") is True
        assert session_tools.session_tool_available("submit_plan", "execution") is False
        assert session_tools.session_tool_available("todo_write", "execution") is True
        assert session_tools.session_tool_available("todo_write", None) is False
        assert session_tools.session_tool_available("fs_read_file", "plan") is False

    def test_execute_unknown_tool_is_in_band(self):
        payload = json.loads(session_tools.execute_session_tool("nope", {}))
        assert payload["error"] == "unknown_session_tool"

    def test_execute_invalid_arguments_is_in_band(self):
        payload = json.loads(session_tools.execute_session_tool("submit_plan", {"unexpected": 1}))
        assert payload["success"] is False
        assert payload["error"] == "invalid_arguments"

    def test_submit_plan_execute_delegates(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        raw = session_tools.execute_session_tool(
            "submit_plan",
            {
                "goal": "Add a flag",
                "steps": [{"title": "do it", "acceptance": "it works"}],
            },
        )
        payload = json.loads(raw)
        assert payload["success"] is True
        assert payload["plan_id"] == session.draft_plan.id
