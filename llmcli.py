from enum import StrEnum
import json
import time
import requests
import subprocess
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Confirm
from pathlib import Path

import typer
from typing import Annotated

# Configuration file path
CONFIG_PATH = Path("~/.config/llmcli/config.json").expanduser()

# Initialize terminal
console = Console()
bindings = KeyBindings()
session = PromptSession(key_bindings=bindings)


class ModeEnum(StrEnum):
    CHAT = "chat"
    EXECUTE = 'execute'


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


def get_default_config():
    """Get default configuration"""
    import configparser
    config = configparser.RawConfigParser()
    try:
        config.read_string(DEFAULT_CONFIG_INI)
        config_dict = dict(config['DEFAULT'])
        config_dict['stream'] = str(config_dict.get('stream', 'true')).lower()
        return config_dict
    except configparser.Error as e:
        console.print(f"[red]Error parsing config: {e}[/red]")
        raise typer.Exit(code=1) from None


@bindings.add(Keys.ControlI)  # Bind Ctrl+I to switch modes
def _(event: KeyPressEvent):
    global current_mode
    current_mode = ModeEnum.CHAT.value if current_mode == ModeEnum.EXECUTE.value else ModeEnum.EXECUTE.value


def load_config():
    """Load LLM API configuration"""
    if not CONFIG_PATH.exists():
        console.print(
            "[bold yellow]Configuration file not found. Creating default configuration file.[/bold yellow]"
        )
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            default_config = get_default_config()
            json.dump(default_config, f, indent=4)
        return default_config
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def call_llm_api(prompt, config):
    """Call LLM API, return streaming output"""
    url = f"{config['base_url']}/chat/completions"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    data = {
        "model": config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": config.get("stream", "true") == "true",
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code != 200:
        console.print(f"[red]API request failed: {response.status_code}[/red]")
        return

    console.print("\n[bold green]Assistant:[/bold green] ", end="")
    full_completion = ""
    # Streaming response loop
    with Live(console=console) as live:
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
                    console.print("[red]Error decoding response JSON[/red]")
                    console.print(f"[red]Error decoding JSON: {decoded_line}[/red]")
            time.sleep(0.05)
    print("\n")


def get_command_from_llm(prompt, config):
    """Request Shell command from LLM"""
    url = f"{config['base_url']}/chat/completions"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    data = {
        "model": config["model"],
        "messages": [
            {
                "role": "system",
                "content": "You are a command line assistant, return one Linux/macOS shell commands only, without explanation and triple-backtick code blocks.",
            },
            {"role": "user", "content": prompt},
        ],
        "stream": config.get("stream", "true") == "true",
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code != 200:
        console.print(f"[red]API request failed: {response.status_code}[/red]")
        return None

    command = response.json()["choices"][0]["message"]["content"].strip()
    return command


def execute_shell_command(command):
    """Execute shell command"""
    console.print(f"\n[bold green]Executing command: [/bold green] {command}\n")
    result = subprocess.run(command, shell=True)
    if result.returncode != 0:
        console.print(f"\n[bold red]Command failed with return code: {result.returncode}[/bold red]")


def get_prompt_tokens():
    if current_mode == ModeEnum.CHAT.value:
        qmark = "💬"
    elif current_mode == ModeEnum.EXECUTE.value:
        qmark = "🚀"
    else:
        qmark = ""
    return [("class:qmark", qmark), ("class:question", " {} ".format(">"))]


def chat_mode(user_input: str, config: dict):
    """Interactive chat mode"""
    if current_mode != ModeEnum.CHAT.value:
        return current_mode

    call_llm_api(user_input, config)
    return ModeEnum.CHAT.value


def execute_mode(user_input: str, config: dict):
    """Execute mode"""
    if user_input == "":
        return current_mode
    if current_mode != ModeEnum.EXECUTE.value:
        return current_mode

    command = get_command_from_llm(user_input, config)
    if command:
        console.print(f"\n[bold magenta]Generated command:[/bold magenta] `{command}`")
        confirm = Confirm.ask("Execute this command?")
        if confirm:
            execute_shell_command(command)
    return ModeEnum.EXECUTE.value


CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "show_default": True,
}

app = typer.Typer(
    name="llmcli",
    context_settings=CONTEXT_SETTINGS,
    pretty_exceptions_enable=False,
    short_help="LLM CLI Tool",
    no_args_is_help=True,
    invoke_without_command=True,
)


def _chat(user_input):
    print(user_input)


def _execute(user_input):
    print(user_input)


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
    global current_mode
    config = load_config()
    if not config["api_key"]:
        console.print("[red]API key not found. Please set it in the configuration file.[/red]")
        return
    current_mode = config["default_mode"]
    # Check run mode
    if all([chat, shell]):
        console.print("[red]Cannot use both --chat and --shell[/red]")
        return
    elif chat:
        current_mode = ModeEnum.CHAT.value
    elif shell:
        current_mode = ModeEnum.EXECUTE.value

    if verbose:
        console.print("[bold yellow]Verbose mode enabled[/bold yellow]")
        console.print(f"[bold yellow]Current mode: {current_mode}[/bold yellow]")
        console.print(f"[bold yellow]Using model: {config['model']}[/bold yellow]")

    # Enable keyboard shortcuts
    get_app().key_bindings = bindings

    # Run main loop
    while True:
        user_input = session.prompt(get_prompt_tokens)
        if current_mode == ModeEnum.CHAT.value:
            chat_mode(user_input, config=config)
        elif current_mode == ModeEnum.EXECUTE.value:
            execute_mode(user_input, config=config)
        else:
            break

        if user_input.lower() in ("exit", "quit"):
            break

    console.print("[bold green]Exiting...[/bold green]")


if __name__ == "__main__":
    app()
