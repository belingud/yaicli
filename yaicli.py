import configparser
import io
import json
import platform
import subprocess
import sys
import time
from os import getenv
from os.path import basename, exists, pathsep, devnull
from pathlib import Path
from typing import Annotated, Optional, Union

import httpx
import jmespath
import typer
from distro import name as distro_name
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory, _StrOrBytesPath
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

SHELL_PROMPT = """Your are a Shell Command Generator.
Generate a command EXCLUSIVELY for {_os} OS with {_shell} shell.
Rules:
1. Use ONLY {_shell}-specific syntax and connectors (&&, ||, |, etc)
2. Output STRICTLY in plain text format
3. NEVER use markdown, code blocks or explanations
4. Chain multi-step commands in SINGLE LINE
5. Return NOTHING except the ready-to-run command"""

DEFAULT_PROMPT = (
    "You are YAICLI, a system management and programing assistant, "
    "You are managing {_os} operating system with {_shell} shell. "
    "Your responses should be concise and use Markdown format, "
    "unless the user explicitly requests more details."
)

CMD_CLEAR = "/clear"
CMD_EXIT = "/exit"
CMD_HISTORY = "/his"

EXEC_MODE = "exec"
CHAT_MODE = "chat"
TEMP_MODE = "temp"

DEFAULT_CONFIG_MAP = {
    "BASE_URL": {"value": "https://api.openai.com/v1", "env_key": "YAI_BASE_URL"},
    "API_KEY": {"value": "", "env_key": "YAI_API_KEY"},
    "MODEL": {"value": "gpt-4o", "env_key": "YAI_MODEL"},
    "SHELL_NAME": {"value": "auto", "env_key": "YAI_SHELL_NAME"},
    "OS_NAME": {"value": "auto", "env_key": "YAI_OS_NAME"},
    "COMPLETION_PATH": {"value": "chat/completions", "env_key": "YAI_COMPLETION_PATH"},
    "ANSWER_PATH": {"value": "choices[0].message.content", "env_key": "YAI_ANSWER_PATH"},
    "STREAM": {"value": "true", "env_key": "YAI_STREAM"},
    "CODE_THEME": {"value": "monokia", "env_key": "YAI_CODE_THEME"},
    "TEMPERATURE": {"value": "0.7", "env_key": "YAI_TEMPERATURE"},
    "TOP_P": {"value": "1.0", "env_key": "YAI_TOP_P"},
    "MAX_TOKENS": {"value": "1024", "env_key": "YAI_MAX_TOKENS"},
    "MAX_HISTORY": {"value": "500", "env_key": "YAI_MAX_HISTORY"},
}

DEFAULT_CONFIG_INI = """[core]
PROVIDER=openai
BASE_URL=https://api.openai.com/v1
API_KEY=
MODEL=gpt-4o

# auto detect shell and os
SHELL_NAME=auto
OS_NAME=auto

# if you want to use custom completions path, you can set it here
COMPLETION_PATH=/chat/completions
# if you want to use custom answer path, you can set it here
ANSWER_PATH=choices[0].message.content

# true: streaming response
# false: non-streaming response
STREAM=true
CODE_THEME=monokia

TEMPERATURE=0.7
TOP_P=1.0
MAX_TOKENS=1024

MAX_HISTORY=500"""

app = typer.Typer(
    name="yaicli",
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,
)


class CasePreservingConfigParser(configparser.RawConfigParser):
    """Case preserving config parser"""

    def optionxform(self, optionstr):
        return optionstr


class LimitedFileHistory(FileHistory):
    def __init__(self, filename: _StrOrBytesPath, max_entries: int = 500, trim_every: int = 5):
        """Limited file history
        Args:
            filename (str): path to history file
            max_entries (int): maximum number of entries to keep
            trim_every (int): trim history every `trim_every` appends

        Example:
            >>> history = LimitedFileHistory("~/.yaicli_history", max_entries=500, trim_every=10)
            >>> history.append_string("echo hello")
            >>> history.append_string("echo world")
            >>> session = PromptSession(history=history)
        """
        self.max_entries = max_entries
        self._append_count = 0
        self._trim_every = trim_every
        super().__init__(filename)

    def store_string(self, string: str) -> None:
        # Call the original method to deposit a new record
        super().store_string(string)

        self._append_count += 1
        if self._append_count >= self._trim_every:
            self._trim_history()
            self._append_count = 0

    def _trim_history(self):
        if not exists(self.filename):
            return

        with open(self.filename, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # By record: each record starts with "# timestamp" followed by a number of "+lines".
        entries = []
        current_entry = []

        for line in lines:
            if line.startswith("# "):
                if current_entry:
                    entries.append(current_entry)
                current_entry = [line]
            elif line.startswith("+") or line.strip() == "":
                current_entry.append(line)

        if current_entry:
            entries.append(current_entry)

        # Keep the most recent max_entries row (the next row is newer)
        trimmed_entries = entries[-self.max_entries :]

        with open(self.filename, "w", encoding="utf-8") as f:
            for entry in trimmed_entries:
                f.writelines(entry)


class CLI:
    CONFIG_PATH = Path("~/.config/yaicli/config.ini").expanduser()

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.console = Console()
        self.bindings = KeyBindings()
        # Disable nonatty warning
        _origin_stderr = None
        if not sys.stderr.isatty():
            _origin_stderr = sys.stderr
            sys.stderr = open(devnull, "w")
        self.session = PromptSession(key_bindings=self.bindings)
        # Restore stderr
        if _origin_stderr:
            sys.stderr.close()
            sys.stderr = _origin_stderr
        self.config = {}
        self.history: list[dict[str, str]] = []
        self.max_history_length = 25
        self.current_mode = TEMP_MODE

    def is_stream(self) -> bool:
        """Check if streaming is enabled"""
        return self.config["STREAM"] == "true"

    def prepare_chat_loop(self) -> None:
        """Setup key bindings and history for chat mode"""
        self._setup_key_bindings()
        # Initialize history
        Path("~/.yaicli_history").expanduser().touch(exist_ok=True)
        self.session = PromptSession(
            key_bindings=self.bindings,
            completer=WordCompleter(["/clear", "/exit", "/his"]),
            complete_while_typing=True,
            history=LimitedFileHistory(
                Path("~/.yaicli_history").expanduser(), max_entries=int(self.config["MAX_HISTORY"])
            ),
            enable_history_search=True,
        )

    def _setup_key_bindings(self) -> None:
        """Setup keyboard shortcuts"""

        @self.bindings.add(Keys.ControlI)  # Bind TAB to switch modes
        def _(event: KeyPressEvent) -> None:
            self.current_mode = EXEC_MODE if self.current_mode == CHAT_MODE else CHAT_MODE

    def load_config(self) -> dict[str, str]:
        """Load LLM API configuration with priority:
        1. Environment variables (highest priority)
        2. Configuration file
        3. Default values (lowest priority)

        Returns:
            dict: merged configuration
        """
        # Start with default configuration (lowest priority)
        merged_config = {k: v["value"] for k, v in DEFAULT_CONFIG_MAP.items()}

        # Create default config file if it doesn't exist
        if not self.CONFIG_PATH.exists():
            self.console.print("[bold yellow]Creating default configuration file.[/bold yellow]")
            self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_PATH, "w") as f:
                f.write(DEFAULT_CONFIG_INI)
        else:
            # Load from configuration file (middle priority)
            config_parser = CasePreservingConfigParser()
            config_parser.read(self.CONFIG_PATH)
            if "core" in config_parser:
                # Update with non-empty values from config file
                merged_config.update({k: v for k, v in config_parser["core"].items() if v.strip()})

        # Override with environment variables (highest priority)
        for key, config in DEFAULT_CONFIG_MAP.items():
            env_value = getenv(config["env_key"])
            if env_value is not None:
                merged_config[key] = env_value

        merged_config["STREAM"] = str(merged_config.get("STREAM", "true")).lower()

        self.config = merged_config
        return merged_config

    def detect_os(self) -> str:
        """Detect operating system + version"""
        if self.config.get("OS_NAME") != "auto":
            return self.config["OS_NAME"]
        current_platform = platform.system()
        if current_platform == "Linux":
            return "Linux/" + distro_name(pretty=True)
        if current_platform == "Windows":
            return "Windows " + platform.release()
        if current_platform == "Darwin":
            return "Darwin/MacOS " + platform.mac_ver()[0]
        return current_platform

    def detect_shell(self) -> str:
        """Detect shell name"""
        if self.config["SHELL_NAME"] != "auto":
            return self.config["SHELL_NAME"]

        current_platform = platform.system()
        if current_platform in ("Windows", "nt"):
            is_powershell = len(getenv("PSModulePath", "").split(pathsep)) >= 3
            return "powershell.exe" if is_powershell else "cmd.exe"
        return basename(getenv("SHELL", None) or "/bin/sh")

    def _filter_command(self, command: str) -> Optional[str]:
        """Filter out unwanted characters from command

        The LLM may return commands in markdown format with code blocks.
        This method removes markdown formatting from the command.
        It handles various formats including:
        - Commands surrounded by ``` (plain code blocks)
        - Commands with language specifiers like ```bash, ```zsh, etc.
        - Commands with specific examples like ```ls -al```

        example:
        ```bash\nls -la\n``` ==> ls -al
        ```zsh\nls -la\n``` ==> ls -al
        ```ls -la``` ==> ls -la
        ls -la ==> ls -la
        ```\ncd /tmp\nls -la\n``` ==> cd /tmp\nls -la
        ```bash\ncd /tmp\nls -la\n``` ==> cd /tmp\nls -la
        ```plaintext\nls -la\n``` ==> ls -la
        """
        if not command or not command.strip():
            return ""

        # Handle commands that are already without code blocks
        if "```" not in command:
            return command.strip()

        # Handle code blocks with or without language specifiers
        lines = command.strip().split("\n")

        # Check if it's a single-line code block like ```ls -al```
        if len(lines) == 1 and lines[0].startswith("```") and lines[0].endswith("```"):
            return lines[0][3:-3].strip()

        # Handle multi-line code blocks
        if lines[0].startswith("```"):
            # Remove the opening ``` line (with or without language specifier)
            content_lines = lines[1:]

            # If the last line is a closing ```, remove it
            if content_lines and content_lines[-1].strip() == "```":
                content_lines = content_lines[:-1]

            # Join the remaining lines and strip any extra whitespace
            return "\n".join(line.strip() for line in content_lines if line.strip())

    def _get_number_with_type(self, key, _type: type, default=None):
        """Get number with type from config"""
        try:
            return _type(self.config.get(key, default))
        except ValueError:
            raise ValueError(f"[red]{key} should be {_type} type.[/red]")

    def post(self, message: list[dict[str, str]]) -> httpx.Response:
        """Post message to LLM API and return response"""
        url = self.config.get("BASE_URL", "").rstrip("/") + "/" + self.config.get("COMPLETION_PATH", "").lstrip("/")
        body = {
            "messages": message,
            "model": self.config.get("MODEL", "gpt-4o"),
            "stream": self.is_stream(),
            "temperature": self._get_number_with_type(key="TEMPERATURE", _type=float, default="0.7"),
            "top_p": self._get_number_with_type(key="TOP_P", _type=float, default="1.0"),
            "max_tokens": self._get_number_with_type(key="MAX_TOKENS", _type=int, default="1024"),
        }
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                url, json=body, headers={"Authorization": f"Bearer {self.config.get('API_KEY', '')}"}
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            self.console.print(f"[red]Error calling API: {e}[/red]")
            if self.verbose:
                self.console.print(f"Reason: {e}\nResponse: {response.text}")
            raise e
        return response

    def get_reasoning_content(self, delta: dict) -> Optional[str]:
        # reasoning: openrouter
        # reasoning_content: infi-ai/deepseek
        for k in ("reasoning_content", "reasoning"):
            if k in delta:
                return delta[k]
        return None

    def _parse_stream_line(self, line: Union[bytes, str]) -> Optional[dict]:
        """Parse a single line from the stream response"""
        if not line:
            return None

        line = str(line)
        if not line.startswith("data: "):
            return None

        line = line[6:]
        if line == "[DONE]":
            return None

        try:
            json_data = json.loads(line)
            if not json_data.get("choices"):
                return None

            return json_data
        except json.JSONDecodeError:
            self.console.print("[red]Error decoding response JSON[/red]")
            if self.verbose:
                self.console.print(f"[red]Error JSON data: {line}[/red]")
            return None

    def _process_reasoning_content(self, reason: str, full_completion: str, in_reasoning: bool) -> tuple[str, bool]:
        """Process reasoning content in the response"""
        if not in_reasoning:
            in_reasoning = True
            full_completion = "> Reasoning:\n> "
        full_completion += reason.replace("\n", "\n> ")
        return full_completion, in_reasoning

    def _process_regular_content(self, content: str, full_completion: str, in_reasoning: bool) -> tuple[str, bool]:
        """Process regular content in the response"""
        if in_reasoning:
            in_reasoning = False
            full_completion += "\n\n"
        full_completion += content
        return full_completion, in_reasoning

    def _print_stream(self, response: httpx.Response) -> str:
        """Print response from LLM in streaming mode"""
        self.console.print("Assistant:", style="bold green")
        full_content = ""
        in_reasoning = False
        cursor_chars = ["_", " "]
        cursor_index = 0

        with Live(console=self.console) as live:
            for line in response.iter_lines():
                json_data = self._parse_stream_line(line)
                if not json_data:
                    continue

                delta = json_data["choices"][0]["delta"]
                reason = self.get_reasoning_content(delta)

                if reason is not None:
                    full_content, in_reasoning = self._process_reasoning_content(reason, full_content, in_reasoning)
                else:
                    full_content, in_reasoning = self._process_regular_content(
                        delta.get("content", "") or "", full_content, in_reasoning
                    )

                cursor = cursor_chars[cursor_index]
                live.update(Markdown(markup=full_content + cursor, code_theme=self.config["CODE_THEME"]), refresh=True)
                cursor_index = (cursor_index + 1) % 2
                time.sleep(0.005)  # Slow down the printing speed, avoiding screen flickering
            live.update(Markdown(markup=full_content, code_theme=self.config["CODE_THEME"]), refresh=True)
        return full_content

    def _print_normal(self, response: httpx.Response) -> str:
        """Print response from LLM in non-streaming mode"""
        self.console.print("Assistant:", style="bold green")
        full_content = jmespath.search(self.config.get("ANSWER_PATH", "choices[0].message.content"), response.json())
        self.console.print(Markdown(full_content + "\n", code_theme=self.config["CODE_THEME"]))
        return full_content

    def get_prompt_tokens(self) -> list[tuple[str, str]]:
        """Return prompt tokens for current mode"""
        qmark = "💬" if self.current_mode == CHAT_MODE else "🚀" if self.current_mode == EXEC_MODE else ""
        return [("class:qmark", qmark), ("class:question", " {} ".format(">"))]

    def _check_history_len(self) -> None:
        """Check history length and remove oldest messages if necessary"""
        if len(self.history) > self.max_history_length:
            self.history = self.history[-self.max_history_length :]

    def _handle_special_commands(self, user_input: str) -> Optional[bool]:
        """Handle special command return: True-continue loop, False-exit loop, None-non-special command"""
        if user_input.lower() == CMD_EXIT:
            return False
        if user_input.lower() == CMD_CLEAR and self.current_mode == CHAT_MODE:
            self.history.clear()
            self.console.print("Chat history cleared\n", style="bold yellow")
            return True
        if user_input.lower() == CMD_HISTORY:
            self.console.print(self.history)
            return True
        return None

    def _confirm_and_execute(self, content: str) -> None:
        """Review, edit and execute the command"""
        cmd = self._filter_command(content)
        if not cmd:
            self.console.print("No command generated", style="bold red")
            return
        self.console.print(Panel(cmd, title="Command", title_align="left", border_style="bold magenta", expand=False))
        _input = Prompt.ask(
            r"Execute command? \[e]dit, \[y]es, \[n]o",
            choices=["y", "n", "e"],
            default="n",
            case_sensitive=False,
            show_choices=False,
        )
        if _input == "y":  # execute cmd
            self.console.print("Output:", style="bold green")
            subprocess.call(cmd, shell=True)
        elif _input == "e":  # edit cmd
            cmd = prompt("Edit command, press enter to execute:\n", default=cmd)
            self.console.print("Output:", style="bold green")
            subprocess.call(cmd, shell=True)

    def _build_messages(self, user_input: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.get_system_prompt()},
            *self.history,
            {"role": "user", "content": user_input},
        ]

    def _handle_llm_response(self, response: httpx.Response, user_input: str) -> str:
        """Print LLM response and update history"""
        content = self._print_stream(response) if self.is_stream() else self._print_normal(response)
        self.history.extend([{"role": "user", "content": user_input}, {"role": "assistant", "content": content}])
        self._check_history_len()
        return content

    def _process_user_input(self, user_input: str) -> bool:
        """Process user input and generate response"""
        try:
            response = self.post(self._build_messages(user_input))
            content = self._handle_llm_response(response, user_input)
            if self.current_mode == EXEC_MODE:
                self._confirm_and_execute(content)
            return True
        except Exception as e:
            self.console.print(f"Error: {e}", style="red")
            return False

    def get_system_prompt(self) -> str:
        """Return system prompt for current mode"""
        prompt = SHELL_PROMPT if self.current_mode == EXEC_MODE else DEFAULT_PROMPT
        return prompt.format(_os=self.detect_os(), _shell=self.detect_shell())

    def _run_repl(self) -> None:
        """Run REPL loop, handling user input and generating responses, saving history, and executing commands"""
        self.prepare_chat_loop()
        self.console.print("""
██    ██  █████  ██  ██████ ██      ██
 ██  ██  ██   ██ ██ ██      ██      ██
  ████   ███████ ██ ██      ██      ██
   ██    ██   ██ ██ ██      ██      ██
   ██    ██   ██ ██  ██████ ███████ ██
""")
        self.console.print("↑/↓: navigate in history")
        self.console.print("Press TAB to change in chat and exec mode", style="bold")
        self.console.print("Type /clear to clear chat history", style="bold")
        self.console.print("Type /his to see chat history", style="bold")
        self.console.print("Press Ctrl+C or type /exit to exit\n", style="bold")

        while True:
            self.console.print(Markdown("---"))
            user_input = self.session.prompt(self.get_prompt_tokens).strip()
            if not user_input:
                continue

            # Handle exit commands
            if user_input.lower() == CMD_EXIT:
                break

            # Handle clear command
            if user_input.lower() == CMD_CLEAR and self.current_mode == CHAT_MODE:
                self.history = []
                self.console.print("[bold yellow]Chat history cleared[/bold yellow]\n")
                continue
            elif user_input.lower() == CMD_HISTORY:
                self.console.print(self.history)
                continue
            if not self._process_user_input(user_input):
                continue

        self.console.print("[bold green]Exiting...[/bold green]")

    def _run_once(self, prompt: str, shell: bool = False) -> None:
        """Run once with given prompt"""

        try:
            response = self.post(self._build_messages(prompt))
            content = self._handle_llm_response(response, prompt)
            if shell:
                self._confirm_and_execute(content)
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")

    def run(self, chat: bool, shell: bool, prompt: str) -> None:
        """Run the CLI"""
        self.load_config()
        if self.verbose:
            self.console.print(f"CODE_THEME: {self.config['CODE_THEME']}")
            self.console.print(f"ANSWER_PATH: {self.config['ANSWER_PATH']}")
            self.console.print(f"COMPLETION_PATH: {self.config['COMPLETION_PATH']}")
            self.console.print(f"BASE_URL: {self.config['BASE_URL']}")
            self.console.print(f"MODEL: {self.config['MODEL']}")
            self.console.print(f"SHELL_NAME: {self.config['SHELL_NAME']}")
            self.console.print(f"OS_NAME: {self.config['OS_NAME']}")
            self.console.print(f"STREAM: {self.config['STREAM']}")
            self.console.print(f"TEMPERATURE: {self.config['TEMPERATURE']}")
            self.console.print(f"TOP_P: {self.config['TOP_P']}")
            self.console.print(f"MAX_TOKENS: {self.config['MAX_TOKENS']}")
        if not self.config.get("API_KEY"):
            self.console.print(
                "[yellow]API key not set. Please set in ~/.config/yaicli/config.ini or AI_API_KEY env[/]"
            )
            raise typer.Exit(code=1)
        if chat:
            self.current_mode = CHAT_MODE
            self._run_repl()
        else:
            self.current_mode = EXEC_MODE if shell else TEMP_MODE
            self._run_once(prompt, shell)


@app.command()
def main(
    ctx: typer.Context,
    prompt: Annotated[Optional[str], typer.Argument(show_default=False, help="The prompt send to the LLM")] = None,
    chat: Annotated[
        bool, typer.Option("--chat", "-c", help="Start in chat mode", rich_help_panel="Run Options")
    ] = False,
    shell: Annotated[
        bool, typer.Option("--shell", "-s", help="Generate and execute shell command", rich_help_panel="Run Options")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-V", help="Show verbose information", rich_help_panel="Run Options")
    ] = False,
    template: Annotated[bool, typer.Option("--template", help="Show the config template.")] = False,
):
    """yaicli - Your AI interface in cli."""
    # Check for stdin input (from pipe or redirect)
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read()
        prompt = f"{stdin_content}\n\n{prompt}"

    if prompt == "":
        typer.echo("Empty prompt, ignored")
        return
    if template:
        typer.echo(DEFAULT_CONFIG_INI)
        return
    if not prompt and not chat:
        typer.echo(ctx.get_help())
        return

    cli = CLI(verbose=verbose)
    cli.run(chat=chat, shell=shell, prompt=prompt or "")


if __name__ == "__main__":
    app()
