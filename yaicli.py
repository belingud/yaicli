import configparser
import json
import subprocess
import time
from enum import StrEnum
from os import getenv
from os.path import basename, pathsep
from pathlib import Path
from typing import Annotated, Optional

import jmespath
import requests
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Confirm


class ModeEnum(StrEnum):
    CHAT = "chat"
    EXECUTE = "exec"
    TEMP = "temp"


class CasePreservingConfigParser(configparser.RawConfigParser):
    def optionxform(self, optionstr):
        return optionstr


class ShellAI:
    # Configuration file path
    CONFIG_PATH = Path("~/.config/yaicli/config.ini").expanduser()

    # Default configuration template
    DEFAULT_CONFIG_INI = """[core]
BASE_URL=https://api.openai.com/v1
API_KEY=
MODEL=gpt-4o

# default run mode, default: temp
# chat: interactive chat mode
# exec: shell command generation mode
# temp: one-shot mode
DEFAULT_MODE=temp

# auto detect shell and os
SHELL_NAME=auto
OS_NAME=auto

# if you want to use custom completions path, you can set it here
COMPLETION_PATH=/chat/completions
# if you want to use custom answer path, you can set it here
ANSWER_PATH=choices[0].message.content

# true: streaming response
# false: non-streaming response
STREAM=true"""

    def __init__(self, verbose: bool = False):
        # Initialize terminal components
        self.verbose = verbose
        self.console = Console()
        self.bindings = KeyBindings()
        self.session = PromptSession(key_bindings=self.bindings)
        self.current_mode = ModeEnum.CHAT.value
        self.config = {}

        # Setup key bindings
        self._setup_key_bindings()

    def _setup_key_bindings(self):
        """Setup keyboard shortcuts"""

        @self.bindings.add(Keys.ControlI)  # Bind Ctrl+I to switch modes
        def _(event: KeyPressEvent):
            self.current_mode = (
                ModeEnum.CHAT.value
                if self.current_mode == ModeEnum.EXECUTE.value
                else ModeEnum.EXECUTE.value
            )

    def get_os(self):
        """Detect operating system"""
        if self.config.get("OS_NAME") != "auto":
            return self.config.get("OS_NAME")
        import platform

        return platform.system()

    def get_shell(self):
        """Detect shell"""
        if self.config.get("SHELL_NAME") != "auto":
            return self.config.get("SHELL_NAME")
        import platform

        current_platform = platform.system()
        if current_platform in ("Windows", "nt"):
            is_powershell = len(getenv("PSModulePath", "").split(pathsep)) >= 3
            return "powershell.exe" if is_powershell else "cmd.exe"
        return basename(getenv("SHELL", "/bin/sh"))

    def get_default_config(self):
        """Get default configuration"""
        config = CasePreservingConfigParser()
        try:
            config.read_string(self.DEFAULT_CONFIG_INI)
            config_dict = {k.upper(): v for k, v in config["core"].items()}
            config_dict["STREAM"] = str(config_dict.get("STREAM", "true")).lower()
            return config_dict
        except configparser.Error as e:
            self.console.print(f"[red]Error parsing config: {e}[/red]")
            raise typer.Exit(code=1) from None

    def load_config(self):
        """Load LLM API configuration"""
        if not self.CONFIG_PATH.exists():
            self.console.print(
                "[bold yellow]Configuration file not found. Creating default configuration file.[/bold yellow]"
            )
            self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_PATH, "w") as f:
                f.write(self.DEFAULT_CONFIG_INI)
            return self.config
        config = CasePreservingConfigParser()
        config.read(self.CONFIG_PATH)
        self.config = dict(config["core"])
        self.config["STREAM"] = str(self.config.get("STREAM", "true")).lower()
        return self.config

    def _call_api(self, url, headers, data):
        """Generic API call method"""
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()  # Raise an exception for non-200 status codes
        return response

    def call_llm_api(self, prompt):
        """Call LLM API, return streaming output"""
        base = self.config.get("BASE_URL", "").rstrip("/")
        if not base:
            self.console.print(
                "[red]Base URL not found. Please set it in the configuration file. Default: https://api.openai.com/v1[/red]"
            )
            return
        COMPLETION_PATH = self.config.get("COMPLETION_PATH", "").lstrip("/")
        if not COMPLETION_PATH:
            self.console.print(
                "[red]Completions path not set. Please set it in the configuration file. Default: `/chat/completions`[/red]"
            )
            return
        url = f"{base}/{COMPLETION_PATH}"
        headers = {"Authorization": f"Bearer {self.config['API_KEY']}"}
        data = {
            "model": self.config["MODEL"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": self.config.get("STREAM", "true") == "true",
        }
        try:
            response = self._call_api(url, headers, data)
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]Error calling API: {e}[/red]")
            return
        if not response:
            return

        self.console.print("\n[bold green]Assistant:[/bold green]")
        full_completion = ""
        # Streaming response loop
        with Live(console=self.console) as live:
            for line in response.iter_lines():
                if not line:
                    continue
                decoded_line = line.decode("utf-8")
                if decoded_line.startswith("data: "):
                    decoded_line = decoded_line[6:]
                    if decoded_line == "[DONE]":
                        break
                    try:
                        json_data = json.loads(decoded_line)
                        content = json_data["choices"][0]["delta"].get("content", "")
                        full_completion += content
                        markdown = Markdown(markup=full_completion)
                        live.update(markdown, refresh=True)
                    except json.JSONDecodeError:
                        self.console.print("[red]Error decoding response JSON[/red]")
                        if self.verbose:
                            self.console.print(f"[red]Error decoding JSON: {decoded_line}[/red]")
                time.sleep(0.05)

        self.console.print()  # Add a newline after the completion

    def get_command_from_llm(self, prompt):
        """Request Shell command from LLM"""
        url = f"{self.config['BASE_URL']}/chat/completions"
        headers = {"Authorization": f"Bearer {self.config['API_KEY']}"}
        data = {
            "model": self.config["MODEL"],
            "messages": [
                {
                    "role": "system",
                    "content": "You are a command line assistant, return one Linux/macOS shell commands only, without explanation and triple-backtick code blocks.",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,  # Always use non-streaming for command generation
        }

        try:
            response = self._call_api(url, headers, data)
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]Error calling API: {e}[/red]")
            return None
        if not response:
            return None
        ANSWER_PATH = self.config.get("ANSWER_PATH", None)
        if not ANSWER_PATH:
            ANSWER_PATH = "choices[0].message.content"
            if self.verbose:
                self.console.print(
                    "[bold yellow]Answer path not set. Using default: `choices[0].message.content`[/bold yellow]"
                )
        content = jmespath.search(ANSWER_PATH, response.json())
        return content.strip()

    def execute_shell_command(self, command):
        """Execute shell command"""
        self.console.print(f"\n[bold green]Executing command: [/bold green] {command}\n")
        result = subprocess.run(command, shell=True)
        if result.returncode != 0:
            self.console.print(
                f"\n[bold red]Command failed with return code: {result.returncode}[/bold red]"
            )

    def get_prompt_tokens(self):
        """Get prompt tokens based on current mode"""
        if self.current_mode == ModeEnum.CHAT.value:
            qmark = "💬"
        elif self.current_mode == ModeEnum.EXECUTE.value:
            qmark = "🚀"
        else:
            qmark = ""
        return [("class:qmark", qmark), ("class:question", " {} ".format(">"))]

    def chat_mode(self, user_input: str):
        """Interactive chat mode"""
        if self.current_mode != ModeEnum.CHAT.value:
            return self.current_mode

        self.call_llm_api(user_input)
        return ModeEnum.CHAT.value

    def _filter_command(self, command):
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
        ```ls -al``` ==> ls -al
        ls -al ==> ls -al
        ```\ncd /tmp\nls -la\n``` ==> cd /tmp\nls -la
        ```bash\ncd /tmp\nls -la\n``` ==> cd /tmp\nls -la
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

    def execute_mode(self, user_input: str):
        """Execute mode"""
        if user_input == "" or self.current_mode != ModeEnum.EXECUTE.value:
            return self.current_mode

        command = self.get_command_from_llm(user_input)
        command = self._filter_command(command)
        if not command:
            self.console.print("[bold red]No command generated[/bold red]")
            return self.current_mode
        self.console.print(f"\n[bold magenta]Generated command:[/bold magenta] {command}")
        confirm = Confirm.ask("Execute this command?")
        if confirm:
            self.execute_shell_command(command)
        return ModeEnum.EXECUTE.value

    def run_repl_loop(self):
        while True:
            user_input = self.session.prompt(self.get_prompt_tokens)
            # Skip empty input
            if not user_input.strip():
                continue

            if user_input.lower() in ("exit", "quit"):
                break

            if self.current_mode == ModeEnum.CHAT.value:
                self.chat_mode(user_input)
            elif self.current_mode == ModeEnum.EXECUTE.value:
                self.execute_mode(user_input)

        self.console.print("[bold green]Exiting...[/bold green]")

    def run_one_shot(self, prompt: str):
        """Run one-shot mode with given prompt"""
        if self.current_mode == ModeEnum.EXECUTE.value:
            self.execute_mode(prompt)  # Execute mode for one-shot prompt
        else:
            self.call_llm_api(prompt)

    def run(self, chat=False, shell=False, prompt: Optional[str] = None):
        """Run the CLI application"""
        # Load configuration
        self.config = self.load_config()
        if not self.config.get("API_KEY", None):
            self.console.print(
                "[red]API key not found. Please set it in the configuration file.[/red]"
            )
            return

        # Set initial mode
        self.current_mode = self.config["DEFAULT_MODE"]

        # Check run mode from command line arguments
        if all([chat, shell]):
            self.console.print("[red]Cannot use both --chat and --shell[/red]")
            return
        elif chat:
            self.current_mode = ModeEnum.CHAT.value
        elif shell:
            self.current_mode = ModeEnum.EXECUTE.value

        if self.verbose:
            self.console.print("[bold yellow]Verbose mode enabled[/bold yellow]")
            self.console.print(f"[bold yellow]Current mode: {self.current_mode}[/bold yellow]")
            self.console.print(f"[bold yellow]Using model: {self.config['MODEL']}[/bold yellow]")

        if self.current_mode in (ModeEnum.TEMP.value, ModeEnum.EXECUTE.value) and prompt:
            self.run_one_shot(prompt)
        elif self.current_mode == ModeEnum.CHAT.value:
            self.run_repl_loop()


# CLI application setup
CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "show_default": True,
}

app = typer.Typer(
    name="ShellAI",
    context_settings=CONTEXT_SETTINGS,
    pretty_exceptions_enable=False,
    short_help="ShellAI Command Line Tool",
    no_args_is_help=True,
    invoke_without_command=True,
)


@app.command()
def main(
    prompt: Annotated[str, typer.Argument(show_default=False, help="The prompt send to the LLM")],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-V", help="Show verbose information")
    ] = False,
    chat: Annotated[bool, typer.Option("--chat", "-c", help="Start in chat mode")] = False,
    shell: Annotated[
        bool, typer.Option("--shell", "-s", help="Generate and execute shell command")
    ] = False,
):
    """LLM CLI Tool"""
    cli = ShellAI()
    cli.run(chat=chat, shell=shell, prompt=prompt)


if __name__ == "__main__":
    app()
