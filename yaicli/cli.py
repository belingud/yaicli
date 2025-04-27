import subprocess
import sys
import time
import traceback
from os.path import devnull
from pathlib import Path
from typing import List, Literal, Optional, Tuple

import typer
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.prompt import Prompt

from yaicli.api import ApiClient
from yaicli.chat_manager import ChatManager, FileChatManager
from yaicli.config import CONFIG_PATH, Config, cfg
from yaicli.console import get_console
from yaicli.const import (
    CHAT_MODE,
    CMD_CLEAR,
    CMD_DELETE_CHAT,
    CMD_EXIT,
    CMD_HISTORY,
    CMD_LIST_CHATS,
    CMD_LOAD_CHAT,
    CMD_MODE,
    CMD_SAVE_CHAT,
    DEFAULT_CODE_THEME,
    DEFAULT_INTERACTIVE_ROUND,
    DEFAULT_OS_NAME,
    DEFAULT_SHELL_NAME,
    EXEC_MODE,
    TEMP_MODE,
    DefaultRoleNames,
)
from yaicli.history import LimitedFileHistory
from yaicli.printer import Printer
from yaicli.roles import RoleManager
from yaicli.utils import detect_os, detect_shell, filter_command


class CLI:
    HISTORY_FILE = Path("~/.yaicli_history").expanduser()

    def __init__(
        self,
        verbose: bool = False,
        stdin: Optional[str] = None,
        api_client: Optional[ApiClient] = None,
        printer: Optional[Printer] = None,
        chat_manager: Optional[ChatManager] = None,
        role: Optional[str] = None,
    ):
        # General settings
        self.verbose = verbose
        self.stdin = stdin
        self.console = get_console()
        self.bindings = KeyBindings()
        self.config: Config = cfg
        self.current_mode: str = TEMP_MODE
        self.role: str = role or DefaultRoleNames.DEFAULT.value

        # Initialize role manager
        self.role_manager = RoleManager()

        # Validate role
        if not self.role_manager.role_exists(self.role):
            self.console.print(f"Role '{self.role}' not found, using default role.", style="yellow")
            self.role = DefaultRoleNames.DEFAULT.value

        # Interactive chat mode settings
        self.history = []
        self.interactive_max_history = self.config.get("INTERACTIVE_MAX_HISTORY", DEFAULT_INTERACTIVE_ROUND)
        self.chat_title = None
        self.chat_start_time = None
        self.is_temp_session = True

        # Get and create chat history directory from configuration
        self.chat_history_dir = Path(self.config["CHAT_HISTORY_DIR"])
        self.chat_history_dir.mkdir(parents=True, exist_ok=True)

        # Initialize chat manager
        self.chat_manager = chat_manager or FileChatManager()

        # Detect OS and Shell if set to auto
        if self.config.get("OS_NAME") == DEFAULT_OS_NAME:
            self.config["OS_NAME"] = detect_os(self.config)
        if self.config.get("SHELL_NAME") == DEFAULT_SHELL_NAME:
            self.config["SHELL_NAME"] = detect_shell(self.config)

        if self.verbose:
            self.console.print("Loading Configuration:", style="bold cyan")
            self.console.print(f"Config file path: {CONFIG_PATH}")
            for key, value in self.config.items():
                display_value = "****" if key == "API_KEY" and value else value
                self.console.print(f"  {key:<17}: {display_value}")
            self.console.print(f"Current role: {self.role}")
            self.console.print(Markdown("---", code_theme=self.config.get("CODE_THEME", DEFAULT_CODE_THEME)))

        self.api_client = api_client or ApiClient(self.config, self.console, self.verbose)
        self.printer = printer or Printer(self.config, self.console, self.verbose, markdown=True)

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

    def get_prompt_tokens(self) -> List[Tuple[str, str]]:
        """Return prompt tokens for current mode"""
        mode_icon = "💬" if self.current_mode == CHAT_MODE else "🚀" if self.current_mode == EXEC_MODE else "📝"
        return [("class:qmark", f" {mode_icon} "), ("class:prompt", "> ")]

    def _check_history_len(self) -> None:
        """Check history length and remove the oldest messages if necessary"""
        target_len = self.interactive_max_history * 2
        if len(self.history) > target_len:
            self.history = self.history[-target_len:]
            if self.verbose:
                self.console.print(f"History trimmed to {target_len} messages.", style="dim")

    # ------------------- Role Command Methods -------------------
    def set_role(self, role: str) -> None:
        """Set the current role for the assistant"""
        if not self.role_manager.role_exists(role):
            self.console.print(f"Role '{role}' not found.", style="bold red")
            return

        self.role = role
        if self.role == DefaultRoleNames.CODER:
            self.printer = Printer(self.config, self.console, self.verbose, content_markdown=False)

    # ------------------- Chat Command Methods -------------------
    def _save_chat(self, title: Optional[str] = None) -> None:
        """Save current chat history to a file using session manager."""
        saved_title = self.chat_manager.save_chat(self.history, title)

        if not saved_title:
            self.console.print("Failed to save chat.", style="bold red")
            return

        # Session list will be refreshed automatically by the save method
        self.console.print(f"Chat saved as: {saved_title}", style="bold green")

        # If this was a temporary session, mark it as non-temporary now that it's saved
        if self.is_temp_session:
            self.is_temp_session = False
            self.chat_title = saved_title
            self.chat_start_time = int(time.time())
            self.console.print(
                "Session is now marked as persistent and will be auto-saved on exit.", style="bold green"
            )

    def _list_chats(self) -> None:
        """List all saved chat sessions using session manager."""
        chats = self.chat_manager.list_chats()

        if not chats:
            self.console.print("No saved chats found.", style="yellow")
            return

        self.console.print("Saved Chats:", style="bold underline")
        for chat in chats:
            index = chat["index"]
            title = chat["title"]
            date = chat.get("date", "")

            if date:
                self.console.print(f"[dim]{index}.[/dim] [bold blue]{title}[/bold blue] - {date}")
            else:
                self.console.print(f"[dim]{index}.[/dim] [bold blue]{title}[/bold blue]")

    def _refresh_chats(self) -> None:
        """Force refresh the chat list."""
        self.chat_manager.refresh_chats()

    def _load_chat_by_index(self, index: int) -> bool:
        """Load a chat session by its index using session manager."""
        if not self.chat_manager.validate_chat_index(index):
            self.console.print("Invalid chat index.", style="bold red")
            return False

        chat_data = self.chat_manager.load_chat_by_index(index)

        if not chat_data:
            self.console.print("Invalid chat index or chat not found.", style="bold red")
            return False

        self.history = chat_data.get("history", [])
        self.chat_title = chat_data.get("title")
        self.chat_start_time = chat_data.get("timestamp", int(time.time()))
        self.is_temp_session = False

        self.console.print(f"Loaded chat: {self.chat_title}", style="bold green")
        return True

    def _delete_chat_by_index(self, index: int) -> bool:
        """Delete a chat session by its index using session manager."""
        if not self.chat_manager.validate_chat_index(index):
            self.console.print("Invalid chat index.", style="bold red")
            return False

        chat_data = self.chat_manager.load_chat_by_index(index)

        if not chat_data:
            self.console.print("Invalid chat index or chat not found.", style="bold red")
            return False

        if self.chat_manager.delete_chat(index):
            self.console.print(f"Deleted chat: {chat_data['title']}", style="bold green")
            return True
        else:
            self.console.print(f"Failed to delete chat: {chat_data['title']}", style="bold red")
            return False

    # ------------------- Special commands -------------------
    def _handle_special_commands(self, user_input: str) -> Optional[bool]:
        """Handle special command return: True-continue loop, False-exit loop, None-non-special command"""
        command = user_input.lower().strip()
        if command == CMD_EXIT:
            return False
        if command == CMD_CLEAR and self.current_mode == CHAT_MODE:
            self.history.clear()
            self.console.print("Chat history cleared", style="bold yellow")
            return True
        if command == CMD_HISTORY:
            if not self.history:
                self.console.print("History is empty.", style="yellow")
            else:
                self.console.print("Chat History:", style="bold underline")
                for i in range(0, len(self.history), 2):
                    user_msg = self.history[i]
                    assistant_msg = self.history[i + 1] if (i + 1) < len(self.history) else None
                    self.console.print(f"[dim]{i // 2 + 1}[/dim] [bold blue]User:[/bold blue] {user_msg['content']}")
                    if assistant_msg:
                        md = Markdown(assistant_msg["content"], code_theme=self.config["CODE_THEME"])
                        padded_md = Padding(md, (0, 0, 0, 4))
                        self.console.print("    Assistant:", style="bold green")
                        self.console.print(padded_md)
            return True

        # Handle /save command - optional title parameter
        if command.startswith(CMD_SAVE_CHAT):
            parts = command.split(maxsplit=1)
            title = parts[1] if len(parts) > 1 else self.chat_title
            self._save_chat(title)
            return True

        # Handle /load command - requires index parameter
        if command.startswith(CMD_LOAD_CHAT):
            parts = command.split(maxsplit=1)
            if len(parts) == 2 and parts[1].isdigit():
                # Try to parse as an index first
                index = int(parts[1])
                self._load_chat_by_index(index=index)
            else:
                self.console.print(f"Usage: {CMD_LOAD_CHAT} <index>", style="yellow")
                self._list_chats()
            return True

        # Handle /delete command - requires index parameter
        if command.startswith(CMD_DELETE_CHAT):
            parts = command.split(maxsplit=1)
            if len(parts) == 2 and parts[1].isdigit():
                index = int(parts[1])
                self._delete_chat_by_index(index=index)
            else:
                self.console.print(f"Usage: {CMD_DELETE_CHAT} <index>", style="yellow")
                self._list_chats()
            return True

        # Handle /list command to list saved chats
        if command == CMD_LIST_CHATS:
            self._list_chats()
            return True

        # Handle /mode command
        if command.startswith(CMD_MODE):
            parts = command.split(maxsplit=1)
            if len(parts) == 2 and parts[1] in [CHAT_MODE, EXEC_MODE]:
                new_mode = parts[1]
                if self.current_mode != new_mode:
                    self.current_mode = new_mode
                else:
                    self.console.print(f"Already in {self.current_mode} mode.", style="yellow")
            else:
                self.console.print(f"Usage: {CMD_MODE} {CHAT_MODE}|{EXEC_MODE}", style="yellow")
            return True
        return None

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
            default="n",
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
            self.console.print("--- Executing --- ", style="bold green")
            try:
                subprocess.call(executed_cmd, shell=True)
            except Exception as e:
                self.console.print(f"[red]Failed to execute command: {e}[/red]")
            self.console.print("--- Finished ---", style="bold green")
        elif _input != "e":
            self.console.print("Execution cancelled.", style="yellow")

    # ------------------- LLM Methods -------------------
    def get_system_prompt(self) -> str:
        """Get the system prompt based on current role and mode"""
        # Use the role manager to get the system prompt
        return self.role_manager.get_system_prompt(self.role)

    def _build_messages(self, user_input: str) -> List[dict]:
        """Build message list for LLM API"""
        # Create the message list
        messages = [{"role": "system", "content": self.get_system_prompt()}]

        # Add previous conversation if available
        for msg in self.history:
            messages.append(msg)

        # Add user input
        messages.append({"role": "user", "content": user_input})
        return messages

    def _handle_llm_response(self, user_input: str) -> Optional[str]:
        """Get response from API (streaming or normal) and print it.
        Returns the full content string or None if an error occurred.

        Args:
            user_input (str): The user's input text.

        Returns:
            Optional[str]: The assistant's response content or None if an error occurred.
        """
        messages = self._build_messages(user_input)
        if self.verbose:
            self.console.print(messages)
        is_code_mode = self.role == DefaultRoleNames.CODER
        try:
            if self.config["STREAM"]:
                stream_iterator = self.api_client.stream_completion(messages)
                content, reasoning = self.printer.display_stream(stream_iterator, not is_code_mode)
            else:
                content, reasoning = self.api_client.completion(messages)
                self.printer.display_normal(content, reasoning, not is_code_mode)

            if content is not None:
                # Add only the content (not reasoning) to history
                self.history.extend(
                    [{"role": "user", "content": user_input}, {"role": "assistant", "content": content}]
                )
                self._check_history_len()
                return content
            else:
                return None
        except Exception as e:
            self.console.print(f"[red]Error processing LLM response: {e}[/red]")
            if self.verbose:
                traceback.print_exc()
            return None

    def _process_user_input(self, user_input: str) -> bool:
        """Process user input: get response, print, update history, maybe execute.
        Returns True to continue REPL, False to exit on critical error.
        """
        content = self._handle_llm_response(user_input)

        if content is None:
            return True

        if self.current_mode == EXEC_MODE:
            self._confirm_and_execute(content)
        return True

    # ------------------- REPL Methods -------------------
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
                f"Current: [bold green]Persistent Session[/bold green]{f': {self.chat_title}' if self.chat_title else ''}"
            )

        self.console.print("Press [bold yellow]TAB[/bold yellow] to switch mode")
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
        while True:
            self.console.print(Markdown("---", code_theme=self.config["CODE_THEME"]))
            try:
                user_input = self.session.prompt(self.get_prompt_tokens)
                user_input = user_input.strip()
                if not user_input:
                    continue
                command_result = self._handle_special_commands(user_input)
                if command_result is False:
                    break
                if command_result is True:
                    continue
                if not self._process_user_input(user_input):
                    break
            except (KeyboardInterrupt, EOFError):
                break

        # Auto-save chat history when exiting if there are messages and not a temporary session
        if not self.is_temp_session:
            self._save_chat(self.chat_title)

        self.console.print("\nExiting YAICLI... Goodbye!", style="bold green")

    def prepare_chat_loop(self) -> None:
        """Setup key bindings and history for interactive modes."""
        self._setup_key_bindings()
        self.HISTORY_FILE.touch(exist_ok=True)
        try:
            self.session = PromptSession(
                key_bindings=self.bindings,
                history=LimitedFileHistory(self.HISTORY_FILE, max_entries=self.interactive_max_history),
                auto_suggest=AutoSuggestFromHistory() if self.config.get("AUTO_SUGGEST", True) else None,
                enable_history_search=True,
            )
        except Exception as e:
            self.console.print(f"[red]Error initializing prompt session history: {e}[/red]")
            self.session = PromptSession(key_bindings=self.bindings)
        if self.chat_title:
            chat_info = self.chat_manager.load_chat_by_title(self.chat_title)
            self.is_temp_session = False
            self.history = chat_info.get("history", [])

    def _setup_key_bindings(self) -> None:
        """Setup keyboard shortcuts (e.g., TAB for mode switching)."""

        @self.bindings.add(Keys.ControlI)  # TAB
        def _(event: KeyPressEvent) -> None:
            self.current_mode = EXEC_MODE if self.current_mode == CHAT_MODE else CHAT_MODE

    def _run_once(self, input: str, shell: bool) -> None:
        """Run a single command (non-interactive)."""
        self.current_mode = EXEC_MODE if shell else TEMP_MODE
        if not self.config.get("API_KEY"):
            self.console.print("[bold red]Error:[/bold red] API key not found.")
            raise typer.Exit(code=1)

        content = self._handle_llm_response(input)

        if content is None:
            raise typer.Exit(code=1)

        if shell:
            self._confirm_and_execute(content)

    # ------------------- Main Entry Point -------------------
    def run(
        self,
        chat: bool,
        shell: bool,
        input: Optional[str],
        role: Optional[str | Literal[DefaultRoleNames.DEFAULT]] = None,
    ) -> None:
        """Run the CLI in the appropriate mode with the selected role."""
        self.set_role(role or self.role)

        # Now handle normal operation
        if shell:
            # Set mode to shell
            self.role = DefaultRoleNames.SHELL
            if input:
                self._run_once(input, shell=True)
            else:
                self.console.print("No prompt provided for shell mode.", style="yellow")
        elif chat:
            # Start interactive chat mode
            self.current_mode = CHAT_MODE
            self.chat_title = input if input else None
            self.prepare_chat_loop()
            self._run_repl()
        elif input:
            # Run once with the given prompt
            self._run_once(input, shell=False)
        else:
            self.console.print("No chat or prompt provided. Exiting.")
