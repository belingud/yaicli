import configparser
import json
import platform
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
from distro import name as distro_name
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


# Default configuration values (lowest priority)
DEFAULT_CONFIG = {
    "BASE_URL": "https://api.openai.com/v1",
    "API_KEY": "",
    "MODEL": "gpt-4o",
    "SHELL_NAME": "auto",
    "OS_NAME": "auto",
    "COMPLETION_PATH": "chat/completions",
    "ANSWER_PATH": "choices[0].message.content",
    "STREAM": "true",
}

# Environment variable mapping (config key -> environment variable name)
ENV_VAR_MAPPING = {
    "BASE_URL": "AI_OPENAI_API_BASE",
    "API_KEY": "AI_OPENAI_API_KEY",
    "MODEL": "AI_MODEL",
    "SHELL_NAME": "AI_SHELL_NAME",
    "OS_NAME": "AI_OS_NAME",
    "COMPLETION_PATH": "AI_COMPLETION_PATH",
    "ANSWER_PATH": "AI_ANSWER_PATH",
    "STREAM": "AI_STREAM",
}


class YAICLI:
    """Main class for YAICLI
    Chat mode: interactive chat mode
    One-shot mode:
        Temp: ask a question and get a response once
        Execute: generate and execute shell commands
    """

    # Configuration file path
    CONFIG_PATH = Path("~/.config/yaicli/config.ini").expanduser()

    # Default configuration template
    DEFAULT_CONFIG_INI = """[core]
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
STREAM=true"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.console = Console()
        self.bindings = KeyBindings()
        self.session = PromptSession(key_bindings=self.bindings)
        self.current_mode = ModeEnum.TEMP.value
        self.config = {}
        self.history = []
        self.max_history_length = 25

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

    def clear_history(self):
        """Clear chat history"""
        self.history = []

    def detect_os(self) -> str:
        """Detect operating system
        Returns:
            str: operating system name
        Raises:
            typer.Exit: if there is an error with the request
        """
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
        """Detect shell
        Returns:
            str: shell name
        Raises:
            typer.Exit: if there is an error with the request
        """
        if self.config["SHELL_NAME"] != "auto":
            return self.config["SHELL_NAME"]
        import platform

        current_platform = platform.system()
        if current_platform in ("Windows", "nt"):
            is_powershell = len(getenv("PSModulePath", "").split(pathsep)) >= 3
            return "powershell.exe" if is_powershell else "cmd.exe"
        return basename(getenv("SHELL", "/bin/sh"))

    def build_cmd_prompt(self) -> str:
        """Build command prompt
        Returns:
            str: command prompt
        Raises:
            typer.Exit: if there is an error with the request
        """
        _os = self.detect_os()
        _shell = self.detect_shell()
        return f"""Your are a Shell Command Generator.
Generate a command EXCLUSIVELY for {_os} OS with {_shell} shell.
Rules:
1. Use ONLY {_shell}-specific syntax and connectors (&&, ||, |, etc)
2. Output STRICTLY in plain text format
3. NEVER use markdown, code blocks or explanations
4. Chain multi-step commands in SINGLE LINE
5. Return NOTHING except the ready-to-run command"""

    def build_default_prompt(self) -> str:
        """Build default prompt
        Returns:
            str: default prompt
        Raises:
            typer.Exit: if there is an error with the request
        """
        _os = self.detect_os()
        _shell = self.detect_shell()
        return (
            "You are yaili, a system management and programing assistant, "
            f"You are managing {_os} operating system with {_shell} shell. "
            "Your responses should be concise and use Markdown format, "
            "unless the user explicitly requests more details."
        )

    def get_default_config(self) -> dict[str, str]:
        """Get default configuration
        Returns:
            dict: default configuration with lowest priority
        """
        return DEFAULT_CONFIG.copy()

    def load_config(self) -> dict[str, str]:
        """Load LLM API configuration with priority:
        1. Environment variables (highest priority)
        2. Configuration file
        3. Default values (lowest priority)

        Returns:
            dict: merged configuration
        """
        # Start with default configuration (lowest priority)
        merged_config = self.get_default_config()

        # Load from configuration file (middle priority)
        if not self.CONFIG_PATH.exists():
            self.console.print(
                "[bold yellow]Configuration file not found. Creating default configuration file.[/bold yellow]"
            )
            self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_PATH, "w") as f:
                f.write(self.DEFAULT_CONFIG_INI)
        else:
            config_parser = CasePreservingConfigParser()
            config_parser.read(self.CONFIG_PATH)
            if "core" in config_parser:
                # Update with values from config file
                for key, value in config_parser["core"].items():
                    if value.strip():  # Only use non-empty values from config file
                        merged_config[key] = value

        # Override with environment variables (highest priority)
        for config_key, env_var in ENV_VAR_MAPPING.items():
            env_value = getenv(env_var)
            if env_value is not None:  # Only override if environment variable exists
                merged_config[config_key] = env_value

        # Ensure STREAM is lowercase string
        merged_config["STREAM"] = str(merged_config.get("STREAM", "true")).lower()

        self.config = merged_config
        return self.config

    def _call_api(self, url: str, headers: dict, data: dict) -> requests.Response:
        """Call the API and return the response.
        Args:
            url: API endpoint URL
            headers: request headers
            data: request data
        Returns:
            requests.Response: response object
        Raises:
            requests.exceptions.RequestException: if there is an error with the request
        """
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()  # Raise an exception for non-200 status codes
        return response

    def get_llm_url(self) -> str:
        """Get LLM API URL
        Returns:
            str: LLM API URL
        Raises:
            typer.Exit: if API key or base URL is not set
        """
        base = self.config.get("BASE_URL", "").rstrip("/")
        if not base:
            self.console.print(
                "[red]Base URL not found. Please set it in the configuration file. Default: https://api.openai.com/v1[/red]"
            )
            raise typer.Exit(code=1)
        COMPLETION_PATH = self.config.get("COMPLETION_PATH", "").lstrip("/")
        if not COMPLETION_PATH:
            self.console.print(
                "[red]Completions path not set. Please set it in the configuration file. Default: `/chat/completions`[/red]"
            )
            raise typer.Exit(code=1)
        return f"{base}/{COMPLETION_PATH}"

    def build_data(self, prompt: str, mode: str = ModeEnum.TEMP.value) -> dict:
        """Build request data
        Args:
            prompt: user input
            mode: chat or execute mode
        Returns:
            dict: request data
        """
        if mode == ModeEnum.EXECUTE.value:
            system_prompt = self.build_cmd_prompt()
        else:
            system_prompt = self.build_default_prompt()

        # Build messages list, first add system prompt
        messages = [{"role": "system", "content": system_prompt}]

        # Add history records in chat mode
        if mode == ModeEnum.CHAT.value and self.history:
            messages.extend(self.history)

        # Add current user message
        messages.append({"role": "user", "content": prompt})

        return {
            "model": self.config["MODEL"],
            "messages": messages,
            "stream": self.config.get("STREAM", "true") == "true",
            "temperature": 0.7,
            "top_p": 0.7,
            "max_tokens": 200,
        }

    def stream_response(self, response: requests.Response) -> str:
        """Stream response from LLM API
        Args:
            response: requests.Response object
        Returns:
            str: full completion text
        """
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

        return full_completion

    def call_llm_api(self, prompt: str) -> str:
        """Call LLM API, return streaming output
        Args:
            prompt: user input
        Returns:
            str: streaming output
        """
        url = self.get_llm_url()
        headers = {"Authorization": f"Bearer {self.config['API_KEY']}"}
        data = self.build_data(prompt)
        try:
            response = self._call_api(url, headers, data)
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]Error calling API: {e}[/red]")
            if self.verbose and e.response:
                self.console.print(f"{e.response.text}")
            raise typer.Exit(code=1) from None
        if not response:
            raise typer.Exit(code=1)

        self.console.print("\n[bold green]Assistant:[/bold green]")
        assistant_response = self.stream_response(
            response
        )  # Stream the response and get the full text
        self.console.print()  # Add a newline after the completion

        return assistant_response

    def get_command_from_llm(self, prompt: str) -> Optional[str]:
        """Request Shell command from LLM
        Args:
            prompt: user input
        Returns:
            str: shell command
        """
        url = self.get_llm_url()
        headers = {"Authorization": f"Bearer {self.config['API_KEY']}"}
        data = self.build_data(prompt, mode=ModeEnum.EXECUTE.value)
        data["stream"] = False
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

    def execute_shell_command(self, command: str) -> int:
        """Execute shell command
        Args:
            command: shell command
        Returns:
            int: return code
        """
        self.console.print(f"\n[bold green]Executing command: [/bold green] {command}\n")
        result = subprocess.run(command, shell=True)
        if result.returncode != 0:
            self.console.print(
                f"\n[bold red]Command failed with return code: {result.returncode}[/bold red]"
            )
        return result.returncode

    def get_prompt_tokens(self):
        """Get prompt tokens based on current mode
        Returns:
            list: prompt tokens for prompt_toolkit
        """
        if self.current_mode == ModeEnum.CHAT.value:
            qmark = "💬"
        elif self.current_mode == ModeEnum.EXECUTE.value:
            qmark = "🚀"
        else:
            qmark = ""
        return [("class:qmark", qmark), ("class:question", " {} ".format(">"))]

    def chat_mode(self, user_input: str):
        """
        This method handles the chat mode.
        It adds the user input to the history and calls the API to get a response.
        It then adds the response to the history and manages the history length.
        Args:
            user_input: user input
        Returns:
            ModeEnum: current mode
        """
        if self.current_mode != ModeEnum.CHAT.value:
            return self.current_mode

        # Add user message to history
        self.history.append({"role": "user", "content": user_input})

        # Call API and get response
        assistant_response = self.call_llm_api(user_input)

        # Add assistant response to history
        if assistant_response:
            self.history.append({"role": "assistant", "content": assistant_response})

        # Manage history length, keep recent conversations
        if (
            len(self.history) > self.max_history_length * 2
        ):  # Each conversation has user and assistant messages
            self.history = self.history[-self.max_history_length * 2 :]

        return ModeEnum.CHAT.value

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
        """
        This method generates a shell command from the user input and executes it.
        If the user confirms the command, it is executed.
        Args:
            user_input: user input
        Returns:
            ModeEnum: current mode
        """
        if user_input == "" or self.current_mode != ModeEnum.EXECUTE.value:
            return self.current_mode

        command = self.get_command_from_llm(user_input)
        if not command:
            self.console.print("[bold red]No command generated[/bold red]")
            return self.current_mode
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

            if user_input.lower() in ("/exit", "/quit", "/q"):
                break

            # Handle special commands
            if self.current_mode == ModeEnum.CHAT.value:
                if user_input.lower() == "/clear":
                    self.clear_history()
                    self.console.print("[bold yellow]Chat history cleared[/bold yellow]\n")
                    continue
                else:
                    self.chat_mode(user_input)
            elif self.current_mode == ModeEnum.EXECUTE.value:
                self.execute_mode(user_input)

        self.console.print("[bold green]Exiting...[/bold green]")

    def run_one_shot(self, prompt: str):
        """Run one-shot mode with given prompt
        Args:
            prompt (str): Prompt to send to LLM
        Returns:
            None
        """
        if self.current_mode == ModeEnum.EXECUTE.value:
            self.execute_mode(prompt)  # Execute mode for one-shot prompt
        else:
            self.call_llm_api(prompt)

    def run(self, chat=False, shell=False, prompt: Optional[str] = None):
        """Run the CLI application
        Args:
            chat (bool): Whether to run in chat mode
            shell (bool): Whether to run in shell mode
            prompt (Optional[str]): Prompt send to LLM

        Returns:
            None
        """
        # Load configuration
        self.config = self.load_config()
        if not self.config.get("API_KEY", None):
            self.console.print(
                "[red]API key not found. Please set it in the configuration file.[/red]"
            )
            return

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
    name="yaicli",
    context_settings=CONTEXT_SETTINGS,
    pretty_exceptions_enable=False,
    short_help="yaicli. Your AI interface in cli.",
    no_args_is_help=True,
    invoke_without_command=True,
)


@app.command()
def main(
    ctx: typer.Context,
    prompt: Annotated[
        str, typer.Argument(show_default=False, help="The prompt send to the LLM")
    ] = "",
    verbose: Annotated[
        bool, typer.Option("--verbose", "-V", help="Show verbose information")
    ] = False,
    chat: Annotated[bool, typer.Option("--chat", "-c", help="Start in chat mode")] = False,
    shell: Annotated[
        bool, typer.Option("--shell", "-s", help="Generate and execute shell command")
    ] = False,
):
    """yaicli. Your AI interface in cli."""
    if not prompt and not chat:
        typer.echo(ctx.get_help())
        raise typer.Exit()

    cli = YAICLI(verbose=verbose)
    cli.run(chat=chat, shell=shell, prompt=prompt)


if __name__ == "__main__":
    app()
