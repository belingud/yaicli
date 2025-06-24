from unittest.mock import MagicMock, mock_open, patch

import pytest

from yaicli.config import DEFAULT_CONFIG_MAP, Config


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

            # Check all default values are set with proper types
            for key, expected_value in TYPED_DEFAULTS.items():
                assert config[key] == expected_value
                assert isinstance(config[key], type(expected_value))

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
