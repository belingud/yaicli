"""Plan command presentation over the explicit coordinator."""

from typing import Optional, Union

from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.table import Table

from ..console import safe_text
from ..const import CMD_PLAN


class PlanCommands:
    def __init__(self, plans, console, config):
        self.plans = plans
        self.console = console
        self.config = config

    def _plan_enabled(self) -> bool:
        """Whether persistent plan mode is enabled (``PLAN_ENABLED``; defaults on)."""
        try:
            return bool(self.config.get("PLAN_ENABLED", True))
        except Exception:  # pragma: no cover - config lookups must never break a command
            return True

    def _print_plan_disabled(self) -> None:
        """One-line notice used by /plan and /todo when the feature is disabled."""
        self.console.print("plan mode is disabled (PLAN_ENABLED=false)", style="dim")

    @staticmethod
    def _truncate_cell(value, limit: int = 48) -> str:
        """Bound a table cell width (Rich tables must stay readable in a terminal)."""
        text = str(value or "")
        return text if len(text) <= limit else text[: max(limit - 1, 0)] + "…"

    def _handle_plan_list(self, argument: str) -> None:
        """``/plan list [--all]``: ID / STATUS / REV / UPDATED / GOAL table."""
        show_all = "--all" in argument.lower().split()
        plans = self.plans.list_plans_from_disk(all_projects=show_all)
        if not plans:
            self.console.print("no plans yet", style="yellow")
            return
        title = "Plans (all projects)" if show_all else "Plans"
        table = Table(title=title)
        table.add_column("ID", no_wrap=True)
        table.add_column("STATUS")
        table.add_column("REV", justify="right")
        table.add_column("UPDATED")
        table.add_column("GOAL", overflow="fold")
        for plan in plans:
            table.add_row(
                safe_text(self._truncate_cell(getattr(plan, "id", ""), 40)),
                safe_text(str(getattr(plan, "status", "") or "")),
                str(getattr(plan, "revision", "")),
                safe_text(self._truncate_cell(getattr(plan, "updated", ""), 25)),
                safe_text(self._truncate_cell(getattr(plan, "goal", ""), 48)),
            )
        self.console.print(table)

    def _handle_plan_show(self, plan_id: Optional[str]) -> None:
        """``/plan show [id]``: render the plan markdown (or a not-found notice)."""
        plan = self.plans.find_plan_from_disk(plan_id)
        if plan is None:
            if plan_id:
                self.console.print(f"plan not found: {safe_text(plan_id)}", style="yellow")
            else:
                self.console.print("no plan in this session", style="yellow")
            return
        self.console.print(Markdown(plan.to_markdown(), code_theme=self.config["CODE_THEME"]))

    def _handle_plan_clear(self, argument: str) -> None:
        """``/plan clear --done|--all``: confirmed cleanup of this project's plans."""
        tokens = [token.lower() for token in argument.split()]
        done_only = "--done" in tokens
        clear_all = "--all" in tokens
        if not done_only and not clear_all:
            self.console.print(f"Usage: {CMD_PLAN} clear --done|--all", style="yellow")
            return
        if not self.plans.state.interactive:
            self.console.print("plan clear needs an interactive confirmation", style="yellow")
            return
        scope = "finished" if done_only else "all"
        try:
            answer = Prompt.ask(f"Delete {scope} plan files of this project?", default="n")
        except (KeyboardInterrupt, EOFError):
            return
        if str(answer or "").strip().lower() not in ("y", "yes"):
            self.console.print("plan clear cancelled", style="dim")
            return
        removed = self.plans.clear_plans_from_disk(done_only=done_only)
        self.console.print(f"cleared {len(removed)} plan file(s)", style="green")

    def _handle_plan_abort(self) -> None:
        """``/plan abort``: confirmed abort of the active plan (todos cleared)."""
        session = self.plans.get_plan_session()
        if getattr(session, "active_plan", None) is None:
            self.console.print("no plan in this session", style="yellow")
            return
        if not self.plans.state.interactive:
            self.console.print("plan abort needs an interactive confirmation", style="yellow")
            return
        try:
            answer = Prompt.ask("Abort the active plan? This clears its todos.", default="n")
        except (KeyboardInterrupt, EOFError):
            return
        if str(answer or "").strip().lower() not in ("y", "yes"):
            self.console.print("plan abort cancelled", style="dim")
            return
        self.plans.abort_current_plan()

    def handle_plan(self, command_input: str = "") -> Union[bool, str]:
        """Handle ``/plan [task|list|show|edit|review|resume|clear|abort]``.

        With no argument it toggles plan mode (same as Shift+Tab). A non-known
        subcommand is treated as a planning task: plan mode is entered and the task
        text is returned so the REPL sends it as the next normal turn.

        Args:
            command_input: the raw ``/plan ...`` line typed by the user

        Returns:
            True to continue the REPL, or the task string to process as a turn.
        """
        console = self.console
        raw = command_input.strip()
        parts = raw.split(maxsplit=1)
        rest = parts[1].strip() if len(parts) > 1 else ""
        if not self._plan_enabled():
            self._print_plan_disabled()
            return True
        if not rest:
            self.plans.toggle_plan_mode()
            return True
        sub_parts = rest.split(maxsplit=1)
        subcommand = sub_parts[0].lower()
        argument = sub_parts[1].strip() if len(sub_parts) > 1 else ""

        if subcommand == "list":
            self._handle_plan_list(argument)
            return True
        if subcommand == "show":
            self._handle_plan_show(argument or None)
            return True
        if subcommand == "edit":
            result = self.plans.edit_current_plan()
            if result is None:
                console.print("no plan in this session", style="yellow")
            return True
        if subcommand == "review":
            self.plans.review_plan_from_disk(argument or None)
            return True
        if subcommand == "resume":
            self.plans.resume_plan_from_disk(argument or None)
            return True
        if subcommand == "clear":
            self._handle_plan_clear(argument)
            return True
        if subcommand == "abort":
            self._handle_plan_abort()
            return True

        # Anything else is a planning task: enter plan mode, then send it as a turn.
        prepared = self.plans.prepare_plan_task(rest)
        if prepared is None:
            return True
        return prepared

    def handle_todo(self) -> bool:
        """Handle ``/todo``: show the current plan's todo table and status line.

        Returns:
            True to continue the REPL loop
        """
        console = self.console
        if not self._plan_enabled():
            self._print_plan_disabled()
            return True
        session = self.plans.get_plan_session()
        plan = getattr(session, "active_plan", None) or getattr(session, "draft_plan", None)
        if plan is None:
            console.print("no plan in this session", style="yellow")
            return True
        todos = list(getattr(session, "todos", None) or [])
        table = Table(title="Plan todos")
        table.add_column("#", justify="right")
        table.add_column("ID")
        table.add_column("STATUS")
        table.add_column("STEP", overflow="fold")
        if todos:
            for index, todo in enumerate(todos, start=1):
                status = str(getattr(todo, "status", "") or "")
                content = str(getattr(todo, "content", "") or "")
                reason = str(getattr(todo, "reason", "") or "")
                if status == "blocked" and reason:
                    content = f"{content} (blocked: {reason})"
                table.add_row(
                    str(index),
                    safe_text(self._truncate_cell(getattr(todo, "id", ""), 12)),
                    safe_text(status),
                    safe_text(self._truncate_cell(content, 72)),
                )
        else:
            # A draft has no todo state yet: show its steps as pending.
            for index, step in enumerate(getattr(plan, "steps", None) or [], start=1):
                table.add_row(
                    str(index),
                    safe_text(self._truncate_cell(getattr(step, "id", ""), 12)),
                    "pending",
                    safe_text(self._truncate_cell(getattr(step, "title", ""), 72)),
                )
        console.print(table)
        plan_id = safe_text(getattr(plan, "id", ""))
        status = safe_text(str(getattr(plan, "status", "") or ""))
        console.print(f"plan: {plan_id} · {status} · revision {getattr(plan, 'revision', '')}")
        return True
