import platform
from os import getenv
from os.path import basename, pathsep
from typing import Any, Optional, TypeVar

from distro import name as distro_name

from yaicli.const import DEFAULT_OS_NAME, DEFAULT_SHELL_NAME

T = TypeVar("T", int, float, str)


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
