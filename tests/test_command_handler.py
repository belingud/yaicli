from unittest.mock import MagicMock, patch

import pytest

from yaicli.cmd_handler import CmdHandler
from yaicli.const import (
    CHAT_MODE,
    EXEC_MODE,
    DefaultRoleNames,
)


@pytest.fixture
def mock_cli():
    """Create a mock CLI for testing CmdHandler."""
    cli = MagicMock()
    cli.console = MagicMock()
    cli.chat = MagicMock()
    cli.chat.history = []
    cli.chat.title = "Test Chat"
    cli.current_mode = CHAT_MODE
    cli.init_role = DefaultRoleNames.DEFAULT
    return cli


@pytest.fixture
def cmd_handler(mock_cli):
    """Create a CmdHandler instance with mock CLI for testing."""
    return CmdHandler(mock_cli)


class TestCmdHandler:
    """Test the CmdHandler class."""

    def test_handle_shell_command(self, cmd_handler):
        """Test handling shell commands with ! prefix."""
        with patch("subprocess.call") as mock_subprocess:
            # Test with a valid command
            result = cmd_handler.handle_shell_command("ls -la")
            assert result is True
            mock_subprocess.assert_called_once_with("ls -la", shell=True)

            # Test with empty command
            mock_subprocess.reset_mock()
            result = cmd_handler.handle_shell_command("")
            assert result is True
            mock_subprocess.assert_not_called()

            # Test with exception
            mock_subprocess.side_effect = Exception("Command failed")
            result = cmd_handler.handle_shell_command("bad-command")
            assert result is True  # Should return True to continue REPL loop
            cmd_handler.cli.console.print.assert_any_call("Failed to execute command: Command failed", style="red")

    def test_handle_exclamation_commands(self, cmd_handler):
        """Test handling commands with exclamation mark prefixes."""
        with patch.object(cmd_handler, "handle_shell_command") as mock_handle:
            mock_handle.return_value = True

            # Test half-width exclamation mark
            result = cmd_handler.handle_command("!ls -la")
            assert result is True
            mock_handle.assert_called_once_with("ls -la")

            # Test full-width exclamation mark
            mock_handle.reset_mock()
            result = cmd_handler.handle_command("！pwd")
            assert result is True
            mock_handle.assert_called_once_with("pwd")

    def test_handle_help_command(self, cmd_handler):
        """Test handling help command."""
        with patch.object(cmd_handler, "handle_help", return_value=True):
            result = cmd_handler.handle_command("/help")
            assert result is True
            cmd_handler.cli.print_help.assert_called_once()

    def test_handle_exit_command(self, cmd_handler):
        """Test handling exit command."""
        result = cmd_handler.handle_command("/exit")
        assert result is False  # Should return False to exit REPL loop

    def test_handle_clear_command(self, cmd_handler):
        """Test handling clear command."""
        # Set up a mock history
        cmd_handler.cli.chat.history = ["message1", "message2"]
        cmd_handler.cli.current_mode = CHAT_MODE

        result = cmd_handler.handle_command("/clear")
        assert result is True
        assert cmd_handler.cli.chat.history == []
        cmd_handler.cli.console.print.assert_any_call("Chat history cleared", style="bold yellow")

        # Test in non-chat mode - should still return True but not clear
        cmd_handler.cli.current_mode = EXEC_MODE
        cmd_handler.cli.chat.history = ["message1", "message2"]
        result = cmd_handler.handle_command("/clear")
        assert result is True
        assert cmd_handler.cli.chat.history == ["message1", "message2"]

    def test_handle_history_command(self, cmd_handler):
        """Test handling history command."""
        # Test with empty history
        cmd_handler.cli.chat.history = []
        result = cmd_handler.handle_command("/his")
        assert result is True
        cmd_handler.cli.console.print.assert_any_call("History is empty.", style="yellow")

        # Test with history content - just verify method behavior as the actual
        # display logic is complex
        cmd_handler.cli.console.print.reset_mock()
        cmd_handler.cli.chat.history = [
            MagicMock(role="user", content="test message"),
            MagicMock(role="assistant", content="test response"),
        ]
        result = cmd_handler.handle_command("/his")
        assert result is True
        # Should print chat history header
        cmd_handler.cli.console.print.assert_any_call("Chat History:", style="bold underline")

    def test_handle_save_command(self, cmd_handler):
        """Test handling save command."""
        # Test with title
        result = cmd_handler.handle_command("/save New Title")
        assert result is True
        cmd_handler.cli._save_chat.assert_called_once_with("New Title")

        # Test without title
        cmd_handler.cli._save_chat.reset_mock()
        result = cmd_handler.handle_command("/save")
        assert result is True
        cmd_handler.cli._save_chat.assert_called_once_with(cmd_handler.cli.chat.title)

    def test_handle_load_command(self, cmd_handler):
        """Test handling load command."""
        # Test with valid index
        result = cmd_handler.handle_command("/load 1")
        assert result is True
        cmd_handler.cli._load_chat_by_index.assert_called_once_with(index="1")

        # Test without index - should show usage message
        cmd_handler.cli._load_chat_by_index.reset_mock()
        cmd_handler.cli.console.print.reset_mock()
        result = cmd_handler.handle_command("/load")
        assert result is True
        cmd_handler.cli.console.print.assert_any_call("Usage: /load <index>", style="yellow")
        cmd_handler.cli._list_chats.assert_called_once()

    def test_handle_delete_command(self, cmd_handler):
        """Test handling delete command."""
        # Test with valid index
        result = cmd_handler.handle_command("/delete 1")
        assert result is True
        cmd_handler.cli._delete_chat_by_index.assert_called_once_with(index="1")

        # Test without index - should show usage message
        cmd_handler.cli._delete_chat_by_index.reset_mock()
        cmd_handler.cli.console.print.reset_mock()
        result = cmd_handler.handle_command("/delete")
        assert result is True
        cmd_handler.cli.console.print.assert_any_call("Usage: /del <index>", style="yellow")
        cmd_handler.cli._list_chats.assert_called_once()

    def test_handle_list_command(self, cmd_handler):
        """Test handling list command."""
        with patch.object(cmd_handler, "handle_list", return_value=True):
            result = cmd_handler.handle_command("/chats")
            assert result is True
            cmd_handler.cli._list_chats.assert_called_once()

    def test_handle_mode_command(self, cmd_handler):
        """Test handling mode command."""
        # Test switching to exec mode
        cmd_handler.cli.current_mode = CHAT_MODE
        result = cmd_handler.handle_command("/mode exec")
        assert result is True
        cmd_handler.cli.set_role.assert_called_once_with(DefaultRoleNames.SHELL)
        assert cmd_handler.cli.current_mode == EXEC_MODE

        # Test with same mode
        cmd_handler.cli.console.print.reset_mock()
        cmd_handler.cli.set_role.reset_mock()
        result = cmd_handler.handle_command("/mode exec")
        assert result is True
        cmd_handler.cli.console.print.assert_any_call("Already in exec mode.", style="yellow")
        cmd_handler.cli.set_role.assert_not_called()

        # Test with invalid mode
        cmd_handler.cli.console.print.reset_mock()
        result = cmd_handler.handle_command("/mode invalid")
        assert result is True
        cmd_handler.cli.console.print.assert_any_call("Usage: /mode chat|exec", style="yellow")

    def test_handle_non_special_command(self, cmd_handler):
        """Test handling non-special command."""
        result = cmd_handler.handle_command("hello world")
        assert result == "hello world"  # Should return the original input
