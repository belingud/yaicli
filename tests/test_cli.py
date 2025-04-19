import pytest
from unittest.mock import MagicMock, patch

from rich.console import Console

from yaicli.cli import CLI
from yaicli.const import CHAT_MODE, EXEC_MODE, TEMP_MODE, CMD_EXIT, CMD_CLEAR, CMD_HISTORY


@pytest.fixture
def mock_console():
    """Fixture for a mocked Console object."""
    return MagicMock(spec=Console)


@pytest.fixture
def mock_api_client():
    """Fixture for a mocked ApiClient."""
    return MagicMock()


@pytest.fixture
def mock_printer():
    """Fixture for a mocked Printer."""
    return MagicMock()


@pytest.fixture
def mock_session():
    """Fixture for a mocked PromptSession."""
    return MagicMock()


@pytest.fixture
def cli_instance(mock_console, mock_api_client, mock_printer, mock_session):
    """Fixture for a CLI instance with mocked dependencies."""
    # Patch dependencies during CLI initialization using nested with statements
    with patch("yaicli.cli.get_console", return_value=mock_console):
        with patch("yaicli.cli.load_config", return_value={}):
            with patch("yaicli.cli.ApiClient", return_value=mock_api_client):
                with patch("yaicli.cli.Printer", return_value=mock_printer):
                    with patch("yaicli.cli.PromptSession", return_value=mock_session):
                        cli = CLI(verbose=False)
                        # Clear history potentially added by init
                        cli.history.clear()
                        return cli

# --- Tests for helper methods --- #

def test_check_history_len(cli_instance):
    """Test history truncation logic."""
    cli_instance.max_history_length = 2 # Set a small limit for testing
    target_len = cli_instance.max_history_length * 2 # = 4

    # Add more messages than allowed (0-5 -> 6 pairs -> 12 items)
    for i in range(target_len + 2):
        cli_instance.history.append({"role": "user", "content": f"msg {i}"})
        cli_instance.history.append({"role": "assistant", "content": f"resp {i}"})

    assert len(cli_instance.history) == (target_len + 2) * 2
    cli_instance._check_history_len()
    assert len(cli_instance.history) == target_len
    # Check that the oldest messages were removed
    # The slice [-target_len:] keeps the last target_len items.
    # With 6 pairs initially and target_len=4, the last 4 items are
    # msg 4, resp 4, msg 5, resp 5.
    assert cli_instance.history[0]["content"] == "msg 4"
    assert cli_instance.history[1]["content"] == "resp 4"


@pytest.mark.parametrize(
    "mode, expected_qmark",
    [
        (CHAT_MODE, "💬"),
        (EXEC_MODE, "🚀"),
        (TEMP_MODE, "📝"),
        ("other_mode", "📝"), # Default to TEMP_MODE qmark if mode unknown
    ]
)
def test_get_prompt_tokens(cli_instance, mode, expected_qmark):
    """Test prompt token generation for different modes."""
    cli_instance.current_mode = mode
    tokens = cli_instance.get_prompt_tokens()
    assert tokens == [("class:qmark", f" {expected_qmark} "), ("class:prompt", "> ")]


@pytest.mark.parametrize(
    "mode, expected_template_fragment",
    [
        (CHAT_MODE, "programing assistant"), # Use fragment from DEFAULT_PROMPT
        (EXEC_MODE, "Shell Command Generator"), # Use fragment from SHELL_PROMPT
        (TEMP_MODE, "programing assistant"), # Use fragment from DEFAULT_PROMPT
    ]
)
def test_get_system_prompt(cli_instance, mode, expected_template_fragment):
    """Test system prompt generation for different modes."""
    cli_instance.current_mode = mode
    test_os = "TestOS"
    test_shell = "TestShell"
    cli_instance.config["OS_NAME"] = test_os
    cli_instance.config["SHELL_NAME"] = test_shell
    prompt_content = cli_instance.get_system_prompt()
    # Check if OS and Shell names are present, not the exact format "OS: ..."
    assert test_os in prompt_content
    assert test_shell in prompt_content
    assert expected_template_fragment in prompt_content

def test_build_messages(cli_instance):
    """Test the construction of the message list for the API."""
    cli_instance.current_mode = CHAT_MODE
    test_os = "TestOS"
    test_shell = "TestShell"
    cli_instance.config["OS_NAME"] = test_os
    cli_instance.config["SHELL_NAME"] = test_shell
    cli_instance.history = [
        {"role": "user", "content": "Previous question"},
        {"role": "assistant", "content": "Previous answer"},
    ]
    user_input = "New question"

    messages = cli_instance._build_messages(user_input)

    assert len(messages) == 4 # System + history (2) + current user input
    assert messages[0]["role"] == "system"
    # Check if OS and Shell names are present in system message content
    assert test_os in messages[0]["content"]
    assert test_shell in messages[0]["content"]
    assert messages[1] == cli_instance.history[0]
    assert messages[2] == cli_instance.history[1]
    assert messages[3]["role"] == "user"
    assert messages[3]["content"] == user_input


# --- Tests for _handle_special_commands --- #

def test_handle_special_commands_exit(cli_instance):
    """Test the /exit command."""
    assert cli_instance._handle_special_commands(CMD_EXIT) is False
    assert cli_instance._handle_special_commands(" /exit ") is False # With spaces

def test_handle_special_commands_clear_chat_mode(cli_instance, mock_console):
    """Test the /clear command in CHAT_MODE."""
    cli_instance.current_mode = CHAT_MODE
    cli_instance.history = [{"role": "user", "content": "test"}]
    assert cli_instance._handle_special_commands(CMD_CLEAR) is True
    assert not cli_instance.history # History should be cleared
    mock_console.clear.assert_called_once()
    mock_console.print.assert_called_with("Chat history cleared\n", style="bold yellow")

def test_handle_special_commands_clear_other_mode(cli_instance, mock_console):
    """Test that /clear does nothing in non-CHAT_MODE."""
    cli_instance.current_mode = EXEC_MODE
    cli_instance.history = [{"role": "user", "content": "test"}]
    assert cli_instance._handle_special_commands(CMD_CLEAR) is None # Not a special command in this mode
    assert cli_instance.history # History should NOT be cleared
    mock_console.clear.assert_not_called()

def test_handle_special_commands_history_empty(cli_instance, mock_console):
    """Test the /history command when history is empty."""
    cli_instance.history = []
    assert cli_instance._handle_special_commands(CMD_HISTORY) is True
    mock_console.print.assert_called_with("History is empty.", style="yellow")

@patch("yaicli.cli.Markdown")
@patch("yaicli.cli.Padding")
def test_handle_special_commands_history_with_content(mock_padding_cls, mock_markdown_cls, cli_instance, mock_console):
    """Test the /history command with content."""
    mock_md_instance = MagicMock()
    mock_markdown_cls.return_value = mock_md_instance
    mock_padded_md_instance = MagicMock()
    mock_padding_cls.return_value = mock_padded_md_instance

    cli_instance.history = [
        {"role": "user", "content": "Question 1"},
        {"role": "assistant", "content": "Answer 1"},
        {"role": "user", "content": "Question 2"}, # No assistant msg yet
    ]
    cli_instance.config["CODE_THEME"] = "test-theme"

    assert cli_instance._handle_special_commands(CMD_HISTORY) is True

    # Check console output
    mock_console.print.assert_any_call("[bold underline]Chat History:[/bold underline]")
    mock_console.print.assert_any_call("[dim]1[/dim] [bold blue]User:[/bold blue] Question 1")
    mock_console.print.assert_any_call("    [bold green]Assistant:[/bold green]")
    mock_console.print.assert_any_call(mock_padded_md_instance) # Check padded markdown was printed
    mock_console.print.assert_any_call("[dim]2[/dim] [bold blue]User:[/bold blue] Question 2")

    # Check Markdown and Padding calls
    mock_markdown_cls.assert_called_once_with("Answer 1", code_theme="test-theme")
    mock_padding_cls.assert_called_once_with(mock_md_instance, (0, 0, 0, 4))


def test_handle_special_commands_unknown(cli_instance):
    """Test an unknown command."""
    assert cli_instance._handle_special_commands("/unknown") is None
    assert cli_instance._handle_special_commands("just normal input") is None

# --- Test Key Binding Setup (placeholder) --- #
# Testing the actual key binding logic is complex and might require
# simulating key presses, which is beyond typical unit testing.
# We can test that the setup method adds a binding.

def test_setup_key_bindings_adds_binding(cli_instance):
    """Verify that _setup_key_bindings registers at least one binding."""
    initial_bindings = len(cli_instance.bindings.bindings)
    cli_instance._setup_key_bindings()
    assert len(cli_instance.bindings.bindings) > initial_bindings
    # We could potentially inspect the bindings list for specific keys like ControlI
    # but simply checking that *something* was added is a basic sanity check. 