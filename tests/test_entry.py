from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from yaicli.const import DefaultRoleNames
from yaicli.exceptions import YaicliError
from yaicli.schemas import ImageData

# Assuming your typer app object is named 'app' in yaicli.entry
from yaicli.entry import DEFAULT_CONFIG_INI, app

runner = CliRunner()


@pytest.fixture
def mock_cli_instance():
    """Fixture to provide a mock CLI instance."""
    return MagicMock()


@pytest.fixture
def mock_cli_class(mock_cli_instance):
    """Fixture to patch the CLI class."""
    with patch("yaicli.cli.CLI", return_value=mock_cli_instance) as mock_class:
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

    @patch("yaicli.cli.CLI")
    def test_chat_mode(self, mock_cli_class):
        """Test invoking chat mode."""
        # Configure CLI mock to avoid actual execution
        mock_cli_instance = MagicMock()
        mock_cli_class.return_value = mock_cli_instance

        # Mock evaluate_role_name to return DEFAULT
        mock_cli_class.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT

        result = runner.invoke(app, ["--chat"])
        assert result.exit_code == 0

    @patch("yaicli.cli.CLI.evaluate_role_name", return_value=DefaultRoleNames.DEFAULT)
    def test_shell_mode(self, mock_evaluate_role_name, mock_cli_class, mock_cli_instance):
        """Test invoking shell mode with a prompt."""
        prompt_text = "list files"
        result = runner.invoke(app, ["--shell", prompt_text])
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(
            verbose=False, role="DEFAULT", print_mode=False, output_format="text", quiet=False
        )
        mock_cli_instance.run.assert_called_once_with(
            chat=False, shell=True, code=False, user_input=prompt_text, images=[]
        )

    @patch("yaicli.cli.CLI.evaluate_role_name", return_value=DefaultRoleNames.DEFAULT)
    def test_prompt_mode(self, mock_evaluate_role_name, mock_cli_class, mock_cli_instance):
        """Test invoking with just a prompt."""
        prompt_text = "what is the date?"
        result = runner.invoke(app, [prompt_text])
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(
            verbose=False, role="DEFAULT", print_mode=False, output_format="text", quiet=False
        )
        mock_cli_instance.run.assert_called_once_with(
            chat=False, shell=False, code=False, user_input=prompt_text, images=[]
        )

    @patch("yaicli.cli.CLI.evaluate_role_name", return_value=DefaultRoleNames.DEFAULT)
    def test_verbose_mode(self, mock_evaluate_role_name, mock_cli_class, mock_cli_instance):
        """Test the --verbose flag."""
        prompt_text = "verbose test"
        result = runner.invoke(app, ["--verbose", prompt_text])
        assert result.exit_code == 0
        # Verify CLI was instantiated with verbose=True
        mock_cli_class.assert_called_once_with(
            verbose=True, role="DEFAULT", print_mode=False, output_format="text", quiet=False
        )
        mock_cli_instance.run.assert_called_once_with(
            chat=False, shell=False, code=False, user_input=prompt_text, images=[]
        )

    @patch("yaicli.cli.CLI.evaluate_role_name", return_value=DefaultRoleNames.DEFAULT)
    def test_stdin_prompt(self, mock_evaluate_role_name, mock_cli_class, mock_cli_instance):
        """Test reading prompt from stdin."""
        stdin_text = "prompt from stdin"
        # Mock sys.stdin.isatty to return False, indicating pipe/redirect
        with patch("sys.stdin.isatty", return_value=False):
            result = runner.invoke(app, input=stdin_text)
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(
            verbose=False, role="DEFAULT", print_mode=False, output_format="text", quiet=False
        )
        mock_cli_instance.run.assert_called_once_with(
            chat=False, shell=False, code=False, user_input=stdin_text, images=[]
        )

    @patch("yaicli.cli.CLI.evaluate_role_name", return_value=DefaultRoleNames.DEFAULT)
    def test_stdin_and_arg_prompt(self, mock_evaluate_role_name, mock_cli_class, mock_cli_instance):
        """Test combining stdin and argument prompt."""
        stdin_text = "stdin part"
        arg_text = "arg part"
        expected_prompt = f"{stdin_text}\n\n{arg_text}"
        with patch("sys.stdin.isatty", return_value=False):
            result = runner.invoke(app, [arg_text], input=stdin_text)
        assert result.exit_code == 0
        mock_cli_class.assert_called_once_with(
            verbose=False, role="DEFAULT", print_mode=False, output_format="text", quiet=False
        )
        mock_cli_instance.run.assert_called_once_with(
            chat=False, shell=False, code=False, user_input=expected_prompt, images=[]
        )

    def test_no_prompt_no_chat(self):
        """Test calling without prompt and without --chat."""
        # Ensure stdin is treated as a TTY
        with patch("sys.stdin.isatty", return_value=True):
            # Mock CLI to avoid actual execution
            with patch("yaicli.cli.CLI") as mock_cli:
                # Set up the mock
                mock_cli.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT
                result = runner.invoke(app)

        # No input prints help and returns, which is a success path.
        assert result.exit_code == 0

    def test_chat_with_prompt_warning(self):
        """Test that a warning is printed (to real stdout) if --chat and prompt are used."""
        # We don't capture print() output with CliRunner by default
        # We mainly care that the app doesn't crash and runs correctly
        # Mock a valid CLI instance to avoid exceptions
        mock_instance = MagicMock()
        mock_instance.had_error = False
        with patch("yaicli.cli.CLI", return_value=mock_instance):
            # Mock no API key to simulate the case
            with patch.dict("os.environ", {"YAI_API_KEY": "test_key"}):
                result = runner.invoke(app, ["--chat", "initial prompt"])
                assert result.exit_code == 0

    def test_cli_init_exception(self, mock_cli_class):
        """An unexpected exception during CLI init must exit non-zero, not 0."""
        # Mock CLI.evaluate_role_name to return DEFAULT
        mock_cli_class.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT
        # Set side effect for CLI constructor
        mock_cli_class.side_effect = Exception("CLI Init Failed")

        result = runner.invoke(app, ["some prompt"])

        assert result.exit_code == 1
        assert "Unknown error: CLI Init Failed" in result.output

    def test_cli_run_exception(self):
        """An unexpected exception during cli.run() must exit non-zero."""
        mock_instance = MagicMock()
        mock_instance.run.side_effect = Exception("CLI Run Failed")
        mock_instance.had_error = False

        with patch("yaicli.cli.CLI", return_value=mock_instance) as mock_cli:
            # Mock evaluate_role_name to return DEFAULT
            mock_cli.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT

            result = runner.invoke(app, ["some prompt"])

        assert result.exit_code == 1
        assert "Unknown error: CLI Run Failed" in result.output

    def test_verbose_unknown_exception_prints_traceback(self):
        """-V prints the traceback for unexpected exceptions before exiting non-zero."""
        mock_instance = MagicMock()
        mock_instance.run.side_effect = Exception("CLI Run Failed")
        mock_instance.had_error = False

        with patch("yaicli.cli.CLI", return_value=mock_instance) as mock_cli:
            mock_cli.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT
            result = runner.invoke(app, ["-V", "some prompt"])

        assert result.exit_code == 1
        assert "Traceback" in result.output + result.stderr

    def test_yaicli_error_exits_nonzero(self):
        """A handled YaicliError exits 1 and keeps its message."""
        mock_instance = MagicMock()
        mock_instance.run.side_effect = YaicliError("provider exploded")
        mock_instance.had_error = False

        with patch("yaicli.cli.CLI", return_value=mock_instance) as mock_cli:
            mock_cli.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT
            result = runner.invoke(app, ["some prompt"])

        assert result.exit_code == 1
        assert "YAICLI Error: provider exploded" in result.output

    def test_abort_propagates_nonzero(self):
        """typer.Abort must not be swallowed as a success."""
        mock_instance = MagicMock()
        mock_instance.run.side_effect = typer.Abort()
        mock_instance.had_error = False

        with patch("yaicli.cli.CLI", return_value=mock_instance) as mock_cli:
            mock_cli.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT
            result = runner.invoke(app, ["some prompt"])

        assert result.exit_code == 1

    @pytest.mark.parametrize("had_error, expected", [(True, 1), (False, 0)])
    def test_single_shot_uses_had_error(self, had_error, expected):
        """Single-shot mode turns a handled LLM failure into a non-zero exit."""
        mock_instance = MagicMock()
        mock_instance.had_error = had_error

        with patch("yaicli.cli.CLI", return_value=mock_instance) as mock_cli:
            mock_cli.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT
            result = runner.invoke(app, ["some prompt"])

        assert result.exit_code == expected

    def test_chat_mode_ignores_had_error(self):
        """The interactive REPL keeps its error-tolerant behaviour: quitting still exits 0."""
        mock_instance = MagicMock()
        mock_instance.had_error = True

        # CliRunner isolates sys.stdin as a non-TTY; patch entry's sys reference so the
        # code takes the interactive (chat) path instead of being downgraded to one-shot.
        with patch("yaicli.entry.sys") as mock_sys:
            mock_sys.stdin.isatty.return_value = True
            with patch("yaicli.cli.CLI", return_value=mock_instance) as mock_cli:
                mock_cli.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT
                result = runner.invoke(app, ["--chat", "title"])

        assert result.exit_code == 0
        assert mock_instance.run.call_args.kwargs["chat"] is True

    def test_provider_init_failure_exits_nonzero(self):
        """The real provider-init failure path (unknown provider/missing API_KEY) exits 1."""
        with patch("yaicli.cli.LLMClient", side_effect=ValueError("API_KEY is required")):
            result = runner.invoke(app, ["some prompt"])

        assert result.exit_code == 1
        assert "Unknown error: API_KEY is required" in result.output


class TestImageOptions:
    """Regression tests for `--image/-i` handling.

    D4: an image-only invocation must not abort in `CLI.run()`; entry sends a
    minimal non-empty prompt so the image is actually submitted.
    """

    def test_image_only_sends_minimal_prompt(self, mock_cli_class, mock_cli_instance):
        """A single image without a prompt reaches CLI.run with a minimal prompt."""
        image = ImageData(data="base64data", media_type="image/png", is_url=False)
        mock_cli_class.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT

        with patch("yaicli.image.process_image_source", return_value=image) as mock_process:
            result = runner.invoke(app, ["--image", "photo.png"])

        assert result.exit_code == 0
        mock_process.assert_called_once_with("photo.png")
        mock_cli_instance.run.assert_called_once_with(
            chat=False,
            shell=False,
            code=False,
            user_input="Describe the image.",
            images=[image],
        )

    def test_multiple_images_send_plural_prompt(self, mock_cli_class, mock_cli_instance):
        """Several images without a prompt use the plural minimal prompt."""
        first = ImageData(data="first", media_type="image/png", is_url=False)
        second = ImageData(data="second", media_type="image/jpeg", is_url=False)
        mock_cli_class.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT

        with patch("yaicli.image.process_image_source", side_effect=[first, second]) as mock_process:
            result = runner.invoke(app, ["--image", "a.png", "--image", "b.jpg"])

        assert result.exit_code == 0
        assert mock_process.call_count == 2
        mock_cli_instance.run.assert_called_once_with(
            chat=False,
            shell=False,
            code=False,
            user_input="Describe these images.",
            images=[first, second],
        )

    def test_image_with_explicit_prompt_keeps_prompt(self, mock_cli_class, mock_cli_instance):
        """An explicit prompt wins over the image-only minimal prompt."""
        image = ImageData(data="base64data", media_type="image/png", is_url=False)
        mock_cli_class.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT

        with patch("yaicli.image.process_image_source", return_value=image):
            result = runner.invoke(app, ["--image", "photo.png", "What is in it?"])

        assert result.exit_code == 0
        mock_cli_instance.run.assert_called_once_with(
            chat=False,
            shell=False,
            code=False,
            user_input="What is in it?",
            images=[image],
        )

    def test_invalid_image_exits_before_cli_is_built(self, mock_cli_class):
        """Bad image sources keep the existing error + exit(1) path.

        v0.19 K04: errors are diagnostics and go to stderr so stdout stays clean.
        """
        with patch(
            "yaicli.image.process_image_source",
            side_effect=typer.BadParameter("Image file not found: missing.png"),
        ):
            result = runner.invoke(app, ["--image", "missing.png"])

        assert result.exit_code == 1
        assert "Image file not found: missing.png" in result.stderr
        assert "Image file not found: missing.png" not in result.stdout
        mock_cli_class.assert_not_called()

    def test_no_prompt_no_image_still_prints_help(self, mock_cli_class):
        """The empty-invocation help path is unchanged."""
        with patch("sys.stdin.isatty", return_value=True):
            result = runner.invoke(app)

        assert result.exit_code == 0
        assert "Usage:" in result.stdout
        mock_cli_class.assert_not_called()
