import json
import platform
from os import getenv
from os.path import basename, pathsep
import re
from typing import Any, Callable, Optional, TypeVar

import typer
from distro import name as distro_name

from yaicli.const import DEFAULT_OS_NAME, DEFAULT_SHELL_NAME

T = TypeVar("T", int, float, str, bool)


def option_callback(func: Callable) -> Callable:  # pragma: no cover
    """
    A decorator for Typer option callbacks that ensures the application exits
    after the callback function is executed.

    Args:
        func (Callable): The callback classmethod to wrap.
    """

    def wrapper(cls, value: T) -> T:
        if not value:
            return value
        func(cls, value)
        raise typer.Exit()

    return wrapper


def detect_os(config: dict[str, Any]) -> str:
    """Detect operating system + version based on config or system info."""
    os_name_config = config.get("OS_NAME", DEFAULT_OS_NAME)
    if os_name_config != DEFAULT_OS_NAME:
        return os_name_config

    current_platform = platform.system()
    if current_platform == "Linux":
        return "Linux/" + distro_name(pretty=True)
    if current_platform == "Windows":
        return "Windows " + platform.release()
    if current_platform == "Darwin":
        return "Darwin/MacOS " + platform.mac_ver()[0]
    return current_platform


def detect_shell(config: dict[str, Any]) -> str:
    """Detect shell name based on config or environment."""
    shell_name_config = config.get("SHELL_NAME", DEFAULT_SHELL_NAME)
    if shell_name_config != DEFAULT_SHELL_NAME:
        return shell_name_config

    current_platform = platform.system()
    if current_platform in ("Windows", "nt"):
        # Basic check for PowerShell based on environment variables
        is_powershell = len(getenv("PSModulePath", "").split(pathsep)) >= 3
        return "powershell.exe" if is_powershell else "cmd.exe"

    # For Linux/MacOS, check SHELL environment variable
    return basename(getenv("SHELL") or "/bin/sh")


def filter_command(command: str) -> Optional[str]:
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
    else:
        # If the first line doesn't start with ```, return the entire command without the ``` characters
        return command.strip().replace("```", "")


def str2bool(value: str) -> bool:
    """Convert a string representation of truth to true (1) or false (0).
    True values are 'y', 'yes', 't', 'true', 'on', and '1';
    false values are 'n', 'no', 'f', 'false', 'off', and '0'.
    Raises ValueError if 'value' is anything else.
    """
    if value in {False, True}:
        return bool(value)

    norm = value.strip().lower()

    if norm in {"1", "true", "t", "yes", "y", "on"}:
        return True

    if norm in {"0", "false", "f", "no", "n", "off"}:
        return False

    # Handle empty strings and other invalid values
    raise ValueError(f"Invalid boolean value: {value}")


def fix_common_json_issues(s: str) -> str:
    """Fix common JSON issues in the string.

    This function handles:
    - Missing closing curly brackets
    - Escaped quotes (e.g. \\" -> ")
    - Illegal line breaks
    - Outer quotes (sometimes the model returns a JSON string as a whole)

    Args:
        s (str): The string to fix

    Returns:
        str: The fixed string
    """
    s = s.strip()

    # Complete the closing curly brackets
    if s.count("{") > s.count("}"):
        s += "}"

    # Replace escaped quotes (e.g. \\" -> ")
    s = s.replace(r"\\", r"")

    # Replace illegal line breaks
    s = re.sub(r"[\r\n]+", " ", s)

    # Remove outer quotes (sometimes the model returns a JSON string as a whole)
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]

    return s



def parse_json(s: str) -> dict[str, Any]:
    """Parse a JSON string.

    This function handles:
    - Missing closing curly brackets
    - Escaped quotes (e.g. \\" -> ")
    - Illegal line breaks
    - Outer quotes (sometimes the model returns a JSON string as a whole)

    Args:
        s (str): The string to parse

    Returns:
        dict[str, Any]: The parsed JSON object
    """
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Try to fix common JSON issues
        return json.loads(fix_common_json_issues(s))
