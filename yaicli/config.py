import configparser
import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from os import getenv
from typing import Any, Optional

from rich import get_console
from rich.console import Console

from .const import (
    CONFIG_PATH,
    DEFAULT_CHAT_HISTORY_DIR,
    DEFAULT_CONFIG_INI,
    DEFAULT_CONFIG_MAP,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from .exceptions import ConfigError
from .utils import str2bool


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

    def _load_defaults(self) -> None:
        """Load default configuration values as strings."""
        # Direct update instead of creating temporary dict
        for key, config_info in DEFAULT_CONFIG_MAP.items():
            self[key] = config_info["value"]

    def _ensure_version_updated_config_keys(self, config_parser: CasePreservingConfigParser) -> None:
        """Ensure configuration keys added in version updates exist in the config file.

        Uses config parser to check for missing keys instead of full text search.
        Only writes to file if keys are actually missing.
        """
        # Check using config parser instead of full text search
        core_section = config_parser["core"] if config_parser.has_section("core") else {}

        if "CHAT_HISTORY_DIR" not in core_section:
            # Only append if the key is missing
            with open(CONFIG_PATH, "a", encoding="utf-8") as f:
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
        try:
            config_parser.read(CONFIG_PATH, encoding="utf-8")
        except configparser.DuplicateOptionError as e:
            self.console.print(f"[red]Error:[/red] {e}", justify=self["JUSTIFY"])
            raise ConfigError(str(e)) from None

        # Check if "core" section exists in the config file
        if not config_parser.has_section("core"):
            return

        # Set default values for missing shell/OS info
        core_section = config_parser["core"]
        for key, default_value in {"SHELL_NAME": "Unknown Shell", "OS_NAME": "Unknown OS"}.items():
            if not core_section.get(key, "").strip():
                core_section[key] = default_value

        # Update config with file values
        self.update(dict(core_section))

        # Check if keys added in version updates are missing and add them
        self._ensure_version_updated_config_keys(config_parser)

    def _load_from_env(self) -> None:
        """Load configuration from environment variables.

        Updates the configuration dictionary in-place.
        """
        for key, config_info in DEFAULT_CONFIG_MAP.items():
            env_value = getenv(config_info["env_key"])
            if env_value is not None:
                self[key] = env_value

    def _convert_value(self, raw_value: str, target_type: type, key: str) -> Any:
        """Convert a raw string value to the target type.

        Args:
            raw_value: The raw string value to convert
            target_type: The target type to convert to
            key: The configuration key (for error reporting)

        Returns:
            The converted value or the default value if conversion fails
        """
        if raw_value is None:
            raw_value = DEFAULT_CONFIG_MAP[key]["value"]

        try:
            if target_type is bool:
                return str2bool(raw_value)
            elif target_type in (int, float, str):
                return target_type(raw_value) if raw_value else raw_value
            elif target_type is dict and raw_value:
                return json.loads(raw_value)
            return raw_value
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            # Log warning and fallback to default
            default_value = DEFAULT_CONFIG_MAP[key]["value"]
            self.console.print(
                f"[yellow]Warning:[/] Invalid value '{raw_value}' for '{key}'. "
                f"Expected type '{target_type.__name__}'. Using default value '{default_value}'. Error: {e}",
                style="dim",
                justify=self["JUSTIFY"],
            )

            # Try to convert default value
            try:
                if target_type is bool:
                    return str2bool(default_value)
                elif target_type in (int, float, str):
                    return target_type(default_value)
                elif target_type is dict:
                    return json.loads(default_value)
            except (ValueError, TypeError, json.JSONDecodeError):
                # If default conversion also fails, log error and return raw value
                self.console.print(
                    f"[red]Error:[/red] Could not convert default value for '{key}'. Using raw value.",
                    style="error",
                    justify=self["JUSTIFY"],
                )
                return raw_value

    def _apply_type_conversion(self) -> None:
        """Apply type conversion to configuration values.

        Optimized version that reduces redundant operations and improves error handling.
        """
        for key, config_info in DEFAULT_CONFIG_MAP.items():
            target_type = config_info["type"]
            raw_value = self[key]

            # Skip conversion if already correct type (optimization for common case)
            if isinstance(raw_value, target_type):
                continue

            # Convert the value
            self[key] = self._convert_value(raw_value, target_type, key)


@lru_cache(1)
def get_config() -> Config:
    """Get the configuration singleton"""
    try:
        return Config()
    except ConfigError:
        sys.exit()


cfg = get_config()
