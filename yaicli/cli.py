import json
import subprocess
import sys
import time
import traceback
from os import devnull
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import typer
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from .chat import Chat, FileChatManager, chat_mgr
from .cmd_handler import CMD_COMPACT, CmdHandler
from .completer import AtPathCompleter
from .config import cfg
from .console import get_console, get_error_console, safe_text, untrusted_text
from .const import (
    CHAT_MODE,
    CMD_CLEAR,
    CMD_DELETE_CHAT,
    CMD_EXIT,
    CMD_HELP,
    CMD_HISTORY,
    CMD_LIST_CHATS,
    CMD_LOAD_CHAT,
    CMD_MODE,
    CMD_SAVE_CHAT,
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
from .errors import EXIT_ERROR, EXIT_OK, EXIT_SIGINT, EXIT_TOOL_DENIED, ErrorKind, classify_exception
from .exceptions import ChatSaveError, YaicliError
from .history import LimitedFileHistory
from .llms import LLMClient
from .printer import Printer
from .role import Role, RoleManager, role_mgr
from .schemas import ChatMessage, ImageData, RefreshLive, ToolPolicy
from .tokens import resolve_context_budget, trim_messages_to_budget, trim_oldest_group
from .tools.approval import ToolApprovalManager
from .utils import detect_os, detect_shell, filter_command

OUTPUT_FORMATS = ("text", "json", "stream-json")
#: Content of the in-band tool result the client appends when a tool call is denied.
TOOL_DENIED_MARKERS = ("declined to execute", "tool_denied")

#: Ctrl-C twice within this many seconds exits the REPL (a single press only clears
#: the current input line / cancels the current turn). Matches common shell/REPL UX.
DOUBLE_CTRL_C_WINDOW_SECONDS = 2.0


class CLI:
    __slots__ = (
        "verbose",
        # ----- v0.19 headless state contract (public; entry.py maps it) -----
        #: True when a human terminal UI is available (TTY stdin+stdout, not -p).
        "interactive",
        #: Process exit code resolved by the CLI for a non-chat run.
        "exit_code",
        #: A handled LLM/tool failure occurred (maps to exit 1).
        "had_error",
        #: The run/turn was interrupted by SIGINT (maps to exit 130).
        "interrupted",
        #: The tool-call depth limit was reached (maps to exit 1 when configured).
        "depth_limit_reached",
        #: At least one tool call was denied in this run (maps to exit 3 with
        #: --fail-on-tool-denied).
        "tool_denied",
        #: Last handled error (kind + message) for JSON output.
        "error_kind",
        "error_message",
        #: Final assistant answer of the last turn (JSON ``content``).
        "last_content",
        #: Tool calls/results of the last turn (JSON ``tool_calls``).
        "tool_calls",
        # ---- headless run options (set by entry.CLI.configure_headless) ----
        "print_mode",
        "output_format",
        "quiet",
        "yes",
        "allowed_tools",
        "fail_on_tool_denied",
        "max_turns",
        "cwd",
        #: True when stdout must contain only results/events (pipe, -p, -q, json).
        "machine_output",
        "init_role",
        "role_name",
        "console",
        "chat_manager",
        "role_manager",
        "role",
        "printer",
        "client",
        "cmd_handler",
        "bindings",
        "current_mode",
        "interactive_round",
        #: K02: one-shot flag so the group-trim notice is printed at most once.
        "_trim_notified",
        "chat_start_time",
        "is_temp_session",
        "chat",
        "chat_history_dir",
        "session",
        "history",
        "context_manager",
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
    ):
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
        self.chat_manager = chat_manager or chat_mgr
        self.role_manager = role_manager or role_mgr
        self.context_manager = context_manager or ctx_mgr
        self.role: Role = self.role_manager.get_role(self.role_name)
        self.printer = self._make_printer()
        self.client = client or self._create_client()
        # Providers capture their own stdout console at construction time; in
        # machine mode every diagnostic (verbose request dumps, error bodies) must
        # use stderr, so re-point the client *and* its provider console here.
        self._sync_client_console()
        self.cmd_handler = CmdHandler(self)

        self.bindings = KeyBindings()

        self.current_mode: str = TEMP_MODE

        self.interactive_round = cfg["INTERACTIVE_ROUND"]
        self._trim_notified = False
        self.chat_start_time = None
        self.is_temp_session = True
        self.chat = Chat(title="", history=[])

        # Get and create chat history directory from configuration
        self.chat_history_dir = Path(cfg["CHAT_HISTORY_DIR"])
        # if not self.chat_history_dir.exists():
        #     self.chat_history_dir.mkdir(parents=True, exist_ok=True)

        # Detect OS and Shell if set to auto
        if cfg["OS_NAME"] == DEFAULT_OS_NAME:
            cfg["OS_NAME"] = detect_os(cfg)
        if cfg["SHELL_NAME"] == DEFAULT_SHELL_NAME:
            cfg["SHELL_NAME"] = detect_shell(cfg)

        if self.verbose:
            # Print verbose configuration (values can come from config/env files: never markup)
            self.console.print("Loading Configuration:", style="bold cyan")
            self.console.print(f"Config file path: {safe_text(CONFIG_PATH)}")
            for key, value in cfg.items():
                display_value = "****" if key == "API_KEY" and value else value
                self.console.print(f"  {safe_text(key):<20}: {safe_text(display_value)}")
            self.console.print(f"Current role: {safe_text(self.role_name)}")
            self.console.print(Markdown("---", code_theme=cfg["CODE_THEME"]))

        # v0.19 K04/K21: do not build a prompt_toolkit session for one-shot/pipe
        # runs (it is useless there and can print warnings); the REPL builds its
        # own session lazily in prepare_chat_loop(). This also keeps -p/--json TTY
        # invocations free of prompt_toolkit cost/noise (K04 D3).
        self.session = None
        if self.interactive and not self.machine_output:
            # Disable prompt_toolkit warning when use non-tty input,
            # e.g. when use pipe or redirect
            _origin_stderr = None
            if not sys.stdin.isatty():
                _origin_stderr = sys.stderr
                sys.stderr = open(devnull, "w", encoding="utf-8")
            try:
                self.session = PromptSession(key_bindings=self.bindings)
            finally:
                if _origin_stderr:
                    sys.stderr.flush()
                    sys.stderr.close()
                    sys.stderr = _origin_stderr

    def _sync_client_console(self) -> None:
        """Point the LLM client and its provider at this CLI's console.

        ``LLMClient`` and every provider capture ``get_console()`` (stdout) when
        constructed. In machine-output modes their diagnostics — verbose request
        dumps, ``Error Response: {...}`` bodies, skipped-tool warnings — must go
        to stderr so structured stdout stays parseable. Tool announcements are
        handled separately by ``yaicli.tools.console`` in :meth:`configure_headless`.
        """
        if self.client is None:  # pragma: no cover - defensive
            return
        try:
            self.client.interactive = bool(self.interactive and not self.machine_output)
            self.client.console = self.console
        except AttributeError:  # pragma: no cover - client without these slots
            return
        try:
            provider = getattr(self.client, "provider", None)
            if provider is not None and hasattr(provider, "console"):
                provider.console = self.console
        except (AttributeError, TypeError):  # pragma: no cover - exotic provider object
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
            return Printer(console=self.console, content_markdown=False, machine=True, events=events)
        return Printer(console=self.console, content_markdown=content_markdown)

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
    ) -> None:
        """Apply the v0.19 headless/scripting flags (called once by entry.main).

        ``print_mode`` forces the one-shot contract (plain output, no prompts).
        ``output_format`` is one of ``text``/``json``/``stream-json``.
        ``--yes``/``--allowed-tools`` are stored for the K06 approval gate.
        """
        self.print_mode = bool(print_mode)
        if output_format not in OUTPUT_FORMATS:
            output_format = DEFAULT_OUTPUT_FORMAT
        self.output_format = output_format
        self.quiet = bool(quiet)
        self.yes = bool(yes)
        self.allowed_tools = list(allowed_tools or [])
        self.fail_on_tool_denied = bool(fail_on_tool_denied)
        if max_turns is not None:
            self.max_turns = int(max_turns)
            cfg["MAX_TOOL_CALL_DEPTH"] = self.max_turns
        else:
            self.max_turns = cfg["MAX_TOOL_CALL_DEPTH"]
        self.cwd = cwd

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
        """Write one stream-json event (one JSON object per line) to stdout."""
        if self.output_format != "stream-json":
            return
        sys.stdout.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()

    def _write_text_result(self, content: Optional[str]) -> None:
        """Write the final text answer to stdout with exactly one trailing newline."""
        if not self.machine_output or self.output_format != "text" or content is None:
            return
        if content == "":
            return
        sys.stdout.write(content.rstrip("\n") + "\n")
        sys.stdout.flush()

    @staticmethod
    def _parse_arguments(arguments: Any) -> Any:
        """Best-effort JSON decoding of tool-call arguments for structured output."""
        if isinstance(arguments, str):
            try:
                return json.loads(arguments)
            except (ValueError, TypeError):
                return arguments
        return arguments

    def _record_error(self, exc: BaseException) -> None:
        """Store a classified error for JSON output/stderr rendering."""
        try:
            agent_error = classify_exception(exc)
            self.error_kind = agent_error.kind
            self.error_message = agent_error.message or str(exc)
        except Exception:  # pragma: no cover - classifier must never break the CLI
            self.error_kind = ErrorKind.UNKNOWN
            self.error_message = str(exc)

    def _error_payload(self) -> Optional[Dict[str, Any]]:
        """The JSON ``error`` field: ``null`` on success, ``{kind, message}``."""
        if not self.error_message:
            return None
        kind = self.error_kind.value if isinstance(self.error_kind, ErrorKind) else str(self.error_kind)
        return {"kind": kind, "message": self.error_message}

    def _build_result(self) -> Dict[str, Any]:
        """The single JSON object emitted by ``--output-format json``."""
        return {
            "content": self.last_content or "",
            "tool_calls": [
                {"name": call.get("name", ""), "arguments": call.get("arguments"), "result": call.get("result")}
                for call in self.tool_calls
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "model": cfg.get("MODEL", ""),
            "provider": cfg.get("PROVIDER", ""),
            "error": self._error_payload(),
            "exit_code": self.exit_code,
        }

    def _record_tool_calls(self, messages: Optional[List[ChatMessage]]) -> None:
        """Extract tool calls/results of the last user turn from the client messages.

        The client mutates the message list in place (no client.py changes needed):
        assistant messages carry ``tool_calls`` and the following ``role=tool``
        messages carry the matching results via ``tool_call_id``.
        """
        calls: List[Dict[str, Any]] = []
        if not messages:
            self.tool_calls = calls
            return
        last_user = -1
        for index, message in enumerate(messages):
            if getattr(message, "role", None) == "user":
                last_user = index
        pending: Dict[str, Dict[str, Any]] = {}
        for message in messages[last_user + 1 :]:
            role = getattr(message, "role", None)
            if role == "assistant":
                for tool_call in getattr(message, "tool_calls", None) or []:
                    entry: Dict[str, Any] = {
                        "name": getattr(tool_call, "name", ""),
                        "arguments": self._parse_arguments(getattr(tool_call, "arguments", None)),
                        "result": None,
                    }
                    calls.append(entry)
                    call_id = getattr(tool_call, "id", None)
                    if call_id:
                        pending[call_id] = entry
            elif role == "tool":
                content = message.content or ""
                if self._is_denied_result(content):
                    self.tool_denied = True
                entry = pending.pop(getattr(message, "tool_call_id", None) or "", None)
                if entry is not None and entry.get("result") is None:
                    entry["result"] = content
                else:
                    calls.append(
                        {
                            "name": getattr(message, "name", None) or "",
                            "arguments": None,
                            "result": content,
                        }
                    )
        self.tool_calls = calls

    @staticmethod
    def _is_denied_result(content: str) -> bool:
        """True when a tool result represents a denied tool call."""
        lowered = (content or "").lower()
        return any(marker in lowered for marker in TOOL_DENIED_MARKERS)

    def _emit_tool_events_from(self, messages: List[ChatMessage], cursor: int) -> int:
        """Emit stream-json tool_call/tool_result events for messages[cursor:]."""
        if self.output_format != "stream-json":
            return len(messages)
        for message in messages[cursor:]:
            role = getattr(message, "role", None)
            if role == "assistant":
                for tool_call in getattr(message, "tool_calls", None) or []:
                    self._emit_event(
                        {
                            "type": "tool_call",
                            "name": getattr(tool_call, "name", ""),
                            "arguments": self._parse_arguments(getattr(tool_call, "arguments", None)),
                        }
                    )
            elif role == "tool":
                content = message.content or ""
                if self._is_denied_result(content):
                    self.tool_denied = True
                self._emit_event(
                    {
                        "type": "tool_result",
                        "name": getattr(message, "name", None) or "",
                        "result": content,
                    }
                )
        return len(messages)

    def _instrument_tool_events(self, stream_iterator, messages: List[ChatMessage]):
        """Tee the LLM stream so stream-json tool events are emitted per round.

        ``RefreshLive`` marks the end of a completion round; the client executes the
        tools when the generator is resumed, so new messages are inspected right
        after the next chunk arrives (or when the stream ends).
        """
        cursor = len(messages)

        def _forward():
            nonlocal cursor
            send_value = None
            boundary_pending = False
            while True:
                try:
                    if send_value is None:
                        chunk = next(stream_iterator)
                    else:
                        chunk = stream_iterator.send(send_value)
                except StopIteration:
                    cursor = self._emit_tool_events_from(messages, cursor)
                    return
                send_value = None
                if boundary_pending:
                    cursor = self._emit_tool_events_from(messages, cursor)
                    boundary_pending = False
                if isinstance(chunk, RefreshLive):
                    boundary_pending = True
                try:
                    send_value = yield chunk
                except GeneratorExit:  # pragma: no cover - consumer stopped early
                    return

        return _forward()

    def _finalize_exit_code(self) -> int:
        """Resolve the process exit code from the public state contract."""
        if self.interrupted:
            self.exit_code = EXIT_SIGINT
        elif self.tool_denied and self.fail_on_tool_denied:
            self.exit_code = EXIT_TOOL_DENIED
        elif self.had_error:
            self.exit_code = EXIT_ERROR
        elif self.depth_limit_reached and cfg.get("EXIT_ON_DEPTH_LIMIT", True):
            self.exit_code = EXIT_ERROR
        else:
            self.exit_code = EXIT_OK
        return self.exit_code

    def _finalize_headless(self) -> int:
        """Emit the final structured output (json/stream-json) and resolve the code."""
        self._finalize_exit_code()
        if self.exit_code != EXIT_OK and not self.error_message:
            # Describe flag-only outcomes (depth limit / denied tool) so JSON and
            # stream-json consumers never see a non-zero code with a null error.
            if self.depth_limit_reached:
                self.error_kind = ErrorKind.DEPTH_LIMIT
                self.error_message = "tool-call depth limit reached"
            elif self.tool_denied and self.fail_on_tool_denied:
                self.error_kind = ErrorKind.TOOL
                self.error_message = "a tool call was denied"
        if self.output_format == "json":
            payload = json.dumps(self._build_result(), ensure_ascii=False, default=str)
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()
        elif self.output_format == "stream-json":
            self._emit_event({"type": "usage", "prompt_tokens": 0, "completion_tokens": 0})
            self._emit_event(
                {
                    "type": "done",
                    "exit_code": self.exit_code,
                    "error": self._error_payload(),
                }
            )
        return self.exit_code

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

    def get_prompt_tokens(self) -> list[tuple[str, str]]:
        """Return prompt tokens for current mode"""
        mode_icon = "💬" if self.current_mode == CHAT_MODE else "🚀" if self.current_mode == EXEC_MODE else "📝"
        return [("class:qmark", f" {mode_icon} "), ("class:prompt", "> ")]

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
        budget = resolve_context_budget(cfg, cfg.get("MODEL", ""))
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
        """Save current chat history to a file using session manager."""
        # Update title if provided
        if title:
            self.chat.title = title

        # Save chat and get the saved title back
        try:
            saved_title = self.chat_manager.save_chat(self.chat)
        except ChatSaveError as e:
            self.console.print(f"Failed to save chat: {safe_text(e)}", style="red")
            return

        # Session list will be refreshed automatically by the save method
        self.console.print(f"Chat saved as: {safe_text(saved_title)}", style="bold green")

        # Mark session as persistent if it was temporary
        if self.is_temp_session:
            self.is_temp_session = False
            self.chat_start_time = int(time.time())
            self.console.print(
                "Session is now marked as persistent and will be auto-saved on exit.", style="bold green"
            )

    def _list_chats(self) -> None:
        """List all saved chat sessions using session manager."""
        chats: list[Chat] = self.chat_manager.list_chats()

        if not chats:
            self.console.print("No saved chats found.", style="yellow")
            return

        self.console.print("Saved Chats:", style="bold underline")
        for chat in chats:
            index = chat.idx
            title = chat.title
            date = chat.date

            if date:
                self.console.print(
                    f"[dim]{safe_text(index)}.[/dim] [bold blue]{safe_text(title)}[/bold blue] - {safe_text(date)}"
                )
            else:
                self.console.print(f"[dim]{safe_text(index)}.[/dim] [bold blue]{safe_text(title)}[/bold blue]")

    def _refresh_chats(self) -> None:
        """Force refresh the chat list."""
        self.chat_manager.refresh_chats()

    def _load_chat_by_index(self, index: str) -> bool:
        """Load a chat session by its index using session manager."""
        if not self.chat_manager.validate_chat_index(index):
            self.console.print("Invalid chat index.", style="bold red")
            return False

        chat_data = self.chat_manager.load_chat_by_index(index)

        if not chat_data:
            self.console.print("Invalid chat index or chat not found.", style="bold red")
            return False

        self.chat = chat_data
        self.chat_start_time = chat_data.date
        self.is_temp_session = False

        self.console.print(f"Loaded chat: {safe_text(self.chat.title)}", style="bold green")
        return True

    def _delete_chat_by_index(self, index: str) -> bool:
        """Delete a chat session by its index using session manager."""
        if not self.chat_manager.validate_chat_index(index):
            self.console.print("Invalid chat index.", style="bold red")
            return False

        chat_data = self.chat_manager.load_chat_by_index(index)

        if not chat_data:
            self.console.print("Invalid chat index or chat not found.", style="bold red")
            return False

        if chat_data.path is None:
            self.console.print(f"Chat has no associated file to delete: {safe_text(chat_data.title)}", style="bold red")
            return False

        if self.chat_manager.delete_chat(chat_data.path):
            self.console.print(f"Deleted chat: {safe_text(chat_data.title)}", style="bold green")
            return True
        else:
            self.console.print(f"Failed to delete chat: {safe_text(chat_data.title)}", style="bold red")
            return False

    # ------------------- Special commands -------------------
    def _handle_special_commands(self, user_input: str) -> Union[bool, str]:
        """Handle special command return: True-continue loop, False-exit loop, str-non-special command"""
        return self.cmd_handler.handle_command(user_input)

    def _build_messages(self, user_input: str, images: Optional[List[ImageData]] = None) -> list[ChatMessage]:
        """Build message list for LLM API with @ file references expanded."""
        # Create the message list with system prompt
        messages = [ChatMessage(role="system", content=self.role.prompt)]

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
            provider = cfg.get("PROVIDER", "").lower()
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
        return ToolPolicy(enable_functions=cfg["ENABLE_FUNCTIONS"], enable_mcp=cfg["ENABLE_MCP"])

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
        messages = self._build_messages(user_input, images=images)
        if not self.machine_output and self.role.name != DefaultRoleNames.CODER:
            self.console.print("Assistant:", style="bold green")
        try:
            response_iterator = self.client.completion_with_tools(
                messages,
                stream=cfg["STREAM"],
                tool_policy=self._get_tool_policy(),
            )
            if self.output_format == "stream-json":
                response_iterator = self._instrument_tool_events(response_iterator, messages)

            content, _ = self.printer.display_stream(response_iterator)

            # Wave-2 coordination (K02/K06): the client reports depth/denial
            # outcomes through its own flags; mirror them onto the CLI contract.
            if getattr(self.client, "depth_limit_reached", False) is True:
                self.depth_limit_reached = True
            if getattr(self.client, "tool_denied", False) is True:
                self.tool_denied = True

            # The 'messages' list is modified by the client in-place
            return content, messages
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

    def _process_user_input(self, user_input: str, images: Optional[List[ImageData]] = None) -> bool:
        """Process user input: get response, print, update history, maybe execute.
        Returns True to continue REPL, False to exit on critical error.
        """
        content, updated_messages = self._handle_llm_response(user_input, images=images)
        self._record_tool_calls(updated_messages)

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
                edited_cmd = prompt("Edit command: ", default=cmd).strip()
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
                subprocess.call(executed_cmd, shell=True)
            except Exception as e:
                self.console.print(f"Failed to execute command: {safe_text(e)}", style="red")
        elif _input != "e":
            self.console.print("Execution cancelled.", style="yellow")

    # ------------------- REPL Methods -------------------
    def prepare_chat_loop(self) -> None:
        """Setup key bindings and history for interactive modes."""
        self.current_mode = CHAT_MODE
        self._setup_key_bindings()

        # K21: a read-only HOME (containers/CI/sandbox) must not crash the REPL
        # because the history file cannot be created; fall back to in-memory
        # history and keep going.
        history = None
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.touch(exist_ok=True)
            history = LimitedFileHistory(HISTORY_FILE, max_entries=cfg["MAX_HISTORY"])
        except OSError as e:
            get_error_console().print(
                f"Warning: could not set up prompt history ({safe_text(e)}); using in-memory history.",
                style="yellow",
            )

        # Set up the prompt session with command history
        try:
            self.session = PromptSession(
                key_bindings=self.bindings,
                history=history,
                auto_suggest=AutoSuggestFromHistory() if cfg.get("AUTO_SUGGEST", True) else None,
                enable_history_search=True,
                completer=AtPathCompleter(),
                complete_while_typing=True,  # Enable auto-completion for @ trigger
                complete_in_thread=True,  # Don't block on completion
            )
        except Exception as e:
            self.console.print(f"Error initializing prompt session history: {safe_text(e)}", style="red")
            self.session = PromptSession(key_bindings=self.bindings)

    def _setup_key_bindings(self) -> None:
        """Setup keyboard shortcuts: Shift+Tab for mode switching, Ctrl+O for the
        last full tool output."""

        @self.bindings.add("s-tab")  # Shift+Tab to switch mode
        def _(event: KeyPressEvent) -> None:
            """Switch between chat and exec mode."""
            self.current_mode = EXEC_MODE if self.current_mode == CHAT_MODE else CHAT_MODE
            self.set_role(DefaultRoleNames.SHELL if self.current_mode == EXEC_MODE else self.init_role)

        @self.bindings.add("c-o")  # Ctrl+O: expand the last tool output
        def _(event: KeyPressEvent) -> None:
            """Print the last tool result in full without leaving the prompt."""
            from prompt_toolkit.application import run_in_terminal

            run_in_terminal(self._show_last_tool_output)

    def _show_last_tool_output(self) -> None:
        """Print the last tool result in full (``Ctrl+O`` / ``/show-output``)."""
        from .tools import show_last_tool_output

        show_last_tool_output(self.console)

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
        self.print_help()

    def print_help(self):
        self.console.print("Press [bold yellow]Shift+Tab[/bold yellow] to switch mode")
        help_cmd = "|".join(CMD_HELP)
        self.console.print(f"{help_cmd:<19}: Show help message")
        self.console.print(f"{CMD_CLEAR:<19}: Clear chat history")
        self.console.print(f"{CMD_HISTORY:<19}: Show chat history")
        self.console.print(f"{CMD_LIST_CHATS:<19}: List saved chats")
        save_cmd = f"{CMD_SAVE_CHAT} <title>"
        self.console.print(f"{save_cmd:<19}: Save current chat")
        load_cmd = f"{CMD_LOAD_CHAT} <index>"
        self.console.print(f"{load_cmd:<19}: Load a saved chat")
        delete_cmd = f"{CMD_DELETE_CHAT} <index>"
        self.console.print(f"{delete_cmd:<19}: Delete a saved chat")
        self.console.print(f"{'/add <path>':<19}: Add @file/dir to context")
        self.console.print(
            f"{'/context, /ctx':<19}: Show context/token usage; manage context (list, add, remove, clear, budget)"
        )
        self.console.print(
            f"{CMD_COMPACT + ' [keep_rounds]':<19}: Compact history, keeping the last N turn groups (default 5)"
        )
        self.console.print(
            f"{'/permissions [revoke <tool-or-index>]':<19}: List/revoke tool permissions and session grants"
        )
        self.console.print(f"{'/show-output':<19}: Show the last tool output in full (same as Ctrl+O)")
        self.console.print("[dim]  Tip: Type '@' for path completion, use Tab/arrows to select[/dim]")
        self.console.print(f"{'!<command>':<19}: Execute shell command directly (e.g., !ls -al)")
        cmd_exit = f"{CMD_EXIT}|Ctrl+D"
        self.console.print(f"{cmd_exit:<19}: Exit")
        self.console.print(f"{'Ctrl+C':<19}: Clear input / cancel turn; press twice to exit")
        cmd_mode = f"{CMD_MODE} {CHAT_MODE}|{EXEC_MODE}"
        self.console.print(f"{cmd_mode:<19}: Switch mode (Case insensitive)", style="dim")

    def _run_repl(self) -> None:
        """Run the main Read-Eval-Print Loop (REPL).

        SIGINT semantics (v0.19 K04): a single Ctrl-C clears the current input
        line / cancels the current turn and keeps the session alive; a second
        Ctrl-C within ``DOUBLE_CTRL_C_WINDOW_SECONDS`` exits the REPL normally
        (Ctrl-D does the same). The REPL never turns a single interrupt into
        exit 130; one-shot/generation interrupts keep their 130 contract.
        """
        self.prepare_chat_loop()
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
                self.console.print(Markdown("---", code_theme=cfg["CODE_THEME"]))

            # --- Read ---
            try:
                user_input = self.session.prompt(self.get_prompt_tokens)
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

        # Auto-save chat history when exiting if there are messages and not a temporary session
        if not self.is_temp_session and self.chat.history:
            self._save_chat(self.chat.title)

        if not quiet:
            self.console.print("\nExiting YAICLI... Goodbye!", style="bold green")

    def _run_once(
        self, user_input: str, shell: bool = False, code: bool = False, images: Optional[List[ImageData]] = None
    ) -> None:
        """Handle default mode"""
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

        if chat:
            # If user provided a title, try to load that chat
            if user_input and isinstance(user_input, str):
                loaded_chat = self.chat_manager.load_chat_by_title(user_input)
                if loaded_chat:
                    self.chat = loaded_chat
                    self.is_temp_session = False
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
        redirect_stdout = self.machine_output
        original_stdout = sys.stdout
        if redirect_stdout:
            sys.stdout = sys.stderr
        try:
            return LLMClient(
                provider_name=cfg["PROVIDER"].lower(),
                verbose=self.verbose,
                config=cfg,
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
