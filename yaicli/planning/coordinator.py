"""Plan application coordination over session, output and turn execution ports."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from rich.markdown import Markdown
from rich.prompt import Prompt

from ..console import get_error_console, safe_text
from ..const import CHAT_MODE, EXEC_MODE
from ..errors import ErrorKind


def _plan_mode_module():
    from . import service

    return service


def _plan_store_module():
    from . import store

    return store


@dataclass
class PlanTurns:
    """The four terminal lifecycle operations needed by plan coordination."""

    process: Callable
    once: Callable
    set_role: Callable
    sync_client: Callable


PLAN_MAX_EXECUTION_TURNS = 20
#: Hidden synthetic instructions that drive the approved plan's execution turns.
PLAN_KICKOFF_INSTRUCTION = (
    "Execute the approved plan now. Use todo_write to mark the current step in_progress, "
    "mark it completed when done and advance the next step. Do not add or remove steps."
)
PLAN_CONTINUE_INSTRUCTION = "Continue executing the approved plan from the current todo state."


class PlanCoordinator:
    """Keep plan business out of the REPL while accepting only its required ports."""

    def __init__(self, config, sessions, state, output, console, printer, turns: PlanTurns):
        self.config = config
        self.sessions = sessions
        self.state = state
        self.output = output
        self.console = console
        self.get_printer = printer
        self.turns = turns
        self.plan_session = None

    def plan_enabled(self) -> bool:
        """Whether persistent plan mode is enabled (``PLAN_ENABLED``; defaults on)."""
        try:
            return bool(self.config.get("PLAN_ENABLED", True))
        except Exception:  # pragma: no cover - config lookups must never break the REPL
            return True

    def get_plan_session(self) -> Any:
        """Return the shared :class:`PlanSession`, configuring it on first use.

        Imports plan_mode/plan_store lazily so a normal (non-plan) run never pays
        those imports, and mirrors the session's mode into the tool schema filter
        and the (lazily created) LLM client.
        """
        session = getattr(self, "plan_session", None)
        if session is not None:
            return session
        plan_mode = _plan_mode_module()
        plan_store = _plan_store_module()
        from ..const import get_config_dir

        session = plan_mode.get_plan_session()
        session.configure(
            plans_root=plan_store.plans_root(str(self.config.get("PLAN_DIR") or ""), get_config_dir()),
            cwd=Path.cwd(),
            model=str(self.config.get("MODEL") or ""),
            session_id=str(getattr(self.sessions.chat, "date", "") or ""),
            max_steps=int(self.config.get("PLAN_MAX_STEPS", 20)),
            keep=int(self.config.get("PLAN_KEEP", 80)),
            allow_readonly_shell=bool(self.config.get("PLAN_ALLOW_READONLY_SHELL", True)),
        )
        self.plan_session = session
        self.sync_plan_tool_mode()
        return session

    def sync_plan_tool_mode(self) -> None:
        """Mirror the plan-session mode into the global tool schema filter."""
        session = getattr(self, "plan_session", None)
        state = getattr(session, "mode", None) if session is not None else None
        if state in ("researching", "revising"):
            target = "plan"
        elif state == "executing":
            target = "execution"
        else:
            target = None
        try:
            from .. import tools as _tools

            setter = getattr(_tools, "set_plan_tool_mode", None)
            if callable(setter):
                setter(target)
        except Exception:  # pragma: no cover - tool plumbing must never break a turn
            pass
        self.turns.sync_client()

    def plan_files_location(self) -> str:
        """Human-readable plans root (``PLAN_DIR`` or ``<config-dir>/plans``)."""
        try:
            configured = str(self.config.get("PLAN_DIR") or "").strip()
            if configured:
                return str(Path(configured).expanduser())
            from ..const import get_config_dir

            return str(get_config_dir() / "plans")
        except Exception:  # pragma: no cover - banner must never break
            return "the config directory"

    def shorten_plan_path(self, path: Any) -> str:
        """Render a plan path with the home directory abbreviated (best-effort)."""
        try:
            return _plan_store_module().shorten_path(path)
        except Exception:  # pragma: no cover
            return str(path)

    def persist_chat_plan(self, data: Any) -> None:
        """Store one session-plan payload on the chat and save it best-effort (K23)."""
        try:
            changed = self.sessions.chat.plan != (data if isinstance(data, dict) else {})
            self.sessions.chat.plan = dict(data) if isinstance(data, dict) else {}
        except Exception:  # pragma: no cover - legacy chat objects
            return
        if self.sessions.is_temp_session:
            return
        try:
            if getattr(self.sessions.chat, "path", None):
                self.sessions.chat.save(self.sessions.chat_history_dir)
        except Exception:  # pragma: no cover - best-effort persistence only
            pass
        if changed:
            self.sessions.checkpoint_reset()

    def sync_chat_plan(self, session: Any = None) -> None:
        """Store the plan pointer/todos in the chat and save it best-effort (K23)."""
        session = session if session is not None else getattr(self, "plan_session", None)
        if session is None:
            return
        try:
            data = session.to_session_dict()
        except Exception:  # pragma: no cover - session serialization must never break a turn
            return
        self.persist_chat_plan(data)

    def toggle_plan_mode(self) -> None:
        """Toggle normal <-> plan mode (``Shift+Tab`` and bare ``/plan``).

        From exec mode this first returns to chat (``/mode`` owns chat/exec).
        REVIEWING cancels the pending submission; researching/revising leaves plan
        mode; a session with an in-progress plan enters revising, otherwise
        exploring. ``PLAN_ENABLED=false`` only prints a one-line notice.
        """
        if not self.plan_enabled():
            self.console.print("plan mode is disabled (PLAN_ENABLED=false)", style="dim")
            return
        session = self.get_plan_session()
        if self.state.current_mode == EXEC_MODE:
            self.state.current_mode = CHAT_MODE
            self.turns.set_role(self.state.init_role)
        if getattr(session, "is_reviewing", False):
            self.cancel_plan_review()
            return
        if getattr(session, "is_plan_mode", False):
            session.cancel_draft()
            self.sync_plan_tool_mode()
            self.sync_chat_plan(session)
            self.console.print("plan mode off", style="dim")
            return
        if getattr(session, "active_plan", None) is not None:
            session.enter_revising()
            self.console.print("[plan] revising (read-only) …", style="dim")
        else:
            session.enter_researching()
            self.console.print("[plan] exploring (read-only) …", style="dim")
        self.console.print("plan mode · read-only", style="dim")
        self.sync_plan_tool_mode()
        self.sync_chat_plan(session)

    @staticmethod
    def discard_revision(session: Any) -> None:
        """Drop the pending revision draft and return to execution (if any)."""
        plan_mode = _plan_mode_module()
        session.cancel_draft()
        if getattr(session, "active_plan", None) is not None:
            try:
                plan_mode.resume_plan(session)
            except Exception:  # pragma: no cover - state machine handles this
                pass

    def cancel_plan_review(self) -> None:
        """Cancel a pending plan submission without approving it."""
        session = getattr(self, "plan_session", None)
        if session is None:  # pragma: no cover - defensive
            return
        if getattr(session, "revision_base", None) is not None:
            self.discard_revision(session)
            self.sync_plan_tool_mode()
            self.sync_chat_plan(session)
            self.console.print("revision discarded", style="dim")
            return
        plan = getattr(session, "draft_plan", None)
        path = getattr(plan, "path", None) if plan is not None else None
        # Capture the draft pointer before cancel_draft() clears it: a saved draft
        # is still an unfinished plan, so --resume must be able to advertise it.
        try:
            snapshot = session.to_session_dict()
        except Exception:  # pragma: no cover - serialization must never break exit
            snapshot = {}
        session.cancel_draft()
        self.sync_plan_tool_mode()
        self.persist_chat_plan(snapshot)
        if path:
            self.console.print(f"plan cancelled; draft saved at {safe_text(self.shorten_plan_path(path))}", style="dim")
        else:  # pragma: no cover - a submitted plan always has a path
            self.console.print("plan cancelled", style="dim")

    def warn_plan_reply_without_plan(self) -> None:
        """One-line hint when a plan-mode turn answered in text without using tools.

        A plan-mode request is not a normal chat request: the model is supposed to
        research with the read-only tools and finish with ``submit_plan``. Weak or
        prompt-dropping provider paths can still produce a plain answer (e.g. code
        in the terminal); surface that instead of pretending a plan exists.
        """
        session = getattr(self, "plan_session", None)
        if session is None or not getattr(session, "is_plan_mode", False):
            return
        if self.output.result.tool_calls:
            return
        if self.state.machine_output:
            return
        mode = str(getattr(session, "mode", ""))
        try:
            _plan_mode_module().plan_audit("no_plan_submitted", mode=mode)
        except Exception:  # pragma: no cover - audit is best-effort
            pass
        self.console.print(
            "[plan] no plan submitted — this turn answered in text without using tools; "
            "ask again to research and submit a plan, or press Shift+Tab to leave plan mode.",
            style="yellow",
        )

    def after_plan_turn(self) -> None:
        """Hook run after each REPL turn: persist plan state and open the panel.

        Headless ``--plan`` runs also call this to persist the submitted plan, but
        they never open the approval panel (the caller only saves the draft).
        """
        session = getattr(self, "plan_session", None)
        if session is None:
            return
        self.sync_chat_plan(session)
        if getattr(session, "mode", None) != "reviewing":
            return
        if self.state.plan_requested:
            return
        if not self.state.interactive:
            return
        self.handle_plan_review_panel()

    @staticmethod
    def next_todo_id(session: Any) -> str:
        """First todo that is not completed (``S1`` fallback); used in re-plan output."""
        for todo in getattr(session, "todos", None) or []:
            if getattr(todo, "status", "") != "completed":
                return str(getattr(todo, "id", "") or "")
        plan = getattr(session, "active_plan", None) or getattr(session, "draft_plan", None)
        steps = getattr(plan, "steps", None) or []
        return str(getattr(steps[0], "id", "")) if steps else ""

    @staticmethod
    def attach_todo_impact(session: Any) -> None:
        """Attach the todo-impact text to the session diff for the printer (K23)."""
        diff = getattr(session, "diff", None)
        if diff is None or getattr(diff, "todo_impact_text", ""):
            return
        try:
            diff.todo_impact_text = diff.todo_impact(session.todos)
        except Exception:  # pragma: no cover - display detail only
            pass

    def confirm_plan_approval_policy(self, session: Any) -> bool:
        """Ask before executing an approved plan when ``TOOL_POLICY=readonly``."""
        try:
            policy = str(self.config.get("TOOL_POLICY", "standard") or "").lower()
        except Exception:  # pragma: no cover
            policy = "standard"
        if policy != "readonly":
            return True
        try:
            answer = Prompt.ask(
                "current TOOL_POLICY=readonly would deny writes; switch to standard?",
                default="n",
            )
        except (KeyboardInterrupt, EOFError):
            return False
        if str(answer or "").strip().lower() in ("y", "yes"):
            try:
                self.config["TOOL_POLICY"] = "standard"
            except Exception:  # pragma: no cover - read-only config objects
                pass
            return True
        return False

    def edit_plan_from_panel(self, session: Any, plan: Any) -> bool:
        """Open ``$EDITOR`` on the draft plan, re-validate it and refresh the panel."""
        plan_mode = _plan_mode_module()
        plan_store = _plan_store_module()
        target = None
        try:
            if getattr(session, "revision_base", None) is not None:
                target = plan_mode.write_plan_editor_draft(session, plan)
            else:
                target = getattr(plan, "path", None)
            if target is None:  # pragma: no cover - defensive
                self.console.print("cannot open editor; plan unchanged", style="yellow")
                return False
            ok, error = plan_mode.edit_plan_file(Path(target))
        except Exception as exc:  # pragma: no cover - editor failures are best-effort
            self.console.print(f"cannot open editor; plan unchanged: {safe_text(exc)}", style="yellow")
            return False
        try:
            if not ok:
                self.console.print(f"invalid plan file: {safe_text(target)}: {safe_text(error)}", style="red")
                return False
            parsed = plan_store.read_plan(Path(target))
            if getattr(session, "revision_base", None) is not None:
                parsed.path = getattr(plan, "path", None)
                session.draft_plan = parsed
                session.diff = plan_mode.diff_plans(session.revision_base, parsed)
            else:
                session.draft_plan = parsed
        except Exception as exc:
            self.console.print(f"invalid plan file: {safe_text(target)}: {safe_text(exc)}", style="red")
            return False
        finally:
            if getattr(session, "revision_base", None) is not None:
                try:
                    Path(target).unlink(missing_ok=True)
                except Exception:  # pragma: no cover - temp cleanup only
                    pass
        self.sync_chat_plan(session)
        return True

    def handle_plan_review_panel(self) -> None:
        """Show the plan/approval panel and act on the user's decision (K23)."""
        session = self.get_plan_session()
        plan_mode = _plan_mode_module()
        while True:
            plan = getattr(session, "draft_plan", None)
            if plan is None:  # pragma: no cover - defensive
                session.cancel_draft()
                self.sync_plan_tool_mode()
                return
            is_revision = getattr(session, "revision_base", None) is not None
            self.attach_todo_impact(session)
            try:
                self.get_printer().show_plan_panel(plan, revision=is_revision, diff=getattr(session, "diff", None))
            except Exception:  # pragma: no cover - display must never block approval
                pass
            decision = self.get_printer().ask_plan_decision(revision=is_revision)

            if decision == "edit":
                self.edit_plan_from_panel(session, plan)
                continue
            if decision == "redo":
                session.cancel_draft()
                if getattr(session, "active_plan", None) is not None:
                    session.enter_revising()
                else:
                    session.enter_researching()
                self.sync_plan_tool_mode()
                self.sync_chat_plan(session)
                self.console.print("[plan] keep planning — send a new message to revise the plan.", style="dim")
                return
            if decision == "approve":
                if not self.confirm_plan_approval_policy(session):
                    continue  # stay in REVIEWING
                if is_revision:
                    result = plan_mode.apply_revision(session)
                    revision = result.get("revision") if isinstance(result, dict) else None
                    if revision is None:
                        active = getattr(session, "active_plan", None)
                        revision = getattr(active, "revision", getattr(plan, "revision", 0))
                    resume_at = result.get("resuming_at", "") if isinstance(result, dict) else ""
                    if not resume_at:
                        resume_at = self.next_todo_id(session)
                    self.console.print(
                        f"✓ revision {safe_text(revision)} applied · plan.md updated in place · "
                        f"resuming execution at {safe_text(resume_at)}",
                        style="green",
                    )
                else:
                    plan_mode.approve_new_plan(session)
                    step_count = len(getattr(plan, "steps", None) or [])
                    self.console.print(
                        f"✓ plan approved · exiting plan mode · todo seeded ({step_count} steps)",
                        style="green",
                    )
                self.sync_chat_plan(session)
                self.sync_plan_tool_mode()
                try:
                    step_count = len(getattr(session, "todos", None) or [])
                except Exception:  # pragma: no cover - defensive
                    step_count = 0
                self.console.print(
                    f"[plan] executing approved plan ({step_count} steps)… todo progress below; Ctrl-C pauses.",
                    style="dim",
                )
                self.execute_plan()
                return

            # save / cancel (and any unknown decision)
            path = getattr(plan, "path", None)
            if is_revision:
                self.discard_revision(session)
                self.sync_plan_tool_mode()
                self.sync_chat_plan(session)
                self.console.print("revision discarded", style="dim")
                return
            # A saved (or cancelled) first plan keeps its draft file: capture the
            # pointer before cancel_draft() clears it so --resume can hint it.
            try:
                snapshot = session.to_session_dict()
            except Exception:  # pragma: no cover - serialization must never break exit
                snapshot = {}
            session.cancel_draft()
            self.sync_plan_tool_mode()
            self.persist_chat_plan(snapshot)
            path_text = safe_text(self.shorten_plan_path(path)) if path else "(unknown path)"
            if decision == "save":
                self.console.print(f"✓ saved as draft ({path_text}) · exit plan mode", style="dim")
                self.console.print(
                    "Use /plan resume to review and execute this plan later.",
                    style="dim",
                )
            else:
                self.console.print(f"plan cancelled; draft saved at {path_text}", style="dim")
                self.console.print(
                    "Use /plan resume to review and execute this plan later.",
                    style="dim",
                )
            return

    def pause_plan_execution(self, plan_mode: Any, session: Any) -> None:
        """Pause the execution loop, keep the todos and print the resume hint."""
        try:
            plan_mode.pause_plan(session)
        except Exception:  # pragma: no cover - state machine handles this
            pass
        self.sync_plan_tool_mode()
        self.sync_chat_plan(session)
        try:
            completed, total = session.todo_progress()
        except Exception:  # pragma: no cover
            completed = total = 0
        self.console.print(
            f"[plan] execution paused at {completed}/{total} steps · /plan resume to continue · /plan abort to abandon",
            style="dim",
        )

    def execute_plan(self) -> None:
        """Run the approved plan with bounded synthetic turns until all todos are done.

        Every turn is a hidden instruction (kickoff then continue); the model drives
        progress via ``todo_write``. Ctrl-C pauses (todos kept); two turns without
        todo progress also pause instead of burning the whole turn budget.
        """
        session = getattr(self, "plan_session", None)
        if session is None:  # pragma: no cover - defensive
            return
        plan_mode = _plan_mode_module()
        turns = no_progress = 0
        try:
            while turns < PLAN_MAX_EXECUTION_TURNS and not session.all_todos_completed():
                before = session.todo_snapshot()
                instruction = PLAN_KICKOFF_INSTRUCTION if turns == 0 else PLAN_CONTINUE_INSTRUCTION
                try:
                    self.turns.process(instruction)
                except KeyboardInterrupt:
                    raise
                turns += 1
                if session.todo_snapshot() == before and not session.all_todos_completed():
                    no_progress += 1
                else:
                    no_progress = 0
                if no_progress >= 2:
                    break
            if session.all_todos_completed():
                try:
                    completed, total = session.todo_progress()
                except Exception:  # pragma: no cover
                    completed = total = 0
                plan_mode.finish_plan(session)
                self.sync_plan_tool_mode()
                self.console.print(f"✓ plan done · {completed}/{total} steps", style="green")
                self.sync_chat_plan(session)
            else:
                self.pause_plan_execution(plan_mode, session)
        except KeyboardInterrupt:
            self.pause_plan_execution(plan_mode, session)

    def run_headless_plan(self, user_input: str) -> None:
        """One-shot ``--plan`` run: explore read-only, save the submitted plan, exit.

        Never executes anything: the plan is written in ``draft`` status and the
        JSON/text output describes it. A model that never calls ``submit_plan``
        ends with ``plan_not_submitted`` (exit 1).
        """
        plan_mode = _plan_mode_module()
        session = self.get_plan_session()
        session.enter_researching()
        self.sync_plan_tool_mode()
        self.output.emit_event({"type": "plan_start"})
        try:
            self.turns.once(user_input)
        finally:
            self.after_plan_turn()
        plan = getattr(session, "draft_plan", None)
        if plan is None:
            self.output.result.had_error = True
            self.output.result.error_kind = ErrorKind.PLAN_NOT_SUBMITTED
            self.output.result.error_message = "plan mode ended: model did not submit a plan"
            get_error_console().print(self.output.result.error_message, style="red")
        else:
            self.output.plan_output = plan
            try:
                plan_mode.plan_audit("headless_saved", plan_id=plan.id, revision=plan.revision)
            except Exception:  # pragma: no cover - audit is best-effort
                pass
            self.output.emit_event(
                {
                    "type": "plan_ready",
                    "steps": len(getattr(plan, "steps", None) or []),
                    "path": str(getattr(plan, "path", "") or ""),
                    "revision": getattr(plan, "revision", 1),
                }
            )
            if self.state.output_format == "text" and not self.state.quiet:
                try:
                    markdown = plan.to_markdown()
                except Exception:  # pragma: no cover - rendering must never break the run
                    markdown = ""
                if markdown:
                    sys.stdout.write(markdown.rstrip("\n") + "\n")
                    sys.stdout.flush()
        session.cancel_draft()
        self.sync_plan_tool_mode()
        self.output.finalize_headless()

    def plan_store_context(self) -> tuple:
        """Return ``(plan_store, plans_root, project_key, cwd)`` for disk access."""
        plan_store = _plan_store_module()
        from ..const import get_config_dir

        root = plan_store.plans_root(str(self.config.get("PLAN_DIR") or ""), get_config_dir())
        cwd = Path.cwd()
        return plan_store, root, plan_store.project_key(cwd), cwd

    def find_plan_from_disk(self, plan_id: Optional[str] = None) -> Any:
        """Find the current-session plan or a plan file by id (``None`` when missing)."""
        session = getattr(self, "plan_session", None)
        plan_store, root, project_key, _ = self.plan_store_context()
        if not plan_id:
            if session is not None:
                plan = getattr(session, "active_plan", None) or getattr(session, "draft_plan", None)
                if plan is not None:
                    return plan
            try:
                return plan_store.find_latest_unfinished(root, project_key)
            except Exception:  # pragma: no cover - corrupt store degrades to "not found"
                return None
        try:
            plan = plan_store.find_plan(root, plan_id, project_key=project_key)
            if plan is None:
                plan = plan_store.find_plan(root, plan_id)  # --all-style cross-project lookup
            return plan
        except Exception:  # pragma: no cover - corrupt plan files are skipped
            return None

    def list_plans_from_disk(self, all_projects: bool = False) -> list:
        """List this project's plans (or all projects') sorted by ``updated`` desc."""
        plan_store, root, project_key, _ = self.plan_store_context()
        try:
            return plan_store.list_plans(root, None if all_projects else project_key)
        except Exception:  # pragma: no cover - listing must never crash the REPL
            return []

    def clear_plans_from_disk(self, done_only: bool = False) -> list:
        """Delete plan files of this project (terminal ones only when ``done_only``)."""
        plan_store, root, project_key, _ = self.plan_store_context()
        try:
            return plan_store.clear_plans(root, project_key, done_only=done_only)
        except Exception:  # pragma: no cover
            return []

    def review_plan_from_disk(self, plan_id: Optional[str] = None) -> bool:
        """Open a draft plan from disk in the approval panel (non-drafts are printed)."""
        session = self.get_plan_session()
        plan_mode = _plan_mode_module()
        plan = self.find_plan_from_disk(plan_id)
        if plan is None:
            if plan_id:
                self.console.print(f"plan not found: {safe_text(plan_id)}", style="yellow")
            else:
                self.console.print("no plan in this session", style="yellow")
            return False
        if getattr(plan, "status", None) != "draft":
            self.console.print(Markdown(plan.to_markdown(), code_theme=self.config["CODE_THEME"]))
            return True
        session.active_plan = None
        session.todos = []
        session.revision_base = None
        session.diff = None
        session.draft_plan = plan
        try:
            session.mode = plan_mode.PlanMode.REVIEWING
        except Exception:  # pragma: no cover - mode is a plain string attribute too
            session.mode = "reviewing"
        self.sync_chat_plan(session)
        self.handle_plan_review_panel()
        return True

    def resume_plan_from_disk(self, plan_id: Optional[str] = None) -> bool:
        """Resume a draft (panel) or in-progress (execution) plan from disk."""
        session = self.get_plan_session()
        plan_mode = _plan_mode_module()
        plan = self.find_plan_from_disk(plan_id)
        if plan is None:
            if plan_id:
                self.console.print(f"plan not found: {safe_text(plan_id)}", style="yellow")
            else:
                self.console.print("no plan in this session", style="yellow")
            return False
        status = str(getattr(plan, "status", "") or "")
        if status == "draft":
            return self.review_plan_from_disk(getattr(plan, "id", None))
        if status != "in-progress":
            self.console.print(
                f"plan {safe_text(getattr(plan, 'id', ''))} is {safe_text(status)}; nothing to resume",
                style="yellow",
            )
            return True
        plan_session_id = str(getattr(plan, "session_id", "") or "")
        chat_session_id = str(getattr(self.sessions.chat, "date", "") or "")
        if plan_session_id and chat_session_id and plan_session_id != chat_session_id:
            self.console.print("plan is already in progress in another session", style="yellow")
            return False
        current = getattr(session, "active_plan", None)
        if current is None or getattr(current, "id", None) != getattr(plan, "id", None):
            session.active_plan = plan
            try:
                session.todos = plan_mode.seed_todos(plan)
            except Exception:  # pragma: no cover - state machine handles todos
                session.todos = []
        try:
            resumed = plan_mode.resume_plan(session)
        except Exception:  # pragma: no cover
            resumed = False
        if not resumed:
            self.console.print("plan is already in progress in another session", style="yellow")
            return False
        self.sync_plan_tool_mode()
        self.sync_chat_plan(session)
        self.execute_plan()
        return True

    def prepare_plan_task(self, task: str) -> Optional[str]:
        """Enter plan mode for ``/plan <task>`` and return the task as the next turn."""
        if not self.plan_enabled():
            self.console.print("plan mode is disabled (PLAN_ENABLED=false)", style="dim")
            return None
        session = self.get_plan_session()
        if getattr(session, "is_reviewing", False):
            self.console.print("a plan is waiting for review; approve or cancel it first", style="yellow")
            return None
        if not getattr(session, "is_plan_mode", False):
            self.toggle_plan_mode()
        return task

    def abort_current_plan(self) -> bool:
        """Abort the active plan (status aborted, todos cleared); False when none."""
        session = getattr(self, "plan_session", None)
        if session is None:
            return False
        if getattr(session, "active_plan", None) is None:
            return False
        plan_mode = _plan_mode_module()
        try:
            plan_mode.abort_plan(session)
        except Exception as exc:  # pragma: no cover - state machine should not fail
            self.console.print(f"failed to abort plan: {safe_text(exc)}", style="red")
            return False
        self.sync_plan_tool_mode()
        self.sync_chat_plan(session)
        self.console.print("plan aborted · todos cleared", style="green")
        return True

    def edit_current_plan(self) -> Optional[bool]:
        """Edit the current plan file in ``$EDITOR``; ``None`` = no plan in session."""
        session = self.get_plan_session()
        plan_mode = _plan_mode_module()
        plan_store = _plan_store_module()
        plan = (
            getattr(session, "draft_plan", None) or getattr(session, "active_plan", None) or self.find_plan_from_disk()
        )
        if plan is None:
            return None
        path = getattr(plan, "path", None)
        if path is None:  # pragma: no cover - a persisted plan always has a path
            return False
        try:
            ok, error = plan_mode.edit_plan_file(path)
        except Exception as exc:  # pragma: no cover - editor failures are best-effort
            self.console.print(f"cannot open editor; plan unchanged: {safe_text(exc)}", style="yellow")
            return False
        if not ok:
            self.console.print(f"invalid plan file: {safe_text(path)}: {safe_text(error)}", style="red")
            return False
        if getattr(session, "draft_plan", None) is not None:
            try:
                session.draft_plan = plan_store.read_plan(path)
            except Exception as exc:
                self.console.print(f"invalid plan file: {safe_text(path)}: {safe_text(exc)}", style="red")
                return False
            self.sync_chat_plan(session)
        return True

    def restore_plan_from_session(self) -> None:
        """Restore the plan pointer of a resumed/loaded chat (always in NORMAL mode).

        ``--resume`` never re-enters plan mode: an unfinished plan only prints a
        two-line hint telling the user which explicit command continues it. Broken
        or stale pointers are dropped with one stderr notice.
        """
        plan_data = getattr(self.sessions.chat, "plan", None)
        if not isinstance(plan_data, dict) or not plan_data:
            return
        session = self.get_plan_session()
        plan_mode = _plan_mode_module()
        _, root, _, cwd = self.plan_store_context()
        try:
            detail = session.restore_from_session(
                plan_data,
                session_id=str(getattr(self.sessions.chat, "date", "") or ""),
                plans_root=root,
                cwd=cwd,
            )
        except Exception:  # pragma: no cover - restore is defensive by contract
            detail = "saved plan not found/inconsistent; starting in normal mode"
        if detail is not None:
            get_error_console().print(str(detail), style="yellow")
            try:
                self.sessions.chat.plan = {}
            except Exception:  # pragma: no cover - legacy chat objects
                pass
            session.reset()
            self.sync_plan_tool_mode()
            return
        plan = getattr(session, "active_plan", None) or getattr(session, "draft_plan", None)
        # Restoring never enables plan mode; tool filtering stays in normal mode.
        self.sync_plan_tool_mode()
        self.sync_chat_plan(session)
        if plan is None:
            return
        try:
            plan_mode.plan_audit("resume_hint", plan_id=plan.id, status=plan.status)
        except Exception:  # pragma: no cover - audit is best-effort
            pass
        if getattr(plan, "status", "") == "draft":
            self.console.print(
                f"  ⚠ unfinished plan found: {safe_text(plan.id)} (draft, revision {plan.revision})",
                style="yellow",
            )
            self.console.print("  Use /plan review to continue it, or /plan list to see all plans.", style="dim")
        else:
            self.console.print(
                f"  ⚠ unfinished plan found: {safe_text(plan.id)} (in-progress, revision {plan.revision})",
                style="yellow",
            )
            self.console.print("  Use /plan resume to continue it, or /plan list to see all plans.", style="dim")
