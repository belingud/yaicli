"""Command handler for processing special commands in YAICLI."""

import shlex
import subprocess
from typing import Union

from rich.markdown import Markdown
from rich.padding import Padding

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
    CMD_SAVE_CHAT,
    EXEC_MODE,
    DefaultRoleNames,
)
from .tokens import estimate_context_usage, trim_messages_to_budget
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
#: Turn groups kept by ``/compact`` when no argument is given.
DEFAULT_COMPACT_KEEP_ROUNDS = 5
#: ``/context`` subcommands that print the estimated usage breakdown.
CONTEXT_BUDGET_SUBCOMMANDS = ("budget", "stats", "usage")


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
            CMD_MODE: self.handle_mode,
            CMD_ADD: self.handle_add_context,
            CMD_CONTEXT[0] if isinstance(CMD_CONTEXT, tuple) else CMD_CONTEXT: self.handle_context,
            "/ctx": self.handle_context,
            CMD_COMPACT: self.handle_compact,
            CMD_PERMISSIONS: self.handle_permissions,
            CMD_SHOW_OUTPUT: self.handle_show_output,
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

    def _context_usage(self):
        """Estimate the current context usage for the ``/context`` command."""
        config = cfg if hasattr(cfg, "get") else None
        return estimate_context_usage(self._history(), config=config, system_text=self._role_prompt())

    def _print_context_usage(self) -> None:
        """Print the estimated usage breakdown (system/history/tool/total/budget)."""
        usage = self._context_usage()
        console = self.cli.console
        console.print("Context usage (estimated):", style="bold")
        console.print(f"  system prompt : {usage.system_tokens:,} tokens")
        console.print(f"  history       : {usage.history_tokens:,} tokens (tool output {usage.tool_output_tokens:,})")
        console.print(
            f"  total         : {usage.total_tokens:,} / {usage.budget_tokens:,} tokens ({usage.used_percent:.1f}%)"
        )
        console.print(f"  remaining     : {usage.remaining_tokens:,} tokens")
        console.print("[dim]  Use /compact [keep_rounds] to drop older turn groups.[/dim]")

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
            self._print_context_usage()
            self.cli.console.print(
                "Subcommands: list, clear, add <path>, remove <path>, budget",
                style="dim",
            )
            # Default to list if no subcommand, preserving the pre-K02 behaviour.
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
            self.cli.console.print("Available: list, clear, add, remove, budget", style="dim")

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

        # Check for commands with parameters (save, load, delete, mode, add, context)
        for cmd_prefix, handler in self.commands.items():
            if lower_input.startswith(cmd_prefix) and cmd_prefix in (
                CMD_SAVE_CHAT,
                CMD_LOAD_CHAT,
                CMD_DELETE_CHAT,
                CMD_MODE,
                CMD_ADD,
                CMD_CONTEXT[0] if isinstance(CMD_CONTEXT, tuple) else CMD_CONTEXT,
                "/ctx",  # Also handle the /ctx alias
                CMD_COMPACT,
                CMD_PERMISSIONS,
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
