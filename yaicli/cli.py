from os import devnull
from pathlib import Path
import sys
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from rich.markdown import Markdown
import typer

from .chat import FileChatManager, chat_mgr
from .config import cfg
from .console import get_console
from .const import (
    CHAT_MODE,
    CONFIG_PATH,
    DEFAULT_OS_NAME,
    DEFAULT_SHELL_NAME,
    EXEC_MODE,
    TEMP_MODE,
    DefaultRoleNames,
)
from .printer import Printer
from .providers.base import Message
from .role import Role, RoleManager, role_mgr
from .utils import detect_os, detect_shell

console = get_console()


class CLI:
    def __init__(
        self,
        verbose: bool = False,
        role: str = DefaultRoleNames.DEFAULT,
        # printer: Optional[Printer] = None,
        chat_manager: Optional[FileChatManager] = None,
        role_manager: Optional[RoleManager] = None,
    ):
        self.verbose: bool = verbose
        # --role can specify a role when enter interactive chat
        # TAB will switch between role and shell
        self.init_role: str = role
        self.role_name: str = role

        self.chat_manager = chat_manager or chat_mgr
        self.role_manager = role_manager or role_mgr
        self.role: Role = self.role_manager.get_role(self.role_name)
        self.printer = Printer()

        self.bindings = KeyBindings()

        self.current_mode: str = TEMP_MODE

        self.history: list[Message] = []
        self.interactive_round = cfg["INTERACTIVE_ROUND"]
        self.chat_title = None
        self.chat_start_time = None
        self.is_temp_session = True

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
            console.print("Loading Configuration:", style="bold cyan")
            console.print(f"Config file path: {CONFIG_PATH}")
            for key, value in cfg.items():
                display_value = "****" if key == "API_KEY" and value else value
                console.print(f"  {key:<17}: {display_value}")
            console.print(f"Current role: {self.role_name}")
            console.print(Markdown("---", code_theme=cfg["CODE_THEME"]))

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

    @classmethod
    def judge_role(cls, code: bool = False, shell: bool = False, role: str = ""):
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
        if len(self.history) > target_len:
            self.history = self.history[-target_len:]
            if self.verbose:
                console.print(f"Dialogue trimmed to {target_len} messages.", style="dim")

    def _run_once(self, input: str, shell: bool = False, code: bool = False) -> None:
        """Handle default mode"""
        from yaicli.providers.factory import ProviderFactory

        self.set_role(self.judge_role(code, shell, self.init_role))

        provider = ProviderFactory.create_provider()
        messages = [Message(role="system", content=self.role.prompt), Message(role="user", content=input)]
        response = provider.completion(messages, self.role, stream=cfg["STREAM"])
        if self.role_name != DefaultRoleNames.CODER:
            console.print("Assistant:", style="bold green")
        if cfg["STREAM"]:
            self.printer.display_stream(response)
        else:
            self.printer.display_normal([response])

    def run(self, chat: bool = False, shell: bool = False, code: bool = False, input: Optional[str] = None):
        print(f"chat: {chat}, shell: {shell}, input: {input}")
        if not input and not chat:
            console.print("No input provided.", style="bold red")
            raise typer.Abort()
        if chat:
            pass
        else:
            self._run_once(input or "", shell=shell, code=code)
