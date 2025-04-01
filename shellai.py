import configparser
import json
import subprocess
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import requests
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Confirm


class ModeEnum(StrEnum):
    CHAT = "chat"
    EXECUTE = "execute"


class ShellAI:
    # Configuration file path
    CONFIG_PATH = Path("~/.config/shellai/config.json").expanduser()

    # Default configuration template
    DEFAULT_CONFIG_INI = """
    [DEFAULT]
    base_url=https://api.openai.com/v1
    api_key=
    model=gpt-4o
    default_mode=chat

    # auto detect shell and os
    shell=auto
    os=auto

    # if you want to use custom completions path, you can set it here
    completions_path=/chat/completions
    # if you want to use custom answer path, you can set it here
    answer_path=choices[0].message.content

    # true: streaming response
    # false: non-streaming response
    stream=true
    """

    def __init__(self):
        # Initialize terminal components
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

    def get_default_config(self):
        """Get default configuration"""
        config = configparser.RawConfigParser()
        try:
            config.read_string(self.DEFAULT_CONFIG_INI)
            config_dict = dict(config["DEFAULT"])
            config_dict["stream"] = str(config_dict.get("stream", "true")).lower()
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
                default_config = self.get_default_config()
                json.dump(default_config, f, indent=4)
            return default_config
        with open(self.CONFIG_PATH, "r") as f:
            return json.load(f)

    def _call_api(self, url, headers, data):
        """Generic API call method"""
        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 200:
            self.console.print(f"[red]API request failed: {response.status_code}[/red]")
            return None
        return response

    def call_llm_api(self, prompt):
        """Call LLM API, return streaming output"""
        url = f"{self.config['base_url']}/chat/completions"
        headers = {"Authorization": f"Bearer {self.config['api_key']}"}
        data = {
            "model": self.config["model"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": self.config.get("stream", "true") == "true",
        }

        response = self._call_api(url, headers, data)
        if not response:
            return

        self.console.print("\n[bold green]Assistant:[/bold green] ", end="")
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
                        self.console.print(f"[red]Error decoding JSON: {decoded_line}[/red]")
                time.sleep(0.05)
        print("\n")

    def get_command_from_llm(self, prompt):
        """Request Shell command from LLM"""
        url = f"{self.config['base_url']}/chat/completions"
        headers = {"Authorization": f"Bearer {self.config['api_key']}"}
        data = {
            "model": self.config["model"],
            "messages": [
                {
                    "role": "system",
                    "content": "You are a command line assistant, return one Linux/macOS shell commands only, without explanation and triple-backtick code blocks.",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,  # Always use non-streaming for command generation
        }

        response = self._call_api(url, headers, data)
        if not response:
            return None

        return response.json()["choices"][0]["message"]["content"].strip()

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

    def execute_mode(self, user_input: str):
        """Execute mode"""
        if user_input == "" or self.current_mode != ModeEnum.EXECUTE.value:
            return self.current_mode

        command = self.get_command_from_llm(user_input)
        if command:
            self.console.print(f"\n[bold magenta]Generated command:[/bold magenta] `{command}`")
            confirm = Confirm.ask("Execute this command?")
            if confirm:
                self.execute_shell_command(command)
        return ModeEnum.EXECUTE.value

    def run(self, verbose=False, chat=False, shell=False):
        """Run the CLI application"""
        # Load configuration
        self.config = self.load_config()
        if not self.config["api_key"]:
            self.console.print(
                "[red]API key not found. Please set it in the configuration file.[/red]"
            )
            return

        # Set initial mode
        self.current_mode = self.config["default_mode"]

        # Check run mode from command line arguments
        if all([chat, shell]):
            self.console.print("[red]Cannot use both --chat and --shell[/red]")
            return
        elif chat:
            self.current_mode = ModeEnum.CHAT.value
        elif shell:
            self.current_mode = ModeEnum.EXECUTE.value

        if verbose:
            self.console.print("[bold yellow]Verbose mode enabled[/bold yellow]")
            self.console.print(f"[bold yellow]Current mode: {self.current_mode}[/bold yellow]")
            self.console.print(f"[bold yellow]Using model: {self.config['model']}[/bold yellow]")

        # Enable keyboard shortcuts
        get_app().key_bindings = self.bindings

        # Run main loop
        while True:
            user_input = self.session.prompt(self.get_prompt_tokens)

            if user_input.lower() in ("exit", "quit"):
                break

            if self.current_mode == ModeEnum.CHAT.value:
                self.chat_mode(user_input)
            elif self.current_mode == ModeEnum.EXECUTE.value:
                self.execute_mode(user_input)

        self.console.print("[bold green]Exiting...[/bold green]")


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
    cli.run(verbose=verbose, chat=chat, shell=shell)


if __name__ == "__main__":
    app()
