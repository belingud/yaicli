import configparser
import json
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from os import getenv
from pathlib import Path
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

# File-system diagnostics go to stderr (the headless contract keeps stdout for
# results) and must never take the process down: importing this module happens
# in containers / read-only HOMEs where creating state is simply not possible.
# ``yaicli.console`` cannot be imported here (console.py imports this module
# first), so this is a plain lazily-created Rich console.
_error_console: Optional[Console] = None
_warned_keys: set = set()
# Key migrations for pre-existing config files are discovered during the (read-only)
# import-time load and appended only when ensure_config_file() runs a real command.
# Keyed by CONFIG_PATH so tests that patch the path (and multiple Config loads) never
# apply another file's pending migration to the active path.
_PENDING_CONFIG_MIGRATIONS: dict[Path, list[str]] = {}
_PENDING_MIGRATION_KEY = "migrate:CHAT_HISTORY_DIR"


def _get_error_console() -> Console:
    global _error_console
    if _error_console is None:
        _error_console = Console(stderr=True)
    return _error_console


def _warn_once(key: str, message: str) -> None:
    """Report one best-effort filesystem failure on stderr; never raise."""
    if key in _warned_keys:
        return
    _warned_keys.add(key)
    try:
        _get_error_console().print(f"[yellow]Warning:[/yellow] {message}", style="dim")
    except Exception:  # noqa: BLE001 - diagnostics must never break startup
        pass


def _chmod(path: Path, mode: int) -> None:
    """Best-effort POSIX mode change (no-op where chmod is unavailable)."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


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

    def _pending_version_updated_config_keys(self, config_parser: CasePreservingConfigParser) -> list[str]:
        """Return config-file migration lines for keys added in version updates.

        Detection is read-only: importing :mod:`yaicli.config` must not touch the
        filesystem (``--version``/``--help``/read-only HOME). The pending lines are
        appended by :func:`ensure_config_file` on the first real run instead.
        """
        core_section = config_parser["core"] if config_parser.has_section("core") else {}
        pending: list[str] = []
        if "CHAT_HISTORY_DIR" not in core_section:
            pending.append(f"CHAT_HISTORY_DIR={DEFAULT_CHAT_HISTORY_DIR}")
        return pending

    def _load_from_file(self) -> None:
        """Load configuration from the config file.

        A missing file is never created here (v0.19 K21): first-run values are
        parsed from the ``DEFAULT_CONFIG_INI`` template in memory, and the file
        is materialised later by :func:`ensure_config_file` when the CLI starts
        doing real work. This keeps read-only/meta commands (``--version``,
        ``--help``, ``--template``) free of filesystem writes and lets a
        read-only HOME run on the defaults instead of crashing.
        """
        config_parser = CasePreservingConfigParser()
        file_existed = CONFIG_PATH.exists()
        try:
            if file_existed:
                parsed_files = config_parser.read(CONFIG_PATH, encoding="utf-8")
                if not parsed_files:
                    # Existing but unreadable file (permission/encoding): use defaults.
                    _warn_once(
                        f"read:{CONFIG_PATH}",
                        f"Could not read configuration file {CONFIG_PATH}. Using in-memory defaults.",
                    )
                    return
            else:
                # Parse the template in memory so a first run exposes the same keys
                # (e.g. PROVIDER) as later runs without touching the disk.
                config_parser.read_string(DEFAULT_CONFIG_INI, source=str(CONFIG_PATH))
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

        # Only migrate a file that already exists: a first run has no file yet and
        # must stay write-free (the created template already contains every key).
        # The actual append is deferred to ensure_config_file() (D7): importing
        # config must never write, even for a legacy config.ini.
        if file_existed:
            pending = self._pending_version_updated_config_keys(config_parser)
            if pending:
                queued = _PENDING_CONFIG_MIGRATIONS.setdefault(CONFIG_PATH, [])
                for line in pending:
                    if line not in queued:
                        queued.append(line)

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
        # Empty file/env values mean "unset": fall back to the typed map default so a
        # config.ini template with `EXTRA_HEADERS=` / `REASONING_EFFORT=` resolves to
        # {} / None on every run (including the first run, which now parses the
        # template it just wrote) instead of leaking raw "" into typed consumers.
        if raw_value is None or raw_value == "":
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

            # Skip conversion if already correct type (optimization for common case).
            # Empty strings are the exception: they mean "unset" and must still go
            # through _convert_value so typed defaults (e.g. None for REASONING_EFFORT,
            # {} for EXTRA_HEADERS) are restored instead of leaking "".
            if isinstance(raw_value, target_type) and raw_value != "":
                continue

            # Convert the value
            self[key] = self._convert_value(raw_value, target_type, key)


def ensure_config_file() -> Optional[Path]:
    """Create the configuration file on demand (first real use of the CLI).

    Importing :mod:`yaicli.config` no longer writes anything: a first run parses
    the ``DEFAULT_CONFIG_INI`` template in memory. The CLI calls this function
    once it actually starts doing work (first request / REPL), so read-only
    HOME and container environments can still run the read-only commands.

    The directory is created with mode ``0700`` and the file with mode ``0600``
    (best effort; sensitive values such as ``API_KEY`` are stored in plain
    text). Any OSError is reported once on stderr and swallowed.

    Returns:
        The configuration path when it exists afterwards (created now or
        already present), or ``None`` when it could not be created.
    """
    try:
        if not CONFIG_PATH.exists():
            _create_config_file()
        _apply_pending_config_migrations()
        return CONFIG_PATH if CONFIG_PATH.exists() else None
    except OSError as e:
        _warn_once(
            f"create:{CONFIG_PATH}",
            f"Could not create configuration file {CONFIG_PATH}: {e}. "
            "Continuing with the in-memory defaults (read-only HOME/container).",
        )
        return None


def _create_config_file() -> None:
    """Create the config file from the template (0600 file, 0700 dir)."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _chmod(CONFIG_PATH.parent, 0o700)
    try:
        fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # pragma: no cover - concurrent creator won the race
        return
    try:
        payload = DEFAULT_CONFIG_INI.encode("utf-8")
        while payload:
            payload = payload[os.write(fd, payload) :]
    finally:
        os.close(fd)
    _chmod(CONFIG_PATH, 0o600)


def _apply_pending_config_migrations() -> None:
    """Append deferred key migrations to an existing config file (best effort).

    Called only from :func:`ensure_config_file`, i.e. on a real CLI run. A
    read-only config directory reports one stderr warning and continues with the
    in-memory defaults. The pending list is cleared once the append succeeds.
    """
    if not CONFIG_PATH.exists():
        return
    lines = _PENDING_CONFIG_MIGRATIONS.pop(CONFIG_PATH, None)
    if not lines:
        return

    # Skip migrations whose key is already present: the file may be a freshly
    # created template (which contains every default key) or another load may have
    # appended the same line already. Without this a duplicate option would make
    # the config file unreadable (configparser DuplicateOptionError).
    parser = CasePreservingConfigParser()
    try:
        parser.read(CONFIG_PATH, encoding="utf-8")
    except (OSError, configparser.Error):  # pragma: no cover - unreadable file: append blind
        parser = CasePreservingConfigParser()
    core_section = parser["core"] if parser.has_section("core") else {}
    to_append = [line for line in lines if line.split("=", 1)[0] not in core_section]
    if not to_append:
        return

    try:
        with open(CONFIG_PATH, "a", encoding="utf-8") as f:
            for line in to_append:
                f.write(f"\n{line}\n")
    except OSError as e:
        # Keep them pending for the next explicit call; a read-only config dir only warns.
        queued = _PENDING_CONFIG_MIGRATIONS.setdefault(CONFIG_PATH, [])
        for line in to_append:
            if line not in queued:
                queued.append(line)
        _warn_once(
            _PENDING_MIGRATION_KEY,
            f"Could not update configuration file {CONFIG_PATH}: {e}. Continuing with the in-memory defaults.",
        )


@lru_cache(1)
def get_config() -> Config:
    """Get the configuration singleton"""
    try:
        return Config()
    except ConfigError:
        # Configuration errors must produce a non-zero process status. This can run
        # at import time (cfg = get_config() below), before the CLI can report it.
        sys.exit(1)


cfg = get_config()
