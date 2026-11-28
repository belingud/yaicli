"""Persisted planning contracts shared by the legacy and extracted entry points."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from yaicli import const, plan_mode, plan_store
from yaicli.config import cfg


@pytest.fixture
def planning_session(tmp_path, monkeypatch):
    monkeypatch.setitem(cfg, "TOOL_AUDIT", True)
    monkeypatch.setattr(const, "TOOL_AUDIT_PATH", tmp_path / "audit.jsonl")
    session = plan_mode.PlanSession()
    session.configure(plans_root=tmp_path / "plans", cwd=tmp_path, session_id="saved-session", model="test-model")
    plan_mode.set_plan_session(session)
    try:
        yield session
    finally:
        plan_mode.reset_plan_session()


def _submit(session):
    session.enter_researching()
    result = plan_mode.handle_submit_plan(
        {
            "goal": "Keep persisted planning contracts",
            "steps": [
                {"title": "Read the existing plan", "acceptance": "The stored fields are preserved"},
                {"title": "Verify execution progress", "acceptance": "The original plan can resume"},
            ],
        }
    )
    assert result["success"] is True
    return session.draft_plan


@pytest.mark.parametrize("approved", [False, True], ids=["saved-draft", "approved-plan"])
def test_saved_plan_restores_with_original_state_and_file_bytes(planning_session, approved):
    session = planning_session
    plan = _submit(session)
    if approved:
        assert plan_mode.approve_new_plan(session)["success"] is True
        result = plan_mode.handle_todo_write(
            {
                "items": [
                    {"id": "S2", "status": "blocked", "reason": "Waiting for review"},
                    {"id": "S1", "status": "completed"},
                ]
            }
        )
        assert result["completed"] == 1
        assert result["blocked"] == 1
    before = plan.path.read_bytes()
    saved = session.to_session_dict()
    restored = plan_mode.PlanSession()
    error = restored.restore_from_session(
        saved, session_id="saved-session", plans_root=session.plans_root, cwd=session.cwd
    )
    assert error is None
    assert restored.mode == "normal"
    current = restored.active_plan if approved else restored.draft_plan
    assert current.id == plan.id
    assert current.path == plan.path
    assert current.steps == plan.steps
    assert current.session_id == "saved-session"
    assert restored.todos == session.todos
    assert plan.path.read_bytes() == before
    if approved:
        assert plan_mode.resume_plan(restored) is True
        context = plan_mode.plan_context_block(restored)
        assert "Progress: 1/2 steps completed" in context
        assert "S2 Verify execution progress — blocked: Waiting for review" in context
        assert b"- [x] **S1** Read the existing plan" in before
        assert b"- [ ] **S2** Verify execution progress (blocked: Waiting for review)" in before
    else:
        assert plan_mode.resume_plan(restored) is False
        assert restored.active_plan is None


def test_rejected_todo_preserves_memory_and_persisted_plan(planning_session):
    session = planning_session
    plan = _submit(session)
    assert plan_mode.approve_new_plan(session)["success"] is True
    before_bytes = plan.path.read_bytes()
    before_todos = [todo.to_dict() for todo in session.todos]
    result = plan_mode.handle_todo_write({"items": [{"id": "S1", "status": "completed"}]})
    assert result == {
        "success": False,
        "error": "invalid_todo",
        "reason": "todo_write must include every step of the current plan revision; missing: S2",
        "hint": "todo_write replaces the whole list; include unchanged steps too.",
    }
    assert [todo.to_dict() for todo in session.todos] == before_todos
    assert plan.path.read_bytes() == before_bytes


def test_revision_only_replaces_approved_bytes_on_approval(planning_session):
    session = planning_session
    plan = _submit(session)
    assert plan_mode.approve_new_plan(session)["success"] is True
    original = plan.path.read_bytes()
    session.enter_revising()
    result = plan_mode.handle_submit_plan(
        {
            "goal": "Keep the revised planning contract",
            "revision": 2,
            "change_summary": "Replace the second step",
            "steps": [
                {"id": "S1", "title": "Read the existing plan", "acceptance": "The stored fields are preserved"},
                {"id": "S3", "title": "Check the revised plan", "acceptance": "The approved path is unchanged"},
            ],
        }
    )
    assert result["success"] is True
    assert session.mode == "reviewing"
    assert session.active_plan is plan
    assert plan.path.read_bytes() == original
    assert session.diff.removed[0].id == "S2"
    applied = plan_mode.apply_revision(session)
    assert applied["success"] is True
    assert Path(applied["path"]) == plan.path
    assert session.active_plan is plan
    persisted = plan_store.read_plan(plan.path)
    assert persisted.id == plan.id
    assert persisted.revision == 2
    assert persisted.status == "in-progress"
    assert [step.id for step in persisted.steps] == ["S1", "S3"]
    assert [todo.status for todo in session.todos] == ["in_progress", "pending"]


def test_legacy_entry_points_share_model_identity_and_default_session():
    from yaicli.planning import model, service, store

    assert plan_mode.PlanMode is model.PlanMode
    assert plan_mode.PlanSession is model.PlanSession
    assert plan_mode.TodoItem is model.TodoItem
    assert plan_mode.RevisionDiff is model.RevisionDiff
    assert plan_store.Plan is store.Plan
    assert plan_store.PlanStep is store.PlanStep
    assert plan_store.PlanStoreError is store.PlanStoreError
    assert plan_mode.handle_submit_plan is service.handle_submit_plan
    assert plan_mode.handle_todo_write is service.handle_todo_write
    explicit = model.PlanSession()
    try:
        plan_mode.set_plan_session(explicit)
        assert service.get_plan_session() is explicit
        service.reset_plan_session()
        fresh = plan_mode.get_plan_session()
        assert fresh is service.get_plan_session()
        assert fresh is not explicit
    finally:
        service.reset_plan_session()


def test_leaf_imports_do_not_load_application_config_or_terminal(tmp_path):
    code = """
import sys
from pathlib import Path
from yaicli.planning import model, store, validation
for forbidden in ('yaicli.cli', 'yaicli.entry', 'yaicli.config', 'rich', 'typer', 'prompt_toolkit'):
    assert forbidden not in sys.modules, forbidden
assert store.PlanStep(id='S1', title='Read') == validation.plan_store.PlanStep(id='S1', title='Read')
assert model.PlanSession().mode == 'normal'
"""
    config_dir = tmp_path / "private-config"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env={"PATH": os.defpath, "HOME": str(tmp_path), "YAI_CONFIG_DIR": str(config_dir)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not config_dir.exists()


def test_planning_core_has_no_cli_or_terminal_imports():
    from yaicli.planning import editor, model, prompt, service, store, validation

    for module in (editor, model, prompt, service, store, validation):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imports = [
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        assert not any(
            name and any(part in name.split(".") for part in ("cli", "entry", "rich", "typer", "printer"))
            for name in imports
        ), (module.__name__, imports)
