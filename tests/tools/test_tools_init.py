"""Tests for yaicli.tools package: name parsing, lazy MCP imports, mcp tool schemas, and execute_tool_call."""

from unittest.mock import MagicMock, patch

import pytest
from rich.panel import Panel

from yaicli.exceptions import MCPToolsError
from yaicli.schemas import ToolCall
from yaicli.tools import (
    execute_tool_call,
    get_anthropic_mcp_tools,
    get_anthropic_schemas,
    get_mcp,
    get_mcp_manager,
    get_openai_mcp_tools,
    get_openai_schemas,
    parse_mcp_tool_name,
)

FAKE_CFG = {"SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False}


class TestParseMcpToolName:
    def test_strips_prefix(self):
        assert parse_mcp_tool_name("_mcp__clock") == "clock"

    def test_no_prefix_unchanged(self):
        assert parse_mcp_tool_name("plain") == "plain"


class TestLazyMcpImports:
    def test_get_mcp_manager_lazy(self):
        """get_mcp_manager lazily delegates to yaicli.tools.mcp.get_mcp_manager."""
        fake_mgr = MagicMock()
        with patch("yaicli.tools.mcp.get_mcp_manager", return_value=fake_mgr) as m:
            result = get_mcp_manager()
        assert result is fake_mgr
        m.assert_called_once()

    def test_get_mcp_lazy(self):
        """get_mcp lazily delegates to yaicli.tools.mcp.get_mcp."""
        fake_tool = MagicMock()
        with patch("yaicli.tools.mcp.get_mcp", return_value=fake_tool) as m:
            result = get_mcp("clock")
        assert result is fake_tool
        m.assert_called_once_with("clock")


class TestMcpToolSchemas:
    def test_openai_mcp_tools_success(self):
        mgr = MagicMock()
        mgr.to_openai_tools.return_value = [{"type": "function"}]
        with patch("yaicli.tools.get_mcp_manager", return_value=mgr):
            assert get_openai_mcp_tools() == [{"type": "function"}]

    def test_openai_mcp_tools_error_wrapped(self):
        with patch("yaicli.tools.get_mcp_manager", side_effect=RuntimeError("boom")):
            with pytest.raises(MCPToolsError, match="Error getting MCP tools"):
                get_openai_mcp_tools()

    def test_anthropic_mcp_tools_success(self):
        mgr = MagicMock()
        mgr.to_anthropic_tools.return_value = [{"name": "x"}]
        with patch("yaicli.tools.get_mcp_manager", return_value=mgr):
            assert get_anthropic_mcp_tools() == [{"name": "x"}]

    def test_anthropic_mcp_tools_error_wrapped(self):
        with patch("yaicli.tools.get_mcp_manager", side_effect=RuntimeError("boom")):
            with pytest.raises(MCPToolsError, match="Error getting MCP tools for Anthropic"):
                get_anthropic_mcp_tools()


class TestExecuteToolCall:
    def test_function_call_success(self):
        tool = MagicMock()
        tool.execute.return_value = "result text"
        console = MagicMock()
        tc = ToolCall(id="1", name="get_weather", arguments='{"city": "NYC"}')
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", console),
        ):
            result, ok = execute_tool_call(tc)

        assert ok is True
        assert result == "result text"
        tool.execute.assert_called_once_with(city="NYC")
        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("@Function call: get_weather" in t for t in printed)

    def test_function_call_show_output_panel(self):
        tool = MagicMock()
        tool.execute.return_value = "result text"
        console = MagicMock()
        tc = ToolCall(id="1", name="get_weather", arguments='{"city": "NYC"}')
        with (
            patch("yaicli.tools.cfg", {"SHOW_FUNCTION_OUTPUT": True, "SHOW_MCP_OUTPUT": False}),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", console),
        ):
            result, ok = execute_tool_call(tc)

        assert ok is True
        assert any(isinstance(c.args[0], Panel) for c in console.print.call_args_list)

    def test_mcp_call_success_strips_prefix(self):
        tool = MagicMock()
        tool.execute.return_value = "mcp result"
        console = MagicMock()
        tc = ToolCall(id="1", name="_mcp__clock", arguments="{}")
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_mcp", return_value=tool),
            patch("yaicli.tools.console", console),
        ):
            result, ok = execute_tool_call(tc)

        assert ok is True
        assert result == "mcp result"
        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any("@Mcp call: clock" in t for t in printed)

    def test_tool_not_found(self):
        console = MagicMock()
        tc = ToolCall(id="1", name="missing", arguments="{}")
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", side_effect=ValueError("nope")),
            patch("yaicli.tools.console", console),
        ):
            result, ok = execute_tool_call(tc)

        assert ok is False
        assert "not exists" in result

    def test_invalid_arguments_not_dict(self):
        tool = MagicMock()
        console = MagicMock()
        tc = ToolCall(id="1", name="fn", arguments='"just a string"')
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", console),
        ):
            result, ok = execute_tool_call(tc)

        assert ok is False
        assert "should be JSON object" in result
        tool.execute.assert_not_called()

    def test_arguments_parse_error(self):
        tool = MagicMock()
        console = MagicMock()
        tc = ToolCall(id="1", name="fn", arguments="{}")
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", console),
            patch("yaicli.tools.repair_json", side_effect=ValueError("bad")),
        ):
            result, ok = execute_tool_call(tc)

        assert ok is False
        assert "Invalid arguments from llm" in result

    def test_execute_raises(self):
        tool = MagicMock()
        tool.execute.side_effect = RuntimeError("exec failed")
        console = MagicMock()
        tc = ToolCall(id="1", name="fn", arguments='{"a": 1}')
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", console),
        ):
            result, ok = execute_tool_call(tc)

        assert ok is False
        assert "Call function error" in result

    def test_announce_false_suppresses_call_line(self):
        tool = MagicMock()
        tool.execute.return_value = "r"
        console = MagicMock()
        tc = ToolCall(id="1", name="fn", arguments="{}")
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", console),
        ):
            result, ok = execute_tool_call(tc, announce=False)

        assert ok is True
        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert not any("call:" in t for t in printed)


class TestSchemas:
    """Tests for get_openai_schemas / get_anthropic_schemas transform + cache."""

    def test_get_openai_schemas_builds_and_caches(self):
        func = MagicMock()
        func.func_cls.openai_schema = {"name": "fn", "parameters": {}}
        with (
            patch("yaicli.tools._openai_schemas_cache", None),
            patch("yaicli.tools.list_functions", return_value=[func]),
        ):
            schemas = get_openai_schemas()

        assert schemas == [{"type": "function", "function": {"name": "fn", "parameters": {}}}]

    def test_get_openai_schemas_returns_cache(self):
        cached = [{"type": "function", "function": {"name": "cached"}}]
        with patch("yaicli.tools._openai_schemas_cache", cached):
            assert get_openai_schemas() is cached

    def test_get_anthropic_schemas_builds(self):
        func = MagicMock()
        func.func_cls.anthropic_schema = {"name": "fn"}
        with (
            patch("yaicli.tools._anthropic_schemas_cache", None),
            patch("yaicli.tools.list_functions", return_value=[func]),
        ):
            schemas = get_anthropic_schemas()

        assert schemas == [{"name": "fn"}]

    def test_get_anthropic_schemas_returns_cache(self):
        cached = [{"name": "cached"}]
        with patch("yaicli.tools._anthropic_schemas_cache", cached):
            assert get_anthropic_schemas() is cached
