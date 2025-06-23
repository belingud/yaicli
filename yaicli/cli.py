import subprocess
import sys
import time
import traceback
from os import devnull
from pathlib import Path
from typing import Optional, Union

import typer
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.prompt import Prompt

from .chat import Chat, FileChatManager, chat_mgr
from .config import cfg
from .console import get_console
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
    DEFAULT_SHELL_NAME,
    EXEC_MODE,
    HISTORY_FILE,
    TEMP_MODE,
    DefaultRoleNames,
)
from .exceptions import ChatSaveError
from .history import LimitedFileHistory
from .llms import LLMClient
from .printer import Printer
from .role import Role, RoleManager, role_mgr
from .schemas import ChatMessage
from .utils import detect_os, detect_shell, filter_command


class CLI:
    def __init__(
        self,
        verbose: bool = False,
        role: str = DefaultRoleNames.DEFAULT,
        chat_manager: Optional[FileChatManager] = None,
        role_manager: Optional[RoleManager] = None,
        client=None,
    ):
        self.verbose: bool = verbose
        # --role can specify a role when enter interactive chat
        # TAB will switch between role and shell
        self.init_role: str = role
        self.role_name: str = role

        self.console = get_console()
        self.chat_manager = chat_manager or chat_mgr
        self.role_manager = role_manager or role_mgr
        self.role: Role = self.role_manager.get_role(self.role_name)
        self.printer = Printer()
        self.client = client or self._create_client()

        self.bindings = KeyBindings()

        self.current_mode: str = TEMP_MODE

        self.interactive_round = cfg["INTERACTIVE_ROUND"]
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
            # Print verbose configuration
            self.console.print("Loading Configuration:", style="bold cyan")
            self.console.print(f"Config file path: {CONFIG_PATH}")
            for key, value in cfg.items():
                display_value = "****" if key == "API_KEY" and value else value
                self.console.print(f"  {key:<20}: {display_value}")
            self.console.print(f"Current role: {self.role_name}")
            self.console.print(Markdown("---", code_theme=cfg["CODE_THEME"]))

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

    def set_role(self, role_name: str) -> None:
        self.role_name = role_name
        self.role = self.role_manager.get_role(role_name)
        if role_name in (DefaultRoleNames.CODER, DefaultRoleNames.SHELL):
            cfg["ENABLE_FUNCTIONS"] = False
        if role_name == DefaultRoleNames.CODER:
            self.printer = Printer(content_markdown=False)
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
        """Check history length and remove the oldest messages if necessary"""
        target_len = self.interactive_round * 2
        if len(self.chat.history) > target_len:
            self.chat.history = self.chat.history[-target_len:]
            if self.verbose:
                self.console.print(f"Dialogue trimmed to {target_len} messages.", style="dim")

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
            self.console.print(f"Failed to save chat: {e}", style="red")
            return

        # Session list will be refreshed automatically by the save method
        self.console.print(f"Chat saved as: {saved_title}", style="bold green")

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
                self.console.print(f"[dim]{index}.[/dim] [bold blue]{title}[/bold blue] - {date}")
            else:
                self.console.print(f"[dim]{index}.[/dim] [bold blue]{title}[/bold blue]")

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

        self.console.print(f"Loaded chat: {self.chat.title}", style="bold green")
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
            self.console.print(f"Chat has no associated file to delete: {chat_data.title}", style="bold red")
            return False

        if self.chat_manager.delete_chat(chat_data.path):
            self.console.print(f"Deleted chat: {chat_data.title}", style="bold green")
            return True
        else:
            self.console.print(f"Failed to delete chat: {chat_data.title}", style="bold red")
            return False

    # ------------------- Special commands -------------------
    def _handle_special_commands(self, user_input: str) -> Union[bool, str]:
        """Handle special command return: True-continue loop, False-exit loop, str-non-special command"""
        lower_input = user_input.lower().strip()
        if lower_input in CMD_HELP:
            # case-insensitive
            self.print_help()
            return True
        if lower_input == CMD_EXIT:
            # case-insensitive
            return False
        if lower_input == CMD_CLEAR and self.current_mode == CHAT_MODE:
            # case-insensitive
            self.chat.history.clear()
            self.console.print("Chat history cleared", style="bold yellow")
            return True
        if lower_input == CMD_HISTORY:
            # case-insensitive
            if not self.chat.history:
                self.console.print("History is empty.", style="yellow")
            else:
                self.console.print("Chat History:", style="bold underline")
                for i in range(0, len(self.chat.history), 2):
                    user_msg = self.chat.history[i]
                    assistant_msg = self.chat.history[i + 1] if (i + 1) < len(self.chat.history) else None
                    self.console.print(f"[dim]{i // 2 + 1}[/dim] [bold blue]User:[/bold blue] {user_msg.content}")
                    if assistant_msg:
                        md = Markdown(assistant_msg.content, code_theme=cfg["CODE_THEME"])
                        padded_md = Padding(md, (0, 0, 0, 4))
                        self.console.print("    Assistant:", style="bold green")
                        self.console.print(padded_md)
            return True

        # Handle /save command - optional title parameter
        if lower_input.startswith(CMD_SAVE_CHAT):
            # Save chat with title from user raw input, case-sensitive
            parts = user_input.split(maxsplit=1)
            title = parts[1] if len(parts) > 1 else self.chat.title
            self._save_chat(title)
            return True

        # Handle /load command - requires index parameter
        if lower_input.startswith(CMD_LOAD_CHAT):
            # Load chat by index from user raw input, case-sensitive
            parts = user_input.split(maxsplit=1)
            if len(parts) == 2 and parts[1].isdigit():
                # Try to parse as an index first
                self._load_chat_by_index(index=parts[1])
            else:
                self.console.print(f"Usage: {CMD_LOAD_CHAT} <index>", style="yellow")
                self._list_chats()
            return True

        # Handle /delete command - requires index parameter
        if lower_input.startswith(CMD_DELETE_CHAT):
            # Delete chat by index from user raw input, case-sensitive
            parts = user_input.split(maxsplit=1)
            if len(parts) == 2 and parts[1].isdigit():
                self._delete_chat_by_index(index=parts[1])
            else:
                self.console.print(f"Usage: {CMD_DELETE_CHAT} <index>", style="yellow")
                self._list_chats()
            return True

        # Handle /list command to list saved chats
        if lower_input == CMD_LIST_CHATS:
            # case-insensitive
            self._list_chats()
            return True

        # Handle /mode command
        if lower_input.startswith(CMD_MODE):
            # Switch mode by lower user input, case-insensitive
            parts = lower_input.split(maxsplit=1)
            if len(parts) == 2 and parts[1] in [CHAT_MODE, EXEC_MODE]:
                new_mode = parts[1]
                if self.current_mode != new_mode:
                    self.current_mode = new_mode
                    self.set_role(DefaultRoleNames.SHELL if self.current_mode == EXEC_MODE else self.init_role)
                else:
                    self.console.print(f"Already in {self.current_mode} mode.", style="yellow")
            else:
                self.console.print(f"Usage: {CMD_MODE} {CHAT_MODE}|{EXEC_MODE}", style="yellow")
            return True
        return user_input

    def _build_messages(self, user_input: str) -> list[ChatMessage]:
        """Build message list for LLM API"""
        # Create the message list with system prompt
        messages = [ChatMessage(role="system", content=self.role.prompt)]

        # Add previous conversation if available
        for msg in self.chat.history:
            messages.append(msg)

        # Add user input
        messages.append(ChatMessage(role="user", content=user_input))
        return messages

    def _handle_llm_response(self, user_input: str) -> tuple[Optional[str], list[ChatMessage]]:
        """Get response from API (streaming or normal) and print it.
        Returns the full content string or None if an error occurred.

        Args:
            user_input (str): The user's input text.

        Returns:
            Optional[str]: The assistant's response content or None if an error occurred.
            list[ChatMessage]: The updated message history.
        """
        messages = self._build_messages(user_input)
        if self.role.name != DefaultRoleNames.CODER:
            self.console.print("Assistant:", style="bold green")
        try:
            response_iterator = self.client.completion_with_tools(messages, stream=cfg["STREAM"])

            content, _ = self.printer.display_stream(response_iterator)

            # The 'messages' list is modified by the client in-place
            return content, messages
        except Exception as e:
            self.console.print(f"Error processing LLM response: {e}", style="red")
            if self.verbose:
                traceback.print_exc()
            return None, messages

    def _process_user_input(self, user_input: str) -> bool:
        """Process user input: get response, print, update history, maybe execute.
        Returns True to continue REPL, False to exit on critical error.
        """
        content, updated_messages = self._handle_llm_response(user_input)

        if content is None and not any(msg.tool_calls for msg in updated_messages):
            return True

        # The client modifies the message list in place, so the updated_messages
        # contains the full history of the turn (system, history, user, assistant, tools).
        # We replace the old history with the new one, removing the system prompt.
        if updated_messages:
            self.chat.history = updated_messages[1:]

        self._check_history_len()

        if self.current_mode == EXEC_MODE:
            self._confirm_and_execute(content)
        return True

    def _confirm_and_execute(self, raw_content: str) -> None:
        """Review, edit and execute the command"""
        cmd = filter_command(raw_content)
        if not cmd:
            self.console.print("No command generated or command is empty.", style="bold red")
            return
        self.console.print(
            Panel(cmd, title="Suggest Command", title_align="left", border_style="bold magenta", expand=False)
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
                self.console.print(f"Failed to execute command: {e}", style="red")
        elif _input != "e":
            self.console.print("Execution cancelled.", style="yellow")

    # ------------------- REPL Methods -------------------
    def prepare_chat_loop(self) -> None:
        """Setup key bindings and history for interactive modes."""
        self.current_mode = CHAT_MODE
        self._setup_key_bindings()
        HISTORY_FILE.touch(exist_ok=True)

        # Set up the prompt session with command history
        try:
            self.session = PromptSession(
                key_bindings=self.bindings,
                history=LimitedFileHistory(HISTORY_FILE, max_entries=self.interactive_round),
                auto_suggest=AutoSuggestFromHistory() if cfg.get("AUTO_SUGGEST", True) else None,
                enable_history_search=True,
            )
        except Exception as e:
            self.console.print(f"Error initializing prompt session history: {e}", style="red")
            self.session = PromptSession(key_bindings=self.bindings)

    def _setup_key_bindings(self) -> None:
        """Setup keyboard shortcuts (e.g., TAB for mode switching)."""

        @self.bindings.add(Keys.ControlI)  # TAB
        def _(event: KeyPressEvent) -> None:
            self.current_mode = EXEC_MODE if self.current_mode == CHAT_MODE else CHAT_MODE
            self.set_role(DefaultRoleNames.SHELL if self.current_mode == EXEC_MODE else self.init_role)

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
                f"Current: [bold green]Persistent Session[/bold green]{f': {self.chat.title}' if self.chat.title else ''}"
            )
        self.print_help()

    def print_help(self):
        self.console.print("Press [bold yellow]TAB[/bold yellow] to switch mode")
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
        cmd_exit = f"{CMD_EXIT}|Ctrl+D|Ctrl+C"
        self.console.print(f"{cmd_exit:<19}: Exit")
        cmd_mode = f"{CMD_MODE} {CHAT_MODE}|{EXEC_MODE}"
        self.console.print(f"{cmd_mode:<19}: Switch mode (Case insensitive)", style="dim")

    def _run_repl(self) -> None:
        """Run the main Read-Eval-Print Loop (REPL)."""
        self.prepare_chat_loop()
        self._print_welcome_message()

        # Main REPL loop
        while True:
            self.console.print(Markdown("---", code_theme=cfg["CODE_THEME"]))
            try:
                # Get user input
                user_input = self.session.prompt(self.get_prompt_tokens)
                user_input = user_input.strip()
                if not user_input:
                    continue

                # Handle special commands
                _continue = self._handle_special_commands(user_input)
                if _continue is False:  # Exit command
                    break
                if _continue is True:  # Other special command
                    continue

                # Process regular chat input
                try:
                    if not self._process_user_input(user_input):
                        break
                except KeyboardInterrupt:
                    self.console.print("KeyboardInterrupt", style="yellow")
                    continue
            except (KeyboardInterrupt, EOFError):
                break

        # Auto-save chat history when exiting if there are messages and not a temporary session
        if not self.is_temp_session and self.chat.history:
            self._save_chat(self.chat.title)

        self.console.print("\nExiting YAICLI... Goodbye!", style="bold green")

    def _run_once(self, user_input: str, shell: bool = False, code: bool = False) -> None:
        """Handle default mode"""
        self.set_role(self.evaluate_role_name(code, shell, self.init_role))
        self._process_user_input(user_input)

    def run(self, chat: bool = False, shell: bool = False, code: bool = False, user_input: Optional[str] = None):
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
        else:
            # Run in single-use mode
            self._run_once(user_input or "", shell=shell, code=code)

    def _create_client(self):
        """Create an LLM client instance based on configuration"""
        return LLMClient(provider_name=cfg["PROVIDER"].lower(), verbose=self.verbose, config=cfg)
