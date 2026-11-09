"""Tests for tool-schema narrowing (v0.22 K19: ENABLED_TOOLS / --tools).

The request payload is dominated by the builtin function schemas (~10 KB for the
12 defaults), so a run can restrict which tools are advertised with comma-separated
glob patterns. The selection must default to "everything", be applied to builtin and
MCP schemas alike, be cached per pattern set, and warn once about literal names that
match nothing.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from yaicli.config import cfg
from yaicli.entry import app
from yaicli.llms.client import LLMClient
from yaicli.llms.provider import Provider, ProviderFactory
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall
from yaicli.tools import (
    _warned_tool_patterns,
    enabled_tool_patterns,
    filter_schemas,
    get_anthropic_mcp_tools,
    get_anthropic_schemas,
    get_openai_mcp_tools,
    get_openai_schemas,
    parse_enabled_tools,
    tool_enabled,
    tool_name_matches,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_schema_state(monkeypatch):
    """Reset the module-level schema caches and the warned-pattern set per test."""
    import yaicli.tools as tools_mod

    monkeypatch.setattr(tools_mod, "_openai_schemas_cache", None)
    monkeypatch.setattr(tools_mod, "_anthropic_schemas_cache", None)
    monkeypatch.setattr(tools_mod, "_filtered_schemas_cache", {})
    monkeypatch.setattr(tools_mod, "_warned_tool_patterns", set())
    monkeypatch.setitem(cfg, "ENABLED_TOOLS", "")


class TestParseEnabledTools:
    def test_empty_values_mean_all_tools(self):
        assert parse_enabled_tools("") == ()
        assert parse_enabled_tools(None) == ()
        assert parse_enabled_tools("  ,  ") == ()

    def test_comma_and_space_separated(self):
        assert parse_enabled_tools("fs_read_file,web_search") == ("fs_read_file", "web_search")
        assert parse_enabled_tools(" fs_* , _mcp__github_* ") == ("fs_*", "_mcp__github_*")

    def test_duplicates_are_dropped_in_order(self):
        assert parse_enabled_tools("fs_*,fs_read_file,fs_*") == ("fs_*", "fs_read_file")

    def test_sequence_input(self):
        assert parse_enabled_tools(["fs_*", "web_search"]) == ("fs_*", "web_search")


class TestToolNameMatches:
    def test_builtin_exact_and_glob(self):
        assert tool_name_matches("fs_read_file", "fs_read_file")
        assert tool_name_matches("fs_read_file", "fs_*")
        assert not tool_name_matches("web_search", "fs_*")

    def test_mcp_names_match_with_and_without_prefix(self):
        assert tool_name_matches("_mcp__github_search", "_mcp__github_*")
        assert tool_name_matches("_mcp__github_search", "github_*")
        assert tool_name_matches("_mcp__github_search", "*github*")

    def test_empty_pattern_matches_everything(self):
        assert tool_name_matches("anything", "")


class TestToolEnabled:
    def test_empty_selection_enables_everything(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "")
        assert tool_enabled("fs_read_file")

    def test_explicit_patterns(self):
        assert tool_enabled("fs_read_file", ["fs_*"])
        assert not tool_enabled("web_search", ["fs_*"])
        assert tool_enabled("_mcp__github_search", ["github_*"])

    def test_config_is_read_when_patterns_are_none(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "fs_read_file")
        assert enabled_tool_patterns() == ("fs_read_file",)
        assert tool_enabled("fs_read_file")
        assert not tool_enabled("web_search")


class TestFilterSchemas:
    def test_filter_keeps_matching_entries(self):
        schemas = [
            {"type": "function", "function": {"name": "fs_read_file"}},
            {"type": "function", "function": {"name": "web_search"}},
        ]
        filtered = filter_schemas(schemas, ["fs_*"], name_getter=lambda item: item["function"]["name"])
        assert [entry["function"]["name"] for entry in filtered] == ["fs_read_file"]

    def test_empty_patterns_returns_a_copy(self):
        schemas = [{"name": "x"}]
        filtered = filter_schemas(schemas, [], name_getter=lambda item: item["name"])
        assert filtered == schemas
        assert filtered is not schemas


class TestNarrowedSchemas:
    def test_default_payload_is_unchanged(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "")
        schemas = get_openai_schemas()
        assert len(schemas) == 12

    def test_glob_narrows_the_offered_tools(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "fs_read_file,fs_list_directory")
        names = [schema["function"]["name"] for schema in get_openai_schemas()]
        # Order follows the loaded-function order (alphabetical), not pattern order.
        assert sorted(names) == ["fs_list_directory", "fs_read_file"]

    def test_anthropic_schemas_are_narrowed_too(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "web_search")
        names = [schema["name"] for schema in get_anthropic_schemas()]
        assert names == ["web_search"]

    def test_filtered_payload_is_much_smaller(self, monkeypatch):
        full_bytes = len(json.dumps(get_openai_schemas(), ensure_ascii=False).encode("utf-8"))
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "fs_read_file")
        small_bytes = len(json.dumps(get_openai_schemas(), ensure_ascii=False).encode("utf-8"))
        assert small_bytes < full_bytes // 3
        assert small_bytes > 0

    def test_cache_is_keyed_by_pattern_set(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "fs_read_file")
        first = get_openai_schemas()
        again = get_openai_schemas()
        assert first is again

        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "web_search")
        other = get_openai_schemas()
        assert other is not first
        assert [schema["function"]["name"] for schema in other] == ["web_search"]

    def test_unfiltered_cache_identity_is_preserved(self, monkeypatch):
        import yaicli.tools as tools_mod

        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "")
        first = get_openai_schemas()
        assert first is tools_mod._openai_schemas_cache
        assert get_openai_schemas() is first


class TestMcpSchemaFilter:
    def test_openai_mcp_tools_filtered(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "_mcp__github_*")
        manager = MagicMock()
        manager.to_openai_tools.return_value = [
            {"type": "function", "function": {"name": "_mcp__github_search"}},
            {"type": "function", "function": {"name": "_mcp__slack_post"}},
        ]
        with patch("yaicli.tools.get_mcp_manager", return_value=manager):
            tools = get_openai_mcp_tools()
        assert [entry["function"]["name"] for entry in tools] == ["_mcp__github_search"]

    def test_anthropic_mcp_tools_filtered(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "github_*")
        manager = MagicMock()
        manager.to_anthropic_tools.return_value = [
            {"name": "_mcp__github_search"},
            {"name": "_mcp__slack_post"},
        ]
        with patch("yaicli.tools.get_mcp_manager", return_value=manager):
            tools = get_anthropic_mcp_tools()
        assert [entry["name"] for entry in tools] == ["_mcp__github_search"]

    def test_no_selection_keeps_every_mcp_tool(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "")
        manager = MagicMock()
        manager.to_openai_tools.return_value = [
            {"type": "function", "function": {"name": "_mcp__a"}},
            {"type": "function", "function": {"name": "_mcp__b"}},
        ]
        with patch("yaicli.tools.get_mcp_manager", return_value=manager):
            tools = get_openai_mcp_tools()
        assert len(tools) == 2


class TestUnknownToolWarning:
    def test_unknown_literal_name_warns_once(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "fs_read_file,not_a_real_tool")
        error_console = MagicMock()
        with patch("yaicli.tools.get_error_console", return_value=error_console):
            get_openai_schemas()
            get_openai_schemas()
        assert error_console.print.call_count == 1
        message = str(error_console.print.call_args.args[0])
        assert "not_a_real_tool" in message
        assert "fs_read_file" not in message

    def test_glob_and_mcp_names_do_not_warn(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "fs_*,_mcp__whatever")
        error_console = MagicMock()
        with patch("yaicli.tools.get_error_console", return_value=error_console):
            get_openai_schemas()
        error_console.print.assert_not_called()
        assert _warned_tool_patterns == set()


class TestGateRejectsDisabledTools:
    """The request gate refuses calls to tools the run does not offer (K19)."""

    class _Provider(Provider):
        """Provider whose first round requests one tool, then answers."""

        def __init__(self, name: str = "fs_read_file"):
            self.name = name
            self.rounds = 0
            self.config = {"ENABLE_FUNCTIONS": True, "ENABLE_MCP": False}
            self.enable_function = True
            self.enable_mcp = False

        def completion(self, messages, stream=False, tool_policy=None):
            self.rounds += 1
            if self.rounds == 1:
                yield LLMResponse(
                    tool_calls=[ToolCall(id="call_1", name=self.name, arguments="{}")],
                    finish_reason="tool_calls",
                )
            else:
                yield LLMResponse(content="done", finish_reason="stop")

        def detect_tool_role(self):
            return "tool"

    @staticmethod
    def _config():
        return {
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            "MAX_TOOL_CALL_DEPTH": 4,
            "TOOL_CONFIRM": False,
            "MODEL": "gpt-4o",
            "PROVIDER": "openai",
            "TOOL_AUDIT": False,
        }

    def _run(self, provider, monkeypatch):
        client = LLMClient(provider_name="openai", config=self._config(), interactive=False)
        messages = [ChatMessage(role="user", content="list files")]
        list(client.completion_with_tools(messages, stream=False))
        return messages

    def test_disabled_tool_is_refused_in_band_and_not_executed(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "web_search")
        provider = self._Provider("fs_read_file")
        with (
            patch.object(ProviderFactory, "create_provider", return_value=provider),
            patch("yaicli.llms.client.execute_tool_call") as execute,
        ):
            messages = self._run(provider, monkeypatch)

        execute.assert_not_called()
        tool_results = [message for message in messages if getattr(message, "role", None) == "tool"]
        assert len(tool_results) == 1
        payload = json.loads(tool_results[0].content)
        assert payload["error"] == "tool_disabled"
        assert "ENABLED_TOOLS" in payload["reason"]
        assert tool_results[0].tool_call_id == "call_1"

    def test_offered_tool_still_executes(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "fs_read_file")
        provider = self._Provider("fs_read_file")
        with (
            patch.object(ProviderFactory, "create_provider", return_value=provider),
            patch("yaicli.llms.client.execute_tool_call", return_value=("ok", True)) as execute,
        ):
            messages = self._run(provider, monkeypatch)

        execute.assert_called_once()
        tool_results = [message for message in messages if getattr(message, "role", None) == "tool"]
        assert [message.content for message in tool_results] == ["ok"]

    def test_empty_selection_keeps_the_old_behaviour(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "")
        provider = self._Provider("fs_read_file")
        with (
            patch.object(ProviderFactory, "create_provider", return_value=provider),
            patch("yaicli.llms.client.execute_tool_call", return_value=("ok", True)) as execute,
        ):
            self._run(provider, monkeypatch)

        execute.assert_called_once()


class TestToolsFlag:
    def test_help_lists_the_flag(self, strip_ansi):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--tools" in strip_ansi(result.stdout)

    def test_flag_sets_the_config_selection(self, monkeypatch):
        monkeypatch.setattr("yaicli.cli.CLI", MagicMock())
        result = runner.invoke(app, ["--tools", "fs_*,web_search", "-p", "hi"])
        assert result.exit_code == 0
        assert cfg["ENABLED_TOOLS"] == "fs_*,web_search"

    def test_absent_flag_leaves_the_config_alone(self, monkeypatch):
        monkeypatch.setitem(cfg, "ENABLED_TOOLS", "")
        monkeypatch.setattr("yaicli.cli.CLI", MagicMock())
        result = runner.invoke(app, ["-p", "hi"])
        assert result.exit_code == 0
        assert cfg["ENABLED_TOOLS"] == ""
