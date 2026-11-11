from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest

from yaicli.cmd_handler import (
    CMD_COMPACT,
    CMD_COST,
    CMD_MODEL,
    CMD_RETRY,
    CMD_ROLE,
    COMMAND_INFO,
    CmdHandler,
    command_completions,
)
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


class TestHandleAddContext:
    """Tests for handle_add_context."""

    def test_shlex_error(self, cmd_handler):
        result = cmd_handler.handle_add_context('/add "unclosed')
        assert result is True
        printed = [str(c.args[0]) for c in cmd_handler.cli.console.print.call_args_list]
        assert any("Error parsing command" in t for t in printed)
        cmd_handler.cli.context_manager.add.assert_not_called()

    def test_missing_path(self, cmd_handler):
        result = cmd_handler.handle_add_context("/add")
        assert result is True
        printed = [str(c.args[0]) for c in cmd_handler.cli.console.print.call_args_list]
        assert any("Usage:" in t for t in printed)
        cmd_handler.cli.context_manager.add.assert_not_called()

    def test_add_path_not_verbose(self, cmd_handler):
        cmd_handler.cli.verbose = False
        result = cmd_handler.handle_add_context("/add myfile.txt")
        assert result is True
        cmd_handler.cli.context_manager.add.assert_called_once_with("myfile.txt")

    def test_add_path_with_at_and_verbose(self, cmd_handler):
        cmd_handler.cli.verbose = True
        result = cmd_handler.handle_add_context("/add @myfile.txt")
        assert result is True
        cmd_handler.cli.context_manager.add.assert_called_once_with("myfile.txt")
        printed = [str(c.args[0]) for c in cmd_handler.cli.console.print.call_args_list]
        assert any("Adding context" in t for t in printed)


class TestHandleContext:
    """Tests for handle_context subcommands."""

    def test_shlex_error(self, cmd_handler):
        result = cmd_handler.handle_context('/context "unclosed')
        assert result is True
        printed = [str(c.args[0]) for c in cmd_handler.cli.console.print.call_args_list]
        assert any("Error parsing command" in t for t in printed)

    def test_no_subcommand_defaults_to_list(self, cmd_handler):
        result = cmd_handler.handle_context("/context")
        assert result is True
        cmd_handler.cli.context_manager.list_items.assert_called_once()
        # The legacy subcommand hint is not repeated after the usage block.
        printed = [str(c.args[0]) for c in cmd_handler.cli.console.print.call_args_list]
        assert not any("Subcommands:" in str(text) for text in printed)

    def test_list(self, cmd_handler):
        result = cmd_handler.handle_context("/context list")
        assert result is True
        cmd_handler.cli.context_manager.list_items.assert_called_once()

    def test_clear(self, cmd_handler):
        result = cmd_handler.handle_context("/context clear")
        assert result is True
        cmd_handler.cli.context_manager.clear.assert_called_once()

    def test_add_missing_path(self, cmd_handler):
        result = cmd_handler.handle_context("/context add")
        assert result is True
        printed = [str(c.args[0]) for c in cmd_handler.cli.console.print.call_args_list]
        assert any("Usage: /context add" in t for t in printed)
        cmd_handler.cli.context_manager.add.assert_not_called()

    def test_add_with_at_prefix(self, cmd_handler):
        result = cmd_handler.handle_context("/context add @f.txt")
        assert result is True
        cmd_handler.cli.context_manager.add.assert_called_once_with("f.txt")

    def test_remove_missing_path(self, cmd_handler):
        result = cmd_handler.handle_context("/context remove")
        assert result is True
        printed = [str(c.args[0]) for c in cmd_handler.cli.console.print.call_args_list]
        assert any("Usage: /context remove" in t for t in printed)
        cmd_handler.cli.context_manager.remove.assert_not_called()

    def test_remove_path(self, cmd_handler):
        result = cmd_handler.handle_context("/context remove f.txt")
        assert result is True
        cmd_handler.cli.context_manager.remove.assert_called_once_with("f.txt")

    def test_remove_alias_rm(self, cmd_handler):
        result = cmd_handler.handle_context("/context rm f.txt")
        assert result is True
        cmd_handler.cli.context_manager.remove.assert_called_once_with("f.txt")

    def test_unknown_subcommand(self, cmd_handler):
        result = cmd_handler.handle_context("/context bogus")
        assert result is True
        printed = [str(c.args[0]) for c in cmd_handler.cli.console.print.call_args_list]
        assert any("Unknown sub-command" in t for t in printed)


class TestHandleHistoryToolCalls:
    """Test history rendering for assistant messages carrying tool calls."""

    def test_history_with_tool_calls(self, cmd_handler):
        tool_call = MagicMock()
        tool_call.name = "get_weather"
        tool_call.arguments = '{"city": "NYC"}'
        assistant_msg = MagicMock(role="assistant", content="Let me check", tool_calls=[tool_call])
        cmd_handler.cli.chat.history = [assistant_msg]

        with patch("yaicli.cmd_handler.cfg", {"CODE_THEME": "monokai"}):
            result = cmd_handler.handle_history()

        assert result is True
        printed = [str(c.args[0]) for c in cmd_handler.cli.console.print.call_args_list]
        assert any("Assistant:" in t for t in printed)


def _printed_text(console):
    """All console.print() first arguments joined into one string."""
    return "\n".join(str(call.args[0]) for call in console.print.call_args_list if call.args)


class TestContextUsageOutput:
    """v0.23 K22: /context shows the window source and the reserve breakdown."""

    @staticmethod
    def _usage(**overrides):
        from yaicli.tokens import ContextUsage

        values = {
            "system_tokens": 12,
            "project_tokens": 1234,
            "extra_tokens": 0,
            "history_tokens": 2175,
            "tool_output_tokens": 1148,
            "overhead_tokens": 3,
            "total_tokens": 3424,
            "budget_tokens": 997952,
            "remaining_tokens": 994528,
            "used_percent": 0.3,
            "message_count": 4,
            "window_tokens": 1000000,
            "max_output_tokens": 128000,
            "source": "metadata",
            "detail": "openrouter /models",
            "reserve_tokens": 2048,
        }
        values.update(overrides)
        return ContextUsage(**values)

    @staticmethod
    def _handler(**cli_attrs):
        cli = MagicMock()
        cli.console = MagicMock()
        cli.chat.history = []
        for name, value in cli_attrs.items():
            setattr(cli, name, value)
        return cli, CmdHandler(cli)

    def test_known_model_prints_window_source_and_reserve(self):
        cli, handler = self._handler()

        with (
            patch(
                "yaicli.cmd_handler.cfg",
                {"PROVIDER": "openrouter", "MAX_TOKENS": 1024, "CONTEXT_SAFETY_TOKENS": 1024},
            ),
            patch("yaicli.cmd_handler.estimate_context_usage", return_value=self._usage()),
        ):
            handler._print_context_usage()

        printed = _printed_text(cli.console)
        assert "Context usage (estimated):" in printed
        assert "  window        : 1,000,000 tokens (source: metadata · openrouter /models)" in printed
        assert "  role prompt   : 12 tokens" in printed
        assert "  project ctx   : 1,234 tokens" in printed
        assert "  /add context  : 0 tokens" in printed
        assert "  history       : 2,175 tokens (tool output 1,148)" in printed
        # v0.23 polish: the request priming overhead is its own row so the buckets
        # (12 + 1,234 + 0 + 2,175 + 3) add up to the rendered total.
        assert "  overhead      : 3 tokens" in printed
        assert "  total         : 3,424 / 997,952 tokens (0.3%)" in printed
        assert "  remaining     : 994,528 tokens" in printed
        assert "  reserve       : 2,048 (MAX_TOKENS 1,024 + safety 1,024)" in printed
        assert "Use /compact [keep_rounds] to drop older turn groups." in printed
        # The heading stays bold and the /compact hint stays dim (plain-text asserts above).
        cli.console.print.assert_any_call("Context usage (estimated):", style="bold")
        cli.console.print.assert_any_call(
            "  Use /compact [keep_rounds] to drop older turn groups.", style="dim", markup=False
        )

    def test_unknown_model_default_source_is_explained(self):
        cli, handler = self._handler()
        usage = self._usage(
            window_tokens=128000,
            source="default",
            detail="assumed for unknown model",
            system_tokens=12,
            project_tokens=0,
            extra_tokens=0,
            history_tokens=2175,
            overhead_tokens=3,
            total_tokens=2190,
            budget_tokens=124928,
            remaining_tokens=122738,
            used_percent=1.8,
        )

        with (
            patch("yaicli.cmd_handler.cfg", {"PROVIDER": "openai", "MAX_TOKENS": 1024}),
            patch("yaicli.cmd_handler.estimate_context_usage", return_value=usage),
        ):
            handler._print_context_usage()

        printed = _printed_text(cli.console)
        assert (
            "  window        : 128,000 tokens "
            "(source: default · assumed for unknown model; set MODEL_CONTEXT_WINDOWS to override)" in printed
        )
        assert "  project ctx   : 0 tokens" in printed
        assert "  overhead      : 3 tokens" in printed
        assert "  total         : 2,190 / 124,928 tokens (1.8%)" in printed
        assert "  remaining     : 122,738 tokens" in printed
        # CONTEXT_SAFETY_TOKENS came from the documented default when cfg has no value.
        assert "  reserve       : 2,048 (MAX_TOKENS 1,024 + safety 1,024)" in printed

    def test_context_usage_wires_role_project_and_added_context(self):
        cli, handler = self._handler()
        cli.chat.history = ["history-message"]
        cli.role.prompt = "ROLE PROMPT"
        cli._get_project_context.return_value = "PROJECT INSTRUCTIONS"
        cli.context_manager.get_context_messages.return_value = ["persistent-context"]
        fake_usage = self._usage()

        with (
            patch("yaicli.cmd_handler.cfg", {"PROVIDER": "openrouter"}),
            patch("yaicli.cmd_handler.estimate_context_usage", return_value=fake_usage) as estimator,
        ):
            assert handler._context_usage() is fake_usage

        args, kwargs = estimator.call_args
        assert args == (["history-message"],)
        assert kwargs["config"] == {"PROVIDER": "openrouter"}
        assert kwargs["system_text"] == "ROLE PROMPT"
        assert kwargs["provider"] == "openrouter"
        assert kwargs["extra_system_text"] == "PROJECT INSTRUCTIONS"
        assert kwargs["extra_messages"] == ["persistent-context"]

    def test_context_usage_tolerates_cli_without_context_hooks(self):
        cli = MagicMock(spec=["console", "chat"])
        cli.console = MagicMock()
        cli.chat = MagicMock()
        cli.chat.history = []
        handler = CmdHandler(cli)
        fake_usage = self._usage()

        with (
            patch("yaicli.cmd_handler.cfg", {"PROVIDER": "openai"}),
            patch("yaicli.cmd_handler.estimate_context_usage", return_value=fake_usage) as estimator,
        ):
            assert handler._context_usage() is fake_usage

        _, kwargs = estimator.call_args
        assert kwargs["system_text"] == ""
        assert kwargs["extra_system_text"] == ""
        assert kwargs["extra_messages"] == []

    def test_budget_subcommand_prints_only_the_usage_block(self):
        cli, handler = self._handler()
        cli.context_manager.list_items = MagicMock()

        with (
            patch("yaicli.cmd_handler.cfg", {"PROVIDER": "openai"}),
            patch("yaicli.cmd_handler.estimate_context_usage", return_value=self._usage()),
        ):
            assert handler.handle_context("/context budget") is True

        printed = _printed_text(cli.console)
        assert "Context usage (estimated):" in printed
        assert "  window        : 1,000,000 tokens (source: metadata · openrouter /models)" in printed
        cli.context_manager.list_items.assert_not_called()


class TestHandleCost:
    """v0.22 K17: /cost reports session tokens, cost, models and tool metrics."""

    @staticmethod
    def _snapshot(**overrides):
        snapshot = {
            "prompt_tokens": 1234,
            "completion_tokens": 567,
            "total_tokens": 1801,
            "cached_tokens": 12,
            "reasoning_tokens": 0,
            "estimated": False,
            "requests": 2,
            "cost_usd": 0.0021,
            "models": {
                "gpt-4o-mini": {
                    "prompt_tokens": 1234,
                    "completion_tokens": 567,
                    "total_tokens": 1801,
                    "estimated": False,
                    "cost_usd": 0.0021,
                }
            },
            "tools": {"count": 2, "duration_ms": 25.0, "result_chars": 4096},
        }
        snapshot.update(overrides)
        return snapshot

    def _handler(self, snapshot):
        cli = MagicMock()
        cli.console = MagicMock()
        cli._client = MagicMock()
        cli._client.usage_snapshot = MagicMock(return_value=snapshot)
        cli._client.last_finish_reason = "stop"
        return CmdHandler(cli)

    def test_cost_without_client_prints_friendly_line(self, mock_cli):
        mock_cli._client = None
        handler = CmdHandler(mock_cli)

        assert handler.handle_command(CMD_COST) is True

        assert "No token usage" in _printed_text(mock_cli.console)

    def test_cost_shows_totals_cost_models_and_tools(self):
        handler = self._handler(self._snapshot())

        assert handler.handle_command(CMD_COST) is True

        printed = _printed_text(handler.cli.console)
        assert "Session usage:" in printed
        assert "1,234 in / 567 out (1,801 total)" in printed
        assert "requests  : 2" in printed
        assert "$0.0021" in printed
        assert "2 call(s)" in printed
        assert "4,096 result chars" in printed
        assert "last stop : stop" in printed
        assert "gpt-4o-mini: 1,234 in / 567 out, $0.0021" in printed

    def test_cost_marks_estimated_usage(self):
        handler = self._handler(self._snapshot(estimated=True))

        handler.handle_cost()

        assert "(estimated)" in _printed_text(handler.cli.console)

    def test_cost_unknown_pricing_fallback(self):
        snapshot = self._snapshot(
            cost_usd=None,
            models={
                "totally-unknown-model": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "estimated": False,
                    "cost_usd": None,
                }
            },
        )
        handler = self._handler(snapshot)

        handler.handle_cost()

        printed = _printed_text(handler.cli.console)
        assert "unknown model pricing" in printed
        assert "totally-unknown-model: 10 in / 5 out, unknown pricing" in printed

    def test_cost_no_usage_recorded_yet(self):
        snapshot = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated": False,
            "requests": 0,
            "cost_usd": None,
            "models": {},
            "tools": {"count": 0, "duration_ms": 0.0, "result_chars": 0},
        }
        handler = self._handler(snapshot)

        assert handler.handle_cost() is True

        assert "No usage recorded yet" in _printed_text(handler.cli.console)


# ---------------------------------------------------------------------------
# /model, /role, /retry + shared help/completion metadata
# ---------------------------------------------------------------------------
_FAKE_MODEL_CFG = {"MODEL": "gpt-4o-mini", "PROVIDER": "openai"}


def _model_handler():
    cli = MagicMock()
    cli.console = MagicMock()
    cli._client = MagicMock()
    return cli, CmdHandler(cli)


class TestHandleModel:
    """/model shows and switches the session model."""

    def test_model_is_registered(self, cmd_handler):
        assert CMD_MODEL in cmd_handler.commands
        assert CMD_MODEL in {command for command, _ in command_completions()}

    def test_show_current_model_and_provider(self):
        cli, handler = _model_handler()
        with patch("yaicli.cmd_handler.cfg", dict(_FAKE_MODEL_CFG)):
            assert handler.handle_command(CMD_MODEL) is True

        printed = _printed_text(cli.console)
        assert "gpt-4o-mini" in printed
        assert "openai" in printed

    def test_switch_model_updates_config_and_invalidates_client(self):
        cli, handler = _model_handler()
        old_client = cli._client
        with patch("yaicli.cmd_handler.cfg", dict(_FAKE_MODEL_CFG)) as fake_cfg:
            assert handler.handle_command(f"{CMD_MODEL} gpt-4o") is True
            assert fake_cfg["MODEL"] == "gpt-4o"

        assert cli._client is None
        assert cli._client is not old_client
        printed = _printed_text(cli.console)
        assert "Model switched: gpt-4o-mini -> gpt-4o" in printed
        # The notice says how to revert.
        assert "Revert with /model gpt-4o-mini" in printed

    def test_switch_to_same_model_is_a_noop(self):
        cli, handler = _model_handler()
        with patch("yaicli.cmd_handler.cfg", dict(_FAKE_MODEL_CFG)):
            handler.handle_command(f"{CMD_MODEL} gpt-4o-mini")

        assert cli._client is cli._client  # untouched client slot
        assert "Already using model" in _printed_text(cli.console)

    def test_switch_without_writable_config_prints_error(self):
        cli, handler = _model_handler()
        # A mapping without __setitem__ models a read-only config object.
        with patch("yaicli.cmd_handler.cfg", MappingProxyType(dict(_FAKE_MODEL_CFG))):
            assert handler.handle_command(f"{CMD_MODEL} other-model") is True

        assert "Could not update the session model" in _printed_text(cli.console)


class TestHandleRole:
    """/role lists/switches the assistant role."""

    @staticmethod
    def _role_handler():
        cli = MagicMock()
        cli.console = MagicMock()
        cli.role_name = "DEFAULT"
        cli.init_role = "DEFAULT"
        cli.current_mode = CHAT_MODE
        cli.role_manager = MagicMock()
        cli.role_manager.list_roles.return_value = [
            {"id": "DEFAULT", "name": "DEFAULT"},
            {"id": "Code Assistant", "name": "Code Assistant"},
            {"id": "SQL Expert", "name": "SQL Expert"},
        ]
        return cli, CmdHandler(cli)

    def test_role_is_registered(self, cmd_handler):
        assert CMD_ROLE in cmd_handler.commands
        assert CMD_ROLE in {command for command, _ in command_completions()}

    def test_show_current_role_and_available(self):
        cli, handler = self._role_handler()
        assert handler.handle_command(CMD_ROLE) is True

        printed = _printed_text(cli.console)
        assert "Role: DEFAULT" in printed
        assert "SQL Expert" in printed

    def test_switch_role_case_insensitively(self):
        cli, handler = self._role_handler()
        assert handler.handle_command(f"{CMD_ROLE} sql expert") is True

        cli.set_role.assert_called_once_with("SQL Expert")
        assert cli.init_role == "SQL Expert"
        printed = _printed_text(cli.console)
        assert "Role switched: DEFAULT -> SQL Expert" in printed
        assert "Revert with /role DEFAULT" in printed

    def test_unknown_role_lists_available_and_does_not_switch(self):
        cli, handler = self._role_handler()
        assert handler.handle_command(f"{CMD_ROLE} nope") is True

        cli.set_role.assert_not_called()
        printed = _printed_text(cli.console)
        assert "Unknown role: nope" in printed
        assert "Available roles:" in printed
        assert "Code Assistant" in printed

    def test_switching_to_non_shell_role_returns_to_chat_mode(self):
        cli, handler = self._role_handler()
        cli.current_mode = EXEC_MODE
        handler.handle_command(f"{CMD_ROLE} SQL Expert")
        assert cli.current_mode == CHAT_MODE


class TestHandleRetry:
    """/retry replays the last user turn from its snapshot."""

    def test_retry_is_registered(self, cmd_handler):
        assert CMD_RETRY in cmd_handler.commands
        assert CMD_RETRY in {command for command, _ in command_completions()}

    def test_retry_delegates_to_cli(self):
        cli = MagicMock()
        cli.console = MagicMock()
        handler = CmdHandler(cli)

        assert handler.handle_command(CMD_RETRY) is True
        cli._retry_last_turn.assert_called_once()

    def test_retry_without_snapshot_support_is_friendly(self):
        cli = MagicMock(spec=["console"])
        cli.console = MagicMock()
        handler = CmdHandler(cli)

        assert handler.handle_retry() is True
        assert "Nothing to retry" in _printed_text(cli.console)

    def test_retry_failure_does_not_escape(self):
        cli = MagicMock()
        cli.console = MagicMock()
        cli._retry_last_turn.side_effect = RuntimeError("boom")
        handler = CmdHandler(cli)

        assert handler.handle_retry() is True
        assert "Retry failed: boom" in _printed_text(cli.console)


class TestCommandMetadata:
    """The help table and the completion menu share one metadata source."""

    def test_every_metadata_entry_is_registered(self, cmd_handler):
        for info in COMMAND_INFO:
            assert info.command in cmd_handler.commands, info.command
            for alias in info.aliases:
                assert alias in cmd_handler.commands, alias

    def test_registered_slash_commands_are_all_offered_by_completion(self, cmd_handler):
        registered = {command for command in cmd_handler.commands if command.startswith("/")}
        offered = {command for command, _ in command_completions()}
        assert offered == registered

    def test_cost_is_registered_and_offered(self, cmd_handler):
        assert "/cost" in cmd_handler.commands
        assert "/cost" in {command for command, _ in command_completions()}


class TestHistoryCommandsRefreshPromptState:
    """History-mutating commands refresh the cached prompt context %."""

    def test_compact_refreshes_percent_and_drops_retry_snapshot(self):
        from yaicli.schemas import ChatMessage

        cli = MagicMock()
        cli.console = MagicMock()
        cli.current_mode = CHAT_MODE
        history = []
        for index in range(3):
            history += [
                ChatMessage(role="user", content=f"question {index}"),
                ChatMessage(role="assistant", content=f"answer {index}"),
            ]
        cli.chat.history = history
        cli._last_turn_snapshot = {"input": "old", "images": [], "history": []}
        handler = CmdHandler(cli)

        assert handler.handle_command(f"{CMD_COMPACT} 1") is True

        cli._update_context_percent.assert_called_once()
        assert cli._last_turn_snapshot is None
