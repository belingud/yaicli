"""Tests for plan revisions: diff, in-place update and todo rebuild (v0.24 K23)."""

import json
import os
from types import SimpleNamespace

import pytest

from yaicli import const, plan_mode, plan_store
from yaicli.config import cfg
from yaicli.tools import set_plan_tool_mode


@pytest.fixture(autouse=True)
def plan_state(tmp_path, monkeypatch):
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


def _first_plan():
    return {
        "goal": "Add a dry-run flag to fs_write_file",
        "steps": [
            {"title": "Locate the write path", "acceptance": "the code path is known"},
            {"title": "Add the flag", "acceptance": "pytest tests/tools passes"},
        ],
    }


def _executing_plan(session):
    """Create + approve a revision-1 plan with S1 completed and S2 in progress."""
    session.enter_researching()
    submitted = plan_mode.handle_submit_plan(_first_plan())
    assert submitted["success"] is True
    assert plan_mode.approve_new_plan(session)["success"] is True
    assert (
        plan_mode.handle_todo_write(
            {"items": [{"id": "S1", "status": "completed"}, {"id": "S2", "status": "in_progress"}]}
        )["success"]
        is True
    )
    return submitted


def _revision_payload(revision=2, change_summary="support a provider override", steps=None):
    if steps is None:
        steps = [
            {"id": "S1", "title": "Locate the write path", "acceptance": "the code path is known"},
            {"id": "S2", "title": "Add the flag and a config knob", "acceptance": "pytest tests/tools passes"},
            {"id": "S3", "title": "Document the flag", "acceptance": "docs updated"},
        ]
    return {
        "goal": "Add a dry-run flag to fs_write_file",
        "steps": steps,
        "revision": revision,
        "change_summary": change_summary,
    }


def _step_ids(plan):
    return [step.id for step in plan.steps]


def _plan_files(session):
    directory = session.active_plan.path.parent
    return sorted(path.name for path in directory.glob("*.md"))


class TestDiffPlans:
    @staticmethod
    def _plan(steps, goal="goal", revision=1):
        return plan_store.Plan(
            id="plan-id",
            goal=goal,
            steps=[plan_store.PlanStep(**step) for step in steps],
            revision=revision,
        )

    def test_added_removed_changed_unchanged(self):
        old = self._plan(
            [
                {"id": "S1", "title": "same", "acceptance": "ok"},
                {"id": "S2", "title": "old title", "acceptance": "ok"},
                {"id": "S3", "title": "removed", "acceptance": "ok"},
            ]
        )
        new = self._plan(
            [
                {"id": "S1", "title": "same", "acceptance": "ok"},
                {"id": "S2", "title": "new title", "acceptance": "ok"},
                {"id": "S4", "title": "added", "acceptance": "ok"},
            ]
        )
        diff = plan_mode.diff_plans(old, new)
        assert [step.id for step in diff.added] == ["S4"]
        assert [step.id for step in diff.removed] == ["S3"]
        assert [step.id for step in diff.changed] == ["S2"]
        assert [step.id for step in diff.unchanged] == ["S1"]

    def test_summary(self):
        old = self._plan([{"id": "S1", "title": "a", "acceptance": "ok"}, {"id": "S2", "title": "b"}])
        new = self._plan(
            [
                {"id": "S1", "title": "a", "acceptance": "ok"},
                {"id": "S2", "title": "b changed"},
                {"id": "S3", "title": "c"},
            ]
        )
        diff = plan_mode.diff_plans(old, new)
        assert diff.summary() == "Changes: +1 step  ~1 step  -0 steps"

    def test_detail_lines(self):
        old = self._plan([{"id": "S1", "title": "one"}, {"id": "S2", "title": "two"}])
        new = self._plan(
            [
                {"id": "S1", "title": "one"},
                {"id": "S2", "title": "two v2"},
                {"id": "S3", "title": "three"},
            ]
        )
        lines = plan_mode.diff_plans(old, new).detail_lines()
        assert " + S3 three" in lines
        assert " ~ S2 two v2" in lines

    def test_detail_lines_are_bounded(self):
        old = self._plan([])
        new = self._plan([{"id": f"S{index}", "title": f"t{index}"} for index in range(1, 20)])
        lines = plan_mode.diff_plans(old, new).detail_lines(max_lines=5)
        assert len(lines) == 5
        assert lines[-1].startswith(" … +")

    def test_todo_impact(self):
        old = self._plan(
            [
                {"id": "S1", "title": "done step"},
                {"id": "S2", "title": "removed done step"},
                {"id": "S3", "title": "in progress"},
            ]
        )
        new = self._plan(
            [
                {"id": "S1", "title": "done step"},
                {"id": "S3", "title": "in progress"},
                {"id": "S4", "title": "new step"},
            ]
        )
        diff = plan_mode.diff_plans(old, new)
        impact = diff.todo_impact(
            [
                plan_mode.TodoItem(id="S1", content="done step", status="completed"),
                plan_mode.TodoItem(id="S2", content="removed done step", status="completed"),
                plan_mode.TodoItem(id="S3", content="in progress", status="in_progress"),
            ]
        )
        assert impact.startswith("Todo impact: ")
        assert "completed S1 kept" in impact
        assert "completed S2 removed" in impact
        assert "S3 still in progress" in impact
        assert "new S4 pending" in impact


class TestSubmitRevision:
    def test_submit_revision_builds_draft_and_diff(self, plan_state):
        session = plan_state.session
        submitted = _executing_plan(session)
        session.enter_revising()
        result = plan_mode.handle_submit_plan(_revision_payload())
        assert result["success"] is True
        assert result["revision"] == 2
        assert session.mode == "reviewing"
        assert session.draft_plan is not None
        assert session.draft_plan.revision == 2
        assert session.draft_plan.change_summary == "support a provider override"
        assert [step.id for step in session.diff.added] == ["S3"]
        assert [step.id for step in session.diff.changed] == ["S2"]
        revision_diff = result["revision_diff"]
        assert revision_diff["summary"] == "Changes: +1 step  ~1 step  -0 steps"
        assert "Todo impact:" in revision_diff["todo_impact"]
        # The revision is in memory only: the file is still revision 1.
        text = open(submitted["path"], encoding="utf-8").read()
        assert "revision: 1" in text
        assert "Add the flag and a config knob" not in text

    def test_revision_audit(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        plan_mode.handle_submit_plan(_revision_payload())
        lines = [json.loads(line) for line in open(plan_state.audit_path, encoding="utf-8").read().splitlines()]
        assert lines[-1]["event"] == "plan.revise_submit"
        assert lines[-1]["change_summary"] == "support a provider override"
        assert lines[-1]["revision"] == 2

    def test_revision_number_must_be_next(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        result = plan_mode.handle_submit_plan(_revision_payload(revision=3))
        assert result["error"] == "invalid_plan"
        assert "revision must be 2" in result["reason"]

    def test_change_summary_is_required(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        result = plan_mode.handle_submit_plan(_revision_payload(change_summary=""))
        assert result["error"] == "invalid_plan"
        assert "change_summary" in result["reason"]

    def test_change_summary_length_cap(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        result = plan_mode.handle_submit_plan(_revision_payload(change_summary="x" * 501))
        assert result["error"] == "invalid_plan"
        assert "500" in result["reason"]

    def test_new_step_id_must_be_the_next_one(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        steps = [
            {"id": "S1", "title": "Locate the write path", "acceptance": "the code path is known"},
            {"id": "S2", "title": "Add the flag", "acceptance": "pytest tests/tools passes"},
            {"id": "S9", "title": "Document the flag", "acceptance": "docs updated"},
        ]
        result = plan_mode.handle_submit_plan(_revision_payload(steps=steps))
        assert result["error"] == "invalid_plan"
        assert "S3" in result["reason"]

    def test_existing_step_ids_must_be_unique(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        steps = [
            {"id": "S1", "title": "Locate the write path", "acceptance": "the code path is known"},
            {"id": "S1", "title": "duplicate", "acceptance": "nope"},
        ]
        result = plan_mode.handle_submit_plan(_revision_payload(steps=steps))
        assert result["error"] == "invalid_plan"
        assert "more than once" in result["reason"]

    def test_revision_needs_at_least_one_step(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        result = plan_mode.handle_submit_plan(_revision_payload(steps=[]))
        assert result["error"] == "invalid_plan"
        assert "at least 1 step" in result["reason"]

    def test_revision_without_active_plan(self, plan_state):
        session = plan_state.session
        session.mode = "revising"
        result = plan_mode.handle_submit_plan(_revision_payload())
        assert result["error"] == "invalid_plan"
        assert "nothing to revise" in result["reason"]

    def test_revision_can_remove_steps(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        steps = [{"id": "S1", "title": "Locate the write path", "acceptance": "the code path is known"}]
        result = plan_mode.handle_submit_plan(_revision_payload(steps=steps))
        assert result["success"] is True
        assert [step.id for step in session.diff.removed] == ["S2"]


class TestApplyRevision:
    def test_applies_in_place_and_preserves_todo_status(self, plan_state):
        session = plan_state.session
        submitted = _executing_plan(session)
        session.enter_revising()
        plan_mode.handle_submit_plan(_revision_payload())
        result = plan_mode.apply_revision(session)
        assert result["success"] is True
        assert result["revision"] == 2
        assert session.mode == "executing"
        assert session.draft_plan is None
        assert session.diff is None
        assert session.active_plan.revision == 2
        # Same file, updated in place — no new plan file was created.
        assert str(session.active_plan.path) == submitted["path"]
        assert _plan_files(session) == [os.path.basename(submitted["path"])]
        text = open(submitted["path"], encoding="utf-8").read()
        assert "revision: 2" in text
        assert "Add the flag and a config knob" in text
        assert "## Steps" in text
        # Todo statuses survive: S1 completed, S2 still in progress, S3 pending.
        assert session.todo_snapshot() == (("S1", "completed"), ("S2", "in_progress"), ("S3", "pending"))
        # Checkboxes are written back from the todo state.
        assert "- [x] **S1** Locate the write path" in text
        assert "Document the flag" in text
        assert result["resuming_at"] == "S2"

    def test_changed_step_keeps_its_status(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        steps = [
            {"id": "S1", "title": "Locate the write path", "acceptance": "the code path is known"},
            {"id": "S2", "title": "Add the flag, now with tests", "acceptance": "pytest tests/tools passes"},
        ]
        plan_mode.handle_submit_plan(_revision_payload(steps=steps, change_summary="align S2 with tests"))
        plan_mode.apply_revision(session)
        todos = {todo.id: todo for todo in session.todos}
        assert todos["S2"].status == "in_progress"
        assert todos["S2"].content == "Add the flag, now with tests"

    def test_removing_the_in_progress_step_leaves_no_in_progress(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        steps = [
            {"id": "S1", "title": "Locate the write path", "acceptance": "the code path is known"},
            {"id": "S3", "title": "Document the flag", "acceptance": "docs updated"},
        ]
        result = plan_mode.handle_submit_plan(_revision_payload(steps=steps))
        assert result["success"] is True
        assert [step.id for step in session.diff.removed] == ["S2"]
        applied = plan_mode.apply_revision(session)
        assert applied["success"] is True
        assert session.todo_snapshot() == (("S1", "completed"), ("S3", "pending"))
        assert all(todo.status != "in_progress" for todo in session.todos)

    def test_apply_without_revision_is_an_error(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        result = plan_mode.apply_revision(session)
        assert result["success"] is False
        assert result["error"] == "no_revision"

    def test_cancel_keeps_the_approved_plan_unchanged(self, plan_state):
        session = plan_state.session
        submitted = _executing_plan(session)
        session.enter_revising()
        plan_mode.handle_submit_plan(_revision_payload())
        session.cancel_draft()
        assert session.mode == "normal"
        assert session.active_plan is not None
        assert session.active_plan.revision == 1
        assert session.todo_snapshot() == (("S1", "completed"), ("S2", "in_progress"))
        text = open(submitted["path"], encoding="utf-8").read()
        assert "revision: 1" in text
        assert "Add the flag and a config knob" not in text

    def test_apply_writes_audit_event(self, plan_state):
        session = plan_state.session
        _executing_plan(session)
        session.enter_revising()
        plan_mode.handle_submit_plan(_revision_payload())
        plan_mode.apply_revision(session)
        lines = [json.loads(line) for line in open(plan_state.audit_path, encoding="utf-8").read().splitlines()]
        assert lines[-1]["event"] == "plan.revise_apply"
        assert lines[-1]["revision"] == 2
        assert lines[-1]["resuming_at"] == "S2"
