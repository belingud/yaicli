import subprocess
import sys
import time
import traceback
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from .application.output import TOOL_DENIED_MARKERS as TOOL_DENIED_MARKERS
from .application.output import MachineOutput
from .application.session import SessionController
from .application.state import RunState
from .chat import Chat, FileChatManager, resolve_default_chat_dir
from .cmd_handler import COMMAND_INFO, CmdHandler
from .config import cfg
from .console import get_console, get_error_console, safe_text, untrusted_text
from .const import (
    CHAT_MODE,
    CMD_PLAN,
    CONFIG_PATH,
    DEFAULT_OS_NAME,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_SHELL_NAME,
    EXEC_MODE,
    HISTORY_FILE,
    NO_VISION_PROVIDERS,
    TEMP_MODE,
    DefaultRoleNames,
)
from .context import ContextManager, ctx_mgr
from .errors import (
    EXIT_OK,
    ErrorKind,
    classify_exception,
)
from .exceptions import ChatSaveError, YaicliError
from .printer import Printer
from .project_context import load_project_context
from .role import Role, RoleManager, role_mgr
from .runtime import SessionContext, bind_config
from .schemas import ChatMessage, ImageData, ToolPolicy
from .tokens import (
    estimate_context_usage,
    resolve_context_budget,
    trim_messages_to_budget,
    trim_oldest_group,
)
from .tools.approval import ToolApprovalManager
from .utils import detect_os, detect_shell, filter_command

#: Lazily imported prompt_toolkit / LLM-client names (K08).
#:
#: They stay module attributes so the existing test seams
#: ``patch("yaicli.cli.PromptSession")`` / ``patch("yaicli.cli.LLMClient")`` keep working, while
#: one-shot/headless runs never pay the prompt_toolkit import and the REPL never pays the provider
#: SDK import at startup.
PromptSession = None  # type: ignore[assignment]
prompt = None  # type: ignore[assignment]
AtPathCompleter = None  # type: ignore[assignment]
ReplCompleter = None  # type: ignore[assignment]
LimitedFileHistory = None  # type: ignore[assignment]
LLMClient = None  # type: ignore[assignment]


def _prompt_session_class() -> Any:
    """Import prompt_toolkit's ``PromptSession`` on first REPL use (patchable seam)."""
    global PromptSession
    if PromptSession is None:
        from prompt_toolkit import PromptSession as _PromptSession

        PromptSession = _PromptSession
    return PromptSession


def _prompt_function() -> Any:
    """Import prompt_toolkit's one-line ``prompt`` on first edit use (patchable seam)."""
    global prompt
    if prompt is None:
        from prompt_toolkit import prompt as _prompt

        prompt = _prompt
    return prompt


def _at_path_completer_class() -> Any:
    """Import the ``@path`` completer lazily (it needs prompt_toolkit)."""
    global AtPathCompleter
    if AtPathCompleter is None:
        from .completer import AtPathCompleter as _AtPathCompleter

        AtPathCompleter = _AtPathCompleter
    return AtPathCompleter


def _repl_completer_class() -> Any:
    """Import the composite REPL completer (slash commands + ``@path``) lazily."""
    global ReplCompleter
    if ReplCompleter is None:
        from .completer import ReplCompleter as _ReplCompleter

        ReplCompleter = _ReplCompleter
    return ReplCompleter


def _limited_history_class() -> Any:
    """Import the file-backed prompt history lazily (it needs prompt_toolkit)."""
    global LimitedFileHistory
    if LimitedFileHistory is None:
        from .history import LimitedFileHistory as _LimitedFileHistory

        LimitedFileHistory = _LimitedFileHistory
    return LimitedFileHistory


def _llm_client_class() -> Any:
    """Import ``LLMClient`` on first use so REPL startup skips the provider SDK import (K08)."""
    global LLMClient
    if LLMClient is None:
        from .llms import LLMClient as _LLMClient

        LLMClient = _LLMClient
    return LLMClient


def _plan_mode_module() -> Any:
    """Import the plan-mode state machine on first use (K23; normal path stays import-free)."""
    from .planning import service

    return service


def _plan_store_module() -> Any:
    """Import the stdlib-only plan store on first use (K23)."""
    from .planning import store

    return store


OUTPUT_FORMATS = ("text", "json", "stream-json")
#: Content of the in-band tool result the client appends when a tool call is denied.

#: v0.24 K23: bounded plan-execution loop (turns that may make no todo progress).
PLAN_MAX_EXECUTION_TURNS = 20
#: Hidden synthetic instructions that drive the approved plan's execution turns.
PLAN_KICKOFF_INSTRUCTION = (
    "Execute the approved plan now. Use todo_write to mark the current step in_progress, "
    "mark it completed when done and advance the next step. Do not add or remove steps."
)
PLAN_CONTINUE_INSTRUCTION = "Continue executing the approved plan from the current todo state."

#: Ctrl-C twice within this many seconds exits the REPL (a single press only clears
#: the current input line / cancels the current turn). Matches common shell/REPL UX.
DOUBLE_CTRL_C_WINDOW_SECONDS = 2.0


class CLI:
    __slots__ = (
        "verbose",
        "runtime",
        # ----- v0.19 headless state contract (public; entry.py maps it) -----
        #: True when a human terminal UI is available (TTY stdin+stdout, not -p).
        #: Process exit code resolved by the CLI for a non-chat run.
        #: A handled LLM/tool failure occurred (maps to exit 1).
        #: The run/turn was interrupted by SIGINT (maps to exit 130).
        #: The tool-call depth limit was reached (maps to exit 1 when configured).
        #: At least one tool call was denied in this run (maps to exit 3 with
        #: --fail-on-tool-denied).
        #: Last handled error (kind + message) for JSON output.
        #: Final assistant answer of the last turn (JSON ``content``).
        #: Tool calls/results of the last turn (JSON ``tool_calls``).
        # ---- headless run options (set by entry.CLI.configure_headless) ----
        #: True when stdout must contain only results/events (pipe, -p, -q, json).
        "_console",
        "_run_state",
        "_output",
        "_sessions",
        "_planning",
        "role_manager",
        "role",
        "printer",
        "_client",
        "cmd_handler",
        "bindings",
        "interactive_round",
        #: K02: one-shot flag so the group-trim notice is printed at most once.
        "_trim_notified",
        #: K12: project instruction files are discovered once, on the first request.
        "_project_context_loaded",
        "_project_context_text",
        #: last-known context usage percentage for the REPL status/usage line (updated
        #: once per turn / history-mutating command; display code must never estimate).
        #: history + input + images of the last turn, used by ``/retry``.
        #: Text typed while the assistant was generating (Ctrl+O watcher); used as
        #: the initial prompt buffer for the next input.
        "_pending_prompt_text",
        "session",
        "history",
        "context_manager",
        # ---- v0.24 K23 persistent plan mode (lazily configured) ----
        #: The shared PlanSession (``None`` until plan mode is first used).
        #: ``--plan`` headless flag (one-shot planning run).
        #: Plan submitted by a ``--plan`` run (JSON output: plan/plan_path/revision).
    )

    def __init__(
        self,
        verbose: bool = False,
        role: str = DefaultRoleNames.DEFAULT,
        chat_manager: Optional[FileChatManager] = None,
        role_manager: Optional[RoleManager] = None,
        context_manager: Optional[ContextManager] = None,
        client=None,
        print_mode: bool = False,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        quiet: bool = False,
        config=None,
    ):
        self.runtime = SessionContext(deepcopy(dict(cfg if config is None else config)))
        self._run_state = RunState()
        self._output = MachineOutput(self.config, self._run_state, lambda: getattr(self, "_client", None))
        self._planning = None
        self.verbose: bool = verbose
        # Set when a handled LLM/API failure occurs; single-shot mode turns it into
        # a non-zero process exit (the REPL only prints and continues).
        self.had_error: bool = False
        # ---- v0.19 headless state contract ----
        # The headless intent must be known *before* the console/printer/client and
        # prompt_toolkit session are created (K04 D3): on a TTY, `-p --json` must
        # not build prompt_toolkit nor print verbose diagnostics to stdout.
        self.print_mode: bool = bool(print_mode)
        self.output_format: str = output_format if output_format in OUTPUT_FORMATS else DEFAULT_OUTPUT_FORMAT
        self.quiet: bool = bool(quiet)
        #: v0.21 K13: --resume continues the newest session of this project.
        self.resume: bool = False
        self.interactive: bool = self._stdin_is_tty() and self._stdout_is_tty() and not self.print_mode
        self.machine_output: bool = (not self.interactive) or self.quiet or self.output_format != "text"
        self.exit_code: int = EXIT_OK
        self.interrupted: bool = False
        self.depth_limit_reached: bool = False
        self.tool_denied: bool = False
        self.error_kind: ErrorKind = ErrorKind.UNKNOWN
        self.error_message: Optional[str] = None
        self.last_content: str = ""
        self.tool_calls: List[Dict[str, Any]] = []
        # Remaining headless run options; entry.py calls configure_headless() with
        # the flags (yes/allowed-tools/fail-on-denied/max-turns/cwd).
        self.yes: bool = False
        self.allowed_tools: List[str] = []
        self.fail_on_tool_denied: bool = False
        self.max_turns: Optional[int] = None
        self.cwd: Optional[str] = None
        # --role can specify a role when enter interactive chat
        # TAB will switch between role and shell
        self.init_role: str = role
        self.role_name: str = role

        # In machine/headless runs all diagnostics go to stderr; stdout is reserved
        # for the final result/events.
        self.console = get_console() if not self.machine_output else get_error_console()
        manager = (
            chat_manager
            if chat_manager is not None
            else FileChatManager(
                chat_dir=resolve_default_chat_dir(self.config), max_saved_chats=self.config["MAX_SAVED_CHATS"]
            )
        )
        self.role_manager = role_manager or role_mgr
        self.context_manager = context_manager or ctx_mgr
        self.role: Role = self.role_manager.get_role(self.role_name)
        self.printer = self._make_printer()
        # K08: construct the LLM client lazily (first ``cli.client`` access). A REPL
        # startup must not pay the provider SDK import (~0.9 s for openai) before the
        # first prompt is shown, and one-shot runs create it at their first request.
        self._client = client
        if client is not None:
            # Providers capture their own stdout console at construction time; in
            # machine mode every diagnostic (verbose request dumps, error bodies) must
            # use stderr, so re-point the client *and* its provider console here.
            self._sync_client_console()
        self._sessions = SessionController(
            self.config, manager, self._run_state, self.console, history_changed=self._update_context_percent
        )
        self.cmd_handler = CmdHandler(self)

        # Created lazily by prepare_chat_loop()/_setup_key_bindings(); prompt_toolkit is
        # only imported for real REPL/exec runs (K08).
        self.bindings = None

        self.current_mode: str = TEMP_MODE

        self.interactive_round = self.config["INTERACTIVE_ROUND"]
        self._trim_notified = False
        # K12: project instruction files (AGENTS.md/CLAUDE.md/.yaicli.md) are loaded
        # lazily on the first request so CLI construction stays write/read-free.
        self._project_context_loaded = False
        self._project_context_text = ""
        # the context percentage is cached once per turn (display code never estimates)
        # and the last turn is snapshotted once so ``/retry`` can replay it cleanly.
        self._context_percent: Optional[float] = None
        self._last_turn_snapshot: Optional[Dict[str, Any]] = None
        # Typed-ahead text captured by the generation-time Ctrl+O watcher.
        self._pending_prompt_text = ""
        self._checkpoint_worker = None
        self._checkpoint_capture = None
        self.chat_start_time = None
        self.is_temp_session = True
        self.chat = Chat(title="", history=[])

        # Session directory actually used by the manager (per-project by default).
        manager_dir = getattr(self.chat_manager, "chat_dir", None)
        self.chat_history_dir = (
            Path(manager_dir) if isinstance(manager_dir, (str, Path)) else resolve_default_chat_dir(self.config)
        )

        # Detect OS and Shell if set to auto
        if self.config["OS_NAME"] == DEFAULT_OS_NAME:
            self.config["OS_NAME"] = detect_os(self.config)
        if self.config["SHELL_NAME"] == DEFAULT_SHELL_NAME:
            self.config["SHELL_NAME"] = detect_shell(self.config)

        if self.verbose:
            # Print verbose configuration (values can come from config/env files: never markup)
            self.console.print("Loading Configuration:", style="bold cyan")
            self.console.print(f"Config file path: {safe_text(CONFIG_PATH)}")
            for key, value in self.config.items():
                display_value = "****" if key == "API_KEY" and value else value
                self.console.print(f"  {safe_text(key):<20}: {safe_text(display_value)}")
            self.console.print(f"Current role: {safe_text(self.role_name)}")
            self.console.print(Markdown("---", code_theme=self.config["CODE_THEME"]))

        # v0.19 K04/K21: one-shot/pipe runs never build a prompt_toolkit session; since
        # K08 the REPL builds the only session in prepare_chat_loop().
        self.session = None

        # v0.24 K23: plan mode state is lazily configured on first use, so a normal
        # one-shot/REPL run never imports plan_mode/plan_store.
        self.plan_session = None
        self.plan_requested = False
        self._plan_output_plan = None

    @property
    def config(self):
        return self.runtime.config

    @property
    def interactive(self):
        return self.run_state.interactive

    @interactive.setter
    def interactive(self, value):
        self.run_state.interactive = value

    @property
    def print_mode(self):
        return self.run_state.print_mode

    @print_mode.setter
    def print_mode(self, value):
        self.run_state.print_mode = value

    @property
    def output_format(self):
        return self.run_state.output_format

    @output_format.setter
    def output_format(self, value):
        self.run_state.output_format = value

    @property
    def quiet(self):
        return self.run_state.quiet

    @quiet.setter
    def quiet(self, value):
        self.run_state.quiet = value

    @property
    def machine_output(self):
        return self.run_state.machine_output

    @machine_output.setter
    def machine_output(self, value):
        self.run_state.machine_output = value

    @property
    def yes(self):
        return self.run_state.yes

    @yes.setter
    def yes(self, value):
        self.run_state.yes = value

    @property
    def allowed_tools(self):
        return self.run_state.allowed_tools

    @allowed_tools.setter
    def allowed_tools(self, value):
        self.run_state.allowed_tools = value

    @property
    def fail_on_tool_denied(self):
        return self.run_state.fail_on_tool_denied

    @fail_on_tool_denied.setter
    def fail_on_tool_denied(self, value):
        self.run_state.fail_on_tool_denied = value

    @property
    def max_turns(self):
        return self.run_state.max_turns

    @max_turns.setter
    def max_turns(self, value):
        self.run_state.max_turns = value

    @property
    def cwd(self):
        return self.run_state.cwd

    @cwd.setter
    def cwd(self, value):
        self.run_state.cwd = value

    @property
    def resume(self):
        return self.run_state.resume

    @resume.setter
    def resume(self, value):
        self.run_state.resume = value

    @property
    def init_role(self):
        return self.run_state.init_role

    @init_role.setter
    def init_role(self, value):
        self.run_state.init_role = value

    @property
    def role_name(self):
        return self.run_state.role_name

    @role_name.setter
    def role_name(self, value):
        self.run_state.role_name = value

    @property
    def current_mode(self):
        return self.run_state.current_mode

    @current_mode.setter
    def current_mode(self, value):
        self.run_state.current_mode = value

    @property
    def plan_requested(self):
        return self.run_state.plan_requested

    @plan_requested.setter
    def plan_requested(self, value):
        self.run_state.plan_requested = value

    @property
    def exit_code(self):
        return self._output.result.exit_code

    @exit_code.setter
    def exit_code(self, value):
        self._output.result.exit_code = value

    @property
    def had_error(self):
        return self._output.result.had_error

    @had_error.setter
    def had_error(self, value):
        self._output.result.had_error = value

    @property
    def interrupted(self):
        return self._output.result.interrupted

    @interrupted.setter
    def interrupted(self, value):
        self._output.result.interrupted = value

    @property
    def depth_limit_reached(self):
        return self._output.result.depth_limit_reached

    @depth_limit_reached.setter
    def depth_limit_reached(self, value):
        self._output.result.depth_limit_reached = value

    @property
    def tool_denied(self):
        return self._output.result.tool_denied

    @tool_denied.setter
    def tool_denied(self, value):
        self._output.result.tool_denied = value

    @property
    def error_kind(self):
        return self._output.result.error_kind

    @error_kind.setter
    def error_kind(self, value):
        self._output.result.error_kind = value

    @property
    def error_message(self):
        return self._output.result.error_message

    @error_message.setter
    def error_message(self, value):
        self._output.result.error_message = value

    @property
    def last_content(self):
        return self._output.result.last_content

    @last_content.setter
    def last_content(self, value):
        self._output.result.last_content = value

    @property
    def tool_calls(self):
        return self._output.result.tool_calls

    @tool_calls.setter
    def tool_calls(self, value):
        self._output.result.tool_calls = value

    @property
    def chat_manager(self):
        return self._sessions.chat_manager

    @chat_manager.setter
    def chat_manager(self, value):
        self._sessions.chat_manager = value

    @property
    def chat_start_time(self):
        return self._sessions.chat_start_time

    @chat_start_time.setter
    def chat_start_time(self, value):
        self._sessions.chat_start_time = value

    @property
    def is_temp_session(self):
        return self._sessions.is_temp_session

    @is_temp_session.setter
    def is_temp_session(self, value):
        self._sessions.is_temp_session = value

    @property
    def chat(self):
        return self._sessions.chat

    @chat.setter
    def chat(self, value):
        self._sessions.chat = value

    @property
    def chat_history_dir(self):
        return self._sessions.chat_history_dir

    @chat_history_dir.setter
    def chat_history_dir(self, value):
        self._sessions.chat_history_dir = value

    @property
    def _last_turn_snapshot(self):
        return self._sessions.retry_snapshot

    @_last_turn_snapshot.setter
    def _last_turn_snapshot(self, value):
        self._sessions.retry_snapshot = value

    @property
    def _checkpoint_capture(self):
        return self._sessions.capture

    @_checkpoint_capture.setter
    def _checkpoint_capture(self, value):
        self._sessions.capture = value

    @property
    def _context_percent(self):
        return self.run_state.context_percent

    @_context_percent.setter
    def _context_percent(self, value):
        self.run_state.context_percent = value

    @property
    def _checkpoint_worker(self):
        return self._sessions.worker

    @_checkpoint_worker.setter
    def _checkpoint_worker(self, value):
        self._sessions.worker = value

    @property
    def _plan_output_plan(self):
        return self._output.plan_output

    @_plan_output_plan.setter
    def _plan_output_plan(self, value):
        self._output.plan_output = value

    @property
    def run_state(self):
        """Shared run options; also usable by a bare prompt-only CLI instance."""
        state = getattr(self, "_run_state", None)
        if state is None:
            state = self._run_state = RunState()
        return state

    @property
    def console(self):
        return self._console

    @console.setter
    def console(self, value):
        self._console = value
        sessions = getattr(self, "_sessions", None)
        if sessions is not None:
            sessions.console = value
        planning = getattr(self, "_planning", None)
        if planning is not None:
            planning.console = value

    @property
    def sessions(self):
        return self._sessions

    @property
    def output(self):
        return self._output

    @property
    def planning(self):
        if self._planning is None:
            from .planning.coordinator import PlanCoordinator, PlanTurns

            self._planning = PlanCoordinator(
                self.config,
                self.sessions,
                self._run_state,
                self.output,
                self.console,
                lambda: self.printer,
                PlanTurns(
                    lambda text: self._process_user_input(text),
                    lambda text: self._run_once(text),
                    self.set_role,
                    self._sync_client_plan_session,
                ),
                runtime=self.runtime,
            )
        return self._planning

    @property
    def plan_session(self):
        return self.runtime.peek_plan_session()

    @plan_session.setter
    def plan_session(self, value):
        self.runtime.set_plan_session(value)

    @property
    def active_client(self):
        """Return an existing client without constructing one."""
        return self._client

    def invalidate_client(self):
        self._client = None

    def refresh_context_percent(self):
        self._update_context_percent()

    def clear_retry_snapshot(self):
        self.sessions.clear_retry_snapshot()

    def retry_last_turn(self):
        return self._retry_last_turn()

    @property
    def client(self):
        """The LLM client, constructed on first use (K08 lazy client)."""
        if self._client is None:
            self._client = self._create_client()
            self._sync_client_console()
            # K23: a plan session configured before the first request (e.g. /plan
            # entered before the REPL's first turn) must reach the lazily built client.
            self._sync_client_plan_session()
        return self._client

    @client.setter
    def client(self, value: Any) -> None:
        """Allow tests/integrations to inject a ready client (``cli.client = mock``)."""
        self._client = value
        self._sync_client_plan_session()

    def _sync_client_console(self) -> None:
        """Point the LLM client and its provider at this CLI's console.

        ``LLMClient`` and every provider capture ``get_console()`` (stdout) when
        constructed. In machine-output modes their diagnostics — verbose request
        dumps, ``Error Response: {...}`` bodies, skipped-tool warnings — must go
        to stderr so structured stdout stays parseable. Tool announcements are
        handled separately by ``yaicli.tools.console`` in :meth:`configure_headless`.
        """
        client = self._client
        if client is None:  # pragma: no cover - defensive
            return
        try:
            client.interactive = bool(self.interactive and not self.machine_output)
            client.console = self.console
        except AttributeError:  # pragma: no cover - client without these slots
            return
        try:
            provider = getattr(client, "provider", None)
            if provider is not None and hasattr(provider, "console"):
                provider.console = self.console
        except (AttributeError, TypeError):  # pragma: no cover - exotic provider object
            pass

    def _sync_client_plan_session(self) -> None:
        """Give the LLM client the shared plan session when both exist (K23)."""
        session = getattr(self, "plan_session", None)
        client = getattr(self, "_client", None)
        if session is None or client is None:
            return
        try:
            client.plan_session = session
        except AttributeError:  # pragma: no cover - mocked/legacy clients use plain attrs
            pass

    # ------------------- v0.19 headless configuration -------------------
    @staticmethod
    def _stdin_is_tty() -> bool:
        try:
            return bool(sys.stdin.isatty())
        except (AttributeError, ValueError):
            return False

    @staticmethod
    def _stdout_is_tty() -> bool:
        try:
            return bool(sys.stdout.isatty())
        except (AttributeError, ValueError):
            return False

    def _make_printer(self, content_markdown: bool = True) -> Printer:
        """Build the renderer for the current output mode."""
        events = self._emit_event if self.output_format == "stream-json" else None
        if self.machine_output:
            return Printer(
                console=self.console, config=self.config, content_markdown=False, machine=True, events=events
            )
        return Printer(console=self.console, config=self.config, content_markdown=content_markdown)

    def configure_headless(
        self,
        *,
        print_mode: bool = False,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        quiet: bool = False,
        yes: bool = False,
        allowed_tools: Optional[List[str]] = None,
        fail_on_tool_denied: bool = False,
        max_turns: Optional[int] = None,
        cwd: Optional[str] = None,
        resume: bool = False,
        plan: bool = False,
    ) -> None:
        """Apply the v0.19 headless/scripting flags (called once by entry.main).

        ``print_mode`` forces the one-shot contract (plain output, no prompts).
        ``output_format`` is one of ``text``/``json``/``stream-json``.
        ``--yes``/``--allowed-tools`` are stored for the K06 approval gate.
        ``plan`` requests the v0.24 K23 one-shot planning run (``--plan``).
        """
        self.print_mode = bool(print_mode)
        self.plan_requested = bool(plan)
        if output_format not in OUTPUT_FORMATS:
            output_format = DEFAULT_OUTPUT_FORMAT
        self.output_format = output_format
        self.quiet = bool(quiet)
        self.yes = bool(yes)
        self.allowed_tools = list(allowed_tools or [])
        self.fail_on_tool_denied = bool(fail_on_tool_denied)
        if max_turns is not None:
            self.max_turns = int(max_turns)
            self.config["MAX_TOOL_CALL_DEPTH"] = self.max_turns
        else:
            self.max_turns = self.config["MAX_TOOL_CALL_DEPTH"]
        self.cwd = cwd
        # v0.21 K13: --resume keeps the newest project session as the REPL target.
        self.resume = bool(resume)

        # The interactive contract: a human terminal is available *and* we are not
        # asked for explicit one-shot output. Everything else is machine output.
        self.interactive = self._stdin_is_tty() and self._stdout_is_tty() and not self.print_mode
        self.machine_output = (not self.interactive) or self.quiet or self.output_format != "text"
        if not self.interactive:
            self.session = None

        # Rebuild the console/printer for the effective output mode: in machine
        # mode stdout carries only the result, so every diagnostic uses stderr.
        self.console = get_console() if not self.machine_output else get_error_console()
        self.printer = self._make_printer(content_markdown=self.role_name != DefaultRoleNames.CODER)

        # K02: in machine-output modes tool announcements/output panels must not reach
        # stdout. ``yaicli.tools`` picks its console at import time (stdout on a TTY);
        # re-point it at the stderr console of this mode. Interactive TTY runs keep
        # their import-time console, so this is a no-op there.
        if self.machine_output:
            try:
                from . import tools as _tools_module

                _tools_module.console = get_error_console()
            except Exception:  # pragma: no cover - tool module is always importable
                pass

        # Keep the LLM client in sync: a one-shot/structured run must not block on
        # interactive tool approval prompts (K06 owns the richer policy), and the
        # client/provider consoles must be the stderr console of this mode so
        # verbose dumps and provider error bodies never reach stdout.
        self._sync_client_console()

    def _emit_event(self, event: Dict[str, Any]) -> None:
        return self.output.emit_event(event)

    def _write_text_result(self, content: Optional[str]) -> None:
        return self.output.write_text_result(content)

    @staticmethod
    def _parse_arguments(arguments: Any) -> Any:
        return MachineOutput.parse_arguments(arguments)

    def _record_error(self, exc: BaseException) -> None:
        return self.output.record_error(exc)

    def _error_payload(self) -> Optional[Dict[str, Any]]:
        return self.output.error_payload()

    # ------------------- v0.22 K17 usage / cost -------------------
    @staticmethod
    def _usage_dict_int(usage: Optional[Dict[str, Any]], key: str) -> int:
        return MachineOutput.usage_dict_int(usage, key)

    def _client_usage_snapshot(self) -> Optional[Dict[str, Any]]:
        return self.output.client_usage_snapshot()

    def _usage_payload(self) -> Dict[str, Any]:
        return self.output.usage_payload()

    def _turn_finish_reason(self) -> Optional[str]:
        return self.output.turn_finish_reason()

    def _turn_output_truncated(self) -> bool:
        return self.output.turn_output_truncated()

    def _show_usage_enabled(self) -> bool:
        return self.output.show_usage_enabled()

    def _format_usage_line(
        self,
        before: Optional[Dict[str, Any]],
        after: Optional[Dict[str, Any]],
        elapsed_seconds: float,
        finish_reason: Optional[str],
    ) -> Optional[str]:
        return self.output.format_usage_line(before, after, elapsed_seconds, finish_reason)

    def _build_result(self) -> Dict[str, Any]:
        return self.output.build_result()

    def _record_tool_calls(self, messages: Optional[List[ChatMessage]]) -> None:
        return self.output.record_tool_calls(messages)

    @staticmethod
    def _is_denied_result(content: str) -> bool:
        return MachineOutput.is_denied_result(content)

    def _emit_tool_events_from(self, messages: List[ChatMessage], cursor: int) -> int:
        return self.output.emit_tool_events_from(messages, cursor)

    def _instrument_tool_events(self, stream_iterator, messages: List[ChatMessage]):
        return self.output.instrument_tool_events(stream_iterator, messages)

    def _finalize_exit_code(self) -> int:
        return self.output.finalize_exit_code()

    def _finalize_headless(self) -> int:
        return self.output.finalize_headless()

    # ------------------- v0.24 K23 persistent plan mode -------------------
    def _plan_enabled(self) -> bool:
        return self.planning.plan_enabled()

    def _get_plan_session(self) -> Any:
        return self.planning.get_plan_session()

    def _sync_plan_tool_mode(self) -> None:
        return self.planning.sync_plan_tool_mode()

    def _plan_files_location(self) -> str:
        return self.planning.plan_files_location()

    def _shorten_plan_path(self, path: Any) -> str:
        return self.planning.shorten_plan_path(path)

    def _persist_chat_plan(self, data: Any) -> None:
        return self.planning.persist_chat_plan(data)

    def _sync_chat_plan(self, session: Any = None) -> None:
        return self.planning.sync_chat_plan(session)

    def _toggle_plan_mode(self) -> None:
        return self.planning.toggle_plan_mode()

    @staticmethod
    def _discard_revision(session: Any) -> None:
        """Drop the pending revision draft and return to execution (if any)."""
        from .planning.coordinator import PlanCoordinator

        PlanCoordinator.discard_revision(session)

    def _cancel_plan_review(self) -> None:
        return self.planning.cancel_plan_review()

    def _warn_plan_reply_without_plan(self) -> None:
        return self.planning.warn_plan_reply_without_plan()

    def _after_plan_turn(self) -> None:
        return self.planning.after_plan_turn()

    @staticmethod
    def _next_todo_id(session: Any) -> str:
        """First todo that is not completed (``S1`` fallback); used in re-plan output."""
        from .planning.coordinator import PlanCoordinator

        return PlanCoordinator.next_todo_id(session)

    @staticmethod
    def _attach_todo_impact(session: Any) -> None:
        """Attach the todo-impact text to the session diff for the printer (K23)."""
        from .planning.coordinator import PlanCoordinator

        PlanCoordinator.attach_todo_impact(session)

    def _confirm_plan_approval_policy(self, session: Any) -> bool:
        return self.planning.confirm_plan_approval_policy(session)

    def _edit_plan_from_panel(self, session: Any, plan: Any) -> bool:
        return self.planning.edit_plan_from_panel(session, plan)

    def _handle_plan_review_panel(self) -> None:
        return self.planning.handle_plan_review_panel()

    def _pause_plan_execution(self, plan_mode: Any, session: Any) -> None:
        return self.planning.pause_plan_execution(plan_mode, session)

    def _execute_plan(self) -> None:
        return self.planning.execute_plan()

    def _run_headless_plan(self, user_input: str) -> None:
        return self.planning.run_headless_plan(user_input)

    def _plan_store_context(self) -> tuple:
        return self.planning.plan_store_context()

    def _find_plan_from_disk(self, plan_id: Optional[str] = None) -> Any:
        return self.planning.find_plan_from_disk(plan_id)

    def _list_plans_from_disk(self, all_projects: bool = False) -> list:
        return self.planning.list_plans_from_disk(all_projects)

    def _clear_plans_from_disk(self, done_only: bool = False) -> list:
        return self.planning.clear_plans_from_disk(done_only)

    def _review_plan_from_disk(self, plan_id: Optional[str] = None) -> bool:
        return self.planning.review_plan_from_disk(plan_id)

    def _resume_plan_from_disk(self, plan_id: Optional[str] = None) -> bool:
        return self.planning.resume_plan_from_disk(plan_id)

    def _prepare_plan_task(self, task: str) -> Optional[str]:
        return self.planning.prepare_plan_task(task)

    def _abort_current_plan(self) -> bool:
        return self.planning.abort_current_plan()

    def _edit_current_plan(self) -> Optional[bool]:
        return self.planning.edit_current_plan()

    def _restore_plan_from_session(self) -> None:
        return self.planning.restore_plan_from_session()

    def set_role(self, role_name: str) -> None:
        self.role_name = role_name
        self.role = self.role_manager.get_role(role_name)
        if role_name == DefaultRoleNames.CODER:
            self.printer = self._make_printer(content_markdown=False)
        elif role_name == DefaultRoleNames.SHELL:
            self.current_mode = EXEC_MODE

    @classmethod
    def evaluate_role_name(cls, code: bool = False, shell: bool = False, role: str = ""):
        """
        Judge the role based on the code, shell, and role options.
        Code and shell are highest priority, then role, then default.
        """
        if code is True:
            return DefaultRoleNames.CODER
        if shell is True:
            return DefaultRoleNames.SHELL
        if role:
            return role
        return DefaultRoleNames.DEFAULT

    # ------------------- prompt (model / context) -------------------
    def _prompt_model_name(self) -> str:
        return self.output.prompt_model_name()

    def get_prompt_tokens(self) -> list[tuple[str, str]]:
        """Return the REPL prompt tokens: the mode icon and ``> ``.

        This is the whole input line (no model/role/context), so the cursor always
        sits at the same column regardless of the model name or the working
        directory. Session state is shown by the dim per-turn usage line (model /
        context / tokens / cost / time) and by the welcome banner; the role is
        deliberately not displayed (a custom ``DEFAULT_ROLE`` like ``master`` is not
        git state, and the prompt never inspects the repository).
        """
        state = getattr(getattr(self, "plan_session", None), "mode", None)
        if state in ("researching", "revising"):
            # v0.24 K23 plan-mode input line; the icon is fixed so the cursor column
            # never depends on model/role/context.
            return [("class:qmark", " [plan] 💬 "), ("class:prompt", "> ")]
        mode = getattr(self, "current_mode", TEMP_MODE)
        mode_icon = "💬" if mode == CHAT_MODE else "🚀" if mode == EXEC_MODE else "📝"
        return [("class:qmark", f" {mode_icon} "), ("class:prompt", "> ")]

    def _update_context_percent(self) -> None:
        """Recompute the cached context usage percentage.

        Never called from the per-turn usage line: the value is refreshed once per
        completed turn and after history-mutating commands (``/compact``,
        ``/clear``, ``/load``, ``/model``). A missing history/role prompt or a
        failing estimator degrades to ``None`` (the segment is then omitted).
        """
        try:
            history = getattr(getattr(self, "chat", None), "history", None)
            if not isinstance(history, list) or not history:
                self._context_percent = None
                return
            role = getattr(self, "role", None)
            system_text = getattr(role, "prompt", "") if role is not None else ""
            usage = estimate_context_usage(
                history,
                config=self.config if hasattr(self.config, "get") else None,
                system_text=system_text if isinstance(system_text, str) else "",
            )
            self._context_percent = float(usage.used_percent)
        except Exception:  # pragma: no cover - prompt decoration must never break a turn
            self._context_percent = None

    def _check_history_len(self) -> None:
        """Keep the in-conversation history inside the token budget, group-aligned.

        v0.19 K02: the old implementation sliced ``history[-INTERACTIVE_ROUND*2:]`` by
        message index, which could split an ``assistant(tool_calls)`` message from its
        ``tool`` results (orphan tool message -> every provider 400). Trimming now
        happens at turn-group boundaries via :mod:`yaicli.tokens`:

        * over the token budget -> drop whole oldest turn groups (system/context
          messages are preserved);
        * ``INTERACTIVE_ROUND * 2`` remains a *maximum message count* cap, applied on
          whole groups only (no split, at least the newest group survives).
        """
        history = self.chat.history
        if not history:
            return
        budget = resolve_context_budget(self.config, self.config.get("MODEL", ""))
        result = trim_messages_to_budget(history, budget=budget, max_messages=self.interactive_round * 2)
        if not result.removed_messages:
            return
        self.chat.history = result.messages
        notice = (
            f"Context trimmed: dropped {result.removed_count} older message(s) "
            f"({result.tokens_before} -> {result.tokens_after} est. tokens)."
        )
        if self.verbose:
            self.console.print(
                f"Dialogue trimmed to {len(result.messages)} messages "
                f"({result.tokens_before} -> {result.tokens_after} est. tokens).",
                style="dim",
            )
        # One stderr notice per session (stdout belongs to the answer/JSON events).
        if not getattr(self, "_trim_notified", False):
            self._trim_notified = True
            get_error_console().print(f"{notice} Use /compact to trim deliberately.", style="dim yellow")

    # ------------------- Chat Command Methods -------------------
    def _save_chat(self, title: Union[str, None] = None) -> None:
        return self.sessions.save_chat(title)

    def _save_chat_inner(self, title: Union[str, None] = None) -> None:
        return self.sessions.save_chat_inner(title)

    def _list_chats(self) -> None:
        return self.sessions.list_chats()

    def _refresh_chats(self) -> None:
        return self.sessions.refresh_chats()

    def _load_chat_by_index(self, index: str) -> bool:
        return self.sessions.load_chat_by_index(index)

    def _delete_chat_by_index(self, index: str) -> bool:
        return self.sessions.delete_chat_by_index(index)

    # ------------------- Session metadata / resume (v0.21 K13) -------------------
    def _apply_session_metadata(self, chat: Chat) -> None:
        return self.sessions.apply_session_metadata(chat)

    @staticmethod
    def _session_notice(chat: Chat) -> str:
        return SessionController.session_notice(chat)

    def _resume_latest_session(self) -> bool:
        return self.sessions.resume_latest_session()

    def _start_chat_by_title(self, title: str) -> None:
        return self.sessions.start_chat_by_title(title)

    # ------------------- Special commands -------------------
    def _handle_special_commands(self, user_input: str) -> Union[bool, str]:
        """Handle special command return: True-continue loop, False-exit loop, str-non-special command"""
        return self.cmd_handler.handle_command(user_input)

    def _get_project_context(self) -> str:
        """Return the auto-loaded project instruction block (``""`` when none/disabled).

        Discovery runs once per CLI instance on the first request (v0.21 K12): the
        project files are not re-read on every turn of a REPL session. Configuration is
        honoured inside :func:`yaicli.project_context.load_project_context`; a disabled
        feature performs no filesystem reads. Any unexpected failure degrades to "no
        project context" so a bad file can never break a turn.

        ``getattr`` is used for the cache slots so CLI instances built via
        ``CLI.__new__`` (as some tests and embedding code do) keep working.
        """
        if getattr(self, "_project_context_loaded", False):
            return getattr(self, "_project_context_text", "")
        self._project_context_loaded = True
        text = ""
        try:
            with bind_config(self.config):
                result = load_project_context()
        except Exception:  # pragma: no cover - defensive: never fail the request
            result = None
        if result is not None and result.has_content:
            text = result.text
        self._project_context_text = text
        return text

    def _plan_context_block_text(self) -> str:
        """Return the plan-mode/execution context block (``""`` outside those states).

        Lazy: a normal session never imports plan_mode, so the request payload and
        startup budget of non-plan runs are unchanged.
        """
        session = getattr(self, "plan_session", None)
        if session is None:
            return ""
        if getattr(session, "mode", None) not in ("researching", "revising", "executing"):
            return ""
        try:
            return str(_plan_mode_module().plan_context_block(session) or "")
        except Exception:  # pragma: no cover - context injection must never break a turn
            return ""

    def _build_messages(self, user_input: str, images: Optional[List[ImageData]] = None) -> list[ChatMessage]:
        """Build message list for LLM API with @ file references expanded."""
        with bind_config(self.config):
            # Create the message list with system prompt. K12: the project instruction files
            # are appended to the role prompt (after it, before persistent/@ context); with
            # no files found the payload stays byte-identical to the pre-K12 behaviour.
            system_prompt = self.role.prompt
            project_context = self._get_project_context()
            if project_context:
                system_prompt = f"{system_prompt}\n\n{project_context}"

            # v0.24 K23: plan mode/execution appends a temporary bounded context block
            # (mode rules + goal/steps or todo status) to the SAME first system message.
            # It must not be a second system message: Anthropic only sends one system
            # prompt and Gemini only reads messages[0] as system_instruction, so a
            # separate message would silently disappear for those providers (and is an
            # invalid message role for Anthropic). Normal runs are byte-identical: no
            # plan session means an empty block.
            plan_context = self._plan_context_block_text()
            if plan_context:
                system_prompt = f"{system_prompt}\n\n{plan_context}"
            messages = [ChatMessage(role="system", content=system_prompt)]

            # Add context messages if any
            context_msgs = self.context_manager.get_context_messages()
            if context_msgs:
                messages.extend(context_msgs)

            # Parse and add temporary @ file references
            at_refs_content, cleaned_input, at_images = self.context_manager.parse_at_references(user_input)
            if at_refs_content:
                messages.append(ChatMessage(role="system", content=at_refs_content))

            # Add previous conversation if available
            for msg in self.chat.history:
                messages.append(msg)

            # Add user input (with @ references cleaned up) and images
            effective_images = list(images or []) + at_images
            if effective_images:
                provider = self.config.get("PROVIDER", "").lower()
                if provider in NO_VISION_PROVIDERS:
                    self.console.print(
                        f"Warning: Provider '{safe_text(provider)}' does not support image input. Images will be ignored.",
                        style="yellow",
                    )
                    effective_images = []
            user_msg = ChatMessage(role="user", content=cleaned_input, images=effective_images)
            messages.append(user_msg)
            return messages

    def _get_tool_policy(self) -> ToolPolicy:
        """Resolve the effective tool policy for the current request."""
        if self.current_mode == EXEC_MODE:
            return ToolPolicy(enable_functions=False, enable_mcp=False)
        return ToolPolicy(enable_functions=self.config["ENABLE_FUNCTIONS"], enable_mcp=self.config["ENABLE_MCP"])

    def _handle_llm_response(
        self, user_input: str, images: Optional[List[ImageData]] = None
    ) -> tuple[Optional[str], list[ChatMessage]]:
        """Get response from API (streaming or normal) and print it.
        Returns the full content string or None if an error occurred.

        Args:
            user_input (str): The user's input text.
            images: Optional list of ImageData for multimodal input.

        Returns:
            Optional[str]: The assistant's response content or None if an error occurred.
            list[ChatMessage]: The updated message history.
        """
        with bind_config(self.config):
            from .debug_log import debug_log

            debug_log("generation.begin", interactive=getattr(self, "interactive", False))
            messages = self._build_messages(user_input, images=images)
            if not self.machine_output and self.role.name != DefaultRoleNames.CODER:
                self.console.print("Assistant:", style="bold green")
            # Generation-time Ctrl+O: while chunks stream there is no prompt reading the
            # keyboard, so a small cbreak watcher captures Ctrl+O (and typed-ahead text).
            # Interactive runs also move the generation pipeline to a worker thread so the
            # viewer can open while the answer keeps streaming (T3).
            watcher = self._start_generation_watcher()
            bridge = None
            routing = None
            saved_worker_consoles: list = []
            result_messages = messages
            try:
                # In background mode the worker mutates its own copy of the message list;
                # it is adopted only when the turn completes, so an aborted or lingering
                # worker can never corrupt the next turn's history.
                request_messages = list(messages) if watcher is not None else messages
                if watcher is not None:
                    result_messages = request_messages
                response_iterator = self.client.completion_with_tools(
                    request_messages,
                    stream=self.config["STREAM"],
                    tool_policy=self._get_tool_policy(),
                )
                if self.output_format == "stream-json":
                    response_iterator = self._instrument_tool_events(response_iterator, request_messages)

                display_iterator = response_iterator
                if watcher is not None:
                    from .stream_bridge import ThreadedStream, set_active_bridge
                    from .worker_console import install_worker_console_routing

                    # Worker output must not touch the terminal directly: route it through
                    # the bridge so the UI thread replays it in order (T2). The bridge is
                    # registered as active before the worker starts (lazy start on first
                    # next()), so even the first tool announcement is marshalled.
                    routing = install_worker_console_routing(self.console, get_error_console())
                    saved_worker_consoles = self._swap_worker_consoles(routing.main)
                    bridge = ThreadedStream(response_iterator, on_console=self._console_replayer(routing))
                    set_active_bridge(bridge)
                    display_iterator = bridge

                if watcher is not None:
                    content, _ = self.printer.display_stream(
                        display_iterator,
                        pause_requested=watcher.take_viewer_request,
                        on_pause=lambda: self._open_viewer_while_generating(watcher),
                    )
                else:
                    content, _ = self.printer.display_stream(display_iterator)

                # Wave-2 coordination (K02/K06): the client reports depth/denial
                # outcomes through its own flags; mirror them onto the CLI contract.
                if getattr(self.client, "depth_limit_reached", False) is True:
                    self.depth_limit_reached = True
                if getattr(self.client, "tool_denied", False) is True:
                    self.tool_denied = True

                # The 'messages' list is modified by the client in-place
                return content, result_messages
            except Exception as e:
                self.had_error = True
                self._record_error(e)
                self._recover_persisted_context_on_overflow(e)
                # K05: print the *classified* message (kind + actionable hint, e.g.
                # "auth (HTTP 401) ... Hint: Check API_KEY") instead of the raw SDK text.
                try:
                    agent_error = classify_exception(e)
                    detail = getattr(agent_error, "user_message", None) or str(e)
                except Exception:  # pragma: no cover - classifier must never break the CLI
                    detail = str(e)
                self.console.print(f"Error processing LLM response: {safe_text(detail)}", style="red")
                if self.verbose:
                    traceback.print_exc()
                return None, messages
            finally:
                debug_log("generation.end")
                # Stop the background generator first (it may still be producing), then
                # restore the consoles it was routed through, then the key watcher.
                abandoned = False
                if bridge is not None:
                    from .stream_bridge import clear_active_bridge

                    clear_active_bridge(bridge)
                    abandoned = bridge.close(timeout=0.5)
                if not abandoned:
                    if routing is not None:
                        routing.restore()
                    self._restore_worker_consoles(saved_worker_consoles)
                else:
                    # A worker blocked in a provider read/tool call keeps the routed
                    # consoles installed (its dead bridge drops anything it prints later);
                    # main-thread output still reaches the real console unchanged.
                    self.console.print(
                        "Background generation is still finishing; its remaining output is ignored.",
                        style="dim",
                    )
                    if getattr(self, "_checkpoint_capture", None) is not None:
                        self._checkpoint_worker = bridge
                        self._checkpoint_capture.barrier = True
                if watcher is not None:
                    pending = watcher.stop()
                    if pending:
                        # Typed-ahead text (anything but Ctrl+O keys) becomes the next
                        # prompt's initial buffer instead of being dropped.
                        self._pending_prompt_text = (getattr(self, "_pending_prompt_text", "") + pending)[-4000:]

    def _start_generation_watcher(self):
        """Install the generation-time Ctrl+O key watcher (interactive streaming only)."""
        from .debug_log import debug_log

        if not getattr(self, "interactive", False):
            debug_log("watcher.skip", reason="not-interactive")
            return None
        if getattr(self, "machine_output", False):
            debug_log("watcher.skip", reason="machine-output")
            return None
        try:
            from .generation_keys import GenerationKeyWatcher

            watcher = GenerationKeyWatcher()
            started = watcher.start()
            debug_log("watcher.ready", started=started)
            return watcher if started else None
        except Exception as exc:  # pragma: no cover - key capture must never break a turn
            debug_log("watcher.error", error=repr(exc))
            return None

    @staticmethod
    def _console_replayer(routing):
        """Main-thread replay of worker console events captured by the bridge."""

        def replay(stderr: bool, args: tuple, kwargs: dict) -> None:
            target = routing.error.real if stderr else routing.main.real
            target.print(*args, **kwargs)

        return replay

    def _swap_worker_consoles(self, console) -> list:
        """Point the client/provider consoles at the routed worker console (T2)."""
        saved: list = []
        client = getattr(self, "client", None)
        if client is None:
            return saved
        saved.append((client, "console", getattr(client, "console", None)))
        try:
            client.console = console
        except (AttributeError, TypeError):  # pragma: no cover - exotic client
            saved.pop()
        provider = getattr(client, "provider", None)
        if provider is not None and hasattr(provider, "console"):
            saved.append((provider, "console", getattr(provider, "console", None)))
            try:
                provider.console = console
            except (AttributeError, TypeError):  # pragma: no cover - exotic provider
                saved.pop()
        return saved

    @staticmethod
    def _restore_worker_consoles(saved: list) -> None:
        """Restore consoles saved by :meth:`_swap_worker_consoles`."""
        for owner, attr, value in saved:
            try:
                setattr(owner, attr, value)
            except (AttributeError, TypeError):  # pragma: no cover - exotic owner
                pass

    def _open_viewer_while_generating(self, watcher) -> None:
        """Open the viewer while the background generator keeps producing (T3)."""
        from .debug_log import debug_log
        from .tools.output_history import viewer_outputs

        entries, label = viewer_outputs()
        debug_log("viewer.request", entries=len(entries), label=label)
        if not entries:
            # Give feedback instead of silently ignoring Ctrl+O during early output.
            self.console.print("No tool output in this turn yet; generation continues.", style="dim")
            return
        watcher.pause()
        try:
            self._open_tool_output_viewer()
        finally:
            watcher.resume()

    def _recover_persisted_context_on_overflow(self, exc: BaseException) -> None:
        """Persist one group trim when the provider rejected the context as too long.

        The client already trims-and-retries the *live* request once; if that still
        failed, dropping one turn group from the saved history gives the next turn a
        chance instead of repeating the same over-window payload forever.
        """
        try:
            kind = classify_exception(exc).kind
        except Exception:  # pragma: no cover - classifier must never break the CLI
            return
        if kind is not ErrorKind.CONTEXT_LENGTH:
            return
        try:
            result = trim_oldest_group(self.chat.history)
        except Exception:  # pragma: no cover - history must never break error handling
            return
        if not result.removed_messages:
            return
        self.chat.history = result.messages
        get_error_console().print(
            f"Context repaired: dropped {result.removed_count} older message(s) from history "
            f"({result.tokens_before} -> {result.tokens_after} est. tokens).",
            style="dim yellow",
        )

    def _remember_turn_for_retry(self, user_input: str, images: Optional[List[ImageData]] = None) -> None:
        return self.sessions.remember_turn_for_retry(user_input, images)

    def _retry_last_turn(self) -> bool:
        """Re-run the last user turn from its pre-turn snapshot (``/retry``).

        Restores the history recorded before the last turn (so the failed turn's
        partial messages are not duplicated), then re-processes the same input and
        images. With no previous turn it only prints a friendly notice.
        """
        snapshot = getattr(self, "_last_turn_snapshot", None)
        user_input = snapshot.get("input") if isinstance(snapshot, dict) else None
        if not isinstance(user_input, str) or not user_input.strip():
            self.console.print("Nothing to retry: no previous user turn in this session.", style="yellow")
            return True
        history = snapshot.get("history")
        if isinstance(history, list):
            try:
                self.chat.history = list(history)
            except (AttributeError, TypeError):  # pragma: no cover - bare/legacy chat objects
                pass
        images = snapshot.get("images")
        self.console.print(f"Retrying last turn: {safe_text(user_input)}", style="dim")
        return self._process_user_input(user_input, images=list(images) if isinstance(images, list) else [])

    def _checkpoint_store(self):
        return self.sessions.checkpoint_store()

    def _checkpoint_reset(self, only_if_new: bool = False) -> None:
        return self.sessions.checkpoint_reset(only_if_new)

    def _process_user_input(self, user_input: str, images: Optional[List[ImageData]] = None) -> bool:
        """Wrap a successful persisted interactive turn in a checkpoint journal."""
        with bind_config(self.config):
            if (
                not self.interactive
                or self.machine_output
                or self.quiet
                or self.is_temp_session
                or self.current_mode == TEMP_MODE
                or not self.config.get("CHECKPOINT_ENABLED", True)
            ):
                return self._process_user_input_inner(user_input, images)
            from .checkpoints import CheckpointError

            store = None
            capture = None
            try:
                store = self._checkpoint_store()
                if store is None:
                    return self._process_user_input_inner(user_input, images)
                if self.chat.checkpoint_head < 0 or store.pending_path.exists():
                    self.chat.checkpoint_head = store.ensure_base(self.chat.to_dict())
                    self.chat.save(self.chat_history_dir)
                records = store.list_records(self.chat.checkpoint_head)
                capture = store.begin_turn((records[-1]["turn"] + 1) if records else 1)
                self._checkpoint_capture = capture
                import copy

                before_plan = copy.deepcopy(self.chat.plan)
                with capture.activate():
                    result = self._process_user_input_inner(user_input, images)
                if getattr(self, "_checkpoint_worker", None) is not None and self._checkpoint_worker.alive:
                    return result
                if self.chat.plan != before_plan:
                    capture.barrier = True
                if not capture.completed:
                    if capture.files or capture.barrier:
                        capture.barrier = True
                    else:
                        store.pending_path.unlink(missing_ok=True)
                        return result

                def commit(snapshot):
                    self.chat.checkpoint_head = snapshot["checkpoint_head"]
                    self.chat.save(self.chat_history_dir)

                self.chat.checkpoint_head, warning = store.finish_turn(capture, self.chat.to_dict(), commit)
                self.chat_manager.refresh_chats()
                if warning:
                    get_error_console().print(warning, markup=False)
                return result
            except (CheckpointError, OSError, ChatSaveError) as exc:
                get_error_console().print(safe_text(str(exc)), markup=False)
                return True
            finally:
                if capture is not None and not (
                    getattr(self, "_checkpoint_worker", None) is not None and self._checkpoint_worker.alive
                ):
                    store.abandon_turn(capture)
                    self._checkpoint_capture = None

    def _process_user_input_inner(self, user_input: str, images: Optional[List[ImageData]] = None) -> bool:
        """Process user input: get response, print, update history, maybe execute.
        Returns True to continue REPL, False to exit on critical error.
        """
        from .tools.output_history import begin_turn

        # Every user input opens a new turn; the Ctrl+O viewer groups tool outputs by it.
        begin_turn()
        # capture the pre-turn state first so /retry can replay this exact turn.
        self._remember_turn_for_retry(user_input, images=images)
        # K17: snapshot the session usage before the turn so the interactive line
        # shows this turn's tokens, not the whole session's.
        usage_before = self._client_usage_snapshot()
        turn_started_at = time.perf_counter()
        content, updated_messages = self._handle_llm_response(user_input, images=images)
        elapsed_seconds = time.perf_counter() - turn_started_at
        self._record_tool_calls(updated_messages)
        self._warn_plan_reply_without_plan()

        if content is None and not any(getattr(msg, "tool_calls", None) for msg in updated_messages):
            self.last_content = ""
            return True

        # The client modifies the message list in place, so the updated_messages
        # contains the full history of the turn (system, history, user, assistant, tools).
        # We replace the old history with the new one, removing system messages (role prompt, context, etc.)
        # to ensure they remain temporary and don't pollute the conversation history.
        if updated_messages:
            self.chat.history = [msg for msg in updated_messages if msg.role != "system"]

        self._check_history_len()
        # refresh the cached prompt context percentage once per completed turn.
        self._update_context_percent()

        result_text = content or ""
        if self.current_mode == EXEC_MODE:
            # --shell generates a command: filter Markdown fences before showing or
            # executing it so stdout carries exactly the command.
            command = filter_command(result_text)
            self.last_content = command
            if self.machine_output:
                self._write_text_result(command)
                self._run_generated_command(command)
            else:
                self._confirm_and_execute(result_text)
        else:
            self.last_content = result_text
            if self.machine_output:
                self._write_text_result(result_text)

        # K17: one stderr warning when the provider truncated the answer at
        # MAX_TOKENS (every mode; stderr keeps structured stdout parseable).
        if self._turn_output_truncated():
            get_error_console().print(
                "Response stopped at MAX_TOKENS; increase MAX_TOKENS (or reduce the context/tool output) "
                "to get a complete answer.",
                style="yellow",
            )
        # K17: one dim per-turn usage line in interactive output (never machine output).
        if not self.machine_output and self._show_usage_enabled():
            usage_line = self._format_usage_line(
                usage_before,
                self._client_usage_snapshot(),
                elapsed_seconds,
                self._turn_finish_reason(),
            )
            if usage_line:
                self.console.print(usage_line, style="dim")
        capture = getattr(self, "_checkpoint_capture", None)
        if capture is not None:
            capture.completed = True
        return True

    def _run_generated_command(self, command: str) -> None:
        """Non-interactive ``--shell`` handling.

        In a pipe/one-shot run the generated command is printed to stdout and only
        executed when ``--yes`` was passed; otherwise the run succeeds without
        executing anything.
        """
        if not command:
            self.console.print("No command generated or command is empty.", style="bold red")
            self.had_error = True
            self.error_message = self.error_message or "no command generated"
            return
        if not self.yes:
            return
        self.console.print("Executing...", style="bold green")
        try:
            return_code = subprocess.call(command, shell=True)
        except OSError as exc:
            self.had_error = True
            self.error_message = f"failed to execute command: {exc}"
            self.console.print(f"Failed to execute command: {safe_text(exc)}", style="red")
            return
        if return_code != 0:
            self.had_error = True
            self.error_message = self.error_message or f"command exited with status {return_code}"

    def _confirm_and_execute(self, raw_content: str) -> None:
        """Review, edit and execute the command"""
        cmd = filter_command(raw_content)
        if not cmd:
            self.console.print("No command generated or command is empty.", style="bold red")
            return
        self.console.print(
            Panel(
                # The command is model output: show it literally so markup can not
                # restyle/hide the command the operator is asked to run.
                untrusted_text(cmd),
                title="Suggest Command",
                title_align="left",
                border_style="bold magenta",
                expand=False,
            )
        )
        _input = Prompt.ask(
            r"Execute command? \[e]dit, \[y]es, \[n]o",
            choices=["y", "n", "e"],
            default="y",
            case_sensitive=False,
            show_choices=False,
        )
        executed_cmd = None
        if _input == "y":
            executed_cmd = cmd
        elif _input == "e":
            try:
                edited_cmd = _prompt_function()("Edit command: ", default=cmd).strip()
                if edited_cmd and edited_cmd != cmd:
                    executed_cmd = edited_cmd
                elif edited_cmd:
                    executed_cmd = cmd
                else:
                    self.console.print("Execution cancelled.", style="yellow")
            except EOFError:
                self.console.print("\nEdit cancelled.", style="yellow")
                return
        if executed_cmd:
            self.console.print("Executing...", style="bold green")
            try:
                if getattr(self, "_checkpoint_capture", None) is not None:
                    self._checkpoint_capture.barrier = True
                subprocess.call(executed_cmd, shell=True)
            except Exception as e:
                self.console.print(f"Failed to execute command: {safe_text(e)}", style="red")
        elif _input != "e":
            self.console.print("Execution cancelled.", style="yellow")

    # ------------------- REPL Methods -------------------
    def prepare_chat_loop(self) -> None:
        """Setup key bindings and history for interactive modes."""
        self.current_mode = CHAT_MODE
        # seed the cached prompt context percentage for a resumed/loaded session.
        self._update_context_percent()
        self._setup_key_bindings()

        # K21: a read-only HOME (containers/CI/sandbox) must not crash the REPL
        # because the history file cannot be created; fall back to in-memory
        # history and keep going. K13: create it with 0600 file / 0700 dirs
        # (it contains every prompt typed, including any pasted secrets).
        history = None
        try:
            from .history import prepare_history_file

            prepare_history_file(HISTORY_FILE)
            history = _limited_history_class()(HISTORY_FILE, max_entries=self.config["MAX_HISTORY"])
        except OSError as e:
            get_error_console().print(
                f"Warning: could not set up prompt history ({safe_text(e)}); using in-memory history.",
                style="yellow",
            )

        # Set up the prompt session with command history (prompt_toolkit is imported
        # here, not at module import, so one-shot/headless runs stay light — K08).
        PromptSessionClass = _prompt_session_class()
        try:
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

            self.session = PromptSessionClass(
                key_bindings=self.bindings,
                history=history,
                auto_suggest=AutoSuggestFromHistory() if self.config.get("AUTO_SUGGEST", True) else None,
                enable_history_search=True,
                # composite completer — slash commands plus the existing @path
                # completer (kept as the patchable ``AtPathCompleter`` seam).
                completer=_repl_completer_class()(path_completer=_at_path_completer_class()()),
                complete_while_typing=True,  # Enable auto-completion for @ trigger
                complete_in_thread=True,  # Don't block on completion
            )
        except Exception as e:
            self.console.print(f"Error initializing prompt session history: {safe_text(e)}", style="red")
            self.session = PromptSessionClass(key_bindings=self.bindings)

    def _setup_key_bindings(self) -> None:
        """Setup keyboard shortcuts: Shift+Tab plan-mode toggle, Ctrl+O viewer and
        multiline input (Alt+Enter / Ctrl+J insert a newline, Enter still submits).
        Imports prompt_toolkit lazily (K08)."""
        from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

        if self.bindings is None:
            self.bindings = KeyBindings()

        @self.bindings.add("s-tab")  # Shift+Tab toggles plan mode (normal <-> plan)
        def _(event: KeyPressEvent) -> None:
            """Toggle persistent plan mode (read-only); /mode switches chat/exec."""
            self._toggle_plan_mode()

        @self.bindings.add("c-o")  # Ctrl+O: open the tool-output viewer
        def _(event: KeyPressEvent) -> None:
            """Exit prompt() with a signal so the REPL can run the viewer app."""
            from .tool_output_viewer import ToolOutputViewerRequested

            event.app.exit(exception=ToolOutputViewerRequested())

        @self.bindings.add("escape", "enter")  # Alt+Enter / Esc,Enter: newline
        def _(event: KeyPressEvent) -> None:
            """Insert a newline instead of submitting (multiline input)."""
            event.current_buffer.insert_text("\n")

        @self.bindings.add("c-j")  # Ctrl+J: newline (terminal-friendly Alt+Enter)
        def _(event: KeyPressEvent) -> None:
            """Insert a newline instead of submitting (multiline input)."""
            event.current_buffer.insert_text("\n")

    def _open_tool_output_viewer(self) -> None:
        """Open the full-screen tool-output viewer (``Ctrl+O`` / ``/show-output``)."""
        from .tool_output_viewer import open_tool_output_viewer

        open_tool_output_viewer(self.console)

    def _print_welcome_message(self) -> None:
        """Prints the initial welcome banner and instructions."""
        self.console.print(
            """
 ██    ██  █████  ██  ██████ ██      ██
  ██  ██  ██   ██ ██ ██      ██      ██
   ████   ███████ ██ ██      ██      ██
    ██    ██   ██ ██ ██      ██      ██
    ██    ██   ██ ██  ██████ ███████ ██
""",
            style="bold cyan",
        )
        self.console.print("Welcome to YAICLI!", style="bold")

        # Display session type
        if self.is_temp_session:
            self.console.print("Current: [bold yellow]Temporary Session[/bold yellow] (use /save to make persistent)")
        else:
            self.console.print(
                "Current: [bold green]Persistent Session[/bold green]"
                f"{f': {safe_text(self.chat.title)}' if self.chat.title else ''}"
            )
        model = self._prompt_model_name()
        if model:
            status = f"Model: [bold]{safe_text(model)}[/bold]"
            percent = getattr(self, "_context_percent", None)
            if isinstance(percent, (int, float)) and not isinstance(percent, bool):
                status += f" · context {max(0.0, float(percent)):.0f}%"
            self.console.print(status)
        self.print_help()
        # v0.24 K23: plan mode uses Shift+Tab / /plan; PLAN_ENABLED=false says so
        # explicitly instead of advertising a shortcut that does nothing.
        if self._plan_enabled():
            self.console.print(
                f"Plan mode: Shift+Tab / {CMD_PLAN} · plan files under {safe_text(self._plan_files_location())}",
                style="dim",
            )
        else:
            self.console.print("Plan mode: disabled (PLAN_ENABLED=false)", style="dim")

    def print_help(self):
        """Print the REPL help table.

        Command rows come from ``cmd_handler.COMMAND_INFO`` — the same metadata the
        slash-command completion menu uses, so help and completion cannot drift
        apart. Rows are printed without Rich markup so usage strings with
        ``[optional]`` arguments are shown verbatim.
        """
        self.console.print("Press [bold yellow]Shift+Tab[/bold yellow] to toggle plan mode (normal ↔ plan, read-only)")
        for info in COMMAND_INFO:
            self.console.print(f"{info.help_text:<19}: {info.description}", markup=False)
        self.console.print(f"{'!<command>':<19}: Execute shell command directly (e.g., !ls -al)")
        self.console.print(f"{'Ctrl+C':<19}: Clear input / cancel turn; press twice to exit")
        self.console.print(f"{'Alt+Enter/Ctrl+J':<19}: Insert a newline (Enter still submits)")
        self.console.print(
            "  Tip: Type '@' for file paths and '/' for slash commands; use Tab/arrows to select",
            style="dim",
        )

    def _run_repl(self) -> None:
        """Run the main Read-Eval-Print Loop (REPL).

        SIGINT semantics (v0.19 K04): a single Ctrl-C clears the current input
        line / cancels the current turn and keeps the session alive; a second
        Ctrl-C within ``DOUBLE_CTRL_C_WINDOW_SECONDS`` exits the REPL normally
        (Ctrl-D does the same). The REPL never turns a single interrupt into
        exit 130; one-shot/generation interrupts keep their 130 contract.
        """
        self.prepare_chat_loop()
        # Ctrl+O closes prompt() through this signal; the REPL then runs the
        # full-screen viewer and re-enters the prompt (alternate screen restores).
        from .tool_output_viewer import ToolOutputViewerRequested

        # getattr fallbacks keep bare/legacy CLI objects (tests build them via
        # CLI.__new__) working without the full v0.19 state contract.
        interactive = getattr(self, "interactive", True)
        quiet = getattr(self, "quiet", False)
        machine_output = getattr(self, "machine_output", False)
        if interactive and not quiet:
            self._print_welcome_message()

        # SIGINT bookkeeping: only two interrupts in quick succession exit, so a
        # stray Ctrl-C can never kill an interactive session.
        last_interrupt_at = 0.0

        def _is_second_interrupt() -> bool:
            nonlocal last_interrupt_at
            now = time.monotonic()
            doubled = last_interrupt_at > 0.0 and (now - last_interrupt_at) <= DOUBLE_CTRL_C_WINDOW_SECONDS
            last_interrupt_at = now
            return doubled

        # Main REPL loop
        while True:
            if not machine_output:
                self.console.print(Markdown("---", code_theme=self.config["CODE_THEME"]))

            # --- Read ---
            from .debug_log import debug_log

            debug_log("prompt.begin")
            pending_text = getattr(self, "_pending_prompt_text", "")
            if pending_text:
                self._pending_prompt_text = ""
            try:
                user_input = self.session.prompt(self.get_prompt_tokens, default=pending_text)
            except ToolOutputViewerRequested:
                # Ctrl+O at the prompt: run the viewer, then return to the prompt.
                self._open_tool_output_viewer()
                continue
            except KeyboardInterrupt:
                # Ctrl-C at the prompt: clear the input; press twice quickly to exit.
                if _is_second_interrupt():
                    break
                self.console.print("Press Ctrl+C again to exit.", style="dim")
                continue
            except EOFError:
                # Ctrl-D: leave the REPL normally (exit code 0).
                break

            last_interrupt_at = 0.0
            user_input = user_input.strip()
            if not user_input:
                continue

            # --- Evaluate special commands ---
            try:
                _continue = self._handle_special_commands(user_input)
            except KeyboardInterrupt:
                # Ctrl-C while running a slash command cancels it; twice exits.
                if _is_second_interrupt():
                    break
                self.console.print("Press Ctrl+C again to exit.", style="dim")
                continue
            except EOFError:
                break
            except Exception as e:
                self.console.print(f"Error: {safe_text(e)}", style="red")
                continue
            if _continue is False:  # Exit command
                break
            if _continue is True:  # Other special command
                continue

            # --- Evaluate a regular turn ---
            try:
                if not self._process_user_input(user_input):
                    break
            except KeyboardInterrupt:
                # Generation Ctrl-C: cancel this turn; press twice quickly to exit.
                if _is_second_interrupt():
                    break
                self.console.print("KeyboardInterrupt", style="yellow")
                self.console.print("Press Ctrl+C again to exit.", style="dim")
                continue
            except EOFError:
                break
            except Exception as e:
                self.console.print(f"Error: {safe_text(e)}", style="red")
                continue
            # v0.24 K23: a submit_plan during the turn opens the approval panel.
            try:
                self._after_plan_turn()
            except KeyboardInterrupt:
                if _is_second_interrupt():
                    break
                self.console.print("KeyboardInterrupt", style="yellow")
                continue
            except Exception as e:
                self.console.print(f"Error: {safe_text(e)}", style="red")
                continue

        # Auto-save chat history when exiting if there are messages and not a temporary session
        if not self.is_temp_session and self.chat.history:
            self._save_chat(self.chat.title)

        if not quiet:
            self.console.print("\nExiting YAICLI... Goodbye!", style="bold green")

    def _run_once(
        self, user_input: str, shell: bool = False, code: bool = False, images: Optional[List[ImageData]] = None
    ) -> None:
        """Handle default mode"""
        with bind_config(self.config):
            self.set_role(self.evaluate_role_name(code, shell, self.init_role))
            self._process_user_input(user_input, images=images)

    def run(
        self,
        chat: bool = False,
        shell: bool = False,
        code: bool = False,
        user_input: Optional[str] = None,
        images: Optional[List[ImageData]] = None,
    ):
        if not user_input and not chat:
            self.console.print("No input provided.", style="bold red")
            raise typer.Abort()

        # v0.24 K23: `--plan` is a one-shot planning run (never a REPL, never exec).
        if getattr(self, "plan_requested", False) and not chat:
            try:
                # _run_headless_plan() emits the final structured output itself.
                self._run_headless_plan(user_input or "")
            except KeyboardInterrupt:
                self.interrupted = True
                self.error_kind = ErrorKind.INTERRUPTED
                self.error_message = self.error_message or "interrupted"
                get_error_console().print("Interrupted.", style="yellow")
                self._finalize_headless()
            return

        if chat:
            if getattr(self, "resume", False):
                # v0.21 K13: continue the newest session of this project
                # (explicit notice + new session when the project has none).
                self._resume_latest_session()
            elif user_input and isinstance(user_input, str):
                # `ai --chat "<title>"`: resume that session, or print an explicit
                # notice that a new session is being started (no silent fallback).
                self._start_chat_by_title(user_input)
            self._apply_session_metadata(self.chat)
            # v0.24 K23: a resumed/loaded session restores its plan pointer but always
            # stays in normal mode (an unfinished plan is only advertised, not entered).
            self._restore_plan_from_session()
            # Run the interactive chat REPL
            self._run_repl()
            return

        # Run in single-use mode. SIGINT is a first-class outcome (exit 130) and
        # must not escape as a traceback; the REPL keeps its own semantics.
        try:
            self._run_once(user_input or "", shell=shell, code=code, images=images)
        except KeyboardInterrupt:
            self.interrupted = True
            self.error_kind = ErrorKind.INTERRUPTED
            self.error_message = self.error_message or "interrupted"
            get_error_console().print("Interrupted.", style="yellow")
        self._finalize_headless()

    def _create_client(self):
        """Create an LLM client instance based on configuration.

        In machine-output mode the client/provider constructors would otherwise
        write their diagnostics (unknown-provider warning, SDK noise) to the real
        stdout before :meth:`_sync_client_console` can re-point their consoles.
        Redirect stdout to stderr for the duration of the construction only; the
        original stream is restored immediately afterwards.
        """
        with bind_config(self.config):
            redirect_stdout = self.machine_output
            original_stdout = sys.stdout
            if redirect_stdout:
                sys.stdout = sys.stderr
            try:
                return _llm_client_class()(
                    provider_name=self.config["PROVIDER"].lower(),
                    verbose=self.verbose,
                    config=self.config,
                    runtime=self.runtime,
                    approval=ToolApprovalManager(),
                    # Machine/one-shot runs must never block on a tool confirmation
                    # prompt; the client then denies unapproved tool calls (K06 owns
                    # the richer --yes/--allowed-tools policy).
                    interactive=bool(self.interactive and not self.machine_output),
                )
            except YaicliError as e:
                self.console.print(f"Error creating client: {safe_text(e)}", style="red")
                raise typer.Abort()
            finally:
                if redirect_stdout:
                    sys.stdout = original_stdout
