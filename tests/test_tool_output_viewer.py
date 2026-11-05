"""Tests for the full-screen Ctrl+O tool-output viewer."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from rich.panel import Panel

from yaicli.tool_output_viewer import (
    ToolOutputViewerRequested,
    _body_text,
    _entry_header,
    _left_fragments,
    _load_full_text,
    build_viewer_app,
    open_tool_output_viewer,
)
from yaicli.tools import output_history
from yaicli.tools.output_history import ToolOutputEntry


@pytest.fixture(autouse=True)
def _reset_history():
    output_history.reset()
    yield
    output_history.reset()


def entry(index=1, turn=1, name="execute_shell_command", text="result text", **kwargs):
    return ToolOutputEntry(
        index=index,
        turn=turn,
        kind=kwargs.pop("kind", "function"),
        name=name,
        arguments=kwargs.pop("arguments", '{"command": "pytest -q"}'),
        text=text,
        total_chars=kwargs.pop("total_chars", len(text)),
        spill_path=kwargs.pop("spill_path", None),
        truncated=kwargs.pop("truncated", False),
        caption=kwargs.pop("caption", ""),
    )


class TestHelpers:
    def test_entry_header(self):
        header = _entry_header(entry(total_chars=12_345, truncated=True), 2, 4)
        assert header.startswith("[2/4] execute_shell_command")
        assert "function" in header
        assert "12,345 chars" in header
        assert "truncated" in header

    def test_entry_header_mcp(self):
        header = _entry_header(entry(kind="mcp", name="_mcp__clock"), 1, 1)
        assert "_mcp__clock" in header
        assert "MCP" in header

    def test_body_text_contains_call_arguments_result_and_spill(self):
        body = _body_text(entry(text="hello", spill_path="/tmp/spill.txt"))
        assert "@ Function call: execute_shell_command" in body
        assert 'arguments: {"command": "pytest -q"}' in body
        assert "hello" in body
        assert "/tmp/spill.txt" in body

    def test_body_text_full_mode(self):
        body = _body_text(entry(text="model text"), full_text="FULL SPILLED TEXT")
        assert "FULL SPILLED TEXT" in body
        assert "model text" not in body
        assert "full spilled output" in body

    def test_left_fragments_marks_selection(self):
        entries = [entry(index=1, name="a"), entry(index=2, name="b")]
        fragments = _left_fragments(entries, 1)
        rendered = "".join(text for _, text in fragments)
        assert "1. a" in rendered and "2. b" in rendered
        selected = [text for style, text in fragments if style == "class:selected"]
        assert any("2. b" in text for text in selected)
        assert not any("1. a" in text for text in selected)

    def test_left_fragments_show_caption_and_size(self):
        entries = [
            entry(index=1, name="execute_shell_command", caption="pytest -q", total_chars=314),
        ]
        rendered = "".join(text for _, text in _left_fragments(entries, 0))
        assert "execute_shell_command" in rendered
        assert "(314c)" in rendered
        assert "pytest -q" in rendered

    def test_left_fragments_show_full_tool_names_for_mixed_turns(self):
        """The list must identify the executed tool; no abbreviated aliases."""
        entries = [
            entry(index=1, name="execute_shell_command", caption="ls"),
            entry(index=2, name="fs_read_file", caption="/tmp/a.py"),
            entry(index=3, name="fetch_webpage", caption="https://example.com"),
        ]
        rendered = "".join(text for _, text in _left_fragments(entries, 0))
        assert "execute_shell_command" in rendered
        assert "fs_read_file" in rendered
        assert "fetch_webpage" in rendered

    def test_left_fragments_mark_truncated_entries(self):
        entries = [entry(index=1, name="execute_shell_command", caption="pytest -q", truncated=True)]
        rendered = "".join(text for _, text in _left_fragments(entries, 0))
        assert "pytest -q · truncated" in rendered

    def test_left_fragments_fall_back_to_arguments(self):
        entries = [entry(index=1, name="fs_read_file", arguments='{"path": "/tmp/a.log"}')]
        rendered = "".join(text for _, text in _left_fragments(entries, 0))
        assert "/tmp/a.log" in rendered

    def test_left_fragments_window_keeps_selection_visible(self):
        entries = [entry(index=i, name="tool") for i in range(1, 21)]
        rendered = "".join(text for _, text in _left_fragments(entries, 15))
        assert "16. tool" in rendered
        assert "11. tool" in rendered
        assert "10. tool" not in rendered
        assert "more above" in rendered
        assert "more below" not in rendered

    def test_left_fragments_window_marks_hidden_below(self):
        entries = [entry(index=i, name="tool") for i in range(1, 21)]
        rendered = "".join(text for _, text in _left_fragments(entries, 2))
        assert "3. tool" in rendered
        assert "more below" in rendered
        assert "more above" not in rendered

    def test_load_full_text_reads_spill(self, tmp_path):
        spill = tmp_path / "out.txt"
        spill.write_text("full content", encoding="utf-8")
        assert _load_full_text(entry(spill_path=str(spill))) == "full content"

    def test_load_full_text_missing_file(self):
        assert _load_full_text(entry(spill_path="/nonexistent/out.txt")) is None
        assert _load_full_text(entry()) is None

    def test_load_full_text_is_capped(self, tmp_path):
        spill = tmp_path / "big.txt"
        spill.write_text("A" * 100, encoding="utf-8")
        with patch("yaicli.tool_output_viewer.MAX_FULL_TEXT_CHARS", 20):
            loaded = _load_full_text(entry(spill_path=str(spill)))
        assert loaded is not None
        assert loaded.startswith("A" * 20)
        assert "viewer capped at 20 chars" in loaded


class TestBuildViewerApp:
    def _run_app(self, entries, keys=b"q", timeout=10.0):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        with create_pipe_input() as pipe:
            app = build_viewer_app(entries, "this turn", input=pipe, output=DummyOutput())
            result = {}

            def run():
                result["done"] = app.run()

            thread = threading.Thread(target=run)
            thread.start()
            time.sleep(0.3)
            pipe.send_bytes(keys)
            thread.join(timeout)
            assert thread.is_alive() is False, "viewer did not exit"
            return result["done"]

    def test_closes_on_q(self):
        self._run_app([entry()], keys=b"q")

    def test_closes_on_ctrl_o(self):
        self._run_app([entry()], keys=b"\x0f")

    def test_closes_on_escape(self):
        self._run_app([entry()], keys=b"\x1b")

    def test_navigation_and_full_toggle_do_not_crash(self, tmp_path):
        spill = tmp_path / "out.txt"
        spill.write_text("full content", encoding="utf-8")
        entries = [
            entry(index=1, name="a", text="first"),
            entry(index=2, name="b", text="second", spill_path=str(spill), truncated=True, total_chars=10_000),
        ]
        # down, tab (focus body), page down, home, end, f (full toggle), f (back), q
        self._run_app(entries, keys=b"\x1b[B\t\x1b[6~\x1b[H\x1b[Fffq")


class TestOpenViewer:
    def test_empty_history_prints_notice(self):
        console = MagicMock()
        open_tool_output_viewer(console)
        console.print.assert_called_once()
        assert "No tool output" in str(console.print.call_args.args[0])

    def test_non_tty_falls_back_to_inline_panel(self):
        output_history.begin_turn()
        output_history.record_output(
            kind="function", name="tool", arguments="{}", text="payload", total_chars=7
        )
        console = MagicMock()
        with patch("yaicli.tool_output_viewer._is_tty", return_value=False):
            open_tool_output_viewer(console)
        printed = [c.args[0] for c in console.print.call_args_list if c.args]
        assert any(isinstance(item, Panel) for item in printed)

    def test_build_failure_falls_back_to_inline_panel(self):
        output_history.begin_turn()
        output_history.record_output(
            kind="function", name="tool", arguments="{}", text="payload", total_chars=7
        )
        console = MagicMock()
        with (
            patch("yaicli.tool_output_viewer._is_tty", return_value=True),
            patch("yaicli.tool_output_viewer.build_viewer_app", side_effect=RuntimeError("terminal broken")),
        ):
            open_tool_output_viewer(console)
        printed = [c.args[0] for c in console.print.call_args_list if c.args]
        assert any("Could not open the tool-output viewer" in str(item) for item in printed)
        assert any(isinstance(item, Panel) for item in printed)

    def test_opens_with_current_turn_entries(self):
        output_history.begin_turn()
        output_history.record_output(kind="function", name="tool-a", arguments="{}", text="a", total_chars=1)
        output_history.record_output(kind="function", name="tool-b", arguments="{}", text="b", total_chars=1)
        console = MagicMock()
        app = MagicMock()
        with (
            patch("yaicli.tool_output_viewer._is_tty", return_value=True),
            patch("yaicli.tool_output_viewer.build_viewer_app", return_value=app) as mock_build,
        ):
            open_tool_output_viewer(console)
        app.run.assert_called_once()
        entries, label = mock_build.call_args.args
        assert label == "this turn"
        assert [item.name for item in entries] == ["tool-a", "tool-b"]

    def test_requested_signal_is_exception(self):
        assert issubclass(ToolOutputViewerRequested, Exception)
