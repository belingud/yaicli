"""Regression tests for P0-S4: untrusted text must never be parsed as Rich markup.

Covers the confirmation/command panels, chat titles, /his output, `/list` output,
tool announce/output rendering, control-character stripping, and the REPL
per-turn exception guard.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import typer
from rich.console import Console
from rich.text import Text

import yaicli.chat as chat_module
import yaicli.tools as tools_module
from yaicli.chat import Chat, FileChatManager
from yaicli.cli import CLI
from yaicli.cmd_handler import CmdHandler
from yaicli.console import escape_markup, safe_text, strip_control_chars, untrusted_text
from yaicli.printer import Printer
from yaicli.role import RoleManager
from yaicli.schemas import ChatMessage, ToolCall
from yaicli.tools import execute_tool_call


def make_recording_console() -> Console:
    return Console(record=True, force_terminal=False, width=100, color_system=None)


def rendered(console: Console) -> str:
    return console.export_text(styles=False)


def make_cli(console: Console) -> CLI:
    cli = CLI.__new__(CLI)
    cli.console = console
    cli.chat = Chat(title="", history=[])
    cli.is_temp_session = True
    cli.current_mode = "chat"
    cli.verbose = False
    cli.printer = Printer(console=console)
    cli.cmd_handler = CmdHandler(cli)
    return cli


class TestConsoleHelpers:
    def test_strip_control_chars_keeps_newline_and_tab(self):
        assert strip_control_chars("a\x1b[31mb\x07c\td\ne") == "a[31mbc\td\ne"
        assert strip_control_chars(None) == ""

    def test_escape_markup(self):
        assert escape_markup("[/]") == "\\[/]"
        assert escape_markup(None) == ""
        assert safe_text("[green]x[/green]") == "\\[green]x\\[/green]"

    def test_untrusted_text_is_literal(self):
        text = untrusted_text("[bold]rm -rf ~[/bold]", style="red")
        assert isinstance(text, Text)
        assert text.plain == "[bold]rm -rf ~[/bold]"


class TestConfirmationPanels:
    def test_confirm_tool_call_with_malformed_markup_does_not_raise(self):
        console = make_recording_console()
        printer = Printer(console=console)
        tool_call = ToolCall(id="c1", name="run", arguments='{"cmd": "rm -rf ~ # [/]"}')

        with patch("yaicli.printer.Prompt.ask", return_value="n"):
            decision = printer._confirm_tool_call(tool_call)

        assert decision.value == "deny"
        out = rendered(console)
        # Both the tool name and the raw (bracketed) arguments are shown literally.
        assert "run(" in out
        assert "[/]" in out
        assert "rm -rf ~" in out

    def test_confirm_tool_call_markup_style_is_not_interpreted(self):
        console = make_recording_console()
        printer = Printer(console=console)
        tool_call = ToolCall(id="c1", name="run", arguments='{"cmd": "echo [green]safe[/green]"}')

        with patch("yaicli.printer.Prompt.ask", return_value="n"):
            printer._confirm_tool_call(tool_call)

        out = rendered(console)
        assert "[green]safe[/green]" in out
        assert "\x1b[32m" not in out  # no green style emitted for the literal tags

    def test_confirm_and_execute_with_bracketed_command(self):
        console = make_recording_console()
        cli = make_cli(console)
        with (
            patch("yaicli.cli.Prompt.ask", return_value="n"),
            patch("yaicli.cli.subprocess.call") as mock_call,
        ):
            cli._confirm_and_execute("echo [/INST]")

        mock_call.assert_not_called()
        out = rendered(console)
        assert "echo [/INST]" in out

    def test_suggested_command_control_chars_stripped(self):
        console = make_recording_console()
        cli = make_cli(console)
        with patch("yaicli.cli.Prompt.ask", return_value="n"):
            cli._confirm_and_execute("echo hi\x1b[31m; echo [/]")
        out = rendered(console)
        assert "\x1b" not in out
        assert "[/]" in out


class TestChatTitlesAndHistory:
    def test_list_chats_with_bracketed_title(self):
        console = make_recording_console()
        cli = make_cli(console)
        cli.chat_manager = MagicMock()
        cli.chat_manager.list_chats.return_value = [
            Chat(idx="1", title="Fix [/etc/hosts]", date="2024-01-01T00:00:00")
        ]
        cli._list_chats()
        out = rendered(console)
        assert "[/etc/hosts]" in out

    def test_welcome_persistent_session_bracketed_title(self):
        console = make_recording_console()
        cli = make_cli(console)
        cli.is_temp_session = False
        cli.chat = Chat(title="Fix [/etc/hosts]")
        with patch.object(CLI, "print_help"):
            cli._print_welcome_message()
        out = rendered(console)
        assert "Fix [/etc/hosts]" in out

    def test_history_with_bracketed_user_and_tool_content(self):
        console = make_recording_console()
        cli = make_cli(console)
        cli.chat = Chat(
            title="t",
            history=[
                ChatMessage(role="user", content="see [/b] and [/INST]"),
                ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="1", name="f", arguments='{"x": "[/]"}')],
                ),
            ],
        )
        cli.cmd_handler.handle_history()
        out = rendered(console)
        assert "[/b]" in out
        assert "[/INST]" in out
        assert "[/]" in out

    def test_print_list_option_bracketed_title(self):
        console = make_recording_console()
        chat = Chat(idx="1", title="A [/] B", date="2024-01-01T00:00:00")
        with (
            patch.object(chat_module, "console", console),
            patch.object(FileChatManager, "list_chats", return_value=[chat]),
        ):
            with pytest.raises(typer.Exit):
                FileChatManager.print_list_option(True)
        out = rendered(console)
        assert "A [/] B" in out

    def test_print_chats_bracketed_title(self, tmp_path):
        console = make_recording_console()
        manager = FileChatManager(chat_dir=tmp_path)
        chat = Chat(idx="1", title="A [/] B", date="2024-01-01T00:00:00")
        with (
            patch.object(chat_module, "console", console),
            patch.object(FileChatManager, "list_chats", return_value=[chat]),
        ):
            manager.print_chats()
        out = rendered(console)
        assert "A [/] B" in out


class TestToolCallRendering:
    def test_announce_with_bracketed_arguments(self, monkeypatch):
        console = make_recording_console()
        monkeypatch.setattr(tools_module, "console", console)
        tool_call = ToolCall(id="1", name="run", arguments='{"cmd": "echo [/]"}')
        with patch.object(tools_module, "get_function", side_effect=ValueError("nope")):
            result, ok = execute_tool_call(tool_call)
        assert ok is False
        out = rendered(console)
        assert "@Function call: run(" in out
        assert "[/]" in out

    def test_tool_output_panel_strips_control_chars(self, monkeypatch):
        console = make_recording_console()
        monkeypatch.setattr(tools_module, "console", console)
        monkeypatch.setitem(tools_module.cfg, "SHOW_FUNCTION_OUTPUT", True)
        tool = MagicMock()
        tool.execute.return_value = "output [/]\x1b[31mred"
        tool_call = ToolCall(id="1", name="get_weather", arguments='{"city": "NYC"}')
        with patch.object(tools_module, "get_function", return_value=tool):
            result, ok = execute_tool_call(tool_call)
        assert ok is True
        assert result == "output [/]\x1b[31mred"  # raw result still goes to the model
        out = rendered(console)
        assert "output [/]" in out
        assert "\x1b" not in out


class TestReplExceptionGuard:
    def _cli(self) -> CLI:
        cli = make_cli(MagicMock())
        session = MagicMock()
        cli.session = session
        return cli

    def test_special_command_exception_keeps_repl_alive(self):
        cli = self._cli()
        cli.session.prompt.side_effect = ["hello", EOFError()]
        with (
            patch.object(CLI, "prepare_chat_loop"),
            patch.object(CLI, "_print_welcome_message"),
            patch.object(CLI, "_handle_special_commands", side_effect=RuntimeError("boom")),
        ):
            cli._run_repl()  # must not raise

        printed = [str(c.args[0]) for c in cli.console.print.call_args_list if c.args]
        assert any("Error: boom" in text for text in printed)

    def test_process_input_exception_keeps_repl_alive(self):
        cli = self._cli()
        cli.session.prompt.side_effect = ["hello", EOFError()]
        with (
            patch.object(CLI, "prepare_chat_loop"),
            patch.object(CLI, "_print_welcome_message"),
            patch.object(CLI, "_handle_special_commands", return_value="hello"),
            patch.object(CLI, "_process_user_input", side_effect=RuntimeError("boom")),
        ):
            cli._run_repl()  # must not raise

        printed = [str(c.args[0]) for c in cli.console.print.call_args_list if c.args]
        assert any("Error: boom" in text for text in printed)

    def test_keyboard_interrupt_during_turn_keeps_repl_alive(self):
        cli = self._cli()
        cli.session.prompt.side_effect = ["hello", EOFError()]
        with (
            patch.object(CLI, "prepare_chat_loop"),
            patch.object(CLI, "_print_welcome_message"),
            patch.object(CLI, "_handle_special_commands", return_value="hello"),
            patch.object(CLI, "_process_user_input", side_effect=KeyboardInterrupt),
        ):
            cli._run_repl()  # must not raise

        printed = [str(c.args[0]) for c in cli.console.print.call_args_list if c.args]
        assert any("KeyboardInterrupt" in text for text in printed)

    def test_eof_during_turn_exits_repl(self):
        cli = self._cli()
        cli.session.prompt.side_effect = ["hello", EOFError()]
        with (
            patch.object(CLI, "prepare_chat_loop"),
            patch.object(CLI, "_print_welcome_message"),
            patch.object(CLI, "_handle_special_commands", return_value="hello"),
            patch.object(CLI, "_process_user_input", side_effect=EOFError),
        ):
            cli._run_repl()  # must not raise

        printed = [str(c.args[0]) for c in cli.console.print.call_args_list if c.args]
        assert not any(text.startswith("Error:") for text in printed)


class TestRoleCommandMarkup:
    """Role names/prompts are user-controlled: role command output must stay literal."""

    def _patch_manager(self, monkeypatch, manager, console):
        monkeypatch.setattr("yaicli.role.RoleManager", lambda: manager)
        monkeypatch.setattr(RoleManager, "console", console)

    def test_show_role_option_escapes_name_and_prompt(self, monkeypatch):
        console = make_recording_console()
        role = MagicMock()
        role.name = "[green]evil[/green]"
        role.prompt = "Reply with [/] and [/INST] literally"
        manager = MagicMock()
        manager.get_role.return_value = role
        self._patch_manager(monkeypatch, manager, console)

        with pytest.raises(typer.Exit):
            RoleManager.show_role_option("bad[/]")

        out = rendered(console)
        assert "[green]evil[/green]" in out
        assert "Reply with [/] and [/INST] literally" in out

    def test_create_role_option_escapes_created_name(self, monkeypatch):
        console = make_recording_console()
        role = MagicMock()
        role.name = "New[/]Role"
        manager = MagicMock()
        manager.roles = {}
        manager.create_role.return_value = role
        self._patch_manager(monkeypatch, manager, console)
        monkeypatch.setattr("typer.prompt", lambda *a, **k: "prompt text")

        with pytest.raises(typer.Exit):
            RoleManager.create_role_option("[green]new[/green]")

        out = rendered(console)
        assert "Created role: New[/]Role" in out

    def test_delete_role_option_escapes_name(self, monkeypatch):
        console = make_recording_console()
        manager = MagicMock()
        manager.roles = {"weird[/]": MagicMock()}
        manager.delete_role.return_value = True
        self._patch_manager(monkeypatch, manager, console)

        with pytest.raises(typer.Exit):
            RoleManager.delete_role_option("weird[/]")

        out = rendered(console)
        assert "Deleted role: weird[/]" in out

    def test_check_id_ok_escapes_missing_role(self, monkeypatch):
        console = make_recording_console()
        manager = MagicMock()
        manager.roles = {}
        self._patch_manager(monkeypatch, manager, console)

        assert RoleManager.check_id_ok("bad[/]") == "DEFAULT"
        out = rendered(console)
        assert "Role 'bad[/]' does not exist" in out

    def test_print_list_option_renders_bracketed_filenames_literally(self, monkeypatch):
        console = make_recording_console()
        role_file = MagicMock()
        role_file.stem = "Bad[/]Role"
        role_file.stat.return_value.st_mtime = 0
        roles_dir = MagicMock()
        roles_dir.glob.return_value = [role_file]
        monkeypatch.setattr(RoleManager, "roles_dir", roles_dir)
        monkeypatch.setattr(RoleManager, "console", console)

        with pytest.raises(typer.Exit):
            RoleManager.print_list_option(True)

        out = rendered(console)
        assert "Bad[/]Role" in out

    def test_load_user_roles_error_escapes_filename(self, monkeypatch, tmp_path):
        console = make_recording_console()
        real_file = tmp_path / "safe.json"
        real_file.write_text("{}", encoding="utf-8")

        class _FakeRoleFile:
            """Reports a bracketed display name while opening a real, readable file."""

            def __str__(self) -> str:
                return "Bad[/]File.json"

            def __fspath__(self) -> str:
                return str(real_file)

        roles_dir = MagicMock()
        roles_dir.exists.return_value = True
        roles_dir.glob.return_value = [_FakeRoleFile()]

        def _boom(_file):
            raise json.JSONDecodeError("bad json", "{}", 1)

        monkeypatch.setattr("yaicli.role.json.load", _boom)

        # A corrupt role file is reported without crashing on the bracketed filename.
        RoleManager(roles_dir=roles_dir, console=console)

        out = rendered(console)
        assert "Bad[/]File.json" in out
