import pytest
import os
from unittest.mock import patch, MagicMock
from yaicli.config import load_config, DEFAULT_CONFIG_MAP

# Mock console fixture
@pytest.fixture
def mock_console():
    return MagicMock()

# Helper to get typed default values
def get_typed_defaults():
    defaults = {}
    for key, info in DEFAULT_CONFIG_MAP.items():
        val = info['value']
        type_ = info['type']
        if type_ is bool:
            defaults[key] = str(val).strip().lower() == 'true'
        else:
            try:
                defaults[key] = type_(val)
            except (ValueError, TypeError): # Should not happen with defaults
                defaults[key] = val # Fallback
    return defaults

TYPED_DEFAULTS = get_typed_defaults()

class TestLoadConfig:

    def test_load_default_config_file_creation(self, mock_console, patched_config_path):
        """Test creating default config file when none exists."""
        assert not patched_config_path.exists()
        config = load_config(mock_console)

        assert patched_config_path.exists()
        # Read created file and compare with default INI content (ignoring whitespace diffs)
        created_content = patched_config_path.read_text(encoding='utf-8')
        assert "[core]" in created_content
        assert "BASE_URL=https://api.openai.com/v1" in created_content # Check a key value
        mock_console.print.assert_any_call("[bold yellow]Creating default configuration file.[/bold yellow]")

        # Check if returned config matches typed defaults
        assert config == TYPED_DEFAULTS

    def test_load_from_existing_file(self, mock_console, patched_config_path):
        """Test loading configuration from an existing INI file."""
        # Create a test config file with some overrides
        test_ini = """
[core]
MODEL = gpt-test-override
TEMPERATURE = 0.9
STREAM = false
UNKNOWN_KEY = ignore_me
API_KEY=
"""
        patched_config_path.parent.mkdir(parents=True, exist_ok=True)
        patched_config_path.write_text(test_ini, encoding='utf-8')

        config = load_config(mock_console)

        # Check overrides
        assert config['MODEL'] == "gpt-test-override"
        assert config['TEMPERATURE'] == 0.9
        assert config['STREAM'] is False
        # Check default values are still present for non-overridden keys
        assert config['BASE_URL'] == TYPED_DEFAULTS['BASE_URL']
        assert config['MAX_TOKENS'] == TYPED_DEFAULTS['MAX_TOKENS']
        # Check empty value from file is ignored (API_KEY uses default)
        assert config['API_KEY'] == TYPED_DEFAULTS['API_KEY']
        # Check unknown key is ignored
        assert "UNKNOWN_KEY" not in config
        mock_console.print.assert_not_called() # No warnings or errors

    def test_load_with_env_var_override(self, mock_console, patched_config_path):
        """Test environment variables overriding file and defaults."""
        # Create a test config file
        test_ini = """
[core]
MODEL = file-model
TEMPERATURE = 0.5
API_KEY = file-key
"""
        patched_config_path.parent.mkdir(parents=True, exist_ok=True)
        patched_config_path.write_text(test_ini, encoding='utf-8')

        # Set environment variables
        env_vars = {
            "YAI_MODEL": "env-model",         # Override file
            "YAI_API_KEY": "env-key",         # Override file
            "YAI_STREAM": "False",            # Override default (STREAM is bool)
            "YAI_MAX_TOKENS": "2048"       # Override default (MAX_TOKENS is int)
        }
        with patch.dict(os.environ, env_vars):
            config = load_config(mock_console)

        # Check overrides
        assert config['MODEL'] == "env-model"
        assert config['API_KEY'] == "env-key"
        assert config['STREAM'] is False
        assert config['MAX_TOKENS'] == 2048
        # Check value from file (not overridden by env) is still used
        assert config['TEMPERATURE'] == 0.5
        # Check default value (not overridden by file or env) is still used
        assert config['TOP_P'] == TYPED_DEFAULTS['TOP_P']
        mock_console.print.assert_not_called()

    @pytest.mark.parametrize(
        "key, file_value, env_value, expected_type, expected_value",
        [
            ("STREAM", "false", None, bool, False),
            ("STREAM", "True", None, bool, True),
            ("STREAM", "yes", None, bool, False), # Only "true" (case-insensitive) is True
            ("STREAM", None, "TRUE", bool, True),
            ("STREAM", None, "false", bool, False),
            ("MAX_TOKENS", "2000", None, int, 2000),
            ("MAX_TOKENS", None, "512", int, 512),
            ("TEMPERATURE", "0.1", None, float, 0.1),
            ("TEMPERATURE", None, "1.5", float, 1.5),
            ("API_KEY", "filekey", None, str, "filekey"),
            ("API_KEY", None, "envkey", str, "envkey"),
        ]
    )
    def test_type_conversion(self, mock_console, patched_config_path, key, file_value, env_value, expected_type, expected_value):
        """Test correct type conversion for bool, int, float, str."""
        # Write to file if file_value is provided
        if file_value is not None:
            test_ini = f"[core]\n{key} = {file_value}\n"
            patched_config_path.parent.mkdir(parents=True, exist_ok=True)
            patched_config_path.write_text(test_ini, encoding='utf-8')
        elif patched_config_path.exists():
            patched_config_path.unlink() # Ensure file doesn't exist if not testing file value

        # Set env var if provided
        env_key = DEFAULT_CONFIG_MAP[key]['env_key']
        env_vars = {env_key: env_value} if env_value is not None else {}

        with patch.dict(os.environ, env_vars):
            config = load_config(mock_console)

        assert isinstance(config[key], expected_type)
        assert config[key] == expected_value

    @pytest.mark.parametrize(
        "key, bad_value, expected_warning_part",
        [
            ("MAX_TOKENS", "not-an-int", "Invalid value 'not-an-int' for 'MAX_TOKENS'"),
            ("TEMPERATURE", "high", "Invalid value 'high' for 'TEMPERATURE'"),
        ]
    )
    def test_type_conversion_error_fallback_to_default(self, mock_console, patched_config_path, key, bad_value, expected_warning_part):
        """Test fallback to default value when type conversion fails."""
        # Set bad value via environment variable (highest priority)
        env_key = DEFAULT_CONFIG_MAP[key]['env_key']
        env_vars = {env_key: bad_value}

        # Ensure config file doesn't interfere
        if patched_config_path.exists():
            patched_config_path.unlink()

        with patch.dict(os.environ, env_vars):
            config = load_config(mock_console)

        # Verify value is the typed default value
        assert config[key] == TYPED_DEFAULTS[key]
        assert isinstance(config[key], type(TYPED_DEFAULTS[key]))

        # Verify warning was printed
        mock_console.print.assert_called()
        found_warning = False
        for call_args in mock_console.print.call_args_list:
             args, kwargs = call_args
             if args and expected_warning_part in args[0]:
                 found_warning = True
                 assert kwargs.get('style') == 'dim'
                 break
        assert found_warning, f"Expected warning containing '{expected_warning_part}' not found."

    def test_load_from_file_no_core_section(self, mock_console, patched_config_path):
        """Test loading from a file that exists but lacks the [core] section."""
        test_ini = """
[other]
SOME_KEY = value
"""
        patched_config_path.parent.mkdir(parents=True, exist_ok=True)
        patched_config_path.write_text(test_ini, encoding='utf-8')

        config = load_config(mock_console)

        # Should load defaults as the [core] section is missing
        assert config == TYPED_DEFAULTS
        mock_console.print.assert_not_called()

    # Potential future test: Malformed INI file (syntax error)
    # This might raise configparser.Error, which load_config doesn't explicitly handle currently.
    # def test_load_malformed_ini(self, mock_console, patched_config_path):
    #     pass 