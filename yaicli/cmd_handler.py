"""Command handler for processing special commands in YAICLI."""

import subprocess
from typing import Union

from rich.markdown import Markdown
from rich.padding import Padding

from .config import cfg
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
    EXEC_MODE,
    DefaultRoleNames,
)


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
        }

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

        # Check for commands with parameters (save, load, delete, mode)
        for cmd_prefix, handler in self.commands.items():
            if lower_input.startswith(cmd_prefix) and cmd_prefix in (
                CMD_SAVE_CHAT,
                CMD_LOAD_CHAT,
                CMD_DELETE_CHAT,
                CMD_MODE,
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

        self.cli.console.print(f"Executing: {cmd}", style="bold green")
        try:
            subprocess.call(cmd, shell=True)
        except Exception as e:
            self.cli.console.print(f"Failed to execute command: {e}", style="red")
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
            for i in range(0, len(self.cli.chat.history), 2):
                user_msg = self.cli.chat.history[i]
                assistant_msg = self.cli.chat.history[i + 1] if (i + 1) < len(self.cli.chat.history) else None
                self.cli.console.print(f"[dim]{i // 2 + 1}[/dim] [bold blue]User:[/bold blue] {user_msg.content}")
                if assistant_msg:
                    md = Markdown(assistant_msg.content or "", code_theme=cfg["CODE_THEME"])
                    padded_md = Padding(md, (0, 0, 0, 4))
                    self.cli.console.print("    Assistant:", style="bold green")
                    self.cli.console.print(padded_md)
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

    def handle_mode(self, command_input: str) -> bool:
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
