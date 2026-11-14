"""v0.24 K23 session resume: --resume / --chat always stay in NORMAL plan state.

The plan pointer lives in ``Chat.plan``; restoring it never re-enters plan mode and
only prints the two-line unfinished-plan hint. Files live under ``tmp_path`` and the
global plan session is reset around every test.
"""

from unittest.mock import MagicMock, patch

import pytest

from yaicli.cli import CLI
from yaicli.config import cfg


@pytest.fixture(autouse=True)
def reset_global_plan_session():
    from yaicli import plan_mode, tools

    plan_mode.reset_plan_session()
    tools.set_plan_tool_mode(None)
    yield
    plan_mode.reset_plan_session()
    tools.set_plan_tool_mode(None)


@pytest.fixture
def plan_cli(tmp_path, monkeypatch):
    monkeypatch.setitem(cfg, "PLAN_DIR", str(tmp_path / "plans"))
    client = MagicMock()
    manager = MagicMock()
    manager.chat_dir = tmp_path / "sessions"
    cli = CLI(verbose=False, client=client, chat_manager=manager)
    cli.console = MagicMock()
    cli.interactive = True
    cli.machine_output = False
    return cli


def _printed(cli) -> str:
    values = []
    for call in cli.console.print.call_args_list:
        if not call.args:
            continue
        first = call.args[0]
        markup = getattr(first, "markup", None)
        values.append(markup if isinstance(markup, str) else str(first))
    return "\n".join(values)


def _stderr_text(console_mock) -> str:
    values = []
    for call in console_mock.print.call_args_list:
        if call.args:
            values.append(str(call.args[0]))
    return "\n".join(values)


def _make_plan(cli, goal="Session plan"):
    """Create a real draft plan through the state machine; returns the Plan."""
    from yaicli import plan_mode

    cli._toggle_plan_mode()
    result = plan_mode.handle_submit_plan(
        {
            "goal": goal,
            "steps": [
                {"title": "First step", "acceptance": "first acceptance"},
                {"title": "Second step", "acceptance": "second acceptance"},
            ],
        }
    )
    assert result.get("success") is True, result
    plan = cli.plan_session.draft_plan
    assert plan is not None and plan.path is not None
    return plan


def _approve(cli, plan):
    """Approve a submitted plan so the plan file is in-progress."""
    from yaicli import plan_mode

    result = plan_mode.approve_new_plan(cli.plan_session)
    assert result.get("success") is True, result
    return plan


def _pointer(plan, todos=()) -> dict:
    """Build the ``Chat.plan`` session JSON for a plan file (draft or in-progress)."""
    return {
        "id": plan.id,
        "path": str(plan.path),
        "status": plan.status,
        "revision": plan.revision,
        "session_id": plan.session_id,
        "base_rev": plan.base_rev,
        "todos": [todo.to_dict() for todo in todos],
        "updated": plan.updated,
    }


def _silence_stderr():
    """Patch the stderr console used by resume hints (returns the mock)."""
    return patch("yaicli.cli.get_error_console")


class TestRestoreUnfinishedPlan:
    """``--resume`` always returns to NORMAL and only hints at the plan."""

    def test_draft_hint_points_at_review(self, plan_cli):
        plan = _make_plan(plan_cli)
        plan_cli.chat.plan = _pointer(plan)

        plan_cli._restore_plan_from_session()

        session = plan_cli.plan_session
        assert session is not None
        assert session.mode == "normal"
        assert session.is_plan_mode is False
        plan_cli.get_prompt_tokens() == [
            ("class:qmark", " 💬 "),
            ("class:prompt", "> "),
        ]
        printed = _printed(plan_cli)
        assert f"unfinished plan found: {plan.id} (draft, revision 1)" in printed
        assert "Use /plan review to continue it, or /plan list to see all plans." in printed

    def test_in_progress_hint_points_at_resume(self, plan_cli):
        plan = _make_plan(plan_cli)
        _approve(plan_cli, plan)
        session = plan_cli.plan_session
        plan_cli.chat.plan = _pointer(plan, session.todos)

        # A fresh CLI instance simulates a new process resuming the saved session.
        fresh = CLI(verbose=False, client=MagicMock(), chat_manager=MagicMock())
        fresh.console = MagicMock()
        fresh.chat = plan_cli.chat
        fresh._restore_plan_from_session()

        restored = fresh.plan_session
        assert restored is not None
        assert restored.mode == "normal"
        assert restored.active_plan is not None
        assert restored.active_plan.id == plan.id
        assert [todo.id for todo in restored.todos] == ["S1", "S2"]
        printed = "\n".join(
            getattr(call.args[0], "markup", None) or str(call.args[0])
            for call in fresh.console.print.call_args_list
            if call.args
        )
        assert f"unfinished plan found: {plan.id} (in-progress, revision 1)" in printed
        assert "Use /plan resume to continue it, or /plan list to see all plans." in printed

    def test_restore_never_enables_plan_tool_mode(self, plan_cli):
        from yaicli import tools

        plan = _make_plan(plan_cli)
        plan_cli.chat.plan = _pointer(plan)

        plan_cli._restore_plan_from_session()

        assert plan_cli.plan_session.mode == "normal"
        assert tools.get_plan_tool_mode() is None

    def test_missing_plan_file_prints_error_and_clears_pointer(self, plan_cli, tmp_path):
        plan = _make_plan(plan_cli)
        pointer = _pointer(plan)
        pointer["path"] = str(tmp_path / "plans" / "gone.md")
        plan_cli.chat.plan = pointer

        with _silence_stderr() as error_console:
            plan_cli._restore_plan_from_session()

        assert "saved plan not found/inconsistent; starting in normal mode" in _stderr_text(error_console.return_value)
        assert plan_cli.chat.plan == {}
        assert plan_cli.plan_session.mode == "normal"

    def test_corrupt_plan_file_prints_error(self, plan_cli):
        plan = _make_plan(plan_cli)
        plan.path.write_text("this is not a plan", encoding="utf-8")
        plan_cli.chat.plan = _pointer(plan)

        with _silence_stderr() as error_console:
            plan_cli._restore_plan_from_session()

        assert "saved plan not found/inconsistent; starting in normal mode" in _stderr_text(error_console.return_value)
        assert plan_cli.chat.plan == {}

    def test_other_session_plan_is_ignored(self, plan_cli, tmp_path):
        plan = _make_plan(plan_cli)
        # A different CLI/process has a different session id: the plan file belongs
        # to the first session and must not be silently adopted.
        other = CLI(verbose=False, client=MagicMock(), chat_manager=MagicMock())
        other.console = MagicMock()
        other.chat.plan = _pointer(plan)

        with _silence_stderr() as error_console:
            other._restore_plan_from_session()

        assert "saved plan not found/inconsistent; starting in normal mode" in _stderr_text(error_console.return_value)
        assert other.plan_session.mode == "normal"
        assert other.chat.plan == {}

    def test_no_plan_pointer_is_a_noop(self, plan_cli):
        plan_cli.chat.plan = {}
        plan_cli._restore_plan_from_session()
        assert plan_cli.plan_session is None


class TestRunResumeFlow:
    """CLI.run's chat branch restores the plan after resuming/loading a session."""

    def test_resume_run_restores_and_stays_normal(self, plan_cli, monkeypatch):
        plan = _make_plan(plan_cli)
        plan_cli.chat.plan = _pointer(plan)
        plan_cli.resume = True

        # The saved session keeps its plan pointer; resuming just re-selects it.
        monkeypatch.setattr(CLI, "_resume_latest_session", lambda self: True)
        monkeypatch.setattr(CLI, "_run_repl", lambda self: None)

        plan_cli.run(chat=True)

        assert plan_cli.plan_session.mode == "normal"
        assert "unfinished plan found" in _printed(plan_cli)

    def test_chat_title_run_restores_and_stays_normal(self, plan_cli, monkeypatch):
        plan = _make_plan(plan_cli)
        plan_cli.chat.plan = _pointer(plan)

        monkeypatch.setattr(CLI, "_start_chat_by_title", lambda self, title: None)
        monkeypatch.setattr(CLI, "_run_repl", lambda self: None)

        plan_cli.run(chat=True, user_input="saved title")

        assert plan_cli.plan_session.mode == "normal"
        assert "unfinished plan found" in _printed(plan_cli)

    def test_run_loads_session_plan_pointer_from_chat(self, plan_cli, monkeypatch):
        """The restore hook runs after a resumed session replaced ``cli.chat``."""
        plan = _make_plan(plan_cli)
        loaded_chat = MagicMock()
        loaded_chat.plan = _pointer(plan)
        loaded_chat.history = []
        loaded_chat.model = ""
        loaded_chat.provider = ""
        loaded_chat.role = ""
        loaded_chat.cwd = ""
        loaded_chat.title = "saved"
        loaded_chat.date = plan.session_id
        calls = []

        def fake_resume(self):
            self.chat = loaded_chat
            return True

        monkeypatch.setattr(CLI, "_resume_latest_session", fake_resume)
        monkeypatch.setattr(CLI, "_run_repl", lambda self: None)
        monkeypatch.setattr(CLI, "_apply_session_metadata", lambda self, chat: None)

        plan_cli.resume = True
        plan_cli.run(chat=True)
        calls.append(True)

        assert calls
        assert plan_cli.plan_session.mode == "normal"
        restored_plan = plan_cli.plan_session.active_plan or plan_cli.plan_session.draft_plan
        assert restored_plan is not None
