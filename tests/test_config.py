from unittest.mock import MagicMock, mock_open, patch

import pytest

import yaicli.config
from yaicli.config import DEFAULT_CONFIG_MAP, Config
from yaicli.const import DEFAULT_CONFIG_INI, DEFAULT_PROVIDER


# Mock console fixture
@pytest.fixture
def mock_console():
    return MagicMock()


# Helper to get typed default values
def get_typed_defaults():
    defaults = {}
    for key, info in DEFAULT_CONFIG_MAP.items():
        val = info["value"]
        type_ = info["type"]
        if type_ is bool:
            defaults[key] = str(val).strip().lower() == "true"
        elif type_ is dict:
            if isinstance(val, dict):
                defaults[key] = val
            elif isinstance(val, str) and val:
                try:
                    import json

                    defaults[key] = json.loads(val)
                except json.JSONDecodeError:
                    defaults[key] = {}  # Fallback to empty dict if invalid JSON
            else:
                defaults[key] = {}  # Empty dict for empty strings or None
        else:
            try:
                defaults[key] = type_(val) if val else val
            except (ValueError, TypeError):  # Should not happen with defaults
                defaults[key] = val  # Fallback
    return defaults


TYPED_DEFAULTS = get_typed_defaults()


def test_dead_code_mode_constant_removed():
    """Runtime modes are TEMP/CHAT/EXEC only; the dead const.CODE_MODE was removed (D2)."""
    from yaicli import const

    assert not hasattr(const, "CODE_MODE")


class TestConfig:
    def test_init_with_defaults(self, mock_console):
        """Test that Config initializes with default values when no config file or env vars exist"""
        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("builtins.open", mock_open()),
            patch("pathlib.Path.mkdir"),
            patch("yaicli.config.getenv", return_value=None),
        ):  # Patch at module level
            config = Config(mock_console)

            # Check all default values are set with proper types. The first run writes
            # DEFAULT_CONFIG_INI and parses it (D1 fix); empty template values must fall
            # back to the typed map default rather than leaking "".
            for key, expected_value in TYPED_DEFAULTS.items():
                assert config[key] == expected_value
                assert isinstance(config[key], type(expected_value))

    def test_first_run_creates_config_on_demand(self, mock_console, tmp_path):
        """A first run parses the template in memory; ensure_config_file() writes it (K21).

        v0.19 defers the first-run config.ini write to an explicit entry point so
        read-only commands (--version/--help/--template) never touch the disk.
        """
        config_file = tmp_path / ".config" / "yaicli" / "config.ini"
        with (
            patch.object(yaicli.config, "CONFIG_PATH", config_file),
            patch("yaicli.config.getenv", return_value=None),
        ):
            config = Config(mock_console)

            # No KeyError: PROVIDER is present from the in-memory template...
            assert config["PROVIDER"] == "openai"
            assert config["PROVIDER"] == DEFAULT_PROVIDER

            # ...and constructing the config must not have created the file.
            assert not config_file.exists()

            # Every DEFAULT_CONFIG_MAP key keeps its typed default on a first run: the
            # template's empty values fall back to the map default (D1).
            for key, expected_value in TYPED_DEFAULTS.items():
                assert config[key] == expected_value
                assert isinstance(config[key], type(expected_value))

            # The file is created on demand (CLI first real request / REPL).
            created_path = yaicli.config.ensure_config_file()
            assert created_path == config_file
            written = config_file.read_text(encoding="utf-8")

            # A later run parses the existing file and yields the very same configuration.
            config_from_existing_file = Config(mock_console)

        # The template is written to disk unchanged (--template output depends on the text).
        assert written == DEFAULT_CONFIG_INI
        assert "PROVIDER=openai" in written
        assert (config_file.stat().st_mode & 0o777) == 0o600
        assert (config_file.parent.stat().st_mode & 0o777) == 0o700
        assert config_from_existing_file == config

    def test_empty_template_values_fall_back_to_typed_defaults(self, mock_console):
        """Empty file values mean "unset": dict/None-typed keys use their typed defaults (D1)."""
        mock_config_content = """[core]
EXTRA_HEADERS=
EXTRA_BODY=
REASONING_EFFORT=
"""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_config_content)),
            patch("yaicli.config.getenv", return_value=None),
        ):
            config = Config(mock_console)

        assert config["EXTRA_HEADERS"] == {}
        assert config["EXTRA_BODY"] == {}
        assert config["REASONING_EFFORT"] is None

    def test_provider_env_override(self, mock_console, tmp_path):
        """YAI_PROVIDER must be read from the environment and win over the config file."""
        config_file = tmp_path / "config.ini"

        def mock_getenv(key, default=None):
            return {"YAI_PROVIDER": "anthropic"}.get(key, default)

        with (
            patch.object(yaicli.config, "CONFIG_PATH", config_file),
            patch("yaicli.config.getenv", side_effect=mock_getenv),
        ):
            config = Config(mock_console)
            assert not config_file.exists()
            yaicli.config.ensure_config_file()

        assert config["PROVIDER"] == "anthropic"
        # The created file keeps the default provider; only the env layer overrides it.
        assert "PROVIDER=openai" in config_file.read_text(encoding="utf-8")

    def test_first_run_parses_template_in_memory(self, mock_console, tmp_path):
        """The in-memory first-run template is parsed even though nothing is written (K21)."""
        custom_ini = """[core]
PROVIDER=ollama
CUSTOM_FILE_ONLY_KEY=parsed-from-created-file
"""
        config_file = tmp_path / "config.ini"
        with (
            patch.object(yaicli.config, "CONFIG_PATH", config_file),
            patch.object(yaicli.config, "DEFAULT_CONFIG_INI", custom_ini),
            patch("yaicli.config.getenv", return_value=None),
        ):
            config = Config(mock_console)

            # The template is parsed without touching the disk...
            assert not config_file.exists()
            assert config["PROVIDER"] == "ollama"
            assert config["CUSTOM_FILE_ONLY_KEY"] == "parsed-from-created-file"

            # ...and ensure_config_file() materialises the same template on demand.
            assert yaicli.config.ensure_config_file() == config_file
            written = config_file.read_text(encoding="utf-8")

        assert written.startswith(custom_ini)

    def test_load_from_file(self, mock_console):
        """Test loading configuration from file"""
        mock_config_content = """[core]
BASE_URL=https://custom-api.com/v1
MODEL=gpt-4-turbo
TEMPERATURE=0.5
STREAM=false
"""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_config_content)),
            patch("yaicli.config.getenv", return_value=None),
        ):  # Patch at module level
            config = Config(mock_console)

            # Check file values are loaded correctly with proper types
            assert config["BASE_URL"] == "https://custom-api.com/v1"
            assert config["MODEL"] == "gpt-4-turbo"
            assert config["TEMPERATURE"] == 0.5
            assert config["STREAM"] is False

            # Other values should be defaults
            assert config["MAX_TOKENS"] == TYPED_DEFAULTS["MAX_TOKENS"]

    def test_load_from_env(self, mock_console):
        """Test that environment variables override file and defaults"""
        mock_config_content = """[core]
BASE_URL=https://file-api.com/v1
MODEL=gpt-4-turbo
"""

        # Define the side effect function for getenv to return our custom values
        def mock_getenv(key, default=None):
            env_vars = {"YAI_BASE_URL": "https://env-api.com/v1", "YAI_TEMPERATURE": "0.9", "YAI_STREAM": "false"}
            return env_vars.get(key, default)

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_config_content)),
            patch("yaicli.config.getenv", side_effect=mock_getenv),
        ):  # Patch at module level
            config = Config(mock_console)

            # Env vars should override file and defaults
            assert config["BASE_URL"] == "https://env-api.com/v1"
            assert config["TEMPERATURE"] == 0.9
            assert config["STREAM"] is False

            # File values for non-overridden settings should remain
            assert config["MODEL"] == "gpt-4-turbo"

            # Default values for remaining settings
            assert config["MAX_TOKENS"] == TYPED_DEFAULTS["MAX_TOKENS"]

    def test_type_conversion(self, mock_console):
        """Test type conversion of config values"""

        def mock_getenv(key, default=None):
            env_vars = {"YAI_TEMPERATURE": "0.5", "YAI_MAX_TOKENS": "2048", "YAI_STREAM": "true", "YAI_TOP_P": "0.95"}
            return env_vars.get(key, default)

        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("builtins.open", mock_open()),
            patch("pathlib.Path.mkdir"),
            patch("yaicli.config.getenv", side_effect=mock_getenv),
        ):  # Patch at module level
            config = Config(mock_console)

            # Check types are correctly converted
            assert config["TEMPERATURE"] == 0.5
            assert isinstance(config["TEMPERATURE"], float)

            assert config["MAX_TOKENS"] == 2048
            assert isinstance(config["MAX_TOKENS"], int)

            assert config["STREAM"] is True
            assert isinstance(config["STREAM"], bool)

            assert config["TOP_P"] == 0.95
            assert isinstance(config["TOP_P"], float)

    def test_type_conversion_errors(self, mock_console):
        """Test handling of invalid types in config values"""

        def mock_getenv(key, default=None):
            env_vars = {
                "YAI_TEMPERATURE": "invalid",  # Should be float
                "YAI_MAX_TOKENS": "not_a_number",  # Should be int
                "YAI_TOP_P": "bad value",  # Add a third invalid value
            }
            return env_vars.get(key, default)

        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("builtins.open", mock_open()),
            patch("pathlib.Path.mkdir"),
            patch("yaicli.config.getenv", side_effect=mock_getenv),
        ):  # Patch at module level
            config = Config(mock_console)

            # Should fall back to defaults when conversion fails
            assert config["TEMPERATURE"] == TYPED_DEFAULTS["TEMPERATURE"]
            assert config["MAX_TOKENS"] == TYPED_DEFAULTS["MAX_TOKENS"]
            assert config["TOP_P"] == TYPED_DEFAULTS["TOP_P"]

            # Console should have been called with warning messages at least 3 times
            assert mock_console.print.call_count >= 3

    def test_extra_headers_and_body(self, mock_console):
        """Test that EXTRA_HEADERS and EXTRA_BODY are correctly loaded and converted"""
        mock_config_content = """[core]
EXTRA_HEADERS={"X-Custom-Header": "value", "Authorization": "Bearer token"}
EXTRA_BODY={"custom_param": 123, "option": true}
"""

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_config_content)),
            patch("yaicli.config.getenv", return_value=None),
        ):
            config = Config(mock_console)

            # Check the headers are loaded correctly as a dict
            assert isinstance(config["EXTRA_HEADERS"], dict)
            assert config["EXTRA_HEADERS"] == {"X-Custom-Header": "value", "Authorization": "Bearer token"}

            # Check the body is loaded correctly as a dict
            assert isinstance(config["EXTRA_BODY"], dict)
            assert config["EXTRA_BODY"] == {"custom_param": 123, "option": True}

    def test_extra_headers_and_body_from_env(self, mock_console):
        """Test that EXTRA_HEADERS and EXTRA_BODY are correctly loaded from environment variables"""

        def mock_getenv(key, default=None):
            env_vars = {
                "YAI_EXTRA_HEADERS": '{"X-API-Key": "abc123", "Content-Type": "application/json"}',
                "YAI_EXTRA_BODY": '{"debug": true, "version": "2.0"}',
            }
            return env_vars.get(key, default)

        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("builtins.open", mock_open()),
            patch("pathlib.Path.mkdir"),
            patch("yaicli.config.getenv", side_effect=mock_getenv),
        ):
            config = Config(mock_console)

            # Check headers from env vars
            assert isinstance(config["EXTRA_HEADERS"], dict)
            assert config["EXTRA_HEADERS"] == {"X-API-Key": "abc123", "Content-Type": "application/json"}

            # Check body from env vars
            assert isinstance(config["EXTRA_BODY"], dict)
            assert config["EXTRA_BODY"] == {"debug": True, "version": "2.0"}

    def test_invalid_extra_headers_and_body(self, mock_console):
        """Test handling of invalid JSON in EXTRA_HEADERS and EXTRA_BODY"""

        def mock_getenv(key, default=None):
            env_vars = {"YAI_EXTRA_HEADERS": "{invalid json}", "YAI_EXTRA_BODY": "{also invalid}"}
            return env_vars.get(key, default)

        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("builtins.open", mock_open()),
            patch("pathlib.Path.mkdir"),
            patch("yaicli.config.getenv", side_effect=mock_getenv),
        ):
            config = Config(mock_console)

            # Should fall back to defaults when JSON parsing fails
            assert config["EXTRA_HEADERS"] == TYPED_DEFAULTS["EXTRA_HEADERS"]
            assert config["EXTRA_BODY"] == TYPED_DEFAULTS["EXTRA_BODY"]

            # Check that warnings were printed
            assert mock_console.print.call_count >= 2

    def test_reload(self, mock_console):
        """Test that reload updates configuration from all sources"""
        # Storage for our current environment variables that will change between calls
        env_vars = {"YAI_BASE_URL": "https://initial-api.com/v1"}

        def mock_getenv(key, default=None):
            return env_vars.get(key, default)

        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("builtins.open", mock_open()),
            patch("pathlib.Path.mkdir"),
            patch("yaicli.config.getenv", side_effect=mock_getenv),
        ):  # Patch at module level
            config = Config(mock_console)

            # Initial config should have first URL
            assert config["BASE_URL"] == "https://initial-api.com/v1"

            # Change environment to updated values
            env_vars["YAI_BASE_URL"] = "https://updated-api.com/v1"

            # Reload config
            config.reload()

            # Should pick up the new URL
            assert config["BASE_URL"] == "https://updated-api.com/v1"

    def test_provider_specific_keys_are_typed_from_file(self, mock_console):
        """Parallel-tool / retry-delay / MiniMax keys load with real types (0.21.2).

        These used to bypass ``DEFAULT_CONFIG_MAP``: a config-file ``false`` was
        read as the truthy string ``"false"`` and sent to the API.
        """
        mock_config_content = """[core]
DISABLE_PARALLEL_TOOL_USE=false
RETRY_MAX_DELAY=3.5
MINIMAX_REASONING_SPLIT=false
"""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_config_content)),
            patch("yaicli.config.getenv", return_value=None),
        ):
            config = Config(mock_console)

            assert config["DISABLE_PARALLEL_TOOL_USE"] is False
            assert config["MINIMAX_REASONING_SPLIT"] is False
            assert config["RETRY_MAX_DELAY"] == 3.5
            assert isinstance(config["RETRY_MAX_DELAY"], float)

    def test_provider_specific_keys_env_override(self, mock_console):
        """The new typed keys also honour their ``YAI_*`` environment aliases."""

        def mock_getenv(key, default=None):
            env_vars = {"YAI_DISABLE_PARALLEL_TOOL_USE": "false", "YAI_RETRY_MAX_DELAY": "2.5"}
            return env_vars.get(key, default)

        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("builtins.open", mock_open()),
            patch("pathlib.Path.mkdir"),
            patch("yaicli.config.getenv", side_effect=mock_getenv),
        ):
            config = Config(mock_console)

            assert config["DISABLE_PARALLEL_TOOL_USE"] is False
            assert config["RETRY_MAX_DELAY"] == 2.5
            assert isinstance(config["RETRY_MAX_DELAY"], float)


def test_get_config_exits_nonzero_on_config_error():
    """A ConfigError must terminate with a non-zero status (entry can hit this at import)."""
    from yaicli.exceptions import ConfigError

    yaicli.config.get_config.cache_clear()
    try:
        with patch.object(yaicli.config, "Config", side_effect=ConfigError("broken config")):
            with pytest.raises(SystemExit) as excinfo:
                yaicli.config.get_config()
        assert excinfo.value.code == 1
    finally:
        yaicli.config.get_config.cache_clear()


class TestEnsureConfigFile:
    """v0.19 K21: config.ini creation is explicit, private and idempotent."""

    def test_creates_dir_and_file_on_demand(self, tmp_path, monkeypatch):
        target = tmp_path / "fresh" / "yaicli" / "config.ini"
        monkeypatch.setattr(yaicli.config, "CONFIG_PATH", target)

        assert not target.exists()
        created = yaicli.config.ensure_config_file()

        assert created == target
        assert target.read_text(encoding="utf-8") == DEFAULT_CONFIG_INI
        # API_KEY is stored in plain text in this file: keep it private.
        assert (target.stat().st_mode & 0o777) == 0o600
        assert (target.parent.stat().st_mode & 0o777) == 0o700

    def test_does_not_overwrite_existing_file(self, tmp_path, monkeypatch):
        target = tmp_path / "yaicli" / "config.ini"
        target.parent.mkdir(parents=True)
        target.write_text("[core]\nPROVIDER=custom\n", encoding="utf-8")
        monkeypatch.setattr(yaicli.config, "CONFIG_PATH", target)

        assert yaicli.config.ensure_config_file() == target
        assert target.read_text(encoding="utf-8") == "[core]\nPROVIDER=custom\n"

    def test_read_only_home_warns_instead_of_raising(self, tmp_path, monkeypatch):
        read_only = tmp_path / "readonly-home"
        read_only.mkdir()
        read_only.chmod(0o500)
        monkeypatch.setattr(yaicli.config, "CONFIG_PATH", read_only / ".config" / "yaicli" / "config.ini")
        try:
            assert yaicli.config.ensure_config_file() is None
        finally:
            read_only.chmod(0o700)
