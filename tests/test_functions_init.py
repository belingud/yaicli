"""Tests for yaicli.functions package CLI callbacks (install/reinstall/print)."""

import json
from unittest.mock import MagicMock, patch

import pytest
import typer

from yaicli.functions import (
    install_functions,
    print_functions,
    print_mcp,
    reinstall_functions,
)


class TestInstallFunctions:
    """Tests for install_functions."""

    def test_install_copies_buildin(self, tmp_path):
        """install_functions copies builtin .py files into a fresh FUNCTIONS_DIR."""
        functions_dir = tmp_path / "funcs"
        console = MagicMock()
        with (
            patch("yaicli.functions.FUNCTIONS_DIR", functions_dir),
            patch("yaicli.functions.console", console),
        ):
            with pytest.raises(typer.Exit):
                install_functions(None, True)

        copied = list(functions_dir.glob("*.py"))
        assert copied
        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("Installing buildin functions" in t for t in printed)
        assert any("Installed" in t for t in printed)

    def test_install_skips_existing(self, tmp_path):
        """A second install skips files that already exist."""
        functions_dir = tmp_path / "funcs"
        console = MagicMock()
        with (
            patch("yaicli.functions.FUNCTIONS_DIR", functions_dir),
            patch("yaicli.functions.console", console),
        ):
            with pytest.raises(typer.Exit):
                install_functions(None, True)
            console.reset_mock()
            with pytest.raises(typer.Exit):
                install_functions(None, True)

        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("already exists, skipping" in t for t in printed)


class TestReinstallFunctions:
    """Tests for reinstall_functions."""

    def test_reinstall_into_empty_dir(self, tmp_path):
        """reinstall into an empty dir creates it and copies builtin files."""
        functions_dir = tmp_path / "funcs"
        console = MagicMock()
        with (
            patch("yaicli.functions.FUNCTIONS_DIR", functions_dir),
            patch("yaicli.functions.console", console),
        ):
            with pytest.raises(typer.Exit):
                reinstall_functions(None, True)

        assert list(functions_dir.glob("*.py"))
        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("Reinstalling builtin functions" in t for t in printed)
        assert any("Reinstalled" in t for t in printed)

    def test_reinstall_overwrites_existing(self, tmp_path):
        """reinstall removes and re-copies files that already exist."""
        functions_dir = tmp_path / "funcs"
        console = MagicMock()
        with (
            patch("yaicli.functions.FUNCTIONS_DIR", functions_dir),
            patch("yaicli.functions.console", console),
        ):
            with pytest.raises(typer.Exit):
                install_functions(None, True)
            console.reset_mock()
            with pytest.raises(typer.Exit):
                reinstall_functions(None, True)

        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("Reinstalled" in t for t in printed)


class TestPrintFunctions:
    """Tests for print_functions."""

    def test_no_functions_dir(self, tmp_path):
        """Reports when no functions directory exists."""
        functions_dir = tmp_path / "missing"
        console = MagicMock()
        with (
            patch("yaicli.functions.FUNCTIONS_DIR", functions_dir),
            patch("yaicli.functions.console", console),
        ):
            with pytest.raises(typer.Exit):
                print_functions(None, True)

        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("No installed functions found" in t for t in printed)

    def test_lists_functions_skips_underscore(self, tmp_path):
        """Lists .py files but skips those starting with underscore."""
        functions_dir = tmp_path / "funcs"
        functions_dir.mkdir()
        (functions_dir / "visible.py").write_text("x")
        (functions_dir / "_hidden.py").write_text("x")
        console = MagicMock()
        with (
            patch("yaicli.functions.FUNCTIONS_DIR", functions_dir),
            patch("yaicli.functions.console", console),
        ):
            with pytest.raises(typer.Exit):
                print_functions(None, True)

        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("visible.py" in t for t in printed)
        assert not any("_hidden.py" in t for t in printed)


class TestPrintMcp:
    """Tests for print_mcp."""

    def test_no_mcp_config(self, tmp_path):
        """Reports when no MCP config file exists."""
        mcp_path = tmp_path / "mcp.json"
        console = MagicMock()
        with (
            patch("yaicli.functions.MCP_JSON_PATH", mcp_path),
            patch("yaicli.functions.console", console),
        ):
            with pytest.raises(typer.Exit):
                print_mcp(None, True)

        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("No mcp config found" in t for t in printed)

    def test_prints_mcp_config(self, tmp_path):
        """Prints the MCP config JSON when the file exists."""
        mcp_path = tmp_path / "mcp.json"
        mcp_path.write_text(json.dumps({"servers": {"a": 1}}))
        console = MagicMock()
        with (
            patch("yaicli.functions.MCP_JSON_PATH", mcp_path),
            patch("yaicli.functions.console", console),
        ):
            with pytest.raises(typer.Exit):
                print_mcp(None, True)

        console.print_json.assert_called_once()
