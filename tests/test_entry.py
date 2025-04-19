import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

# Assuming your typer app object is named 'app' in yaicli.entry
from yaicli.entry import app, DEFAULT_CONFIG_INI

runner = CliRunner()


@pytest.fixture
def mock_cli_instance():
    """Fixture to provide a mock CLI instance."""
    return MagicMock()

@pytest.fixture
def mock_cli_class(mock_cli_instance):
    """Fixture to patch the CLI class."""
    with patch('yaicli.entry.CLI', return_value=mock_cli_instance) as mock_class:
        yield mock_class

# Need conftest fixtures to be available if CLI() accesses config/history
# No extra setup needed if using global patched_config_path from conftest.py

class TestTyperApp:

    def test_help_option(self):
        """Test the --help option."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage: main" in result.stdout
        assert "--chat" in result.stdout
        assert "--shell" in result.stdout
        assert "--verbose" in result.stdout
        assert "--template" in result.stdout

    def test_template_option(self):
        """Test the --template option."""
        result = runner.invoke(app, ["--template"])
        assert result.exit_code == 0
        # Compare stripped lines to be robust against minor whitespace differences
        expected_lines = {line.strip() for line in DEFAULT_CONFIG_INI.strip().splitlines()}
        output_lines = {line.strip() for line in result.stdout.strip().splitlines()}
        assert output_lines == expected_lines

    def test_chat_mode(self, mock_cli_class, mock_cli_instance):
        """Test invoking chat mode."""
        result = runner.invoke(app, ["--chat"])
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(verbose=False)
        mock_cli_instance.run.assert_called_once_with(chat=True, shell=False, prompt=None)

    def test_shell_mode(self, mock_cli_class, mock_cli_instance):
        """Test invoking shell mode with a prompt."""
        prompt_text = "list files"
        result = runner.invoke(app, ["--shell", prompt_text])
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(verbose=False)
        mock_cli_instance.run.assert_called_once_with(chat=False, shell=True, prompt=prompt_text)

    def test_prompt_mode(self, mock_cli_class, mock_cli_instance):
        """Test invoking with just a prompt."""
        prompt_text = "what is the date?"
        result = runner.invoke(app, [prompt_text])
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(verbose=False)
        mock_cli_instance.run.assert_called_once_with(chat=False, shell=False, prompt=prompt_text)

    def test_verbose_mode(self, mock_cli_class, mock_cli_instance):
        """Test the --verbose flag."""
        prompt_text = "verbose test"
        result = runner.invoke(app, ["--verbose", prompt_text])
        assert result.exit_code == 0
        # Verify CLI was instantiated with verbose=True
        mock_cli_class.assert_called_once_with(verbose=True)
        mock_cli_instance.run.assert_called_once_with(chat=False, shell=False, prompt=prompt_text)

    def test_stdin_prompt(self, mock_cli_class, mock_cli_instance):
        """Test reading prompt from stdin."""
        stdin_text = "prompt from stdin"
        # Mock sys.stdin.isatty to return False, indicating pipe/redirect
        with patch('sys.stdin.isatty', return_value=False):
            result = runner.invoke(app, input=stdin_text)
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(verbose=False)
        mock_cli_instance.run.assert_called_once_with(chat=False, shell=False, prompt=stdin_text)

    def test_stdin_and_arg_prompt(self, mock_cli_class, mock_cli_instance):
        """Test combining stdin and argument prompt."""
        stdin_text = "stdin part"
        arg_text = "arg part"
        expected_prompt = f"{stdin_text}\n\n{arg_text}"
        with patch('sys.stdin.isatty', return_value=False):
            result = runner.invoke(app, [arg_text], input=stdin_text)
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(verbose=False)
        mock_cli_instance.run.assert_called_once_with(chat=False, shell=False, prompt=expected_prompt)

    def test_no_prompt_no_chat(self):
        """Test calling without prompt and without --chat."""
        # Ensure stdin is treated as a TTY
        with patch('sys.stdin.isatty', return_value=True):
            result = runner.invoke(app)
        assert result.exit_code == 0 # Typer exits with 0 after showing help by default
        assert "Usage: main" in result.stdout # Should print help

    def test_chat_with_prompt_warning(self, mock_cli_class, mock_cli_instance):
        """Test that a warning is printed (to real stdout) if --chat and prompt are used."""
        # We don't capture print() output with CliRunner by default
        # We mainly care that the app doesn't crash and calls run correctly
        result = runner.invoke(app, ["--chat", "initial prompt"])
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(verbose=False)
        # Chat mode takes precedence, prompt is ignored in run call
        mock_cli_instance.run.assert_called_once_with(chat=True, shell=False, prompt="initial prompt")
        # We can't easily assert the print() warning without more complex stdout capture

    def test_cli_init_exception(self, mock_cli_class):
        """Test handling of exception during CLI initialization."""
        mock_cli_class.side_effect = Exception("CLI Init Failed")
        result = runner.invoke(app, ["some prompt"])
        assert result.exit_code == 1
        assert "An error occurred: CLI Init Failed" in result.stdout

    def test_cli_run_exception(self, mock_cli_class, mock_cli_instance):
        """Test handling of exception during cli.run()."""
        mock_cli_instance.run.side_effect = Exception("CLI Run Failed")
        result = runner.invoke(app, ["some prompt"])
        assert result.exit_code == 1
        assert "An error occurred: CLI Run Failed" in result.stdout 