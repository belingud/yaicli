"""v0.24 K23 plan approval panel and execution loop (with re-plan revisions).

Everything network/provider/editor related is mocked; plans live under ``tmp_path``
and the process-global plan session is reset around each test.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from yaicli import cli as cli_module
from yaicli import plan_mode
from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.plan_store import PLAN_STATUS_DONE, PLAN_STATUS_DRAFT, PLAN_STATUS_IN_PROGRESS, read_plan


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
    cli.printer = MagicMock()
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


SPEC = [
    {"title": "First step", "acceptance": "first acceptance"},
    {"title": "Second step", "acceptance": "second acceptance"},
]


def _submit(cli, steps=None, goal="Execution plan"):
    from yaicli import plan_mode

    result = plan_mode.handle_submit_plan({"goal": goal, "steps": list(steps or SPEC)})
    assert result.get("success") is True, result
    plan = cli.plan_session.draft_plan
    assert plan is not None and plan.path is not None
    return plan


def _enter_reviewing(cli, steps=None, goal="Execution plan"):
    cli._toggle_plan_mode()
    return _submit(cli, steps=steps, goal=goal)


def _approve(cli):
    from yaicli import plan_mode

    result = plan_mode.approve_new_plan(cli.plan_session)
    assert result.get("success") is True, result
    return cli.plan_session.active_plan


def _todo_items(cli, statuses):
    plan = cli.plan_session.active_plan
    return {
        "items": [
            {"id": step.id, "content": step.title, "status": status} for step, status in zip(plan.steps, statuses)
        ]
    }


def _no_execute(monkeypatch):
    """Replace the execution loop with a recorder (approval tests don't run turns)."""
    executed = []
    monkeypatch.setattr(CLI, "_execute_plan", lambda self: executed.append(True))
    return executed


class TestApprovalPanel:
    """[a]pprove seeds todos + starts execution; readonly policy is guarded."""

    def test_approve_seeds_todos_and_starts_execution(self, plan_cli, monkeypatch):
        plan = _enter_reviewing(plan_cli)
        executed = _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.return_value = "approve"

        plan_cli._handle_plan_review_panel()

        assert executed, "approving must start the execution loop"
        assert plan_cli.plan_session.mode == "executing"
        assert "✓ plan approved · exiting plan mode · todo seeded (2 steps)" in _printed(plan_cli)
        persisted = read_plan(plan.path)
        assert persisted.status == PLAN_STATUS_IN_PROGRESS
        todos = plan_cli.plan_session.todos
        assert [(todo.id, todo.status) for todo in todos] == [("S1", "in_progress"), ("S2", "pending")]

    def test_save_only_keeps_draft_and_exits_normal(self, plan_cli, monkeypatch):
        plan = _enter_reviewing(plan_cli)
        executed = _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.return_value = "save"

        plan_cli._handle_plan_review_panel()

        assert not executed
        assert plan_cli.plan_session.mode == "normal"
        assert read_plan(plan.path).status == PLAN_STATUS_DRAFT
        printed = _printed(plan_cli)
        assert "✓ saved as draft (" in printed
        assert "· exit plan mode" in printed
        # The saved draft is still an unfinished plan: its pointer survives so a
        # later --resume can print the "unfinished plan found" hint.
        assert plan_cli.chat.plan["id"] == plan.id
        assert plan_cli.chat.plan["status"] == PLAN_STATUS_DRAFT

    def test_saved_draft_pointer_restores_on_resume(self, plan_cli, monkeypatch):
        plan = _enter_reviewing(plan_cli)
        _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.return_value = "save"
        plan_cli._handle_plan_review_panel()

        resumed = CLI(verbose=False, client=MagicMock(), chat_manager=MagicMock())
        resumed.console = MagicMock()
        resumed.chat = plan_cli.chat
        resumed._restore_plan_from_session()

        assert resumed.plan_session.mode == "normal"
        printed = "\n".join(
            getattr(call.args[0], "markup", None) or str(call.args[0])
            for call in resumed.console.print.call_args_list
            if call.args
        )
        assert f"unfinished plan found: {plan.id} (draft, revision 1)" in printed
        assert "Use /plan review to continue it" in printed

    def test_cancel_keeps_draft_file(self, plan_cli, monkeypatch):
        plan = _enter_reviewing(plan_cli)
        _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.return_value = "cancel"

        plan_cli._handle_plan_review_panel()

        assert plan_cli.plan_session.mode == "normal"
        assert plan.path.exists()
        assert read_plan(plan.path).status == PLAN_STATUS_DRAFT
        assert "plan cancelled; draft saved at " in _printed(plan_cli)
        assert plan_cli.chat.plan["id"] == plan.id
        assert plan_cli.chat.plan["status"] == PLAN_STATUS_DRAFT

    def test_redo_returns_to_planning(self, plan_cli, monkeypatch):
        _enter_reviewing(plan_cli)
        _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.return_value = "redo"

        plan_cli._handle_plan_review_panel()

        assert plan_cli.plan_session.mode == "researching"
        assert "keep planning — send a new message to revise the plan." in _printed(plan_cli)

    def test_readonly_policy_prompt_declined_stays_reviewing(self, plan_cli, monkeypatch):
        plan = _enter_reviewing(plan_cli)
        monkeypatch.setitem(cfg, "TOOL_POLICY", "readonly")
        executed = _no_execute(monkeypatch)
        asked = []

        def fake_ask(prompt, **kwargs):
            asked.append(prompt)
            return "n"

        monkeypatch.setattr("yaicli.cli.Prompt.ask", fake_ask)
        plan_cli.printer.ask_plan_decision.side_effect = ["approve", "save"]

        plan_cli._handle_plan_review_panel()

        assert asked and asked[0] == "current TOOL_POLICY=readonly would deny writes; switch to standard?"
        assert not executed
        # Declining the policy switch keeps the plan in REVIEWING until the user
        # picks another action (here: save only).
        assert plan_cli.plan_session.mode == "normal"
        assert read_plan(plan.path).status == PLAN_STATUS_DRAFT
        assert cfg.get("TOOL_POLICY") == "readonly"

    def test_readonly_policy_accepted_switches_to_standard(self, plan_cli, monkeypatch):
        _enter_reviewing(plan_cli)
        monkeypatch.setitem(cfg, "TOOL_POLICY", "readonly")
        executed = _no_execute(monkeypatch)
        monkeypatch.setattr("yaicli.cli.Prompt.ask", lambda prompt, **kwargs: "y")
        plan_cli.printer.ask_plan_decision.return_value = "approve"

        plan_cli._handle_plan_review_panel()

        assert cfg.get("TOOL_POLICY") == "standard"
        assert executed
        assert plan_cli.plan_session.mode == "executing"

    def test_shift_tab_cancels_from_the_modal_panel(self):
        """Shift+Tab inside the modal approval panel == Esc (cancel submission)."""
        import yaicli.printer as printer_module

        bindings = printer_module._plan_decision_bindings()
        by_key = {}
        for binding in bindings.bindings:
            for key in binding.keys:
                by_key[getattr(key, "value", None)] = binding

        assert by_key["escape"].handler is not by_key["s-tab"].handler
        escape_event = MagicMock()
        by_key["escape"].handler(escape_event)
        shift_tab_event = MagicMock()
        by_key["s-tab"].handler(shift_tab_event)
        escape_event.app.exit.assert_called_once_with(result="cancel")
        shift_tab_event.app.exit.assert_called_once_with(result="cancel")


class TestExecutionLoop:
    """The bounded kickoff/continue loop drives todo progress to done or pause."""

    def test_execution_runs_until_done(self, plan_cli, monkeypatch):
        plan = _enter_reviewing(plan_cli)
        _approve(plan_cli)
        turns = []

        def fake_process(self, instruction, images=None):
            turns.append(instruction)
            if len(turns) == 1:
                items = _todo_items(plan_cli, ["completed", "in_progress"])
            else:
                items = _todo_items(plan_cli, ["completed", "completed"])
            result = plan_mode.handle_todo_write(items)
            assert result.get("success") is True, result
            return True

        monkeypatch.setattr(CLI, "_process_user_input", fake_process)

        plan_cli._execute_plan()

        assert turns == [cli_module.PLAN_KICKOFF_INSTRUCTION, cli_module.PLAN_CONTINUE_INSTRUCTION]
        assert "✓ plan done · 2/2 steps" in _printed(plan_cli)
        assert plan_cli.plan_session.mode == "normal"
        assert plan_cli.plan_session.active_plan is None
        assert read_plan(plan.path).status == PLAN_STATUS_DONE

    def test_ctrl_c_pauses_and_resume_continues(self, plan_cli, monkeypatch):
        _enter_reviewing(plan_cli)
        _approve(plan_cli)

        def interrupted(self, instruction, images=None):
            raise KeyboardInterrupt

        monkeypatch.setattr(CLI, "_process_user_input", interrupted)

        plan_cli._execute_plan()

        assert "[plan] execution paused at 0/2 steps · /plan resume to continue · /plan abort to abandon" in _printed(
            plan_cli
        )
        assert plan_cli.plan_session.mode == "normal"
        assert plan_cli.plan_session.active_plan is not None
        assert len(plan_cli.plan_session.todos) == 2

        executed = _no_execute(monkeypatch)
        assert plan_cli._resume_plan_from_disk() is True
        assert executed
        assert plan_cli.plan_session.mode == "executing"

    def test_no_progress_pauses_before_turn_budget(self, plan_cli, monkeypatch):
        _enter_reviewing(plan_cli)
        _approve(plan_cli)
        turns = []

        def idle(self, instruction, images=None):
            turns.append(instruction)
            return True

        monkeypatch.setattr(CLI, "_process_user_input", idle)

        plan_cli._execute_plan()

        assert len(turns) == 2, "two turns without todo progress must stop the loop"
        assert "execution paused at 0/2 steps" in _printed(plan_cli)
        assert plan_cli.plan_session.mode == "normal"

    def test_turn_budget_caps_execution(self, plan_cli, monkeypatch):
        _enter_reviewing(plan_cli)
        _approve(plan_cli)
        monkeypatch.setattr(cli_module, "PLAN_MAX_EXECUTION_TURNS", 1)
        turns = []

        def idle(self, instruction, images=None):
            turns.append(instruction)
            return True

        monkeypatch.setattr(CLI, "_process_user_input", idle)

        plan_cli._execute_plan()

        assert len(turns) == 1
        assert plan_cli.plan_session.mode == "normal"


class TestReplanRevision:
    """Execution -> Shift+Tab revising -> submit revision -> panel -> apply/discard."""

    def _approved_with_progress(self, plan_cli):
        from yaicli import plan_mode

        plan = _enter_reviewing(plan_cli)
        _approve(plan_cli)
        result = plan_mode.handle_todo_write(_todo_items(plan_cli, ["completed", "in_progress"]))
        assert result.get("success") is True, result
        return plan

    def _submit_revision(self, plan_cli, goal="Updated goal", new_step=True):
        from yaicli import plan_mode

        steps = [
            {"id": "S1", "title": "First step", "acceptance": "first acceptance"},
            {"id": "S2", "title": "Second step", "acceptance": "second acceptance"},
        ]
        if new_step:
            steps.append({"id": "S3", "title": "Third step", "acceptance": "third acceptance"})
        result = plan_mode.handle_submit_plan(
            {
                "goal": goal,
                "revision": 2,
                "change_summary": "add a third step",
                "steps": steps,
            }
        )
        assert result.get("success") is True, result
        return result

    def test_apply_revision_updates_plan_in_place_and_resumes(self, plan_cli, monkeypatch):
        plan = self._approved_with_progress(plan_cli)
        plan_cli._toggle_plan_mode()
        assert plan_cli.plan_session.mode == "revising"

        self._submit_revision(plan_cli)
        assert plan_cli.plan_session.mode == "reviewing"
        assert plan_cli.plan_session.diff is not None

        executed = _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.return_value = "approve"

        plan_cli._handle_plan_review_panel()

        assert executed
        printed = _printed(plan_cli)
        assert "✓ revision 2 applied · plan.md updated in place · resuming execution at S2" in printed
        session = plan_cli.plan_session
        assert session.mode == "executing"
        assert session.active_plan.revision == 2
        assert [(todo.id, todo.status) for todo in session.todos] == [
            ("S1", "completed"),
            ("S2", "in_progress"),
            ("S3", "pending"),
        ]
        persisted = read_plan(plan.path)
        assert persisted.revision == 2
        assert persisted.status == PLAN_STATUS_IN_PROGRESS
        # Revision updates the same file in place: no extra plan file appears.
        assert [entry.name for entry in plan.path.parent.iterdir()] == [plan.path.name]

    def test_diff_is_rendered_in_the_panel(self, plan_cli):
        self._approved_with_progress(plan_cli)
        plan_cli._toggle_plan_mode()
        self._submit_revision(plan_cli)
        session = plan_cli.plan_session
        assert session.diff.added and session.diff.added[0].id == "S3"
        session.diff.todo_impact_text = session.diff.todo_impact(session.todos)
        assert session.diff.summary() == "Changes: +1 step  ~0 step  -0 steps"
        plan_cli.printer.ask_plan_decision.return_value = "save"

        plan_cli._handle_plan_review_panel()

        assert plan_cli.printer.show_plan_panel.called
        call = plan_cli.printer.show_plan_panel.call_args
        assert call.kwargs.get("revision") is True
        rendered_diff = call.kwargs.get("diff")
        assert rendered_diff is not None
        assert rendered_diff.summary() == "Changes: +1 step  ~0 step  -0 steps"
        assert rendered_diff.todo_impact_text.startswith("Todo impact:")

    def test_shift_tab_in_reviewing_revision_discards(self, plan_cli, monkeypatch):
        """Shift+Tab while reviewing a revision == Esc: drop it, back to executing."""
        plan = self._approved_with_progress(plan_cli)
        plan_cli._toggle_plan_mode()
        self._submit_revision(plan_cli)
        executed = _no_execute(monkeypatch)

        plan_cli._toggle_plan_mode()

        assert not executed
        assert "revision discarded" in _printed(plan_cli)
        assert plan_cli.plan_session.mode == "executing"
        assert read_plan(plan.path).revision == 1

    def test_discard_revision_returns_to_execution(self, plan_cli, monkeypatch):
        plan = self._approved_with_progress(plan_cli)
        plan_cli._toggle_plan_mode()
        self._submit_revision(plan_cli)

        executed = _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.return_value = "cancel"

        plan_cli._handle_plan_review_panel()

        assert not executed
        assert "revision discarded" in _printed(plan_cli)
        session = plan_cli.plan_session
        assert session.mode == "executing"
        assert session.active_plan.revision == 1
        assert read_plan(plan.path).revision == 1
        assert [(todo.id, todo.status) for todo in session.todos] == [("S1", "completed"), ("S2", "in_progress")]


class TestEditPlanFromPanel:
    """[e]dit opens $EDITOR, re-validates and refreshes the panel."""

    def test_edit_first_plan_reloads_draft(self, plan_cli, monkeypatch, tmp_path):
        from yaicli import plan_mode

        plan = _enter_reviewing(plan_cli)
        _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.side_effect = ["edit", "save"]

        edited_paths = []

        def fake_edit(path):
            edited_paths.append(Path(path))
            text = Path(path).read_text(encoding="utf-8").replace("Execution plan", "Edited plan")
            Path(path).write_text(text, encoding="utf-8")
            return True, ""

        monkeypatch.setattr(plan_mode, "edit_plan_file", fake_edit)

        plan_cli._handle_plan_review_panel()

        assert edited_paths == [plan.path]
        assert plan_cli.printer.show_plan_panel.call_count == 2
        assert read_plan(plan.path).goal == "Edited plan"
        assert plan_cli.plan_session.mode == "normal"

    def test_edit_invalid_file_stays_in_reviewing(self, plan_cli, monkeypatch):
        from yaicli import plan_mode

        _enter_reviewing(plan_cli)
        _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.side_effect = ["edit", "cancel"]
        monkeypatch.setattr(plan_mode, "edit_plan_file", lambda path: (False, "invalid plan file"))

        plan_cli._handle_plan_review_panel()

        printed = _printed(plan_cli)
        assert "invalid plan file:" in printed
        assert plan_cli.printer.show_plan_panel.call_count == 2

    def test_edit_revision_reloads_diff(self, plan_cli, monkeypatch):
        plan = _enter_reviewing(plan_cli)
        _approve(plan_cli)
        result = plan_mode.handle_todo_write(_todo_items(plan_cli, ["completed", "in_progress"]))
        assert result.get("success") is True
        plan_cli._toggle_plan_mode()
        revision = {
            "goal": "Updated goal",
            "revision": 2,
            "change_summary": "add a third step",
            "steps": [
                {"id": "S1", "title": "First step", "acceptance": "first acceptance"},
                {"id": "S2", "title": "Second step", "acceptance": "second acceptance"},
                {"id": "S3", "title": "Third step", "acceptance": "third acceptance"},
            ],
        }
        assert plan_mode.handle_submit_plan(revision).get("success") is True
        _no_execute(monkeypatch)
        plan_cli.printer.ask_plan_decision.side_effect = ["edit", "cancel"]

        def fake_edit(path):
            Path(path).write_text(
                Path(path).read_text(encoding="utf-8").replace("Third step", "Third step edited"),
                encoding="utf-8",
            )
            return True, ""

        monkeypatch.setattr(plan_mode, "edit_plan_file", fake_edit)

        plan_cli._handle_plan_review_panel()

        # Panel call #2 shows the re-parsed draft + recomputed diff (call #1 was
        # the pre-edit draft); the save decision then discards the revision.
        assert plan_cli.printer.show_plan_panel.call_count == 2
        rendered_plan = plan_cli.printer.show_plan_panel.call_args.args[0]
        rendered_diff = plan_cli.printer.show_plan_panel.call_args.kwargs.get("diff")
        assert rendered_plan.steps[2].title == "Third step edited"
        assert rendered_diff is not None
        assert [step.id for step in rendered_diff.added] == ["S3"]
        assert rendered_diff.summary() == "Changes: +1 step  ~0 step  -0 steps"
        assert plan_cli.plan_session.mode == "executing"
        # The hidden editor draft must be cleaned up after re-validation.
        assert not list(plan.path.parent.glob(".*.editor.md"))


class TestDecisionPromptMapping:
    """The modal panel bindings exit with decision words; map them to actions.

    Regression: pressing ``a`` in the real terminal returned ``"approve"`` from the
    prompt_toolkit binding, but the old single-letter mapping turned every result into
    ``cancel`` — approving a plan silently cancelled it and never executed.
    """

    @staticmethod
    def _printer():
        from yaicli.printer import Printer

        return Printer(console=MagicMock(is_terminal=True))

    @pytest.mark.parametrize(
        "binding_result,expected",
        [
            ("approve", "approve"),
            ("edit", "edit"),
            ("redo", "redo"),
            ("save", "save"),
            ("cancel", "cancel"),
            ("a", "approve"),
            ("e", "edit"),
            ("r", "redo"),
            ("s", "save"),
            ("", "cancel"),
        ],
    )
    def test_binding_results_map_to_decisions(self, binding_result, expected, monkeypatch):
        from yaicli import printer as printer_module

        printer = self._printer()
        monkeypatch.setattr(printer_module, "_prompt_function", lambda: (lambda *args, **kwargs: binding_result))
        assert printer.ask_plan_decision() == expected

    def test_approval_panel_approves_and_starts_execution(self, plan_cli, monkeypatch):
        from yaicli import printer as printer_module
        from yaicli.printer import Printer

        plan_cli._toggle_plan_mode()
        _submit(plan_cli)
        executed = _no_execute(monkeypatch)
        plan_cli.printer = Printer(console=MagicMock(is_terminal=True))
        monkeypatch.setattr(printer_module, "_prompt_function", lambda: (lambda *args, **kwargs: "approve"))

        plan_cli._handle_plan_review_panel()

        printed = _printed(plan_cli)
        assert executed, "approving through the real decision prompt must execute"
        assert plan_cli.plan_session.mode == "executing"
        assert "✓ plan approved" in printed
        assert "plan cancelled" not in printed
        assert "[plan] executing approved plan" in printed
