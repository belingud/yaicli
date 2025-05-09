import configparser
from dataclasses import dataclass
from functools import lru_cache
from os import getenv
from typing import Any, Optional

from rich import get_console
from rich.console import Console

from yaicli.const import (
    CONFIG_PATH,
    DEFAULT_CHAT_HISTORY_DIR,
    DEFAULT_CONFIG_INI,
    DEFAULT_CONFIG_MAP,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from yaicli.utils import str2bool


class CasePreservingConfigParser(configparser.RawConfigParser):
    """Case preserving config parser"""

    def optionxform(self, optionstr):
        return optionstr


@dataclass
class ProviderConfig:
    """Provider configuration"""

    api_key: str
    model: str
    base_url: Optional[str] = None
    temperature: float = DEFAULT_TEMPERATURE
    top_p: float = DEFAULT_TOP_P


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
        self._load_defaults()

        # Load from config file
        self._load_from_file()

        # Load from environment variables and apply type conversion
        self._load_from_env()
        self._apply_type_conversion()

    def _load_defaults(self) -> dict[str, Any]:
        """Load default configuration values as strings.

        Returns:
            Dictionary with default configuration values
        """
        defaults = {k: v["value"] for k, v in DEFAULT_CONFIG_MAP.items()}
        self.update(defaults)
        return defaults

    def _ensure_version_updated_config_keys(self):
        """Ensure configuration keys added in version updates exist in the config file.
        Appends missing keys to the config file if they don't exist.
        """
        with open(CONFIG_PATH, "r+", encoding="utf-8") as f:
            config_content = f.read()
            if "CHAT_HISTORY_DIR" not in config_content.strip():  # Check for empty lines
                f.write(f"\nCHAT_HISTORY_DIR={DEFAULT_CHAT_HISTORY_DIR}\n")

    def _load_from_file(self) -> None:
        """Load configuration from the config file.

        Creates default config file if it doesn't exist.
        """
        if not CONFIG_PATH.exists():
            self.console.print("Creating default configuration file.", style="bold yellow", justify=self["JUSTIFY"])
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(DEFAULT_CONFIG_INI)
            return

        config_parser = CasePreservingConfigParser()
        config_parser.read(CONFIG_PATH, encoding="utf-8")

        # Check if "core" section exists in the config file
        if "core" not in config_parser or not config_parser["core"]:
            return

        for k, v in {"SHELL_NAME": "Unknown Shell", "OS_NAME": "Unknown OS"}.items():
            if not config_parser["core"].get(k, "").strip():
                config_parser["core"][k] = v

        self.update(dict(config_parser["core"]))

        # Check if keys added in version updates are missing and add them
        self._ensure_version_updated_config_keys()

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
        default_values_str = {k: v["value"] for k, v in DEFAULT_CONFIG_MAP.items()}

        for key, config_info in DEFAULT_CONFIG_MAP.items():
            target_type = config_info["type"]
            raw_value = self[key]
            converted_value = None

            try:
                if raw_value is None:
                    raw_value = default_values_str.get(key, "")
                if target_type is bool:
                    converted_value = str2bool(raw_value)
                elif target_type in (int, float, str):
                    converted_value = target_type(raw_value)
            except (ValueError, TypeError) as e:
                self.console.print(
                    f"[yellow]Warning:[/] Invalid value '{raw_value}' for '{key}'. "
                    f"Expected type '{target_type.__name__}'. Using default value '{default_values_str[key]}'. Error: {e}",
                    style="dim",
                    justify=self["JUSTIFY"],
                )
                # Fallback to default string value if conversion fails
                try:
                    if target_type is bool:
                        converted_value = str2bool(default_values_str[key])
                    else:
                        converted_value = target_type(default_values_str[key])
                except (ValueError, TypeError):
                    # If default also fails (unlikely), keep the raw merged value or a sensible default
                    self.console.print(
                        f"[red]Error:[/red] Could not convert default value for '{key}'. Using raw value.",
                        style="error",
                        justify=self["JUSTIFY"],
                    )
                    converted_value = raw_value  # Or assign a hardcoded safe default

            self[key] = converted_value


@lru_cache(1)
def get_config() -> Config:
    """Get the configuration singleton"""
    return Config()


cfg = get_config()