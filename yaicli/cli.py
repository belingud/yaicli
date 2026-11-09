import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from .chat import Chat, FileChatManager, chat_mgr, resolve_default_chat_dir
from .cmd_handler import COMMAND_INFO, CmdHandler
from .config import cfg
from .console import get_console, get_error_console, safe_text, untrusted_text
from .const import (
    CHAT_MODE,
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
    EXIT_ERROR,
    EXIT_OK,
    EXIT_SIGINT,
    EXIT_TOOL_DENIED,
    ErrorKind,
    classify_exception,
)
from .exceptions import ChatLoadError, ChatSaveError, YaicliError
from .printer import Printer
from .project_context import load_project_context
from .role import Role, RoleManager, role_mgr
from .schemas import ChatMessage, ImageData, RefreshLive, ToolPolicy
from .tokens import (
    estimate_context_usage,
    resolve_context_budget,
    trim_messages_to_budget,
    trim_oldest_group,
)
from .tools.approval import ToolApprovalManager
from .usage import Usage, estimate_cost
from .utils import detect_os, detect_shell, filter_command

#: Lazily imported prompt_toolkit / LLM-client names (K08).
#:
#: They stay module attributes so the existing test seams
#: ``patch("yaicli.cli.PromptSession")`` / ``patch("yaicli.cli.LLMClient")`` keep working, while
#: one-shot/headless runs never pay the prompt_toolkit import and the REPL never pays the provider
#: SDK import at startup.
PromptSession = None  # type: ignore[assignment]
prompt = None  # type: ignore[assignment]
PromptStyle = None  # type: ignore[assignment]
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


def _prompt_style() -> Any:
    """Build the REPL prompt style on first REPL use (needs prompt_toolkit).

    Only the info line above the input is styled: the model name uses the terminal's
    light/dim palette so it recedes next to the crisp input line. Everything else
    keeps prompt_toolkit's default styles (colored ``qmark`` icon, bold ``>``).
    """
    global PromptStyle
    if PromptStyle is None:
        from prompt_toolkit.styles import Style

        PromptStyle = Style.from_dict({"prompt-model": "fg:ansibrightblack nobold"})
    return PromptStyle


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
        "resume",
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
        "_client",
        "cmd_handler",
        "bindings",
        "current_mode",
        "interactive_round",
        #: K02: one-shot flag so the group-trim notice is printed at most once.
        "_trim_notified",
        #: K12: project instruction files are discovered once, on the first request.
        "_project_context_loaded",
        "_project_context_text",
        #: last-known context usage percentage for the prompt (updated once per
        #: turn / history-mutating command; the prompt render must never estimate).
        "_context_percent",
        #: history + input + images of the last turn, used by ``/retry``.
        "_last_turn_snapshot",
        #: Text typed while the assistant was generating (Ctrl+O watcher); used as
        #: the initial prompt buffer for the next input.
        "_pending_prompt_text",
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
        self.chat_manager = chat_manager or chat_mgr
        if chat_manager is None and hasattr(self.chat_manager, "chat_dir"):
            # ``--cwd`` may have changed the process cwd after import: re-resolve
            # the per-project session directory (v0.21 K13).
            self.chat_manager.chat_dir = resolve_default_chat_dir()
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
        self.cmd_handler = CmdHandler(self)

        # Created lazily by prepare_chat_loop()/_setup_key_bindings(); prompt_toolkit is
        # only imported for real REPL/exec runs (K08).
        self.bindings = None

        self.current_mode: str = TEMP_MODE

        self.interactive_round = cfg["INTERACTIVE_ROUND"]
        self._trim_notified = False
        # K12: project instruction files (AGENTS.md/CLAUDE.md/.yaicli.md) are loaded
        # lazily on the first request so CLI construction stays write/read-free.
        self._project_context_loaded = False
        self._project_context_text = ""
        # prompt context percentage is cached (never computed during render) and
        # the last turn is snapshotted once so ``/retry`` can replay it cleanly.
        self._context_percent: Optional[float] = None
        self._last_turn_snapshot: Optional[Dict[str, Any]] = None
        # Typed-ahead text captured by the generation-time Ctrl+O watcher.
        self._pending_prompt_text = ""
        self.chat_start_time = None
        self.is_temp_session = True
        self.chat = Chat(title="", history=[])

        # Session directory actually used by the manager (per-project by default).
        manager_dir = getattr(self.chat_manager, "chat_dir", None)
        self.chat_history_dir = (
            Path(manager_dir) if isinstance(manager_dir, (str, Path)) else resolve_default_chat_dir()
        )

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

        # v0.19 K04/K21: one-shot/pipe runs never build a prompt_toolkit session; since
        # K08 the REPL builds the only session in prepare_chat_loop().
        self.session = None

    @property
    def client(self):
        """The LLM client, constructed on first use (K08 lazy client)."""
        if self._client is None:
            self._client = self._create_client()
            self._sync_client_console()
        return self._client

    @client.setter
    def client(self, value: Any) -> None:
        """Allow tests/integrations to inject a ready client (``cli.client = mock``)."""
        self._client = value

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
        resume: bool = False,
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

    # ------------------- v0.22 K17 usage / cost -------------------
    @staticmethod
    def _usage_dict_int(usage: Optional[Dict[str, Any]], key: str) -> int:
        """Read a non-negative integer field from a usage snapshot (never raises)."""
        if not isinstance(usage, dict):
            return 0
        value = usage.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return max(0, value)

    def _client_usage_snapshot(self) -> Optional[Dict[str, Any]]:
        """Return the live client's session usage snapshot, or ``None``.

        The private client slot is used on purpose: emitting a result or a usage
        line must never construct the LLM client as a side effect. Any missing
        client/API degrades to ``None`` instead of breaking output.
        """
        client = getattr(self, "_client", None)
        if client is None:
            return None
        snapshot = getattr(client, "usage_snapshot", None)
        if not callable(snapshot):
            return None
        try:
            data = snapshot()
        except Exception:  # pragma: no cover - usage reporting must never break the CLI
            return None
        return data if isinstance(data, dict) else None

    def _usage_payload(self) -> Dict[str, Any]:
        """The JSON ``usage`` object: real session usage or a zeroed fallback."""
        snapshot = self._client_usage_snapshot()
        if snapshot is not None:
            return snapshot
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
            "estimated": False,
            "requests": 0,
            "cost_usd": None,
            "models": {},
            "tools": {"count": 0, "duration_ms": 0.0, "result_chars": 0},
        }

    def _turn_finish_reason(self) -> Optional[str]:
        """Last provider ``finish_reason`` (only when the client exposed a string)."""
        client = getattr(self, "_client", None)
        if client is None:
            return None
        try:
            value = getattr(client, "last_finish_reason", None)
        except Exception:  # pragma: no cover
            return None
        return value if isinstance(value, str) else None

    def _turn_output_truncated(self) -> bool:
        """True when the last turn stopped at MAX_TOKENS (``finish_reason=length``)."""
        client = getattr(self, "_client", None)
        if client is None:
            return False
        try:
            if getattr(client, "output_truncated", False) is True:
                return True
        except Exception:  # pragma: no cover
            pass
        return self._turn_finish_reason() == "length"

    @staticmethod
    def _show_usage_enabled() -> bool:
        """Whether the interactive per-turn usage line is enabled (``SHOW_USAGE``)."""
        try:
            return bool(cfg.get("SHOW_USAGE", True))
        except Exception:  # pragma: no cover - config lookups must never break a turn
            return True

    def _format_usage_line(
        self,
        before: Optional[Dict[str, Any]],
        after: Optional[Dict[str, Any]],
        elapsed_seconds: float,
        finish_reason: Optional[str],
    ) -> Optional[str]:
        """Build the dim per-turn line (``tokens … · $… · 1.2s · stop``).

        ``before``/``after`` are session snapshots; the difference is this turn's
        usage. Returns ``None`` when no usage data is available at all (graceful
        degrade); unknown model pricing simply omits the cost segment.
        """
        if not isinstance(after, dict):
            return None
        prompt = max(0, self._usage_dict_int(after, "prompt_tokens") - self._usage_dict_int(before, "prompt_tokens"))
        completion = max(
            0, self._usage_dict_int(after, "completion_tokens") - self._usage_dict_int(before, "completion_tokens")
        )
        parts: List[str] = []
        if prompt or completion:
            parts.append(f"tokens {prompt:,} in / {completion:,} out")
            try:
                model = str(cfg.get("MODEL") or "")
                cost = estimate_cost(model, Usage(prompt, completion, prompt + completion), cfg)
            except Exception:  # pragma: no cover - cost display must never break a turn
                cost = None
            if cost is not None:
                parts.append(f"${cost:.4f}")
        else:
            parts.append("tokens n/a")
        parts.append(f"{max(0.0, elapsed_seconds):.1f}s")
        if finish_reason:
            parts.append(str(finish_reason))
        return " · ".join(parts)

    def _build_result(self) -> Dict[str, Any]:
        """The single JSON object emitted by ``--output-format json``."""
        return {
            "content": self.last_content or "",
            "tool_calls": [
                {"name": call.get("name", ""), "arguments": call.get("arguments"), "result": call.get("result")}
                for call in self.tool_calls
            ],
            "usage": self._usage_payload(),
            "finish_reason": self._turn_finish_reason(),
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
            usage_event: Dict[str, Any] = {"type": "usage", **self._usage_payload()}
            finish_reason = self._turn_finish_reason()
            if finish_reason is not None:
                usage_event["finish_reason"] = finish_reason
            self._emit_event(usage_event)
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

    # ------------------- prompt (model / context) -------------------
    @staticmethod
    def _prompt_model_name() -> str:
        """Return the short model name for the prompt (``""`` when unknown)."""
        try:
            model = cfg.get("MODEL") if hasattr(cfg, "get") else ""
        except Exception:  # pragma: no cover - config lookups must never break the prompt
            return ""
        if not isinstance(model, str):
            return ""
        # Provider-prefixed ids ("openai/gpt-4o") are shown without the prefix.
        model = model.strip().rsplit("/", 1)[-1]
        return model if len(model) <= 32 else model[:31] + "…"

    def get_prompt_tokens(self) -> list[tuple[str, str]]:
        """Return the input-line REPL prompt tokens: mode icon and ``> ``.

        Only the mode icon and the terminator live on the input line, so the cursor
        always sits at the same column regardless of the model name or the working
        directory. The session info moved to :meth:`get_prompt_info_tokens` (rendered
        on the line above by :meth:`get_prompt_message`).
        """
        mode = getattr(self, "current_mode", TEMP_MODE)
        mode_icon = "💬" if mode == CHAT_MODE else "🚀" if mode == EXEC_MODE else "📝"
        return [("class:qmark", f" {mode_icon} "), ("class:prompt", "> ")]

    def get_prompt_info_tokens(self) -> list[tuple[str, str]]:
        """Return the info fragments rendered on the line above the input.

        Only the model and the cached context percentage are shown. The role is
        deliberately omitted: a custom ``DEFAULT_ROLE`` (e.g. ``master``) is easy to
        mistake for git state, and the REPL prompt never inspects the repository.
        Everything degrades to "omitted" for bare/legacy CLI objects built via
        ``CLI.__new__`` or when the config/history is unavailable.
        """
        segments: list[tuple[str, str]] = []
        model = self._prompt_model_name()
        if model:
            segments.append(("class:prompt-model", model))
        percent = getattr(self, "_context_percent", None)
        if isinstance(percent, (int, float)) and not isinstance(percent, bool):
            segments.append(("class:prompt-context", f"{max(0.0, float(percent)):.0f}%"))
        tokens: list[tuple[str, str]] = []
        for index, (class_name, text) in enumerate(segments):
            if index:
                tokens.append(("class:prompt-sep", " · "))
            tokens.append((class_name, text))
        if tokens:
            # The leading space aligns the info line with the icon/input line below.
            tokens.insert(0, ("class:prompt-info", " "))
        return tokens

    def get_prompt_message(self) -> list[tuple[str, str]]:
        """Return the full prompt message: info line above, input line below.

        ``prompt_toolkit`` renders the fragments before the last newline on their own
        line above the input and the fragments after it as the inline prompt. The
        double newline leaves one blank line between the info line and the input, so
        the info reads as a header and the input line stays visually separate. With
        no info to show this degrades to the plain one-line prompt (no empty line),
        and the context percentage is the cached ``_context_percent`` value (updated
        once per completed turn and after history-mutating commands): this callback
        runs on every keypress, so it must never estimate tokens here.
        """
        prompt = self.get_prompt_tokens()
        info = self.get_prompt_info_tokens()
        if not info:
            return prompt
        return [*info, ("class:prompt-info", "\n\n"), *prompt]

    def _update_context_percent(self) -> None:
        """Recompute the cached prompt context percentage.

        Never called from the prompt render path: the value is refreshed once per
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
                config=cfg if hasattr(cfg, "get") else None,
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

        # v0.21 K13: persist model/provider/role/cwd/created_at/updated_at.
        try:
            self._apply_session_metadata(self.chat)
        except AttributeError:
            # Legacy/bare Chat-like object (tests/integrations): keep saving it.
            pass

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
        # the loaded conversation has its own turn history — forget the old
        # /retry snapshot and refresh the prompt's context percentage immediately.
        self._last_turn_snapshot = None
        self._update_context_percent()

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

    # ------------------- Session metadata / resume (v0.21 K13) -------------------
    def _apply_session_metadata(self, chat: Chat) -> None:
        """Record model/provider/role/cwd on a session before it is saved.

        Resumed sessions keep their recorded values (they describe how the
        conversation was produced); new/legacy sessions get the current config.
        """
        model = str(cfg.get("MODEL", "") or "")
        provider = str(cfg.get("PROVIDER", "") or "")
        try:
            cwd = os.getcwd()
        except OSError:  # pragma: no cover - deleted cwd
            cwd = ""
        if not chat.model:
            chat.model = model
        if not chat.provider:
            chat.provider = provider
        chat.role = chat.role or str(self.role_name or "")
        if not chat.cwd:
            chat.cwd = cwd
        chat.update_metadata()

    @staticmethod
    def _session_notice(chat: Chat) -> str:
        """One-line description of a resumed session (title + recorded metadata)."""
        model = chat.model or "unknown"
        provider = chat.provider or "unknown"
        role = chat.role or "unknown"
        return (
            f'Resumed session "{chat.title}" '
            f"(model={model}, provider={provider}, role={role}, messages={len(chat.history)})"
        )

    def _resume_latest_session(self) -> bool:
        """Make the newest saved session of this project the active one (--resume).

        Returns:
            bool: True when an existing session was resumed, False when a new
            session was started after printing an explicit notice.
        """
        try:
            latest = self.chat_manager.latest_chat()
        except ChatLoadError as e:
            get_error_console().print(f"Could not load the latest session: {safe_text(e)}", style="yellow")
            latest = None

        if latest is None:
            get_error_console().print(
                "No saved session found for this project; starting a new session.",
                style="yellow",
            )
            self.chat = Chat(title="", history=[])
            self._apply_session_metadata(self.chat)
            self.is_temp_session = True
            return False

        self.chat = latest
        self.is_temp_session = False
        self.chat_start_time = latest.date
        self.console.print(self._session_notice(latest), style="bold green")
        return True

    def _start_chat_by_title(self, title: str) -> None:
        """Load the session named ``title`` or explicitly start a new one.

        v0.21 K13: a missed title must never silently create a session; print
        one explicit notice instead (the old behaviour made the user believe
        they were resuming a saved conversation).
        """
        loaded: Optional[Chat] = None
        try:
            loaded = self.chat_manager.load_chat_by_title(title)
        except ChatLoadError as e:
            get_error_console().print(f"Could not load session '{safe_text(title)}': {safe_text(e)}", style="yellow")

        if loaded is not None and loaded.path is not None:
            self.chat = loaded
            self.is_temp_session = False
            self.chat_start_time = loaded.date
            return

        self.chat = loaded if loaded is not None else Chat(title=title, history=[])
        self.is_temp_session = False
        get_error_console().print(
            f'No saved session titled "{safe_text(title)}" for this project; starting a new session.',
            style="yellow",
        )

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
            result = load_project_context()
        except Exception:  # pragma: no cover - defensive: never fail the request
            result = None
        if result is not None and result.has_content:
            text = result.text
        self._project_context_text = text
        return text

    def _build_messages(self, user_input: str, images: Optional[List[ImageData]] = None) -> list[ChatMessage]:
        """Build message list for LLM API with @ file references expanded."""
        # Create the message list with system prompt. K12: the project instruction files
        # are appended to the role prompt (after it, before persistent/@ context); with
        # no files found the payload stays byte-identical to the pre-K12 behaviour.
        system_prompt = self.role.prompt
        project_context = self._get_project_context()
        if project_context:
            system_prompt = f"{system_prompt}\n\n{project_context}"
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
                stream=cfg["STREAM"],
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
        """Snapshot the conversation + input *before* a turn so ``/retry`` can replay it.

        The snapshot is restored by :meth:`_retry_last_turn`, which drops any
        partial/duplicated assistant or tool messages a failed turn produced
        before sending the same input again.
        """
        try:
            history = getattr(getattr(self, "chat", None), "history", None)
            history_snapshot = list(history) if isinstance(history, list) else []
        except (AttributeError, TypeError):  # pragma: no cover - bare/legacy CLI objects
            history_snapshot = []
        self._last_turn_snapshot = {
            "input": user_input,
            "images": list(images or []),
            "history": history_snapshot,
        }

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

    def _process_user_input(self, user_input: str, images: Optional[List[ImageData]] = None) -> bool:
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
            history = _limited_history_class()(HISTORY_FILE, max_entries=cfg["MAX_HISTORY"])
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
                auto_suggest=AutoSuggestFromHistory() if cfg.get("AUTO_SUGGEST", True) else None,
                enable_history_search=True,
                # composite completer — slash commands plus the existing @path
                # completer (kept as the patchable ``AtPathCompleter`` seam).
                completer=_repl_completer_class()(path_completer=_at_path_completer_class()()),
                complete_while_typing=True,  # Enable auto-completion for @ trigger
                complete_in_thread=True,  # Don't block on completion
                style=_prompt_style(),  # light model name on the info line
            )
        except Exception as e:
            self.console.print(f"Error initializing prompt session history: {safe_text(e)}", style="red")
            self.session = PromptSessionClass(key_bindings=self.bindings, style=_prompt_style())

    def _setup_key_bindings(self) -> None:
        """Setup keyboard shortcuts: Shift+Tab mode switch, Ctrl+O viewer and
        multiline input (Alt+Enter / Ctrl+J insert a newline, Enter still submits).
        Imports prompt_toolkit lazily (K08)."""
        from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

        if self.bindings is None:
            self.bindings = KeyBindings()

        @self.bindings.add("s-tab")  # Shift+Tab to switch mode
        def _(event: KeyPressEvent) -> None:
            """Switch between chat and exec mode."""
            self.current_mode = EXEC_MODE if self.current_mode == CHAT_MODE else CHAT_MODE
            self.set_role(DefaultRoleNames.SHELL if self.current_mode == EXEC_MODE else self.init_role)

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
        self.print_help()

    def print_help(self):
        """Print the REPL help table.

        Command rows come from ``cmd_handler.COMMAND_INFO`` — the same metadata the
        slash-command completion menu uses, so help and completion cannot drift
        apart. Rows are printed without Rich markup so usage strings with
        ``[optional]`` arguments are shown verbatim.
        """
        self.console.print("Press [bold yellow]Shift+Tab[/bold yellow] to switch mode")
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
                self.console.print(Markdown("---", code_theme=cfg["CODE_THEME"]))

            # --- Read ---
            from .debug_log import debug_log

            debug_log("prompt.begin")
            pending_text = getattr(self, "_pending_prompt_text", "")
            if pending_text:
                self._pending_prompt_text = ""
            try:
                user_input = self.session.prompt(self.get_prompt_message, default=pending_text)
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
            if getattr(self, "resume", False):
                # v0.21 K13: continue the newest session of this project
                # (explicit notice + new session when the project has none).
                self._resume_latest_session()
            elif user_input and isinstance(user_input, str):
                # `ai --chat "<title>"`: resume that session, or print an explicit
                # notice that a new session is being started (no silent fallback).
                self._start_chat_by_title(user_input)
            self._apply_session_metadata(self.chat)
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
            return _llm_client_class()(
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
