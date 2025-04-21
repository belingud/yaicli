import subprocess
import sys
import time
import traceback
from os.path import devnull
from pathlib import Path
from typing import List, Optional, Tuple

import typer
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from rich import get_console
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.prompt import Prompt

from yaicli.api import ApiClient
from yaicli.chat_manager import ChatManager, FileChatManager
from yaicli.config import CONFIG_PATH, Config
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
    DEFAULT_PROMPT,
    DEFAULT_SHELL_NAME,
    EXEC_MODE,
    SHELL_PROMPT,
    TEMP_MODE,
)
from yaicli.history import LimitedFileHistory
from yaicli.printer import Printer
from yaicli.utils import detect_os, detect_shell, filter_command


class CLI:
    HISTORY_FILE = Path("~/.yaicli_history").expanduser()

    def __init__(
        self,
        verbose: bool = False,
        api_client: Optional[ApiClient] = None,
        printer: Optional[Printer] = None,
        chat_manager: Optional[ChatManager] = None,
    ):
        self.verbose = verbose
        self.console = get_console()
        self.bindings = KeyBindings()
        self.config: Config = Config(self.console)
        self.current_mode: str = TEMP_MODE

        self.history = []
        self.interactive_max_history = self.config.get("INTERACTIVE_MAX_HISTORY", DEFAULT_INTERACTIVE_ROUND)
        self.chat_title = None
        self.chat_start_time = None
        self.is_temp_session = True

        # Get and create chat history directory from configuration
        self.chat_history_dir = Path(self.config["CHAT_HISTORY_DIR"])
        self.chat_history_dir.mkdir(parents=True, exist_ok=True)

        # Initialize session manager
        self.chat_manager = chat_manager or FileChatManager(self.config)

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
                self.console.print(f"  {key:<16}: {display_value}")
            self.console.print(Markdown("---", code_theme=self.config.get("CODE_THEME", DEFAULT_CODE_THEME)))

        self.api_client = api_client or ApiClient(self.config, self.console, self.verbose)
        self.printer = printer or Printer(self.config, self.console, self.verbose)

        _origin_stderr = None
        if not sys.stdin.isatty():
            _origin_stderr = sys.stderr
            sys.stderr = open(devnull, "w", encoding="utf-8")
        try:
            self.session = PromptSession(key_bindings=self.bindings)
        finally:
            if _origin_stderr:
                sys.stderr.close()
                sys.stderr = _origin_stderr

    def get_prompt_tokens(self) -> List[Tuple[str, str]]:
        """Return prompt tokens for current mode"""
        mode_icon = "💬" if self.current_mode == CHAT_MODE else "🚀" if self.current_mode == EXEC_MODE else "📝"
        return [("class:qmark", f" {mode_icon} "), ("class:prompt", "> ")]

    def _check_history_len(self) -> None:
        """Check history length and remove oldest messages if necessary"""
        target_len = self.interactive_max_history * 2
        if len(self.history) > target_len:
            self.history = self.history[-target_len:]

    def _save_chat(self, title: Optional[str] = None) -> None:
        """Save current chat history to a file using session manager."""
        if not self.history:
            self.console.print("No chat history to save.", style="yellow")
            return

        title = title or self.chat_title or f"Chat-{int(time.time())}"
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

        chat_data = self.chat_manager.load_chat(index)

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

        chat_data = self.chat_manager.load_chat(index)

        if not chat_data:
            self.console.print("Invalid chat index or chat not found.", style="bold red")
            return False

        if self.chat_manager.delete_chat(index):
            self.console.print(f"Deleted chat: {chat_data['title']}", style="bold green")
            return True
        else:
            self.console.print(f"Failed to delete chat: {chat_data['title']}", style="bold red")
            return False

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
                code_theme = self.config.get("CODE_THEME", "monokai")
                for i in range(0, len(self.history), 2):
                    user_msg = self.history[i]
                    assistant_msg = self.history[i + 1] if (i + 1) < len(self.history) else None
                    self.console.print(f"[dim]{i // 2 + 1}[/dim] [bold blue]User:[/bold blue] {user_msg['content']}")
                    if assistant_msg:
                        md = Markdown(assistant_msg["content"], code_theme=code_theme)
                        padded_md = Padding(md, (0, 0, 0, 4))
                        self.console.print("    Assistant:", style="bold green")
                        self.console.print(padded_md)
            return True

        # Handle /save command - optional title parameter
        if command.startswith(CMD_SAVE_CHAT):
            parts = command.split(maxsplit=1)
            title = parts[1] if len(parts) > 1 else None
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

        # Handle /chats command to list saved chats
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
                    mode_name = "Chat" if self.current_mode == CHAT_MODE else "Exec"
                    self.console.print(f"Switched to [bold yellow]{mode_name}[/bold yellow] mode")
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

    def get_system_prompt(self) -> str:
        """Return system prompt for current mode"""
        prompt_template = SHELL_PROMPT if self.current_mode == EXEC_MODE else DEFAULT_PROMPT
        return prompt_template.format(
            _os=self.config.get("OS_NAME", "Unknown OS"), _shell=self.config.get("SHELL_NAME", "Unknown Shell")
        )

    def _build_messages(self, user_input: str) -> List[dict]:
        """Build the list of messages for the API call."""
        return [
            {"role": "system", "content": self.get_system_prompt()},
            *self.history,
            {"role": "user", "content": user_input},
        ]

    def _handle_llm_response(self, user_input: str) -> Optional[str]:
        """Get response from API (streaming or normal) and print it.
        Returns the full content string or None if an error occurred.

        Args:
            user_input (str): The user's input text.

        Returns:
            Optional[str]: The assistant's response content or None if an error occurred.
        """
        messages = self._build_messages(user_input)
        content = None
        reasoning = None

        try:
            if self.config.get("STREAM", True):
                stream_iterator = self.api_client.stream_completion(messages)
                content, reasoning = self.printer.display_stream(stream_iterator)
            else:
                content, reasoning = self.api_client.completion(messages)
                self.printer.display_normal(content, reasoning)

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
        save_cmd = f"{CMD_SAVE_CHAT} <title>"
        self.console.print(f"{save_cmd:<19}: Save current chat")
        load_cmd = f"{CMD_LOAD_CHAT} <index>"
        self.console.print(f"{load_cmd:<19}: Load a saved chat")
        delete_cmd = f"{CMD_DELETE_CHAT} <index>"
        self.console.print(f"{delete_cmd:<19}: Delete a saved chat")
        self.console.print(f"{CMD_LIST_CHATS:<19}: List saved chats")
        cmd_exit = f"{CMD_EXIT}|Ctrl+D|Ctrl+C"
        self.console.print(f"{cmd_exit:<19}: Exit")
        cmd_mode = f"{CMD_MODE} {CHAT_MODE}|{EXEC_MODE}"
        self.console.print(f"{cmd_mode:<19}: Switch mode (Case insensitive)", style="dim")

    def _run_repl(self) -> None:
        """Run the main Read-Eval-Print Loop (REPL)."""
        self.prepare_chat_loop()
        self._print_welcome_message()
        chat_info = {}
        if self.chat_title:
            chat_info = self.chat_manager.load_chat_by_title(self.chat_title)
            self.history = chat_info.get("history", [])
        while True:
            self.console.print(Markdown("---", code_theme=self.config.get("CODE_THEME", "monokai")))
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
        if not self.is_temp_session and self.history:
            if self.chat_title:
                self._save_chat(self.chat_title)
            else:
                self._save_chat()

        self.console.print("\nExiting YAICLI... Goodbye!", style="bold green")

    def _run_once(self, prompt_arg: str, is_shell_mode: bool) -> None:
        """Run a single command (non-interactive)."""
        self.current_mode = EXEC_MODE if is_shell_mode else TEMP_MODE
        if not self.config.get("API_KEY"):
            self.console.print("[bold red]Error:[/bold red] API key not found.")
            raise typer.Exit(code=1)

        content = self._handle_llm_response(prompt_arg)

        if content is None:
            raise typer.Exit(code=1)

        if is_shell_mode:
            self._confirm_and_execute(content)

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

    def _setup_key_bindings(self) -> None:
        """Setup keyboard shortcuts (e.g., TAB for mode switching)."""

        @self.bindings.add(Keys.ControlI)  # TAB
        def _(event: KeyPressEvent) -> None:
            self.current_mode = EXEC_MODE if self.current_mode == CHAT_MODE else CHAT_MODE

    def run(self, chat: bool, shell: bool, prompt: Optional[str]) -> None:
        """Main entry point to run the CLI (REPL or single command)."""
        if chat:
            if not self.config.get("API_KEY"):
                self.console.print("[bold red]Error:[/bold red] API key not found. Cannot start chat mode.")
                return
            self.current_mode = CHAT_MODE

            # Only set chat start time and title if a prompt is provided
            if prompt:
                self.chat_start_time = int(time.time())
                self.chat_title = self.chat_manager.make_chat_title(prompt)
                self.console.print(f"Chat title: [bold]{self.chat_title}[/bold]")
                self.is_temp_session = False
            else:
                # Mark as temporary session if no prompt
                self.is_temp_session = True
                self.console.print(
                    "Starting a temporary chat session (will not be saved automatically)", style="yellow"
                )

            self._run_repl()
        elif prompt:
            self._run_once(prompt, shell)
        else:
            self.console.print("No chat or prompt provided. Exiting.")
