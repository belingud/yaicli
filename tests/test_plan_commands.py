"""v0.24 K23 plan-mode REPL surface: /plan + /todo, prompt tokens, help/banner.

These tests use the real plan_mode/plan_store modules with ``PLAN_DIR`` pointed at
``tmp_path`` (never the developer's real config directory) and mock every
provider/editor boundary. Global plan state is reset around each test.
"""

from unittest.mock import MagicMock

import pytest
from rich.table import Table

from yaicli.cli import CLI
from yaicli.cmd_handler import COMMAND_INFO, CmdHandler, command_completions
from yaicli.config import cfg
from yaicli.const import CHAT_MODE, CMD_PLAN, CMD_TODO
from yaicli.schemas import ChatMessage, ToolCall


@pytest.fixture(autouse=True)
def reset_global_plan_session():
    """Reset the process-global plan session / tool mode around every test."""
    from yaicli import plan_mode, tools

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
    cli.interactive = True
    cli.machine_output = False
    return cli


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


def _tables(cli):
    return [call.args[0] for call in cli.console.print.call_args_list if call.args and isinstance(call.args[0], Table)]


def _submit(cli, goal="Plan the feature", steps=None):
    """Submit a first plan through the real state machine (as submit_plan would)."""
    from yaicli import plan_mode

    steps = steps or [
        {"title": "First step", "acceptance": "first acceptance"},
        {"title": "Second step", "acceptance": "second acceptance"},
    ]
    result = plan_mode.handle_submit_plan({"goal": goal, "steps": steps})
    assert result.get("success") is True, result
    assert cli.plan_session.draft_plan is not None
    return cli.plan_session.draft_plan


class TestCommandMetadata:
    """The help table and completion menu expose /plan and /todo."""

    def test_plan_and_todo_metadata(self):
        infos = {info.command: info for info in COMMAND_INFO}
        assert CMD_PLAN in infos
        assert CMD_TODO in infos
        plan_info = infos[CMD_PLAN]
        assert "toggle" in plan_info.description
        for fragment in ("list [--all]", "review [id]", "resume [id]", "clear [--done|--all]", "abort"):
            assert fragment in plan_info.usage
        offered = dict(command_completions())
        assert CMD_PLAN in offered
        assert CMD_TODO in offered

    def test_handlers_registered_and_completion_parity(self, plan_cli):
        handler = CmdHandler(plan_cli)
        for info in COMMAND_INFO:
            assert info.command in handler.commands, info.command
        registered = {command for command in handler.commands if command.startswith("/")}
        offered = {command for command, _ in command_completions()}
        assert offered == registered


class TestPromptAndBanner:
    """Prompt tokens, status line and the welcome banner reflect plan mode."""

    def test_toggle_reaches_plan_prompt_and_back(self, plan_cli):
        from yaicli import tools

        plan_cli.current_mode = CHAT_MODE
        assert plan_cli.cmd_handler.handle_command(CMD_PLAN) is True
        session = plan_cli.plan_session
        assert session.mode == "researching"
        assert tools.get_plan_tool_mode() == "plan"
        assert plan_cli.get_prompt_tokens() == [("class:qmark", " [plan] 💬 "), ("class:prompt", "> ")]
        printed = _printed(plan_cli)
        assert "[plan] exploring (read-only) …" in printed
        assert "plan mode · read-only" in printed

        assert plan_cli.cmd_handler.handle_command(CMD_PLAN) is True
        assert session.mode == "normal"
        assert tools.get_plan_tool_mode() is None
        assert "plan mode off" in _printed(plan_cli)
        assert plan_cli.get_prompt_tokens() == [("class:qmark", " 💬 "), ("class:prompt", "> ")]

    def test_shift_tab_in_reviewing_cancels_and_persists_draft(self, plan_cli):
        """Shift+Tab while reviewing = cancel submission (draft file kept)."""
        plan_cli._toggle_plan_mode()
        plan = _submit(plan_cli)
        assert plan_cli.plan_session.mode == "reviewing"

        plan_cli._toggle_plan_mode()

        assert plan_cli.plan_session.mode == "normal"
        assert "plan cancelled; draft saved at " in _printed(plan_cli)
        assert plan_cli.chat.plan["id"] == plan.id
        assert plan_cli.chat.plan["status"] == "draft"
        assert plan.path.exists()

    def test_toggle_while_executing_enters_revising(self, plan_cli):
        from yaicli import plan_mode

        plan_cli.current_mode = CHAT_MODE
        plan_cli._toggle_plan_mode()
        _submit(plan_cli)
        plan_mode.approve_new_plan(plan_cli.plan_session)
        assert plan_cli.plan_session.mode == "executing"

        plan_cli._toggle_plan_mode()
        assert plan_cli.plan_session.mode == "revising"
        assert "[plan] revising (read-only) …" in _printed(plan_cli)

    def test_plan_disabled_prints_one_line(self, plan_cli, monkeypatch):
        monkeypatch.setitem(cfg, "PLAN_ENABLED", False)
        assert plan_cli.cmd_handler.handle_command(CMD_PLAN) is True
        assert plan_cli.plan_session is None
        assert "plan mode is disabled (PLAN_ENABLED=false)" in _printed(plan_cli)

    def test_help_and_banner_mention_plan_mode(self, plan_cli):
        plan_cli.print_help()
        printed = _printed(plan_cli)
        assert "toggle plan mode (normal ↔ plan, read-only)" in printed
        assert CMD_PLAN in printed
        assert CMD_TODO in printed

        plan_cli._print_welcome_message()
        banner = _printed(plan_cli)
        assert "Plan mode: Shift+Tab / /plan" in banner
        assert "plan files under" in banner

    def test_banner_disabled(self, plan_cli, monkeypatch):
        monkeypatch.setitem(cfg, "PLAN_ENABLED", False)
        plan_cli._print_welcome_message()
        assert "Plan mode: disabled (PLAN_ENABLED=false)" in _printed(plan_cli)


class TestPlanSubcommands:
    """/plan <task>, list/show/clear/abort and /todo."""

    def test_plan_task_enters_mode_and_returns_task(self, plan_cli):
        task = "investigate the token estimator"
        result = plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} {task}")
        assert result == task
        assert plan_cli.plan_session.mode == "researching"

    def test_plan_task_rejected_while_reviewing(self, plan_cli):
        plan_cli._toggle_plan_mode()
        _submit(plan_cli)
        result = plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} do something else")
        assert result is True
        assert "a plan is waiting for review; approve or cancel it first" in _printed(plan_cli)
        assert plan_cli.plan_session.mode == "reviewing"

    def test_plan_list_empty(self, plan_cli):
        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} list") is True
        assert "no plans yet" in _printed(plan_cli)

    def test_plan_list_and_show_after_submit(self, plan_cli):
        plan_cli._toggle_plan_mode()
        plan = _submit(plan_cli, goal="Listed goal")

        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} list") is True
        tables = _tables(plan_cli)
        assert tables, "expected a plan list table"
        assert tables[0].title == "Plans"
        assert len(tables[0].rows) == 1

        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} show {plan.id}") is True
        rendered = [getattr(call.args[0], "markup", "") for call in plan_cli.console.print.call_args_list if call.args]
        assert any("Listed goal" in text for text in rendered)

    def test_plan_show_not_found(self, plan_cli):
        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} show 20990101-000000-nope") is True
        assert "plan not found: 20990101-000000-nope" in _printed(plan_cli)

    def test_plan_show_without_plan(self, plan_cli):
        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} show") is True
        assert "no plan in this session" in _printed(plan_cli)

    def test_plan_clear_usage_and_noninteractive(self, plan_cli):
        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} clear") is True
        assert f"Usage: {CMD_PLAN} clear --done|--all" in _printed(plan_cli)

        plan_cli.interactive = False
        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} clear --done") is True
        assert "plan clear needs an interactive confirmation" in _printed(plan_cli)

    def test_plan_clear_removes_finished_plans(self, plan_cli, monkeypatch):
        from yaicli import plan_mode
        from yaicli.plan_store import PLAN_STATUS_DONE

        plan_cli._toggle_plan_mode()
        plan = _submit(plan_cli)
        plan_mode.approve_new_plan(plan_cli.plan_session)
        plan_mode.finish_plan(plan_cli.plan_session)
        assert plan.status == PLAN_STATUS_DONE

        monkeypatch.setattr("yaicli.cmd_handler.Prompt.ask", lambda *args, **kwargs: "y")
        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} clear --done") is True
        assert "cleared 1 plan file(s)" in _printed(plan_cli)
        assert not plan.path.exists()

    def test_plan_abort_without_plan(self, plan_cli):
        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} abort") is True
        assert "no plan in this session" in _printed(plan_cli)

    def test_plan_abort_with_plan(self, plan_cli, monkeypatch):
        from yaicli import plan_mode
        from yaicli.plan_store import PLAN_STATUS_ABORTED

        plan_cli._toggle_plan_mode()
        plan = _submit(plan_cli)
        plan_mode.approve_new_plan(plan_cli.plan_session)
        monkeypatch.setattr("yaicli.cmd_handler.Prompt.ask", lambda *args, **kwargs: "y")

        assert plan_cli.cmd_handler.handle_command(f"{CMD_PLAN} abort") is True
        assert "plan aborted · todos cleared" in _printed(plan_cli)
        assert plan_cli.plan_session.active_plan is None
        assert plan.status == PLAN_STATUS_ABORTED


class TestTodoCommand:
    """``/todo`` renders the current plan's todo table."""

    def test_todo_without_plan(self, plan_cli):
        assert plan_cli.cmd_handler.handle_command(CMD_TODO) is True
        assert "no plan in this session" in _printed(plan_cli)

    def test_todo_table_after_approve(self, plan_cli):
        from yaicli import plan_mode

        plan_cli._toggle_plan_mode()
        plan = _submit(plan_cli)
        plan_mode.approve_new_plan(plan_cli.plan_session)

        assert plan_cli.cmd_handler.handle_command(CMD_TODO) is True
        tables = _tables(plan_cli)
        assert len(tables) == 1
        assert len(tables[0].rows) == 2
        assert f"plan: {plan.id} · in-progress · revision 1" in _printed(plan_cli)

    def test_todo_shows_draft_steps_as_pending(self, plan_cli):
        plan_cli._toggle_plan_mode()
        _submit(plan_cli)

        assert plan_cli.cmd_handler.handle_command(CMD_TODO) is True
        tables = _tables(plan_cli)
        assert len(tables) == 1
        assert tables[0].row_count == 2
        cells = [str(cell) for column in tables[0].columns for cell in column._cells]
        assert "pending" in cells


class TestPlanReplyWithoutPlanHint:
    """A text-only plan-mode answer is flagged instead of pretending a plan exists.

    This is the guard for the reported failure mode: the user asks for an HTML page
    in plan mode and the model replies with the code (possibly because a provider
    dropped the plan-mode system block). The turn still completes, but the REPL
    must surface that no plan was submitted.
    """

    @staticmethod
    def _run_turn(plan_cli, monkeypatch, updated_messages):
        monkeypatch.setattr(
            CLI,
            "_handle_llm_response",
            lambda self, user_input, images=None: ("<html>weather</html>", list(updated_messages)),
        )
        return plan_cli._process_user_input("build a weather page")

    def test_text_only_reply_prints_hint(self, plan_cli, monkeypatch):
        plan_cli._toggle_plan_mode()
        self._run_turn(plan_cli, monkeypatch, [])
        assert "[plan] no plan submitted" in _printed(plan_cli)

    def test_reply_with_tool_calls_prints_no_hint(self, plan_cli, monkeypatch):
        plan_cli._toggle_plan_mode()
        messages = [
            ChatMessage(role="user", content="build a weather page"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call-1", name="fs_read_file", arguments='{"file_paths": ["a.py"]}')],
            ),
        ]
        self._run_turn(plan_cli, monkeypatch, messages)
        assert "[plan] no plan submitted" not in _printed(plan_cli)

    def test_normal_mode_reply_prints_no_hint(self, plan_cli, monkeypatch):
        self._run_turn(plan_cli, monkeypatch, [])
        assert "[plan] no plan submitted" not in _printed(plan_cli)

    def test_machine_output_reply_prints_no_hint(self, plan_cli, monkeypatch):
        plan_cli._toggle_plan_mode()
        plan_cli.machine_output = True
        self._run_turn(plan_cli, monkeypatch, [])
        assert "[plan] no plan submitted" not in _printed(plan_cli)
