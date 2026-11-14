"""Command handler for processing special commands in YAICLI."""

import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple, Union

from rich.markdown import Markdown
from rich.padding import Padding
from rich.prompt import Prompt
from rich.table import Table

from .config import cfg
from .console import safe_text, strip_control_chars
from .const import (
    CHAT_MODE,
    CMD_ADD,
    CMD_CLEAR,
    CMD_CONTEXT,
    CMD_DELETE_CHAT,
    CMD_EXIT,
    CMD_HELP,
    CMD_HISTORY,
    CMD_LIST_CHATS,
    CMD_LOAD_CHAT,
    CMD_MODE,
    CMD_PLAN,
    CMD_SAVE_CHAT,
    CMD_TODO,
    EXEC_MODE,
    DefaultRoleNames,
)
from .tokens import ContextUsage, estimate_context_usage, trim_messages_to_budget
from .tools import workspace
from .tools.approval import PermissionRule

#: Slash command to manually compact the conversation (v0.19 K02).
#: Defined here (not in const.py) because the context-economy commands are owned by
#: this module; ``cli.print_help`` imports it from here.
CMD_COMPACT = "/compact"
#: Slash command to list/revoke tool permissions (v0.19 K06).
#: Defined here (not in const.py) for the same reason as :data:`CMD_COMPACT`.
CMD_PERMISSIONS = "/permissions"
#: Slash command to re-print the last tool result in full (same as ``Ctrl+O``).
CMD_SHOW_OUTPUT = "/show-output"
#: Slash command to restore the last file mutation made by the agent (v0.21 K11).
#: Defined here (not in const.py) for the same reason as :data:`CMD_COMPACT`.
CMD_UNDO = "/undo"
#: Slash command to show session token usage and estimated cost (v0.22 K17).
#: Defined here (not in const.py) for the same reason as :data:`CMD_COMPACT`.
CMD_COST = "/cost"
#: Slash command to show or switch the model for the current session.
#: Defined here (not in const.py) for the same reason as :data:`CMD_COMPACT`.
CMD_MODEL = "/model"
#: Slash command to show or switch the assistant role.
#: Defined here (not in const.py) for the same reason as :data:`CMD_COMPACT`.
CMD_ROLE = "/role"
#: Slash command to re-run the last user turn from its pre-turn snapshot.
#: Defined here (not in const.py) for the same reason as :data:`CMD_COMPACT`.
CMD_RETRY = "/retry"
#: Turn groups kept by ``/compact`` when no argument is given.
DEFAULT_COMPACT_KEEP_ROUNDS = 5
#: ``/context`` subcommands that print the estimated usage breakdown.
CONTEXT_BUDGET_SUBCOMMANDS = ("budget", "stats", "usage")


@dataclass(frozen=True)
class CommandInfo:
    """One slash command's help/completion metadata.

    ``command`` is the token inserted by the REPL completion menu and
    ``description`` its one-line explanation. ``usage`` is the spelling shown in
    the help table (defaults to ``command``) and ``aliases`` are alternate
    registered slash spellings offered by completion with the same description.
    """

    command: str
    description: str
    usage: Optional[str] = None
    aliases: Tuple[str, ...] = ()

    @property
    def help_text(self) -> str:
        """The usage column shown by ``CLI.print_help``."""
        return self.usage or self.command


#: Single source of truth for the REPL help table *and* the slash-command
#: completion menu: ``CLI.print_help`` renders it and :class:`SlashCommandCompleter`
#: offers it, so the two can never diverge. Keep it in sync with
#: ``CmdHandler.commands`` (tests/test_command_handler.py asserts the parity).
COMMAND_INFO: Tuple[CommandInfo, ...] = (
    CommandInfo(CMD_HELP[0], "Show help message", usage="|".join(CMD_HELP)),
    CommandInfo(CMD_CLEAR, "Clear chat history"),
    CommandInfo(CMD_HISTORY, "Show chat history"),
    CommandInfo(CMD_LIST_CHATS, "List saved chats", usage=f"{CMD_LIST_CHATS}|/chats", aliases=("/chats",)),
    CommandInfo(CMD_SAVE_CHAT, "Save current chat", usage=f"{CMD_SAVE_CHAT} <title>"),
    CommandInfo(CMD_LOAD_CHAT, "Load a saved chat", usage=f"{CMD_LOAD_CHAT} <index>"),
    CommandInfo(
        CMD_DELETE_CHAT,
        "Delete a saved chat",
        usage=f"{CMD_DELETE_CHAT}|/delete <index>",
        aliases=("/delete",),
    ),
    CommandInfo(CMD_ADD, "Add @file/dir to context", usage=f"{CMD_ADD} <path>"),
    CommandInfo(
        CMD_CONTEXT[0],
        "Show context/token usage; manage context (list, add, remove, clear, budget)",
        usage="/context, /ctx",
        aliases=("/ctx",),
    ),
    CommandInfo(
        CMD_PLAN,
        "Plan mode: toggle, or plan a task; list/show/edit/review/resume/clear/abort",
        usage=f"{CMD_PLAN} [task|list [--all]|show [id]|edit|review [id]|resume [id]|clear [--done|--all]|abort]",
    ),
    CommandInfo(CMD_TODO, "Show the current plan todos"),
    CommandInfo(CMD_COST, "Show session token usage and estimated cost"),
    CommandInfo(
        CMD_COMPACT,
        f"Compact history, keeping the last N turn groups (default {DEFAULT_COMPACT_KEEP_ROUNDS})",
        usage=f"{CMD_COMPACT} [keep_rounds]",
    ),
    CommandInfo(
        CMD_PERMISSIONS,
        "List/revoke tool permissions and session grants",
        usage=f"{CMD_PERMISSIONS} [revoke <tool-or-index>]",
    ),
    CommandInfo(CMD_SHOW_OUTPUT, "View this turn's tool outputs (same as Ctrl+O)"),
    CommandInfo(CMD_UNDO, "Undo the last file change made by a tool"),
    CommandInfo(CMD_MODEL, "Show or switch the model for this session", usage=f"{CMD_MODEL} [name]"),
    CommandInfo(CMD_ROLE, "Show or switch the assistant role", usage=f"{CMD_ROLE} [name]"),
    CommandInfo(CMD_RETRY, "Re-run the last user turn (e.g. after an API error)"),
    CommandInfo(CMD_EXIT, "Exit (Ctrl+D also exits)", usage=f"{CMD_EXIT}|Ctrl+D"),
    CommandInfo(CMD_MODE, "Switch mode (Case insensitive)", usage=f"{CMD_MODE} {CHAT_MODE}|{EXEC_MODE}"),
)


def command_completions() -> Tuple[Tuple[str, str], ...]:
    """Return ``(command, description)`` pairs for the REPL completion menu.

    Canonical commands come first, then every slash alias with the same
    description. Non-slash aliases (``?``) are not offered: completion only fires
    on a leading ``/``.
    """
    entries = []
    for info in COMMAND_INFO:
        entries.append((info.command, info.description))
        for alias in info.aliases:
            if alias.startswith("/"):
                entries.append((alias, info.description))
    return tuple(entries)


class CmdHandler:
    """Handler for special commands used in the CLI."""

    def __init__(self, cli):
        """Initialize command handler with reference to CLI instance.

        Args:
            cli: CLI instance to access methods and properties
        """
        self.cli = cli
        self.commands = {
            # Register special commands with their handlers
            CMD_HELP[0] if isinstance(CMD_HELP, tuple) else CMD_HELP: self.handle_help,
            "?": self.handle_help,  # support ? as help command
            CMD_EXIT: self.handle_exit,
            CMD_CLEAR: self.handle_clear,
            CMD_HISTORY: self.handle_history,
            CMD_LIST_CHATS: self.handle_list,
            "/chats": self.handle_list,  # support /chats as alias for list command
            CMD_SAVE_CHAT: self.handle_save,
            CMD_LOAD_CHAT: self.handle_load,
            CMD_DELETE_CHAT: self.handle_delete,
            "/delete": self.handle_delete,  # long-form alias (accepted since prefixes matched)
            CMD_MODE: self.handle_mode,
            CMD_ADD: self.handle_add_context,
            CMD_CONTEXT[0] if isinstance(CMD_CONTEXT, tuple) else CMD_CONTEXT: self.handle_context,
            "/ctx": self.handle_context,
            CMD_PLAN: self.handle_plan,
            CMD_TODO: self.handle_todo,
            CMD_COMPACT: self.handle_compact,
            CMD_PERMISSIONS: self.handle_permissions,
            CMD_SHOW_OUTPUT: self.handle_show_output,
            CMD_UNDO: self.handle_undo,
            CMD_COST: self.handle_cost,
            CMD_MODEL: self.handle_model,
            CMD_ROLE: self.handle_role,
            CMD_RETRY: self.handle_retry,
        }

    def handle_add_context(self, command_input: str = "") -> bool:
        """Handle /add command to add file/dir to context.

        Args:
            command_input: "/add path/to/file"

        Returns:
            True to continue REPL
        """
        try:
            parts = shlex.split(command_input)
        except ValueError as e:
            self.cli.console.print(f"Error parsing command: {safe_text(e)}", style="red")
            return True

        if len(parts) < 2:
            self.cli.console.print(f"Usage: {CMD_ADD} <path>", style="yellow")
            return True

        path = parts[1]
        if path.startswith("@"):
            path = path[1:]
        if self.cli.verbose:
            self.cli.console.print(f"[dim][DEBUG] Adding context: {safe_text(path)}[/dim]")
        self.cli.context_manager.add(path)
        return True

    # ------------------- context economy commands (v0.19 K02) -------------------
    def _history(self) -> list:
        """Return the conversation history as a list (defensive against mocks)."""
        chat = getattr(self.cli, "chat", None)
        history = getattr(chat, "history", None) if chat is not None else None
        return history if isinstance(history, list) else []

    def _role_prompt(self) -> str:
        """Return the active role prompt text (empty when unavailable)."""
        role = getattr(self.cli, "role", None)
        prompt = getattr(role, "prompt", "") if role is not None else ""
        return prompt if isinstance(prompt, str) else ""

    def _project_context(self) -> str:
        """Return the auto-loaded project instruction block (``""`` when unavailable)."""
        getter = getattr(self.cli, "_get_project_context", None)
        if not callable(getter):
            return ""
        try:
            project = getter()
        except Exception:  # defensive: /context must never fail on a project file
            return ""
        return project if isinstance(project, str) else ""

    def _persistent_context(self) -> list:
        """Return the persistent ``/add`` context messages (``[]`` when unavailable)."""
        manager = getattr(self.cli, "context_manager", None)
        getter = getattr(manager, "get_context_messages", None) if manager is not None else None
        if not callable(getter):
            return []
        try:
            messages = getter()
        except Exception:  # defensive: /context must never fail on a context file
            return []
        return messages if isinstance(messages, list) else []

    def _context_usage(self) -> "ContextUsage":
        """Estimate the current context usage for the ``/context`` command.

        Passes the parts the request assembler sends besides the role prompt
        (project instructions block + persistent ``/add`` context) so the shown
        total matches what the provider will actually receive.
        """
        config = cfg if hasattr(cfg, "get") else None
        provider = str(config.get("PROVIDER", "") or "") if config is not None else ""
        return estimate_context_usage(
            self._history(),
            config=config,
            system_text=self._role_prompt(),
            provider=provider,
            extra_system_text=self._project_context(),
            extra_messages=self._persistent_context(),
        )

    @staticmethod
    def _cfg_int(key: str, default: int = 0) -> int:
        """Read an integer config value, tolerating mocks/legacy strings."""
        config = cfg if hasattr(cfg, "get") else None
        if config is None:
            return default
        try:
            value = config.get(key)
        except Exception:  # defensive: a broken config mapping must not break /context
            return default
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _print_context_usage(self) -> None:
        """Print the estimated usage breakdown with the window source and reserve."""
        usage = self._context_usage()
        console = self.cli.console
        source = usage.source or "default"
        if source == "default":
            # An unknown model must say so and tell the user how to fix it.
            detail = usage.detail or "assumed for unknown model"
            source_text = f"{detail}; set MODEL_CONTEXT_WINDOWS to override"
        else:
            source_text = usage.detail or ""
        window_line = f"  window        : {usage.window_tokens:,} tokens (source: {source}"
        if source_text:
            window_line += f" · {source_text}"
        window_line += ")"
        console.print("Context usage (estimated):", style="bold")
        console.print(window_line)
        console.print(f"  role prompt   : {usage.system_tokens:,} tokens")
        console.print(f"  project ctx   : {usage.project_tokens:,} tokens")
        console.print(f"  /add context  : {usage.extra_tokens:,} tokens")
        console.print(f"  history       : {usage.history_tokens:,} tokens (tool output {usage.tool_output_tokens:,})")
        console.print(f"  overhead      : {usage.overhead_tokens:,} tokens")
        console.print(
            f"  total         : {usage.total_tokens:,} / {usage.budget_tokens:,} tokens ({usage.used_percent:.1f}%)"
        )
        console.print(f"  remaining     : {usage.remaining_tokens:,} tokens")
        max_tokens = self._cfg_int("MAX_TOKENS", 1024)
        safety_tokens = self._cfg_int("CONTEXT_SAFETY_TOKENS", 1024)
        console.print(
            f"  reserve       : {usage.reserve_tokens:,} (MAX_TOKENS {max_tokens:,} + safety {safety_tokens:,})"
        )
        # markup=False keeps the literal ``[keep_rounds]`` (Rich markup would eat it).
        console.print("  Use /compact [keep_rounds] to drop older turn groups.", style="dim", markup=False)

    def handle_compact(self, command_input: str = "") -> bool:
        """Handle ``/compact [keep_rounds]``: drop old whole turn groups from history.

        Only complete turn groups are removed, so the tool_call <-> tool pairing
        stays valid. Prints the estimated token counts before/after.

        Args:
            command_input: "/compact" or "/compact 3"

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.split()
        keep_rounds = DEFAULT_COMPACT_KEEP_ROUNDS
        if len(parts) > 1:
            try:
                keep_rounds = int(parts[1])
            except (TypeError, ValueError):
                keep_rounds = 0
            if keep_rounds < 1:
                self.cli.console.print(f"Usage: {CMD_COMPACT} [keep_rounds]", style="yellow")
                return True

        history = self._history()
        if not history:
            self.cli.console.print("Chat history is empty; nothing to compact.", style="yellow")
            return True

        result = trim_messages_to_budget(history, budget=0, keep_recent_groups=keep_rounds)
        if not result.removed_messages:
            self.cli.console.print(
                f"Nothing to compact: history already has at most {keep_rounds} turn groups.", style="dim"
            )
            return True

        self.cli.chat.history = result.messages
        self.cli.console.print(
            f"Compacted context: {result.tokens_before:,} -> {result.tokens_after:,} estimated tokens "
            f"({result.removed_count} message(s) removed, keeping the last {keep_rounds} turn groups).",
            style="bold green",
        )
        # The conversation moved on: refresh the prompt's context % and drop the
        # /retry snapshot (restoring it would undo the compaction).
        self._clear_retry_snapshot()
        self._refresh_context_percent()
        return True

    # ------------------- permission commands (v0.19 K06) -------------------
    def _approval_manager(self):
        """Return the ToolApprovalManager backing the current session, if any."""
        client = getattr(self.cli, "client", None)
        manager = getattr(client, "approval", None)
        if manager is None:
            manager = getattr(self.cli, "approval", None)
        return manager

    @staticmethod
    def _permission_names(value) -> list:
        """Normalize a session/persistent name collection to a sorted list."""
        if isinstance(value, (set, frozenset, list, tuple)):
            return sorted(str(item) for item in value)
        return []

    def _print_permissions(self, manager) -> None:
        """Print session approvals, persistent allowlist entries and indexed rules."""
        console = self.cli.console
        session = self._permission_names(getattr(manager, "session_allow", None))
        persisted = self._permission_names(getattr(manager, "persistent_allow", None))
        rules = [rule for rule in getattr(manager, "persistent_rules", None) or [] if isinstance(rule, PermissionRule)]
        path = getattr(manager, "permissions_path", "")

        console.print("Tool permissions:", style="bold")
        console.print(f"  Session approvals (this run only): {len(session)}")
        if session:
            for name in session:
                console.print(f"    - {safe_text(name)}")
        else:
            console.print("    (none)")
        console.print(f"  Persistent always_allow: {len(persisted)}  {safe_text(path)}")
        if persisted:
            for name in persisted:
                console.print(f"    - {safe_text(name)}")
        else:
            console.print("    (none)")
        console.print(f"  Persistent rules: {len(rules)}")
        if rules:
            for index, rule in enumerate(rules, start=1):
                console.print(f"    {index}. {safe_text(rule.describe())}")
        else:
            console.print("    (none)")
        console.print(f"[dim]  Use {CMD_PERMISSIONS} revoke <tool-or-index> to remove a persistent permission.[/dim]")

    def handle_permissions(self, command_input: str = "") -> bool:
        """Handle ``/permissions`` and ``/permissions revoke <tool-or-index>``.

        Lists the persistent rules and session approvals, or revokes one persistent
        allowlist entry / rule (by tool name or by the 1-based rule index shown by the
        listing) so the tool asks again. ``remove`` is accepted as an alias of
        ``revoke``.

        Args:
            command_input: "/permissions" or "/permissions revoke <tool-or-index>"

        Returns:
            True to continue the REPL loop
        """
        manager = self._approval_manager()
        if manager is None:
            self.cli.console.print("No tool permission store is available in this session.", style="yellow")
            return True
        try:
            parts = shlex.split(command_input)
        except ValueError as e:
            self.cli.console.print(f"Error parsing command: {safe_text(e)}", style="red")
            return True

        args = parts[1:] if parts else []
        if not args:
            self._print_permissions(manager)
            return True

        action = args[0].lower()
        if action in ("revoke", "remove", "rm"):
            if len(args) < 2:
                self.cli.console.print(f"Usage: {CMD_PERMISSIONS} revoke <tool-or-index>", style="yellow")
                return True
            target = args[1]
            revoke = getattr(manager, "revoke", None)
            if not callable(revoke):
                self.cli.console.print("This permission store does not support revocation.", style="yellow")
                return True
            try:
                revoked = revoke(target)
            except OSError as e:
                self.cli.console.print(f"Could not update the permission file: {safe_text(e)}", style="red")
                return True
            if revoked:
                self.cli.console.print(
                    f"Revoked {safe_text(revoked)}. The tool will ask for approval again.", style="bold green"
                )
            else:
                self.cli.console.print(f"No permission matched '{safe_text(target)}'.", style="yellow")
                self._print_permissions(manager)
            return True

        self.cli.console.print(f"Unknown sub-command: {safe_text(action)}", style="yellow")
        self.cli.console.print(safe_text(f"Usage: {CMD_PERMISSIONS} [revoke <tool-or-index>]"), style="dim")
        return True

    def handle_show_output(self) -> bool:
        """Handle /show-output: open the full-screen viewer for this turn's outputs.

        The viewer lists every tool result of the current turn; closing it
        restores the REPL. Same entry point as ``Ctrl+O``.

        Returns:
            True to continue the REPL loop
        """
        opener = getattr(self.cli, "_open_tool_output_viewer", None)
        if callable(opener):
            opener()
        else:  # pragma: no cover - bare/legacy CLI objects without the viewer
            from .tools import show_last_tool_output

            show_last_tool_output(self.cli.console)
        return True

    def handle_undo(self) -> bool:
        """Handle /undo: restore the last file mutation the agent made.

        The undo stack is populated by ``yaicli.tools.execute_tool_call`` (K11): an
        overwritten/edited/deleted/moved file is restored from its backup, and a
        file/directory the agent created is deleted. Prints what was done (or a
        friendly message when there is nothing to undo).

        Returns:
            True to continue the REPL loop
        """
        outcome = workspace.undo_last()
        if outcome is None:
            self.cli.console.print(
                "Nothing to undo: no file changes were recorded in this session.",
                style="yellow",
            )
            return True

        verb = "restore" if outcome.restored else "remove"
        self.cli.console.print(
            f"Undid the last file change ({safe_text(outcome.tool)}): {verb} "
            f"{len(outcome.restored) + len(outcome.deleted)} path(s).",
            style="bold green" if not outcome.errors else "bold yellow",
        )
        for path in outcome.restored:
            self.cli.console.print(f"  restored: {safe_text(path)}", style="green")
        for path in outcome.deleted:
            self.cli.console.print(f"  deleted: {safe_text(path)}", style="green")
        for error in outcome.errors:
            self.cli.console.print(f"  failed: {safe_text(error)}", style="red")
        if outcome.errors:
            self.cli.console.print(
                "The undo was only partially applied; fix the reported errors and retry.",
                style="yellow",
            )
        return True

    # ------------------- usage / cost commands (v0.22 K17) -------------------
    @staticmethod
    def _usage_int(snapshot, key: str) -> int:
        """Read a non-negative integer field from a usage snapshot (never raises)."""
        if not isinstance(snapshot, dict):
            return 0
        value = snapshot.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return max(0, value)

    @staticmethod
    def _usage_cost(value):
        """Return a finite float cost or ``None`` (unknown pricing/invalid value)."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _cost_snapshot(self):
        """Return the live client's usage snapshot, or ``None`` when unavailable.

        Uses the private client slot: ``/cost`` must not construct the LLM client
        as a side effect (and must never raise on a mock/legacy client).
        """
        client = getattr(self.cli, "_client", None)
        if client is None:
            return None
        getter = getattr(client, "usage_snapshot", None)
        if not callable(getter):
            return None
        try:
            snapshot = getter()
        except Exception:  # pragma: no cover - usage reporting must never break the REPL
            return None
        return snapshot if isinstance(snapshot, dict) else None

    def handle_cost(self) -> bool:
        """Handle ``/cost``: show session tokens, per-model usage and estimated cost.

        Reports provider-reported plus estimated usage, the estimated USD cost
        (``unknown model pricing`` when no price is known), tool call metrics and
        the last provider finish reason.

        Returns:
            True to continue the REPL loop
        """
        console = self.cli.console
        snapshot = self._cost_snapshot()
        if snapshot is None:
            console.print(
                "No token usage is available in this session yet; make a request, then run /cost again.",
                style="yellow",
            )
            return True

        prompt = self._usage_int(snapshot, "prompt_tokens")
        completion = self._usage_int(snapshot, "completion_tokens")
        total = self._usage_int(snapshot, "total_tokens") or (prompt + completion)
        requests = self._usage_int(snapshot, "requests")
        cached = self._usage_int(snapshot, "cached_tokens")
        reasoning = self._usage_int(snapshot, "reasoning_tokens")
        estimated = bool(snapshot.get("estimated"))
        models = snapshot.get("models")
        has_models = isinstance(models, dict) and bool(models)
        if requests == 0 and total == 0 and not has_models:
            console.print(
                "No usage recorded yet in this session. Make a request, then run /cost again.",
                style="yellow",
            )
            return True

        label = " (estimated)" if estimated else ""
        console.print("Session usage:", style="bold")
        console.print(f"  tokens    : {prompt:,} in / {completion:,} out ({total:,} total){label}")
        if cached:
            console.print(f"  cached    : {cached:,} tokens")
        if reasoning:
            console.print(f"  reasoning : {reasoning:,} tokens")
        console.print(f"  requests  : {requests:,}")

        cost = self._usage_cost(snapshot.get("cost_usd"))
        if cost is None:
            console.print("  cost      : unknown model pricing (set MODEL_PRICING for an estimate)")
        else:
            console.print(f"  cost      : ${cost:.4f} estimated USD")

        tools = snapshot.get("tools")
        if isinstance(tools, dict):
            tool_count = self._usage_int(tools, "count")
            duration = tools.get("duration_ms", 0)
            duration_text = f"{float(duration):.0f} ms" if self._usage_cost(duration) is not None else "0 ms"
            result_chars = self._usage_int(tools, "result_chars")
            console.print(f"  tools     : {tool_count:,} call(s), {duration_text}, {result_chars:,} result chars")

        client = getattr(self.cli, "_client", None)
        finish = getattr(client, "last_finish_reason", None) if client is not None else None
        if isinstance(finish, str) and finish:
            console.print(f"  last stop : {safe_text(finish)}")

        if has_models:
            console.print("Per model:", style="bold")
            for name, data in models.items():
                if not isinstance(data, dict):
                    continue
                model_in = self._usage_int(data, "prompt_tokens")
                model_out = self._usage_int(data, "completion_tokens")
                model_cost = self._usage_cost(data.get("cost_usd"))
                cost_text = f"${model_cost:.4f}" if model_cost is not None else "unknown pricing"
                console.print(f"  {safe_text(str(name))}: {model_in:,} in / {model_out:,} out, {cost_text}")
        return True

    # ------------------- model / role / retry commands -------------------
    @staticmethod
    def _cfg_value(key: str, default=""):
        """Read a config value defensively (never raise on mock/legacy config)."""
        try:
            if hasattr(cfg, "get"):
                value = cfg.get(key, default)
                return value if value is not None else default
        except Exception:  # pragma: no cover - config lookups must never break a command
            return default
        return default

    @staticmethod
    def _set_cfg_value(key: str, value) -> bool:
        """Write one config value for this session (returns False when unsupported)."""
        try:
            cfg[key] = value
            return True
        except Exception:  # pragma: no cover - read-only/legacy config objects
            return False

    def _invalidate_client(self) -> None:
        """Drop the lazily-created LLM client so the next request rebuilds it."""
        try:
            self.cli._client = None
        except (AttributeError, TypeError):  # pragma: no cover - bare/legacy CLI objects
            pass

    def _refresh_context_percent(self) -> None:
        """Refresh the CLI's cached context-usage percentage after a history change."""
        updater = getattr(self.cli, "_update_context_percent", None)
        if not callable(updater):  # pragma: no cover - lightweight CLI stand-ins
            return
        try:
            updater()
        except Exception:  # pragma: no cover - prompt decoration must never break a command
            pass

    def _clear_retry_snapshot(self) -> None:
        """Forget the ``/retry`` snapshot: the conversation it belonged to moved on."""
        try:
            self.cli._last_turn_snapshot = None
        except (AttributeError, TypeError):  # pragma: no cover - bare/legacy CLI objects
            pass

    def _current_role_name(self) -> str:
        """Return the active role name (``""`` when unknown)."""
        value = getattr(self.cli, "role_name", "")
        return value if isinstance(value, str) else ""

    def _available_role_names(self) -> list:
        """Return the registered role ids/names (empty when the manager cannot list)."""
        manager = getattr(self.cli, "role_manager", None)
        lister = getattr(manager, "list_roles", None)
        if not callable(lister):
            return []
        try:
            entries = lister()
        except Exception:  # pragma: no cover - listing must never break the command
            return []
        if not isinstance(entries, (list, tuple)):
            return []
        names: list = []
        for entry in entries:
            if isinstance(entry, dict):
                name = entry.get("id") or entry.get("name")
            else:
                name = getattr(entry, "name", None)
            if isinstance(name, str) and name and name not in names:
                names.append(name)
        return names

    def _resolve_role_name(self, requested: str) -> Optional[str]:
        """Resolve a role name exactly, then case-insensitively; ``None`` if unknown."""
        names = self._available_role_names()
        if requested in names:
            return requested
        folded = requested.casefold()
        for name in names:
            if name.casefold() == folded:
                return name
        if names:
            return None
        # A manager that cannot list roles may still resolve the exact name.
        manager = getattr(self.cli, "role_manager", None)
        getter = getattr(manager, "get_role", None)
        if not callable(getter):  # pragma: no cover - lightweight CLI stand-ins
            return None
        try:
            role = getter(requested)
        except Exception:
            return None
        name = getattr(role, "name", None)
        return name if isinstance(name, str) and name else requested

    def handle_model(self, command_input: str = "") -> bool:
        """Handle ``/model [name]``: show or switch the model for this session.

        Switching writes ``cfg["MODEL"]``, drops the lazily-created provider client
        so the next request rebuilds it, and keeps the chat history. The change is
        session-only; the notice names the previous model so it can be restored.

        Args:
            command_input: "/model" or "/model <name>"

        Returns:
            True to continue the REPL loop
        """
        console = self.cli.console
        current = self._cfg_value("MODEL")
        provider = self._cfg_value("PROVIDER")
        parts = command_input.split(maxsplit=1)
        requested = parts[1].strip() if len(parts) > 1 else ""

        if not requested:
            console.print(f"Model    : {safe_text(str(current or 'unknown'))}")
            console.print(f"Provider : {safe_text(str(provider or 'unknown'))}")
            console.print(
                f"[dim]  Use {CMD_MODEL} <name> to switch the model for this session; "
                f"changes are not written to the config file.[/dim]"
            )
            return True

        if requested == current:
            console.print(f"Already using model '{safe_text(requested)}'.", style="yellow")
            return True

        if not self._set_cfg_value("MODEL", requested):
            console.print("Could not update the session model for this CLI.", style="red")
            return True

        # The provider/client captured the old model at construction: rebuild it on
        # the next request so the switch takes effect without touching the history.
        self._invalidate_client()
        self._refresh_context_percent()
        old = str(current) if current else "unknown"
        console.print(
            f"Model switched: {safe_text(old)} -> {safe_text(requested)} (session only).",
            style="bold green",
        )
        console.print(
            f"[dim]  Chat history is kept and the provider client is rebuilt on the next request. "
            f"Revert with {CMD_MODEL} {safe_text(old)}, or restart to use the configured model.[/dim]"
        )
        return True

    def handle_role(self, command_input: str = "") -> bool:
        """Handle ``/role [name]``: show or switch the assistant role.

        Role names resolve exactly first, then case-insensitively. An unknown role
        prints the available names instead of raising. Switching keeps the prompt
        in sync (``CLI.set_role`` updates the role prompt); a non-shell role returns
        the session to chat mode.

        Args:
            command_input: "/role" or "/role <name>"

        Returns:
            True to continue the REPL loop
        """
        console = self.cli.console
        current = self._current_role_name()
        available = self._available_role_names()
        parts = command_input.split(maxsplit=1)
        requested = parts[1].strip() if len(parts) > 1 else ""

        if not requested:
            console.print(f"Role: {safe_text(current or 'unknown')}", style="bold")
            if available:
                console.print(f"[dim]  Available: {safe_text(', '.join(available))}[/dim]")
            console.print(f"[dim]  Use {CMD_ROLE} <name> to switch the assistant role.[/dim]")
            return True

        resolved = self._resolve_role_name(requested)
        if resolved is None:
            console.print(f"Unknown role: {safe_text(requested)}", style="yellow")
            if available:
                console.print(f"Available roles: {safe_text(', '.join(available))}")
                console.print("[dim]  Use --list-roles outside the REPL for role details.[/dim]")
            else:  # pragma: no cover - a manager without a role list
                console.print("Use --list-roles outside the REPL to see the available roles.", style="dim")
            return True

        if resolved == current:
            console.print(f"Already using role '{safe_text(resolved)}'.", style="yellow")
            return True

        setter = getattr(self.cli, "set_role", None)
        if not callable(setter):  # pragma: no cover - lightweight CLI stand-ins
            console.print("This CLI cannot switch roles in the current session.", style="yellow")
            return True

        setter(resolved)
        # Keep Shift+Tab/mode switching consistent with the newly selected role.
        try:
            self.cli.init_role = resolved
        except (AttributeError, TypeError):  # pragma: no cover - bare/legacy CLI objects
            pass
        if resolved != DefaultRoleNames.SHELL and getattr(self.cli, "current_mode", None) == EXEC_MODE:
            self.cli.current_mode = CHAT_MODE
        self._refresh_context_percent()
        old = current or "unknown"
        console.print(f"Role switched: {safe_text(old)} -> {safe_text(resolved)}.", style="bold green")
        console.print(f"[dim]  Revert with {CMD_ROLE} {safe_text(old)}, or restart to use the configured role.[/dim]")
        return True

    def handle_retry(self) -> bool:
        """Handle ``/retry``: re-run the last user turn from its pre-turn snapshot.

        The CLI snapshots history + input + images before each turn, so a turn
        that failed (e.g. an API error) can be replayed without duplicating the
        partial assistant/tool messages it produced.

        Returns:
            True to continue the REPL loop
        """
        retry = getattr(self.cli, "_retry_last_turn", None)
        if not callable(retry):
            self.cli.console.print("Nothing to retry: this CLI has no turn snapshot.", style="yellow")
            return True
        try:
            retry()
        except Exception as e:  # the REPL must survive a failed retry
            self.cli.console.print(f"Retry failed: {safe_text(e)}", style="red")
        return True

    def handle_context(self, command_input: str = "") -> bool:
        """Handle /context (or /ctx) command.

        With no subcommand (or ``budget``/``stats``) it prints the estimated context
        usage; the file-context subcommands stay exactly as before.

        Subcommands:
            list: List context items
            clear: Clear context
            remove <path>: Remove item from context
            add <path>: Add item (same as /add)
            budget: Show the estimated usage breakdown (alias: stats/usage)

        Args:
            command_input: "/context <subcmd> [args]"
        """
        try:
            parts = shlex.split(command_input)
        except ValueError as e:
            self.cli.console.print(f"Error parsing command: {safe_text(e)}", style="red")
            return True

        if len(parts) < 2:
            # Bare ``/context`` = usage block + the legacy ``/add`` list. The
            # subcommand hint is not repeated here: it is long, already rendered
            # by ``/help``/the docstring, and belongs to the error path below.
            self._print_context_usage()
            self.cli.context_manager.list_items()
            return True

        subcmd = parts[1].lower()

        if subcmd in CONTEXT_BUDGET_SUBCOMMANDS:
            self._print_context_usage()
        elif subcmd == "list":
            self.cli.context_manager.list_items()
        elif subcmd == "clear":
            self.cli.context_manager.clear()
        elif subcmd == "add":
            if len(parts) < 3:
                self.cli.console.print("Usage: /context add <path>", style="yellow")
            else:
                path = parts[2]
                if path.startswith("@"):
                    path = path[1:]
                self.cli.context_manager.add(path)
        elif subcmd in ("remove", "rm", "delete", "del"):
            if len(parts) < 3:
                self.cli.console.print("Usage: /context remove <path>", style="yellow")
            else:
                self.cli.context_manager.remove(parts[2])
        else:
            self.cli.console.print(f"Unknown sub-command: {safe_text(subcmd)}", style="yellow")
            self.cli.console.print("Available: list, clear, add <path>, remove <path>, budget", style="dim")

        return True

    # ------------------- plan mode commands (v0.24 K23) -------------------
    @staticmethod
    def _plan_enabled() -> bool:
        """Whether persistent plan mode is enabled (``PLAN_ENABLED``; defaults on)."""
        try:
            return bool(cfg.get("PLAN_ENABLED", True))
        except Exception:  # pragma: no cover - config lookups must never break a command
            return True

    def _print_plan_disabled(self) -> None:
        """One-line notice used by /plan and /todo when the feature is disabled."""
        self.cli.console.print("plan mode is disabled (PLAN_ENABLED=false)", style="dim")

    @staticmethod
    def _truncate_cell(value, limit: int = 48) -> str:
        """Bound a table cell width (Rich tables must stay readable in a terminal)."""
        text = str(value or "")
        return text if len(text) <= limit else text[: max(limit - 1, 0)] + "…"

    def _handle_plan_list(self, argument: str) -> None:
        """``/plan list [--all]``: ID / STATUS / REV / UPDATED / GOAL table."""
        show_all = "--all" in argument.lower().split()
        plans = self.cli._list_plans_from_disk(all_projects=show_all)
        if not plans:
            self.cli.console.print("no plans yet", style="yellow")
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
        self.cli.console.print(table)

    def _handle_plan_show(self, plan_id: Optional[str]) -> None:
        """``/plan show [id]``: render the plan markdown (or a not-found notice)."""
        plan = self.cli._find_plan_from_disk(plan_id)
        if plan is None:
            if plan_id:
                self.cli.console.print(f"plan not found: {safe_text(plan_id)}", style="yellow")
            else:
                self.cli.console.print("no plan in this session", style="yellow")
            return
        self.cli.console.print(Markdown(plan.to_markdown(), code_theme=cfg["CODE_THEME"]))

    def _handle_plan_clear(self, argument: str) -> None:
        """``/plan clear --done|--all``: confirmed cleanup of this project's plans."""
        tokens = [token.lower() for token in argument.split()]
        done_only = "--done" in tokens
        clear_all = "--all" in tokens
        if not done_only and not clear_all:
            self.cli.console.print(f"Usage: {CMD_PLAN} clear --done|--all", style="yellow")
            return
        if not getattr(self.cli, "interactive", False):
            self.cli.console.print("plan clear needs an interactive confirmation", style="yellow")
            return
        scope = "finished" if done_only else "all"
        try:
            answer = Prompt.ask(f"Delete {scope} plan files of this project?", default="n")
        except (KeyboardInterrupt, EOFError):
            return
        if str(answer or "").strip().lower() not in ("y", "yes"):
            self.cli.console.print("plan clear cancelled", style="dim")
            return
        removed = self.cli._clear_plans_from_disk(done_only=done_only)
        self.cli.console.print(f"cleared {len(removed)} plan file(s)", style="green")

    def _handle_plan_abort(self) -> None:
        """``/plan abort``: confirmed abort of the active plan (todos cleared)."""
        session = self.cli._get_plan_session()
        if getattr(session, "active_plan", None) is None:
            self.cli.console.print("no plan in this session", style="yellow")
            return
        if not getattr(self.cli, "interactive", False):
            self.cli.console.print("plan abort needs an interactive confirmation", style="yellow")
            return
        try:
            answer = Prompt.ask("Abort the active plan? This clears its todos.", default="n")
        except (KeyboardInterrupt, EOFError):
            return
        if str(answer or "").strip().lower() not in ("y", "yes"):
            self.cli.console.print("plan abort cancelled", style="dim")
            return
        self.cli._abort_current_plan()

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
        console = self.cli.console
        raw = command_input.strip()
        parts = raw.split(maxsplit=1)
        rest = parts[1].strip() if len(parts) > 1 else ""
        if not self._plan_enabled():
            self._print_plan_disabled()
            return True
        if not rest:
            self.cli._toggle_plan_mode()
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
            result = self.cli._edit_current_plan()
            if result is None:
                console.print("no plan in this session", style="yellow")
            return True
        if subcommand == "review":
            self.cli._review_plan_from_disk(argument or None)
            return True
        if subcommand == "resume":
            self.cli._resume_plan_from_disk(argument or None)
            return True
        if subcommand == "clear":
            self._handle_plan_clear(argument)
            return True
        if subcommand == "abort":
            self._handle_plan_abort()
            return True

        # Anything else is a planning task: enter plan mode, then send it as a turn.
        prepared = self.cli._prepare_plan_task(rest)
        if prepared is None:
            return True
        return prepared

    def handle_todo(self) -> bool:
        """Handle ``/todo``: show the current plan's todo table and status line.

        Returns:
            True to continue the REPL loop
        """
        console = self.cli.console
        if not self._plan_enabled():
            self._print_plan_disabled()
            return True
        session = self.cli._get_plan_session()
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

    def handle_command(self, user_input: str) -> Union[bool, str]:
        """Handle special command return: True-continue loop, False-exit loop, str-non-special command

        Args:
            user_input: Raw input from the user

        Returns:
            True if command handled and should continue loop
            False if should exit loop
            user_input if not a special command
        """
        lower_input = user_input.lower().strip()

        # Check if input starts with exclamation mark (both half-width ! and full-width ！)
        if user_input.startswith("!") or user_input.startswith("！"):
            cmd = user_input[1:].strip()
            return self.handle_shell_command(cmd)

        # Check for commands with exact command names
        if lower_input in self.commands:
            return self.commands[lower_input]()

        # Check for commands with parameters. Match the first whitespace-delimited
        # token (not a raw string prefix) so e.g. ``/model`` is never mistaken for
        # ``/mode`` and an unknown ``/modelx`` stays a normal prompt.
        parts = lower_input.split(maxsplit=1)
        if len(parts) == 2:
            command_token = parts[0]
            handler = self.commands.get(command_token)
            if handler is not None and command_token in (
                CMD_SAVE_CHAT,
                CMD_LOAD_CHAT,
                CMD_DELETE_CHAT,
                "/delete",  # long-form alias of /del
                CMD_MODE,
                CMD_ADD,
                CMD_CONTEXT[0] if isinstance(CMD_CONTEXT, tuple) else CMD_CONTEXT,
                "/ctx",  # Also handle the /ctx alias
                CMD_PLAN,
                CMD_COMPACT,
                CMD_PERMISSIONS,
                CMD_MODEL,
                CMD_ROLE,
            ):
                return handler(user_input)

        # Not a special command
        return user_input

    def handle_shell_command(self, cmd: str) -> bool:
        """Execute a shell command directly with current environment variables.

        Args:
            cmd: Shell command to execute

        Returns:
            True to continue the REPL loop
        """
        if not cmd:
            return True

        self.cli.console.print(f"Executing: {safe_text(cmd)}", style="bold green")
        try:
            subprocess.call(cmd, shell=True)
        except Exception as e:
            self.cli.console.print(f"Failed to execute command: {safe_text(e)}", style="red")
        return True

    def handle_help(self) -> bool:
        """Show help message.

        Returns:
            True to continue the REPL loop
        """
        self.cli.print_help()
        return True

    def handle_exit(self) -> bool:
        """Exit the REPL loop.

        Returns:
            False to exit the REPL loop
        """
        return False

    def handle_clear(self) -> bool:
        """Clear chat history.

        Returns:
            True to continue the REPL loop
        """
        if self.cli.current_mode == CHAT_MODE:
            self.cli.chat.history.clear()
            self.cli.console.print("Chat history cleared", style="bold yellow")
            # A cleared conversation has no turn to retry and no context to report.
            self._clear_retry_snapshot()
            self._refresh_context_percent()
        return True

    def handle_history(self) -> bool:
        """Show chat history.

        Returns:
            True to continue the REPL loop
        """
        if not self.cli.chat.history:
            self.cli.console.print("History is empty.", style="yellow")
        else:
            self.cli.console.print("Chat History:", style="bold underline")
            message_count = 1
            for msg in self.cli.chat.history:
                if msg.role == "user" and msg.content:
                    self.cli.console.print(
                        f"[dim]{message_count}[/dim] [bold blue]User:[/bold blue] {safe_text(msg.content)}"
                    )
                    message_count += 1
                elif msg.role == "assistant" and (msg.content or msg.tool_calls):
                    content = strip_control_chars(msg.content or "")
                    if msg.tool_calls:
                        content += "\n" if content else ""  # Add newline if there's assistant content before tool calls
                        for t in msg.tool_calls:
                            content += (
                                f">Tool Call: {strip_control_chars(t.name)}({strip_control_chars(t.arguments)})\n"
                            )
                    md = Markdown(content, code_theme=cfg["CODE_THEME"])
                    padded_md = Padding(md, (0, 0, 0, 4))
                    self.cli.console.print("    Assistant:", style="bold green")
                    self.cli.console.print(padded_md)
                # Skip other roles (like "tool") and empty messages - they are not displayed
        return True

    def handle_list(self) -> bool:
        """List saved chats.

        Returns:
            True to continue the REPL loop
        """
        self.cli._list_chats()
        return True

    def handle_save(self, command_input: str = "") -> bool:
        """Save current chat.

        Args:
            command_input: Raw command input that may contain a title

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.split(maxsplit=1)
        title = parts[1] if len(parts) > 1 else self.cli.chat.title
        self.cli._save_chat(title)
        return True

    def handle_load(self, command_input: str = "") -> bool:
        """Load saved chat.

        Args:
            command_input: Raw command input that should contain an index

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.split(maxsplit=1)
        if len(parts) == 2 and parts[1].isdigit():
            self.cli._load_chat_by_index(index=parts[1])
        else:
            self.cli.console.print(f"Usage: {CMD_LOAD_CHAT} <index>", style="yellow")
            self.cli._list_chats()
        return True

    def handle_delete(self, command_input: str = "") -> bool:
        """Delete saved chat.

        Args:
            command_input: Raw command input that should contain an index

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.split(maxsplit=1)
        if len(parts) == 2 and parts[1].isdigit():
            self.cli._delete_chat_by_index(index=parts[1])
        else:
            self.cli.console.print(f"Usage: {CMD_DELETE_CHAT} <index>", style="yellow")
            self.cli._list_chats()
        return True

    def handle_mode(self, command_input: str = "") -> bool:
        """Switch between chat and exec modes.

        Args:
            command_input: Raw command input that should contain the mode

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.lower().split(maxsplit=1)
        if len(parts) == 2 and parts[1] in [CHAT_MODE, EXEC_MODE]:
            new_mode = parts[1]
            if self.cli.current_mode != new_mode:
                self.cli.current_mode = new_mode
                self.cli.set_role(DefaultRoleNames.SHELL if self.cli.current_mode == EXEC_MODE else self.cli.init_role)
            else:
                self.cli.console.print(f"Already in {self.cli.current_mode} mode.", style="yellow")
        else:
            self.cli.console.print(f"Usage: {CMD_MODE} {CHAT_MODE}|{EXEC_MODE}", style="yellow")
        return True
