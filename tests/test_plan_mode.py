"""Tests for the persistent plan-mode state machine (v0.24 K23).

Everything runs against a temporary plans root (never the real config dir) and a
fresh global plan session; no provider/network/editor calls are made.
"""

import json
import os
import stat
from types import SimpleNamespace
import pytest

from yaicli import const, plan_mode
from yaicli.config import cfg
from yaicli.tools import set_plan_tool_mode


@pytest.fixture(autouse=True)
def plan_state(tmp_path, monkeypatch):
    """Isolate the global plan session, plans root and audit log per test."""
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


def _valid_plan(**overrides):
    """A minimal valid first-submission payload."""
    payload = {
        "goal": "Add a dry-run flag to fs_write_file",
        "assumptions": ["fs_write_file has no dry-run mode yet"],
        "steps": [
            {"title": "Locate the write path", "detail": "read the builtin", "acceptance": "the code path is known"},
            {"title": "Add the flag", "acceptance": "pytest tests/tools passes"},
        ],
        "risks": ["file format change"],
        "not_doing": ["documentation"],
    }
    payload.update(overrides)
    return payload


def _audit_events(audit_path):
    if not os.path.exists(audit_path):
        return []
    return [json.loads(line) for line in open(audit_path, encoding="utf-8").read().splitlines() if line.strip()]


def _submit_and_approve(session):
    if session.mode == "normal" and session.active_plan is None and session.draft_plan is None:
        session.enter_researching()
    result = plan_mode.handle_submit_plan(_valid_plan())
    assert result["success"] is True
    approved = plan_mode.approve_new_plan(session)
    assert approved["success"] is True
    return result, approved


class TestToolVisibility:
    def test_plan_allowlist_contains_readonly_and_submit_plan(self):
        allowed = plan_mode.plan_tool_allowlist(allow_readonly_shell=True)
        for name in ("fs_read_file", "fs_list_directory", "fs_search_files", "fetch_webpage", "web_search"):
            assert name in allowed
        assert "submit_plan" in allowed
        assert "execute_shell_command" in allowed
        for blocked in ("fs_write_file", "fs_edit_file", "fs_file_operations", "todo_write"):
            assert blocked not in allowed

    def test_shell_can_be_disabled(self):
        allowed = plan_mode.plan_tool_allowlist(allow_readonly_shell=False)
        assert "execute_shell_command" not in allowed
        assert plan_mode.is_tool_allowed_in_plan("execute_shell_command", allow_readonly_shell=False) is False
        assert plan_mode.is_tool_allowed_in_plan("fs_read_file", allow_readonly_shell=False) is True

    def test_write_tools_are_never_allowed_in_plan(self):
        for name in ("fs_write_file", "fs_edit_file", "fs_file_operations", "todo_write", "_mcp__whatever"):
            assert plan_mode.is_tool_allowed_in_plan(name) is False

    def test_execution_tool_names(self):
        assert plan_mode.execution_tool_names() == frozenset({"todo_write"})

    def test_mode_value_helpers(self):
        assert plan_mode.is_plan_mode_value("researching")
        assert plan_mode.is_plan_mode_value("revising")
        assert not plan_mode.is_plan_mode_value("executing")
        assert not plan_mode.is_plan_mode_value("normal")
        assert plan_mode.is_execution_mode_value("executing")
        assert not plan_mode.is_execution_mode_value("researching")


class TestSessionState:
    def test_fresh_session_defaults(self, plan_state):
        session = plan_mode.get_plan_session()
        assert session.mode == "normal"
        assert session.is_plan_mode is False
        assert session.is_reviewing is False
        assert session.is_executing is False
        assert session.active_plan_id == ""
        assert session.all_todos_completed() is False
        assert session.todo_progress() == (0, 0)
        assert session.todo_snapshot() == ()

    def test_configure_resolves_project_plan_dir(self, plan_state):
        session = plan_state.session
        assert session.plan_dir is not None
        assert session.plan_dir.parent == (plan_state.tmp_path / "plans").resolve()
        assert len(session.plan_dir.name) == 16
        assert session.session_id == "sess-1"
        assert session.max_steps == 20
        assert session.keep == 80
        assert session.allow_readonly_shell is True

    def test_enter_and_cancel_researching(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        assert session.mode == "researching"
        assert session.is_plan_mode is True
        assert session.is_reviewing is False
        session.cancel_draft()
        assert session.mode == "normal"
        assert session.draft_plan is None

    def test_enter_and_cancel_revising_keeps_active_plan(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        session.enter_revising()
        assert session.mode == "revising"
        assert session.revision_base is not None
        session.cancel_draft()
        assert session.mode == "normal"
        assert session.active_plan is not None
        assert session.todos

    def test_reset_clears_state_but_keeps_paths(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        session.reset()
        assert session.mode == "normal"
        assert session.active_plan is None
        assert session.todos == []
        assert session.plan_dir is not None

    def test_set_and_reset_global_session(self):
        custom = plan_mode.PlanSession(mode="researching")
        plan_mode.set_plan_session(custom)
        try:
            assert plan_mode.get_plan_session() is custom
        finally:
            plan_mode.reset_plan_session()
        assert plan_mode.get_plan_session() is not custom


class TestSubmitFirstPlan:
    def test_first_submit_writes_draft_and_enters_reviewing(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        result = plan_mode.handle_submit_plan(_valid_plan())
        assert result["success"] is True
        assert result["revision"] == 1
        assert result["steps"] == 2
        assert result["revision_diff"] is None
        assert session.mode == "reviewing"
        assert session.is_reviewing is True
        assert session.draft_plan is not None
        assert session.draft_plan.status == "draft"
        assert session.draft_plan.step_ids() == ["S1", "S2"]
        path = session.draft_plan.path
        assert path is not None and path.is_file()
        assert result["path"] == str(path)
        text = path.read_text(encoding="utf-8")
        assert "# Plan: Add a dry-run flag to fs_write_file" in text
        assert "## Steps" in text
        assert "- [ ] **S1** Locate the write path" in text
        assert "- acceptance: the code path is known" in text
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    def test_submit_audit_event(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        plan_mode.handle_submit_plan(_valid_plan())
        events = _audit_events(plan_state.audit_path)
        assert events and events[-1]["event"] == "plan.submit"
        assert events[-1]["plan_id"] == session.draft_plan.id
        assert events[-1]["revision"] == 1

    def test_second_submit_is_rejected(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        plan_mode.handle_submit_plan(_valid_plan())
        again = plan_mode.handle_submit_plan(_valid_plan(goal="another plan"))
        assert again["success"] is False
        assert again["error"] == "plan_already_submitted"

    def test_submit_outside_plan_mode_is_rejected(self, plan_state):
        result = plan_mode.handle_submit_plan(_valid_plan())
        assert result["success"] is False
        assert result["error"] == "plan_not_active"

    def test_submit_uses_configured_max_steps(self, plan_state):
        session = plan_state.session
        session.configure(plans_root=plan_state.tmp_path / "plans", cwd=plan_state.tmp_path, max_steps=2)
        session.enter_researching()
        payload = _valid_plan(steps=[{"title": f"step {index}", "acceptance": "ok"} for index in range(3)])
        result = plan_mode.handle_submit_plan(payload)
        assert result["error"] == "invalid_plan"
        assert "at most 2 steps" in result["reason"]

    def test_handle_submit_plan_never_raises(self, plan_state):
        plan_state.session.enter_researching()
        result = plan_mode.handle_submit_plan({"goal": None, "steps": "not-a-list"})
        assert result["error"] == "invalid_plan"


class TestSubmitPlanValidation:
    def _submit_error(self, plan_state, **overrides):
        plan_state.session.enter_researching()
        return plan_mode.handle_submit_plan(_valid_plan(**overrides))

    def test_empty_goal(self, plan_state):
        result = self._submit_error(plan_state, goal="   ")
        assert result["error"] == "invalid_plan"
        assert "goal" in result["reason"]

    def test_goal_too_long(self, plan_state):
        result = self._submit_error(plan_state, goal="x" * 501)
        assert result["error"] == "invalid_plan"
        assert "500" in result["reason"]

    def test_steps_must_be_a_non_empty_list(self, plan_state):
        result = self._submit_error(plan_state, steps=[])
        assert result["error"] == "invalid_plan"
        assert "at least 1 step" in result["reason"]
        plan_state.session.reset()
        plan_state.session.enter_researching()
        result = plan_mode.handle_submit_plan(_valid_plan(steps="nope"))
        assert result["error"] == "invalid_plan"

    def test_step_requires_title_and_acceptance(self, plan_state):
        result = self._submit_error(plan_state, steps=[{"title": "", "acceptance": "ok"}])
        assert "title" in result["reason"]
        plan_state.session.reset()
        plan_state.session.enter_researching()
        result = plan_mode.handle_submit_plan(_valid_plan(steps=[{"title": "t", "acceptance": ""}]))
        assert "acceptance" in result["reason"]

    def test_step_must_be_an_object(self, plan_state):
        result = self._submit_error(plan_state, steps=["S1 do it"])
        assert result["error"] == "invalid_plan"

    def test_oversized_plan_is_rejected(self, plan_state):
        steps = [{"title": "t" * 400, "acceptance": "a" * 400, "detail": "d" * 400} for _ in range(10)]
        result = self._submit_error(plan_state, steps=steps)
        assert result["error"] == "invalid_plan"
        assert "8 KB" in result["reason"] or "too large" in result["reason"]

    def test_assumptions_must_be_a_string_list(self, plan_state):
        result = self._submit_error(plan_state, assumptions="one assumption")
        assert result["error"] == "invalid_plan"
        assert "assumptions" in result["reason"]


class TestAudit:
    def test_audit_disabled_writes_nothing(self, plan_state, monkeypatch):
        monkeypatch.setitem(cfg, "TOOL_AUDIT", False)
        plan_mode.plan_audit("submit", plan_id="x")
        assert not os.path.exists(plan_state.audit_path)

    def test_audit_line_shape(self, plan_state):
        plan_mode.plan_audit("shell_denied", command="rm -rf /", reason="nope")
        events = _audit_events(plan_state.audit_path)
        assert events[-1]["event"] == "plan.shell_denied"
        assert events[-1]["command"] == "rm -rf /"
        assert events[-1]["reason"] == "nope"
        assert "ts" in events[-1]

    def test_audit_never_raises_on_unwritable_path(self, plan_state, monkeypatch):
        monkeypatch.setattr(const, "TOOL_AUDIT_PATH", "/proc/definitely/not/writable/audit.jsonl")
        plan_mode.plan_audit("submit", plan_id="x")  # must not raise


class TestPlanContext:
    def test_normal_mode_has_no_block(self, plan_state):
        assert plan_mode.plan_context_block(plan_state.session) == ""

    def test_researching_block_mentions_read_only_and_submit_plan(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        block = plan_mode.plan_context_block(session)
        assert "PLAN MODE" in block
        assert "read-only" in block.lower()
        assert "submit_plan" in block

    def test_revising_block_mentions_revision_and_todos(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        session.enter_revising()
        block = plan_mode.plan_context_block(session)
        assert "revising" in block.lower()
        assert "revision" in block.lower()
        assert "S1" in block
        assert "Todo" in block

    def test_executing_block_has_goal_and_todos(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        block = plan_mode.plan_context_block(session)
        assert "Plan execution" in block
        assert "Add a dry-run flag to fs_write_file" in block
        assert "[todo 1/2] S1 Locate the write path" in block

    def test_block_is_bounded(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        block = plan_mode.plan_context_block(session, max_chars=80)
        assert len(block) <= 120
        assert "truncated" in block

    def test_todo_summary_empty_without_todos(self, plan_state):
        assert plan_mode.todo_summary(plan_state.session) == ""

    def test_todo_summary_lists_statuses(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        summary = plan_mode.todo_summary(session)
        assert "[todo 1/2] S1" in summary
        assert "in_progress" in summary

    def test_todo_snapshot_and_progress(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        assert session.todo_progress() == (0, 2)
        assert session.todo_snapshot() == (("S1", "in_progress"), ("S2", "pending"))
        session.todos[0].status = "completed"
        assert session.todo_progress() == (1, 2)
        assert session.all_todos_completed() is False
        session.todos[1].status = "completed"
        assert session.all_todos_completed() is True


class TestSessionDictRestore:
    def test_no_plan_means_empty_dict(self, plan_state):
        assert plan_state.session.to_session_dict() == {}

    def test_draft_save_only_round_trip(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        plan_mode.handle_submit_plan(_valid_plan())
        # Simulate the [s]ave-only decision: keep the draft pointer, leave plan mode.
        session.mode = "normal"
        data = session.to_session_dict()
        assert data["status"] == "draft"
        assert data["id"] == session.draft_plan.id
        assert data["path"] == str(session.draft_plan.path)
        assert data["session_id"] == "sess-1"
        assert "todos" not in data

        restored = plan_mode.PlanSession()
        detail = restored.restore_from_session(
            data, session_id="sess-1", plans_root=plan_state.tmp_path / "plans", cwd=plan_state.tmp_path
        )
        assert detail is None
        assert restored.mode == "normal"
        assert restored.draft_plan is not None
        assert restored.draft_plan.id == data["id"]
        assert restored.active_plan is None

    def test_in_progress_round_trip_preserves_todos(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        plan_mode.handle_todo_write(
            {"items": [{"id": "S1", "status": "completed"}, {"id": "S2", "status": "in_progress"}]}
        )
        data = session.to_session_dict()
        assert data["status"] == "in-progress"
        assert data["revision"] == 1
        assert [item["status"] for item in data["todos"]] == ["completed", "in_progress"]

        restored = plan_mode.PlanSession()
        detail = restored.restore_from_session(
            data, session_id="sess-1", plans_root=plan_state.tmp_path / "plans", cwd=plan_state.tmp_path
        )
        assert detail is None
        assert restored.mode == "normal"
        assert restored.active_plan is not None
        assert restored.active_plan.id == data["id"]
        assert restored.todo_snapshot() == (("S1", "completed"), ("S2", "in_progress"))

    def test_restore_missing_file(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        data = plan_mode.handle_submit_plan(_valid_plan())
        session.mode = "normal"
        payload = session.to_session_dict()
        os.unlink(data["path"])
        restored = plan_mode.PlanSession()
        detail = restored.restore_from_session(
            payload, session_id="sess-1", plans_root=plan_state.tmp_path / "plans", cwd=plan_state.tmp_path
        )
        assert detail == "saved plan not found/inconsistent; starting in normal mode"
        assert restored.active_plan is None and restored.draft_plan is None

    def test_restore_corrupt_file(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        data = plan_mode.handle_submit_plan(_valid_plan())
        session.mode = "normal"
        payload = session.to_session_dict()
        with open(data["path"], "w", encoding="utf-8") as handle:
            handle.write("definitely not a plan")
        restored = plan_mode.PlanSession()
        detail = restored.restore_from_session(
            payload, session_id="sess-1", plans_root=plan_state.tmp_path / "plans", cwd=plan_state.tmp_path
        )
        assert detail is not None
        assert "saved plan not found/inconsistent" in detail

    def test_restore_other_session_is_ignored(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        plan_mode.handle_submit_plan(_valid_plan())
        session.mode = "normal"
        payload = session.to_session_dict()
        restored = plan_mode.PlanSession()
        detail = restored.restore_from_session(
            payload, session_id="another-session", plans_root=plan_state.tmp_path / "plans", cwd=plan_state.tmp_path
        )
        assert detail is not None

    def test_restore_status_mismatch_is_ignored(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        plan_mode.handle_submit_plan(_valid_plan())
        session.mode = "normal"
        payload = session.to_session_dict()
        payload["status"] = "done"
        restored = plan_mode.PlanSession()
        detail = restored.restore_from_session(
            payload, session_id="sess-1", plans_root=plan_state.tmp_path / "plans", cwd=plan_state.tmp_path
        )
        assert detail is not None


class TestLifecycle:
    def test_seed_todos(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        plan_mode.handle_submit_plan(_valid_plan())
        todos = plan_mode.seed_todos(session.draft_plan)
        assert [todo.id for todo in todos] == ["S1", "S2"]
        assert [todo.status for todo in todos] == ["in_progress", "pending"]
        assert todos[0].content == "Locate the write path"

    def test_approve_marks_in_progress_and_seeds_todos(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        submitted = plan_mode.handle_submit_plan(_valid_plan())
        result = plan_mode.approve_new_plan(session)
        assert result["success"] is True
        assert session.mode == "executing"
        assert session.active_plan_id == submitted["plan_id"]
        assert session.draft_plan is None
        assert [todo.status for todo in session.todos] == ["in_progress", "pending"]
        text = session.active_plan.path.read_text(encoding="utf-8")
        assert "status: in-progress" in text
        assert "approved_at: " in text

    def test_approve_without_draft_fails(self, plan_state):
        result = plan_mode.approve_new_plan(plan_state.session)
        assert result["success"] is False

    def test_pause_and_resume(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        plan_mode.pause_plan(session)
        assert session.mode == "normal"
        assert session.active_plan is not None
        assert session.todos
        assert plan_mode.resume_plan(session) is True
        assert session.mode == "executing"

    def test_resume_without_plan_returns_false(self, plan_state):
        assert plan_mode.resume_plan(plan_state.session) is False

    def test_finish_plan(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        session.todos[0].status = "completed"
        session.todos[1].status = "completed"
        path = session.active_plan.path
        result = plan_mode.finish_plan(session)
        assert result["success"] is True
        assert (result["completed"], result["total"]) == (2, 2)
        assert session.mode == "normal"
        assert session.active_plan is None
        assert session.todos == []
        assert "status: done" in path.read_text(encoding="utf-8")

    def test_finish_without_plan_returns_error(self, plan_state):
        assert plan_mode.finish_plan(plan_state.session)["success"] is False

    def test_abort_plan(self, plan_state):
        session = plan_state.session
        _submit_and_approve(session)
        path = session.active_plan.path
        result = plan_mode.abort_plan(session)
        assert result["success"] is True
        assert session.mode == "normal"
        assert session.active_plan is None
        assert session.todos == []
        assert "status: aborted" in path.read_text(encoding="utf-8")

    def test_abort_without_plan_returns_error(self, plan_state):
        assert plan_mode.abort_plan(plan_state.session)["success"] is False

    def test_editor_draft_is_hidden_and_private(self, plan_state):
        session = plan_state.session
        session.enter_researching()
        plan_mode.handle_submit_plan(_valid_plan())
        draft_path = plan_mode.write_plan_editor_draft(session, session.draft_plan)
        assert draft_path.name.startswith(".")
        assert draft_path.name.endswith(".editor.md")
        assert "# Plan:" in draft_path.read_text(encoding="utf-8")
        if os.name != "nt":
            assert stat.S_IMODE(draft_path.stat().st_mode) == 0o600

    def test_edit_plan_file_success(self, plan_state, monkeypatch):
        session = plan_state.session
        session.enter_researching()
        result = plan_mode.handle_submit_plan(_valid_plan())
        target = result["path"]

        def fake_run(argv, check=False):
            with open(target, encoding="utf-8") as handle:
                text = handle.read()
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(text.replace("Add the flag", "Add the --dry-run flag"))
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(plan_mode.subprocess, "run", fake_run)
        ok, error = plan_mode.edit_plan_file(target)
        assert ok is True
        assert error == ""
        assert "Add the --dry-run flag" in open(target, encoding="utf-8").read()

    def test_edit_plan_file_invalid_result(self, plan_state, monkeypatch):
        session = plan_state.session
        session.enter_researching()
        result = plan_mode.handle_submit_plan(_valid_plan())
        target = result["path"]

        def fake_run(argv, check=False):
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("broken")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(plan_mode.subprocess, "run", fake_run)
        ok, error = plan_mode.edit_plan_file(target)
        assert ok is False
        assert "invalid plan file" in error

    def test_edit_plan_file_editor_missing(self, plan_state, monkeypatch):
        def fake_run(argv, check=False):
            raise FileNotFoundError("no such editor")

        monkeypatch.setattr(plan_mode.subprocess, "run", fake_run)
        ok, error = plan_mode.edit_plan_file(plan_state.tmp_path / "x.md")
        assert ok is False
        assert "cannot open editor" in error


class TestTodoItem:
    def test_round_trip(self):
        todo = plan_mode.TodoItem(id="S1", content="do it", status="blocked", reason="waiting")
        restored = plan_mode.TodoItem.from_dict(todo.to_dict())
        assert restored == todo

    def test_from_dict_tolerates_garbage(self):
        todo = plan_mode.TodoItem.from_dict({"id": 1, "status": "bogus"})
        assert todo.id == "1"
        assert todo.status == "pending"


class TestConsoleSafety:
    """plan_mode is Rich-free: rendering belongs to the CLI/printer layer."""

    def test_no_rich_import(self):
        with open(plan_mode.__file__, encoding="utf-8") as handle:
            text = handle.read()
        assert "import rich" not in text


def test_get_plan_session_creates_singleton():
    plan_mode.reset_plan_session()
    try:
        first = plan_mode.get_plan_session()
        assert plan_mode.get_plan_session() is first
    finally:
        plan_mode.reset_plan_session()
