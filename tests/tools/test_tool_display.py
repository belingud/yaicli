"""Tests for the compact terminal rendering of tool calls (v0.19.1).

The terminal preview is independent from the model-facing truncation: only the
first TOOL_DISPLAY_MAX_LINES / TOOL_DISPLAY_MAX_CHARS are rendered, the model
still receives the text capped by TOOL_OUTPUT_MAX_CHARS, and Ctrl+O (covered in
tests/test_tool_output_viewer.py) opens the full-screen viewer.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from rich.panel import Panel

from yaicli.const import DEFAULT_CONFIG_INI, DEFAULT_CONFIG_MAP
from yaicli.schemas import ToolCall
from yaicli.tools import execute_tool_call, get_last_tool_output, show_last_tool_output
from yaicli.tools import output_history
from yaicli.tools.limits import (
    build_preview_marker,
    make_display_preview,
    summarize_arguments,
    truncate_tool_output_meta,
)


@pytest.fixture(autouse=True)
def _reset_history():
    """Keep the process-wide tool-output history deterministic per test."""
    output_history.reset()
    yield
    output_history.reset()


def _tool_call(arguments: str = '{"city": "NYC"}', result: str = "result text"):
    output_history.begin_turn()
    tool = MagicMock()
    tool.execute.return_value = result
    console = MagicMock()
    tc = ToolCall(id="1", name="get_weather", arguments=arguments)
    patches = (
        patch("yaicli.tools.cfg", {"SHOW_FUNCTION_OUTPUT": True, "SHOW_MCP_OUTPUT": False}),
        patch("yaicli.tools.get_function", return_value=tool),
        patch("yaicli.tools.console", console),
    )
    for p in patches:
        p.start()
    try:
        result_text, ok = execute_tool_call(tc)
    finally:
        for p in patches:
            p.stop()
    return result_text, ok, console


class TestMakeDisplayPreview:
    def test_short_text_is_not_truncated(self):
        preview = make_display_preview("hello\nworld", max_lines=15, max_chars=4000)
        assert preview.truncated is False
        assert preview.text == "hello\nworld"
        assert preview.label == ""
        assert build_preview_marker(preview) == ""

    def test_head_only_lines(self):
        text = "\n".join(f"line {i}" for i in range(1, 41))
        preview = make_display_preview(text, max_lines=15, max_chars=100_000)
        assert preview.truncated is True
        assert preview.limit == "lines"
        assert preview.text.splitlines() == [f"line {i}" for i in range(1, 16)]
        assert "line 16" not in preview.text
        assert preview.total_lines == 40
        assert preview.omitted_lines == 25
        assert preview.label == "first 15 / 40 lines"
        assert build_preview_marker(preview) == "… +25 lines · Ctrl+O to expand"

    def test_char_cap_for_single_huge_line(self):
        preview = make_display_preview("x" * 10_000, max_lines=15, max_chars=100)
        assert preview.truncated is True
        assert preview.limit == "chars"
        assert len(preview.text) == 100
        assert preview.omitted_chars == 9_900
        assert preview.label == "first 100 / 10,000 chars"
        assert "9,900 chars" in build_preview_marker(preview)

    def test_zero_limits_disable_truncation(self):
        text = "\n".join(f"line {i}" for i in range(50))
        preview = make_display_preview(text, max_lines=0, max_chars=0)
        assert preview.truncated is False
        assert preview.text == text

    def test_trailing_newline_does_not_add_a_phantom_line(self):
        preview = make_display_preview("a\nb\n", max_lines=1, max_chars=1000)
        assert preview.total_lines == 2
        assert preview.text == "a"
        assert preview.omitted_lines == 1

    def test_empty_text(self):
        preview = make_display_preview("", max_lines=15, max_chars=4000)
        assert preview.truncated is False
        assert preview.text == ""
        assert preview.total_lines == 0

    def test_defaults_come_from_config(self):
        with patch(
            "yaicli.tools.limits.cfg",
            {"TOOL_DISPLAY_MAX_LINES": 2, "TOOL_DISPLAY_MAX_CHARS": 1000},
        ):
            preview = make_display_preview("\n".join(f"l{i}" for i in range(5)))
        assert preview.truncated is True
        assert preview.text.splitlines() == ["l0", "l1"]

    def test_config_value_zero_falls_back_to_unlimited(self):
        with patch("yaicli.tools.limits.cfg", {"TOOL_DISPLAY_MAX_LINES": 0, "TOOL_DISPLAY_MAX_CHARS": 0}):
            preview = make_display_preview("\n".join(f"l{i}" for i in range(30)))
        assert preview.truncated is False


class TestSummarizeArguments:
    def test_short_arguments_kept(self):
        assert summarize_arguments('{"command": "pytest -q"}') == '{"command": "pytest -q"}'

    def test_large_value_summarized(self):
        raw = json.dumps({"path": "/tmp/a.txt", "content": "A" * 2000})
        summary = summarize_arguments(raw)
        assert '"path": "/tmp/a.txt"' in summary
        assert "<2,000 chars>" in summary
        assert "A" * 100 not in summary
        assert len(summary) <= 300

    def test_multiline_value_summarized(self):
        raw = json.dumps({"command": "line one\nline two\n" + "x" * 500})
        summary = summarize_arguments(raw)
        assert summary.startswith('{"command": "line one…"')
        assert "<" in summary and "chars>" in summary

    def test_invalid_json_is_clipped(self):
        raw = "not json " * 100
        summary = summarize_arguments(raw)
        assert len(summary) <= 300
        assert summary.endswith("…")

    def test_zero_disables_preview(self):
        raw = '{"content": "' + "A" * 500 + '"}'
        assert summarize_arguments(raw, max_chars=0) == raw

    def test_many_fields_stay_under_limit(self):
        raw = json.dumps({f"k{i}": "v" * 50 for i in range(20)})
        summary = summarize_arguments(raw)
        assert len(summary) <= 300


class TestExecuteToolCallDisplay:
    def test_short_output_has_no_marker(self):
        _, ok, console = _tool_call(result="short result")
        assert ok is True
        panel = next(c.args[0] for c in console.print.call_args_list if isinstance(c.args[0], Panel))
        assert str(panel.title) == "Function output"
        assert "Ctrl+O to expand" not in str(panel.renderable)

    def test_long_output_is_head_only(self):
        result = "\n".join(f"line {i}" for i in range(1, 101))
        _, ok, console = _tool_call(result=result)
        assert ok is True
        panel = next(c.args[0] for c in console.print.call_args_list if isinstance(c.args[0], Panel))
        rendered = str(panel.renderable)
        assert "line 1\n" in rendered
        assert "line 16" not in rendered
        assert "Ctrl+O to expand" in rendered
        assert "first 15 / 100 lines" in str(panel.title)

    def test_model_still_receives_full_result(self):
        result = "\n".join(f"line {i}" for i in range(1, 101))
        model_result, ok, _ = _tool_call(result=result)
        assert ok is True
        assert model_result == result

    def test_call_line_arguments_are_summarized(self):
        raw = json.dumps({"path": "/tmp/out.txt", "content": "A" * 2000})
        _, ok, console = _tool_call(arguments=raw)
        assert ok is True
        call_line = next(str(c.args[0]) for c in console.print.call_args_list if c.args)
        assert call_line.startswith("@Function call: get_weather(")
        assert "<2,000 chars>" in call_line
        assert "A" * 100 not in call_line

    def test_result_is_recorded_in_history(self):
        result = "\n".join(f"line {i}" for i in range(1, 101))
        _tool_call(result=result)
        entries, label = output_history.viewer_outputs()
        assert label == "this turn"
        assert len(entries) == 1
        assert entries[0].name == "get_weather"
        assert entries[0].kind == "function"
        assert entries[0].text == result
        assert entries[0].total_chars == len(result)
        assert entries[0].truncated is False

    def test_unknown_tool_records_nothing(self):
        console = MagicMock()
        tc = ToolCall(id="1", name="nope", arguments="{}")
        with (
            patch("yaicli.tools.cfg", {"SHOW_FUNCTION_OUTPUT": True, "SHOW_MCP_OUTPUT": False}),
            patch("yaicli.tools.get_function", side_effect=ValueError("missing")),
            patch("yaicli.tools.console", console),
        ):
            _, ok = execute_tool_call(tc)
        assert ok is False
        assert get_last_tool_output() is None
        assert output_history.all_outputs() == []


class TestTruncationMetadata:
    def test_meta_returns_spill_path_and_original_size(self, tmp_path):
        original = "x" * 1000
        config = {"TOOL_OUTPUT_DIR": str(tmp_path), "TOOL_OUTPUT_MAX_CHARS": 32000}
        with patch("yaicli.tools.limits.cfg", config):
            meta = truncate_tool_output_meta(original, "execute_shell_command", max_chars=400)
        assert meta.truncated is True
        assert meta.total_chars == len(original)
        assert meta.spill_path is not None
        assert "truncated" in meta.text
        from pathlib import Path

        assert Path(meta.spill_path).read_text(encoding="utf-8") == original

    def test_meta_short_text_has_no_spill(self):
        meta = truncate_tool_output_meta("short", "execute_shell_command", max_chars=100)
        assert meta.truncated is False
        assert meta.text == "short"
        assert meta.total_chars == 5
        assert meta.spill_path is None


class TestShowLastToolOutput:
    def test_reports_when_nothing_ran(self):
        console = MagicMock()
        assert show_last_tool_output(console) is False
        console.print.assert_called_once()
        assert "No tool output" in str(console.print.call_args.args[0])

    def test_prints_panel_with_last_result(self):
        output_history.record_output(
            kind="function", name="get_weather", arguments='{"city": "NYC"}', text="full text", total_chars=9
        )
        console = MagicMock()
        assert show_last_tool_output(console) is True
        panel = console.print.call_args.args[0]
        assert isinstance(panel, Panel)
        assert "get_weather" in str(panel.title)
        assert "full text" in str(panel.renderable)


class TestConfigKeys:
    def test_template_and_env_keys(self):
        assert "TOOL_DISPLAY_MAX_LINES=" in DEFAULT_CONFIG_INI
        assert "TOOL_DISPLAY_MAX_CHARS=" in DEFAULT_CONFIG_INI
        assert "TOOL_CALL_PREVIEW_MAX_CHARS=" in DEFAULT_CONFIG_INI
        assert DEFAULT_CONFIG_MAP["TOOL_DISPLAY_MAX_LINES"]["env_key"] == "YAI_TOOL_DISPLAY_MAX_LINES"
        assert DEFAULT_CONFIG_MAP["TOOL_DISPLAY_MAX_CHARS"]["env_key"] == "YAI_TOOL_DISPLAY_MAX_CHARS"
        assert DEFAULT_CONFIG_MAP["TOOL_CALL_PREVIEW_MAX_CHARS"]["env_key"] == "YAI_TOOL_CALL_PREVIEW_MAX_CHARS"
        assert DEFAULT_CONFIG_MAP["TOOL_DISPLAY_MAX_LINES"]["value"] == 15
        assert DEFAULT_CONFIG_MAP["TOOL_DISPLAY_MAX_CHARS"]["value"] == 4000
        assert DEFAULT_CONFIG_MAP["TOOL_CALL_PREVIEW_MAX_CHARS"]["value"] == 300
