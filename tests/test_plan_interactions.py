"""v0.24 K23 cross-feature interactions (Lead-owned integration tests).

Covers the seams that are owned by no single module test file:

* ``/compact`` must not disturb the plan session, the injected plan context block
  or the persisted ``Chat.plan`` pointer (acceptance criterion 12).
* ``/plan review`` must re-open a saved draft from disk in the approval panel.
* ``/plan resume`` must restore an in-progress plan, seed its todos and start the
  execution loop (acceptance criterion 8, by explicit user action).

Plans always live under ``tmp_path``; every provider/editor boundary is mocked and
the process-global plan state is reset around each test.
"""

from unittest.mock import MagicMock

import pytest

from yaicli import plan_mode
from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.schemas import ChatMessage


@pytest.fixture(autouse=True)
def reset_global_plan_session():
    """Reset the process-global plan session / tool mode around every test."""
    from yaicli import tools

    plan_mode.reset_plan_session()
    tools.set_plan_tool_mode(None)
    yield
    plan_mode.reset_plan_session()
    tools.set_plan_tool_mode(None)


@pytest.fixture
def plan_cli(tmp_path, monkeypatch):
    """A real CLI with a mocked LLM client and its plans root inside tmp_path."""
    monkeypatch.setitem(cfg, "PLAN_DIR", str(tmp_path / "plans"))
    client = MagicMock()
    manager = MagicMock()
    manager.chat_dir = tmp_path / "sessions"
    cli = CLI(verbose=False, client=client, chat_manager=manager)
    cli.console = MagicMock()
    cli.printer = MagicMock()
    cli.interactive = True
    cli.machine_output = False
    # The repository itself contains AGENTS.md/CLAUDE.md; keep request assembly pure.
    monkeypatch.setattr(CLI, "_get_project_context", lambda self: "")
    return cli


STEPS = [
    {"title": "First step", "acceptance": "first acceptance"},
    {"title": "Second step", "acceptance": "second acceptance"},
]


def _printed(cli) -> str:
    """All text printed through the mocked console (Renderables included)."""
    values = []
    for call in cli.console.print.call_args_list:
        if not call.args:
            continue
        first = call.args[0]
        markup = getattr(first, "markup", None)
        values.append(markup if isinstance(markup, str) else str(first))
    return "\n".join(values)


def _submit(cli, goal: str = "Interaction plan"):
    """Submit a first plan through the real state machine (as submit_plan would)."""
    session = cli._get_plan_session()
    if not session.is_plan_mode:
        session.enter_researching()
    result = plan_mode.handle_submit_plan({"goal": goal, "steps": [dict(step) for step in STEPS]})
    assert result.get("success") is True, result
    assert cli.plan_session.draft_plan is not None
    return cli.plan_session.draft_plan


def _system_text(messages) -> str:
    return "\n".join(str(message.content) for message in messages if message.role == "system")


class TestCompactInteraction:
    """``/compact`` trims history only: plan state/context survive untouched."""

    def test_compact_keeps_plan_state_and_context(self, plan_cli):
        for index in range(4):
            plan_cli.chat.history.append(ChatMessage(role="user", content=f"question {index}"))
            plan_cli.chat.history.append(ChatMessage(role="assistant", content=f"answer {index}"))

        plan = _submit(plan_cli)
        plan_mode.approve_new_plan(plan_cli.plan_session)
        plan_cli._sync_chat_plan()
        todos_before = plan_cli.plan_session.todo_snapshot()
        plan_pointer_before = dict(plan_cli.chat.plan)

        # The command routes through the real CmdHandler (prefix match included).
        assert plan_cli.cmd_handler.handle_command("/compact 1") is True

        session = plan_cli.plan_session
        assert session.active_plan is not None
        assert session.active_plan.id == plan.id
        assert session.todo_snapshot() == todos_before
        assert plan_cli.chat.plan == plan_pointer_before

        blocks = _system_text(plan_cli._build_messages("continue"))
        assert "EXECUTING THE APPROVED PLAN" in blocks
        assert plan.goal in blocks
        assert "Todo 1/2 completed" not in blocks  # fresh approved plan: S1 in progress only

    def test_compact_keeps_plan_mode_context_while_planning(self, plan_cli):
        plan_cli._toggle_plan_mode()
        _submit(plan_cli, goal="Research plan")
        assert plan_cli.plan_session.mode == "reviewing"
        # A reviewing submission keeps the draft as the injected plan base.
        plan_cli.plan_session.mode = "researching"
        plan_cli.chat.history = [
            ChatMessage(role="user", content="older question"),
            ChatMessage(role="assistant", content="older answer"),
            ChatMessage(role="user", content="recent question"),
            ChatMessage(role="assistant", content="recent answer"),
        ]
        assert plan_cli.cmd_handler.handle_command("/compact 1") is True
        blocks = _system_text(plan_cli._build_messages("more research"))
        assert "PLAN MODE IS ACTIVE (read-only)" in blocks
        assert "Research plan" in blocks


class TestPlanDiskCommands:
    """``/plan review`` and ``/plan resume`` re-open persisted plans explicitly."""

    def test_plan_review_reopens_saved_draft(self, plan_cli):
        plan = _submit(plan_cli, goal="Draft to review")
        plan_cli.printer.ask_plan_decision.return_value = "save"
        plan_cli._handle_plan_review_panel()
        assert plan_cli.plan_session.mode == "normal"
        plan_path = plan.path
        assert plan_path is not None and plan_path.is_file()

        # Simulate a fresh process: in-memory session is gone, Chat.plan survived.
        plan_mode.reset_plan_session()
        plan_cli.plan_session = None
        assert plan_cli.chat.plan.get("id") == plan.id

        plan_cli.printer.ask_plan_decision.return_value = "cancel"
        assert plan_cli.cmd_handler.handle_plan("/plan review") is True

        session = plan_cli.plan_session
        assert session.mode == "normal"  # cancel left plan mode again
        assert plan_path.is_file()
        assert plan_path.read_text(encoding="utf-8").startswith("---")
        assert "plan cancelled; draft saved at" in _printed(plan_cli)
        assert plan_cli.chat.plan.get("id") == plan.id

    def test_plan_resume_continues_in_progress_plan(self, plan_cli, monkeypatch):
        plan = _submit(plan_cli, goal="Resume me")
        plan_mode.approve_new_plan(plan_cli.plan_session)
        plan_mode.pause_plan(plan_cli.plan_session)
        plan_cli._sync_chat_plan()
        assert plan_cli.plan_session.mode == "normal"
        plan_mode.reset_plan_session()
        plan_cli.plan_session = None

        executed = []
        monkeypatch.setattr(CLI, "_execute_plan", lambda self: executed.append(True))

        assert plan_cli.cmd_handler.handle_plan("/plan resume") is True

        session = plan_cli.plan_session
        assert executed, "/plan resume must start the execution loop"
        assert session.active_plan is not None and session.active_plan.id == plan.id
        assert session.mode == "executing"
        assert [todo.id for todo in session.todos] == ["S1", "S2"]

    def test_plan_resume_rejects_other_session_plan(self, plan_cli, monkeypatch):
        plan = _submit(plan_cli, goal="Other session")
        plan_mode.approve_new_plan(plan_cli.plan_session)
        plan_mode.pause_plan(plan_cli.plan_session)
        plan_mode.reset_plan_session()
        plan_cli.plan_session = None
        plan_cli.chat.date = "2026-01-01T00:00:00"  # different session id
        monkeypatch.setattr(CLI, "_execute_plan", lambda self: pytest.fail("must not execute"))

        assert plan_cli.cmd_handler.handle_plan(f"/plan resume {plan.id}") is True
        assert "plan is already in progress in another session" in _printed(plan_cli)

    def test_plan_abort_clears_todos(self, plan_cli, monkeypatch):
        plan = _submit(plan_cli, goal="Abort me")
        plan_mode.approve_new_plan(plan_cli.plan_session)
        plan_cli._sync_chat_plan()
        monkeypatch.setattr("yaicli.cmd_handler.Prompt.ask", lambda *args, **kwargs: "y")
        assert plan_cli.cmd_handler.handle_plan("/plan abort") is True
        session = plan_cli.plan_session
        assert session.active_plan is None
        assert session.todos == []
        assert plan.path is not None and plan.path.exists()
        assert "plan aborted · todos cleared" in _printed(plan_cli)


class TestPlanPromptDelivery:
    """Plan rules must travel in the FIRST system message (provider portability).

    Anthropic only sends one system prompt and Gemini only reads ``messages[0]`` as
    ``system_instruction``; a second system message carrying the plan rules would be
    silently dropped there (and is an invalid role for Anthropic), which made plan
    mode behave like plain chat for those providers.
    """

    @staticmethod
    def _messages(cli, mode: str):
        session = cli._get_plan_session()
        if mode == "executing":
            _submit(cli, goal="Delivery plan")
            plan_mode.approve_new_plan(session)
        session.mode = mode
        return cli._build_messages("go on")

    def test_researching_rules_are_in_the_first_system_message(self, plan_cli):
        messages = self._messages(plan_cli, "researching")
        system_messages = [message for message in messages if message.role == "system"]
        assert len(system_messages) == 1
        content = system_messages[0].content
        assert "PLAN MODE IS ACTIVE (read-only)" in content
        assert "submit_plan" in content
        assert "MUST NOT write the implementation" in content

    def test_revising_rules_are_in_the_first_system_message(self, plan_cli):
        _submit(plan_cli, goal="Revise me")
        plan_mode.approve_new_plan(plan_cli.plan_session)
        plan_cli.plan_session.enter_revising()
        messages = plan_cli._build_messages("adjust the plan")
        system_messages = [message for message in messages if message.role == "system"]
        assert len(system_messages) == 1
        assert "PLAN MODE IS ACTIVE (revising)" in system_messages[0].content
        assert "revision=2" in system_messages[0].content

    def test_execution_rules_are_in_the_first_system_message(self, plan_cli):
        messages = self._messages(plan_cli, "executing")
        system_messages = [message for message in messages if message.role == "system"]
        assert len(system_messages) == 1
        content = system_messages[0].content
        assert "EXECUTING THE APPROVED PLAN" in content
        assert "Delivery plan" in content

    def test_normal_mode_adds_no_plan_prompt(self, plan_cli):
        messages = plan_cli._build_messages("hello")
        system_messages = [message for message in messages if message.role == "system"]
        assert len(system_messages) == 1
        assert "PLAN MODE" not in (system_messages[0].content or "")
        assert "EXECUTING THE APPROVED PLAN" not in (system_messages[0].content or "")
