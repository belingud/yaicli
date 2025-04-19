import configparser
from os import getenv
from pathlib import Path
from typing import Optional

from rich import get_console
from rich.console import Console

DEFAULT_CONFIG_MAP = {
    # Core API settings
    "BASE_URL": {"value": "https://api.openai.com/v1", "env_key": "YAI_BASE_URL", "type": str},
    "API_KEY": {"value": "", "env_key": "YAI_API_KEY", "type": str},
    "MODEL": {"value": "gpt-4o", "env_key": "YAI_MODEL", "type": str},
    # System detection hints
    "SHELL_NAME": {"value": "auto", "env_key": "YAI_SHELL_NAME", "type": str},
    "OS_NAME": {"value": "auto", "env_key": "YAI_OS_NAME", "type": str},
    # API response parsing
    "COMPLETION_PATH": {"value": "chat/completions", "env_key": "YAI_COMPLETION_PATH", "type": str},
    "ANSWER_PATH": {"value": "choices[0].message.content", "env_key": "YAI_ANSWER_PATH", "type": str},
    # API call parameters
    "STREAM": {"value": "true", "env_key": "YAI_STREAM", "type": bool},
    "TEMPERATURE": {"value": "0.7", "env_key": "YAI_TEMPERATURE", "type": float},
    "TOP_P": {"value": "1.0", "env_key": "YAI_TOP_P", "type": float},
    "MAX_TOKENS": {"value": "1024", "env_key": "YAI_MAX_TOKENS", "type": int},
    # UI/UX settings
    "CODE_THEME": {"value": "monokai", "env_key": "YAI_CODE_THEME", "type": str},
    "MAX_HISTORY": {"value": "500", "env_key": "YAI_MAX_HISTORY", "type": int},
    "AUTO_SUGGEST": {"value": "true", "env_key": "YAI_AUTO_SUGGEST", "type": bool},
}

DEFAULT_CONFIG_INI = f"""[core]
PROVIDER=openai
BASE_URL={DEFAULT_CONFIG_MAP["BASE_URL"]["value"]}
API_KEY={DEFAULT_CONFIG_MAP["API_KEY"]["value"]}
MODEL={DEFAULT_CONFIG_MAP["MODEL"]["value"]}

# auto detect shell and os (or specify manually, e.g., bash, zsh, powershell.exe)
SHELL_NAME={DEFAULT_CONFIG_MAP["SHELL_NAME"]["value"]}
OS_NAME={DEFAULT_CONFIG_MAP["OS_NAME"]["value"]}

# API paths (usually no need to change for OpenAI compatible APIs)
COMPLETION_PATH={DEFAULT_CONFIG_MAP["COMPLETION_PATH"]["value"]}
ANSWER_PATH={DEFAULT_CONFIG_MAP["ANSWER_PATH"]["value"]}

# true: streaming response, false: non-streaming
STREAM={DEFAULT_CONFIG_MAP["STREAM"]["value"]}

# LLM parameters
TEMPERATURE={DEFAULT_CONFIG_MAP["TEMPERATURE"]["value"]}
TOP_P={DEFAULT_CONFIG_MAP["TOP_P"]["value"]}
MAX_TOKENS={DEFAULT_CONFIG_MAP["MAX_TOKENS"]["value"]}

# UI/UX
CODE_THEME={DEFAULT_CONFIG_MAP["CODE_THEME"]["value"]}
MAX_HISTORY={DEFAULT_CONFIG_MAP["MAX_HISTORY"]["value"]}
AUTO_SUGGEST={DEFAULT_CONFIG_MAP["AUTO_SUGGEST"]["value"]}
"""

CONFIG_PATH = Path("~/.config/yaicli/config.ini").expanduser()


class CasePreservingConfigParser(configparser.RawConfigParser):
    """Case preserving config parser"""

    def optionxform(self, optionstr):
        return optionstr


class Config(dict):
    """Configuration class that loads settings on initialization.

    This class encapsulates the configuration loading logic with priority:
    1. Environment variables (highest priority)
    2. Configuration file
    3. Default values (lowest priority)

    It handles type conversion and validation based on DEFAULT_CONFIG_MAP.
    """

    def __init__(self, console: Optional[Console] = None):
        """Initializes and loads the configuration."""
        self.console = console or get_console()
        super().__init__()
        self.reload()

    def reload(self) -> None:
        """Reload configuration from all sources.

        Follows priority order: env vars > config file > defaults
        """
        # Start with defaults
        self.clear()
        self.update(self._load_defaults())

        # Load from config file
        file_config = self._load_from_file()
        if file_config:
            self.update(file_config)

        # Load from environment variables and apply type conversion
        self._load_from_env()
        self._apply_type_conversion()

    def _load_defaults(self) -> dict[str, str]:
        """Load default configuration values as strings.

        Returns:
            Dictionary with default configuration values
        """
        return {k: v["value"] for k, v in DEFAULT_CONFIG_MAP.items()}

    def _load_from_file(self) -> dict[str, str]:
        """Load configuration from the config file.

        Creates default config file if it doesn't exist.

        Returns:
            Dictionary with configuration values from file, or empty dict if no valid values
        """
        if not CONFIG_PATH.exists():
            self.console.print("Creating default configuration file.", style="bold yellow")
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(DEFAULT_CONFIG_INI)
            return {}

        config_parser = CasePreservingConfigParser()
        config_parser.read(CONFIG_PATH, encoding="utf-8")
        if "core" in config_parser:
            return {k: v for k, v in config_parser["core"].items() if k in DEFAULT_CONFIG_MAP and v.strip()}
        return {}

    def _load_from_env(self) -> None:
        """Load configuration from environment variables.

        Updates the configuration dictionary in-place.
        """
        for key, config_info in DEFAULT_CONFIG_MAP.items():
            env_value = getenv(config_info["env_key"])
            if env_value is not None:
                self[key] = env_value

    def _apply_type_conversion(self) -> None:
        """Apply type conversion to configuration values.

        Updates the configuration dictionary in-place with properly typed values.
        Falls back to default values if conversion fails.
        """
        default_values_str = self._load_defaults()

        for key, config_info in DEFAULT_CONFIG_MAP.items():
            target_type = config_info["type"]
            raw_value = self.get(key, default_values_str.get(key))
            converted_value = None

            try:
                if target_type is bool:
                    converted_value = str(raw_value).strip().lower() == "true"
                elif target_type in (int, float, str):
                    converted_value = target_type(raw_value)
            except (ValueError, TypeError) as e:
                self.console.print(
                    f"[yellow]Warning:[/yellow] Invalid value '{raw_value}' for '{key}'. "
                    f"Expected type '{target_type.__name__}'. Using default value '{default_values_str[key]}'. Error: {e}",
                    style="dim",
                )
                # Fallback to default string value if conversion fails
                try:
                    if target_type is bool:
                        converted_value = str(default_values_str[key]).strip().lower() == "true"
                    else:
                        converted_value = target_type(default_values_str[key])
                except (ValueError, TypeError):
                    # If default also fails (unlikely), keep the raw merged value or a sensible default
                    self.console.print(
                        f"[red]Error:[/red] Could not convert default value for '{key}'. Using raw value.",
                        style="error",
                    )
                    converted_value = raw_value  # Or assign a hardcoded safe default

            self[key] = converted_value
