import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from rich.console import Console, Group

from yaicli.printer import Printer
from yaicli.schemas import ConfirmToolCall, LLMResponse, RefreshLive, ToolCall, ToolConfirmDecision


class TestPrinter(unittest.TestCase):
    def setUp(self):
        # Mock the console and config
        self.mock_console = MagicMock()
        self.mock_config = {"CODE_THEME": "monokai", "SHOW_REASONING": True}

        # Create the printer instance
        self.printer = Printer()

        # Replace the console and config with our mocks after initialization
        self.printer.console = self.mock_console
        self.printer.config = self.mock_config

        # Set the code theme and show reasoning to match our mock config
        self.printer.code_theme = "monokai"
        self.printer.show_reasoning = True

    def test_initialization(self):
        """Test proper initialization of the Printer class."""
        # Verify attributes were properly set during initialization
        self.assertEqual(self.printer.console, self.mock_console)
        self.assertEqual(self.printer.config, self.mock_config)
        self.assertEqual(self.printer.code_theme, "monokai")
        self.assertEqual(self.printer.show_reasoning, True)
        self.assertTrue(self.printer.content_markdown)
        self.assertFalse(self.printer.in_reasoning)

    def test_confirm_tool_call_maps_choices(self):
        """Each keypress maps to the matching ToolConfirmDecision."""
        tc = ToolCall(id="c1", name="get_weather", arguments="{}")
        cases = {
            "y": ToolConfirmDecision.ONCE,
            "a": ToolConfirmDecision.SESSION,
            "A": ToolConfirmDecision.PERSIST,
            "n": ToolConfirmDecision.DENY,
        }
        for key, expected in cases.items():
            with patch("yaicli.printer.Prompt.ask", return_value=key):
                self.assertEqual(self.printer._confirm_tool_call(tc), expected)

    def test_confirm_tool_call_keyboard_interrupt_denies(self):
        """Ctrl-C at the prompt is treated as deny, not propagated."""
        tc = ToolCall(id="c1", name="get_weather", arguments="{}")
        with patch("yaicli.printer.Prompt.ask", side_effect=KeyboardInterrupt):
            self.assertEqual(self.printer._confirm_tool_call(tc), ToolConfirmDecision.DENY)

    def test_confirm_tool_call_eof_denies(self):
        """EOF (no input stream) at the prompt is treated as deny."""
        tc = ToolCall(id="c1", name="get_weather", arguments="{}")
        with patch("yaicli.printer.Prompt.ask", side_effect=EOFError):
            self.assertEqual(self.printer._confirm_tool_call(tc), ToolConfirmDecision.DENY)

    def test_display_stream_streams_reasoning_once(self):
        """Reasoning is emitted append-only (header once, no per-frame re-render)."""
        buf = StringIO()
        console = Console(file=buf, force_terminal=False, width=80)
        printer = Printer(console=console)
        printer.show_reasoning = True

        def gen():
            yield LLMResponse(reasoning="line one\n")
            yield LLMResponse(reasoning="line two\n")
            yield LLMResponse(content="The answer")

        printer.display_stream(gen())
        out = buf.getvalue()
        # Header printed exactly once, both reasoning lines present, content rendered.
        self.assertEqual(out.count("Thinking:"), 1)
        self.assertIn("line one", out)
        self.assertIn("line two", out)
        self.assertIn("The answer", out)

    def test_reset_state(self):
        """Test _reset_state method properly resets printer state."""
        # Set in_reasoning to True first
        self.printer.in_reasoning = True

        # Reset the state
        self.printer._reset_state()

        # Verify state was reset
        self.assertFalse(self.printer.in_reasoning)

    def test_check_and_update_think_tags_opening(self):
        """Test _check_and_update_think_tags with opening tag."""
        content = "Hello <think>thinking content"
        reasoning = ""

        new_content, new_reasoning = self.printer._check_and_update_think_tags(content, reasoning)

        self.assertEqual(new_content, "Hello ")
        self.assertEqual(new_reasoning, "thinking content")
        self.assertTrue(self.printer.in_reasoning)

    def test_check_and_update_think_tags_closing(self):
        """Test _check_and_update_think_tags with closing tag."""
        content = "Hello "
        reasoning = "thinking content</think> additional content"

        # Set in_reasoning to True first
        self.printer.in_reasoning = True

        new_content, new_reasoning = self.printer._check_and_update_think_tags(content, reasoning)

        self.assertEqual(new_content, "Hello  additional content")
        self.assertEqual(new_reasoning, "thinking content")
        self.assertFalse(self.printer.in_reasoning)

    def test_check_and_update_think_tags_complete(self):
        """Test _check_and_update_think_tags with complete tags in content."""
        content = "Hello <think>thinking content</think> goodbye"
        reasoning = ""

        new_content, new_reasoning = self.printer._check_and_update_think_tags(content, reasoning)

        self.assertEqual(new_content, "Hello  goodbye")
        self.assertEqual(new_reasoning, "thinking content")
        self.assertFalse(self.printer.in_reasoning)

    def test_process_chunk_content_only(self):
        """Test _process_chunk with content only."""
        result_content, result_reasoning = self.printer._process_chunk(
            "new content", "", "existing content ", "existing reasoning"
        )

        self.assertEqual(result_content, "existing content new content")
        self.assertEqual(result_reasoning, "existing reasoning")

    def test_process_chunk_reasoning_only(self):
        """Test _process_chunk with reasoning only."""
        result_content, result_reasoning = self.printer._process_chunk(
            "", "new reasoning", "existing content", "existing reasoning "
        )

        self.assertEqual(result_content, "existing content")
        self.assertEqual(result_reasoning, "existing reasoning new reasoning")

    def test_process_chunk_with_think_tags(self):
        """Test _process_chunk with think tags in content."""
        result_content, result_reasoning = self.printer._process_chunk(
            "content <think>some thoughts", "", "previous ", ""
        )

        self.assertEqual(result_content, "previous content ")
        self.assertEqual(result_reasoning, "some thoughts")
        self.assertTrue(self.printer.in_reasoning)

    def test_format_display_text_content_only(self):
        """Test _format_display_text with only content."""
        result = self.printer._format_display_text("sample content", "")

        # The implementation returns a Group even for content-only, so we'll test that it contains the content
        self.assertIsInstance(result, Group)

        # Verify content formatter was called with correct parameters
        self.printer.content_formatter = MagicMock()
        self.printer._format_display_text("sample content", "")
        self.printer.content_formatter.assert_called_once_with("sample content", code_theme="monokai")

    def test_format_display_text_with_reasoning(self):
        """Test _format_display_text with content and reasoning."""
        # Mock formatters to return input for easy assertion
        self.printer.content_formatter = MagicMock(side_effect=lambda x, **kwargs: f"CONTENT:{x}")
        self.printer.reasoning_formatter = MagicMock(side_effect=lambda x, **kwargs: f"REASONING:{x}")

        result = self.printer._format_display_text("sample content", "sample reasoning")

        # Should be a Group with content and reasoning
        self.assertIsInstance(result, Group)

        # Verify both formatters were called
        self.printer.content_formatter.assert_called_once()
        self.printer.reasoning_formatter.assert_called_once()

    def test_process_chunk_in_reasoning_appends_content(self):
        """When in reasoning mode, chunk content is appended to reasoning, not content."""
        self.printer.in_reasoning = True
        content, reasoning = self.printer._process_chunk("more thinking", "", "", "existing ")
        self.assertEqual(content, "")
        self.assertEqual(reasoning, "existing more thinking")

    def test_format_display_text_empty_returns_empty_string(self):
        """No content and no reasoning yields an empty string."""
        result = self.printer._format_display_text("", "")
        self.assertEqual(result, "")

    def test_display_normal_real(self):
        """display_normal renders reasoning then content and returns accumulated text."""
        buf = StringIO()
        console = Console(file=buf, force_terminal=False, width=80)
        printer = Printer(console=console)
        printer.show_reasoning = True

        def gen():
            yield LLMResponse(reasoning="thinking process")
            yield LLMResponse(content="final answer")

        content, reasoning = printer.display_normal(gen())
        self.assertIn("final answer", content)
        self.assertIn("thinking process", reasoning)
        out = buf.getvalue()
        self.assertIn("Thinking:", out)
        self.assertIn("final answer", out)

    def test_display_normal_skips_non_llmresponse(self):
        """display_normal ignores non-LLMResponse items in the iterator."""
        buf = StringIO()
        console = Console(file=buf, force_terminal=False, width=80)
        printer = Printer(console=console)

        def gen():
            yield RefreshLive()
            yield LLMResponse(content="answer")

        content, _ = printer.display_normal(gen())
        self.assertIn("answer", content)

    def test_emit_reasoning_disabled(self):
        """_emit_reasoning returns immediately when reasoning display is off."""
        self.printer.show_reasoning = False
        printed_len, header = self.printer._emit_reasoning("some reasoning", 0, False, flush=True)
        self.assertEqual(printed_len, len("some reasoning"))
        self.assertFalse(header)

    def test_emit_reasoning_buffers_incomplete_line(self):
        """Without flush and no newline, _emit_reasoning buffers and returns unchanged."""
        self.printer.show_reasoning = True
        printed_len, header = self.printer._emit_reasoning("partial line", 0, False, flush=False)
        self.assertEqual(printed_len, 0)
        self.assertFalse(header)

    @patch("yaicli.printer.Live")
    def test_display_stream_confirm_tool_call(self, mock_live):
        """A ConfirmToolCall pauses the live, prompts, and resumes with the decision."""
        mock_live.return_value = MagicMock()
        printer = Printer()
        printer.console = MagicMock()
        printer.show_reasoning = True

        tc = ToolCall(id="c1", name="fn", arguments="{}")
        received = []

        def gen():
            decision = yield ConfirmToolCall(tool_call=tc)
            received.append(decision)
            yield LLMResponse(content="done")

        with patch.object(printer, "_confirm_tool_call", return_value=ToolConfirmDecision.ONCE):
            printer.display_stream(gen())

        self.assertEqual(received, [ToolConfirmDecision.ONCE])

    @patch("yaicli.printer.Live")
    def test_display_stream_refresh_live_resets(self, mock_live):
        """A RefreshLive flushes reasoning, restarts the live, and resets accumulators."""
        mock_live.return_value = MagicMock()
        printer = Printer()
        printer.console = MagicMock()
        printer.show_reasoning = True

        def gen():
            yield LLMResponse(reasoning="first thinking\n")
            yield RefreshLive()
            yield LLMResponse(content="second answer")

        content, _ = printer.display_stream(gen())
        self.assertIn("second answer", content)

    def test_emit_reasoning_flush_emits_partial_line(self):
        """With flush, _emit_reasoning emits buffered text even without a trailing newline."""
        self.printer.show_reasoning = True
        self.printer.console = MagicMock()
        printed_len, header = self.printer._emit_reasoning("partial no newline", 0, False, flush=True)
        self.assertEqual(printed_len, len("partial no newline"))
        self.assertTrue(header)
        self.printer.console.print.assert_any_call("Thinking:")

    @patch("yaicli.printer.Live")
    def test_display_stream_propagates_error(self, mock_live):
        """An error raised while processing a chunk stops the live and propagates."""
        mock_live.return_value = MagicMock()
        printer = Printer()
        printer.console = MagicMock()

        def gen():
            yield LLMResponse(content="x")

        with patch.object(printer, "_process_chunk", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                printer.display_stream(gen())
