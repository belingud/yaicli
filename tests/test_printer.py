import pytest
from unittest.mock import MagicMock, patch

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from yaicli.printer import Printer


@pytest.fixture
def mock_console():
    """Fixture for a mocked Console object."""
    console = MagicMock(spec=Console)
    return console


def test_printer_init(mock_console):
    """Test Printer initialization."""
    config = {"CODE_THEME": "solarized-dark", "OTHER_CONFIG": "value"}
    printer = Printer(config=config, console=mock_console, verbose=True)
    assert printer.config == config
    assert printer.console == mock_console
    assert printer.verbose is True
    assert printer.code_theme == "solarized-dark"


def test_printer_init_default_theme(mock_console):
    """Test Printer initialization with default code theme."""
    config = {}
    printer = Printer(config=config, console=mock_console, verbose=False)
    assert printer.code_theme == "monokai"
    assert printer.verbose is False


# Tests for _process_reasoning_chunk
@pytest.mark.parametrize(
    "chunk, full_completion_in, in_reasoning_in, expected_completion, expected_in_reasoning",
    [
        ("Step 1", "", False, "> Reasoning:\n> Step 1\n> ", True), # Start reasoning (ends with \n> )
        ("Step 1", "Initial\n", False, "Initial\n\n> Reasoning:\n> Step 1\n> ", True), # Start reasoning after content (needs \n\n)
        ("Step 1", "Initial\n\n", False, "Initial\n\n> Reasoning:\n> Step 1\n> ", True), # Start reasoning after content (already \n\n)
        ("Step 2", "> Reasoning:\n> Step 1\n> ", True, "> Reasoning:\n> Step 1\n> Step 2\n> ", True), # Continue reasoning (ends with \n> )
        # Chunk contains \n, replace adds \n>, logic ensures ends with \n>
        ("Step 2\nMore details", "> Reasoning:\n> Step 1\n> ", True, "> Reasoning:\n> Step 1\n> Step 2\n> More details\n> ", True),
        # Chunk ends with \n, replace adds \n>, logic ensures ends with \n>
        ("Final Step\n", "> Reasoning:\n> Prev Step\n> ", True, "> Reasoning:\n> Prev Step\n> Final Step\n> ", True), # Final correction: ends with \n>
    ]
)
def test_process_reasoning_chunk(mock_console, chunk, full_completion_in, in_reasoning_in, expected_completion, expected_in_reasoning):
    """Test the _process_reasoning_chunk method."""
    printer = Printer(config={}, console=mock_console, verbose=False)
    full_completion_out, in_reasoning_out = printer._process_reasoning_chunk(
        chunk, full_completion_in, in_reasoning_in
    )
    assert full_completion_out == expected_completion
    assert in_reasoning_out == expected_in_reasoning


# Tests for _process_content_chunk
@pytest.mark.parametrize(
    "chunk, full_completion_in, in_reasoning_in, expected_completion, expected_in_reasoning",
    [
        ("Hello", "", False, "Hello", False), # Simple content
        (" World", "Hello", False, "Hello World", False), # Append content
        ("The result is:", "> Reasoning:\n> Step 1\n> Step 2\n> ", True, "> Reasoning:\n> Step 1\n> Step 2\n\nThe result is:", False), # Switch from reasoning to content
        ("Result.", "> Reasoning:\n> Step1\n> ", True, "> Reasoning:\n> Step1\n\nResult.", False), # Switch from reasoning ending with \n> 
    ]
)
def test_process_content_chunk(mock_console, chunk, full_completion_in, in_reasoning_in, expected_completion, expected_in_reasoning):
    """Test the _process_content_chunk method."""
    printer = Printer(config={}, console=mock_console, verbose=False)
    full_completion_out, in_reasoning_out = printer._process_content_chunk(
        chunk, full_completion_in, in_reasoning_in
    )
    assert full_completion_out == expected_completion
    assert in_reasoning_out == expected_in_reasoning


# Tests for display_normal
def test_display_normal_with_content(mock_console):
    """Test display_normal with valid string content."""
    printer = Printer(config={}, console=mock_console, verbose=False)
    content = "This is the response."
    printer.display_normal(content)
    mock_console.print.assert_any_call("Assistant:", style="bold green")
    # Check that Markdown object was created and printed
    args, kwargs = mock_console.print.call_args_list[1] # Second call is Markdown
    assert isinstance(args[0], Markdown)
    assert args[0].markup == content
    assert args[0].code_theme == "monokai"
    mock_console.print.assert_any_call() # Check for trailing newline

def test_display_normal_with_non_string_content(mock_console):
    """Test display_normal with non-string (but convertible) content."""
    printer = Printer(config={}, console=mock_console, verbose=False)
    # Pass a string that looks like a number to align with type hint
    content = "12345"
    printer.display_normal(content)
    mock_console.print.assert_any_call("Assistant:", style="bold green")
    args, kwargs = mock_console.print.call_args_list[1]
    assert isinstance(args[0], Markdown)
    assert args[0].markup == "12345"
    mock_console.print.assert_any_call()

def test_display_normal_with_none(mock_console):
    """Test display_normal when content is None."""
    printer = Printer(config={}, console=mock_console, verbose=False)
    printer.display_normal(None)
    mock_console.print.assert_any_call("Assistant:", style="bold green")
    mock_console.print.assert_any_call("[yellow]Assistant did not provide any content.[/yellow]")
    # Ensure Markdown wasn't printed
    assert len(mock_console.print.call_args_list) == 2


# Tests for display_stream
@patch("yaicli.printer.Live")
@patch("yaicli.printer.time.sleep", return_value=None) # Mock sleep
def test_display_stream_content_and_finish(mock_sleep, mock_live_cls, mock_console):
    """Test display_stream with content and finish events."""
    # Configure the mock instance that the patched Live class will return
    mock_live_instance = MagicMock(spec=Live)
    mock_live_instance.__enter__.return_value = mock_live_instance
    mock_live_instance.__exit__.return_value = None
    mock_live_cls.return_value = mock_live_instance

    printer = Printer(config={}, console=mock_console, verbose=False)
    stream_iterator = [
        {"type": "content", "chunk": "Hello "},
        {"type": "content", "chunk": "World!"},
        {"type": "finish", "reason": "stop"}
    ]

    result = printer.display_stream(iter(stream_iterator))

    assert result == "Hello World!"
    mock_console.print.assert_called_once_with("Assistant:", style="bold green")
    mock_live_cls.assert_called_once_with(console=mock_console, auto_refresh=False, vertical_overflow="visible")

    # Check Live updates on the instance returned by the patch
    # Total updates = (updates in loop) + 1 (final update)
    # Updates in loop = 2 (for the two content chunks)
    assert len(mock_live_instance.update.call_args_list) == 3 # Corrected: 2 + 1 = 3

    # Check first content update (inside loop)
    args, kwargs = mock_live_instance.update.call_args_list[0]
    assert isinstance(args[0], Markdown)
    assert args[0].markup == "Hello _"
    assert kwargs["refresh"] is True

    # Check second content update (inside loop)
    args, kwargs = mock_live_instance.update.call_args_list[1]
    assert isinstance(args[0], Markdown)
    assert args[0].markup == "Hello World! "
    assert kwargs["refresh"] is True

    # Check final update (outside loop)
    final_args, final_kwargs = mock_live_instance.update.call_args_list[2]
    assert isinstance(final_args[0], Markdown)
    assert final_args[0].markup == "Hello World!"
    assert final_kwargs["refresh"] is True

    mock_live_instance.stop.assert_called_once()

@patch("yaicli.printer.Live")
@patch("yaicli.printer.time.sleep", return_value=None)
def test_display_stream_reasoning_content_finish(mock_sleep, mock_live_cls, mock_console):
    """Test display_stream with reasoning, content, and finish events."""
    mock_live_instance = MagicMock(spec=Live)
    mock_live_instance.__enter__.return_value = mock_live_instance
    mock_live_instance.__exit__.return_value = None
    mock_live_cls.return_value = mock_live_instance

    printer = Printer(config={}, console=mock_console, verbose=True)
    stream_iterator = [
        {"type": "reasoning", "chunk": "Thinking..."},
        {"type": "reasoning", "chunk": "Done thinking."},
        {"type": "content", "chunk": "Here is the answer."},
        {"type": "finish", "reason": "stop"}
    ]

    expected_output = "> Reasoning:\n> Thinking...\n> Done thinking.\n\nHere is the answer."
    result = printer.display_stream(iter(stream_iterator))

    assert result == expected_output

    # Check Live updates
    update_calls = mock_live_instance.update.call_args_list
    # Expect 2 reasoning + 1 content = 3 updates inside loop, +1 final update = 4 total
    assert len(update_calls) == 4

    # Check first reasoning update (markup includes cursor)
    args, kwargs = update_calls[0]
    assert args[0].markup == "> Reasoning:\n> Thinking...\n_" # Ends with \n + cursor

    # Check second reasoning update (markup includes cursor)
    args, kwargs = update_calls[1]
    # Corrected expectation: content ends with \n, cursor is space
    assert args[0].markup == "> Reasoning:\n> Thinking...\n> Done thinking.\n "

    # Check content update (markup includes cursor)
    args, kwargs = update_calls[2]
    assert args[0].markup == expected_output + "_"

    # Check final update content (no cursor, no trailing '> ')
    args, kwargs = update_calls[3]
    assert isinstance(args[0], Markdown)
    assert args[0].markup == expected_output

    # Check verbose output for finish
    mock_console.print.assert_any_call("[dim]Stream finished. Reason: stop[/dim]")
    mock_live_instance.stop.assert_called_once()


@patch("yaicli.printer.Live")
@patch("yaicli.printer.time.sleep", return_value=None)
def test_display_stream_error_event(mock_sleep, mock_live_cls, mock_console):
    """Test display_stream with an error event (verbose=True)."""
    mock_live_instance = MagicMock(spec=Live)
    mock_live_instance.__enter__.return_value = mock_live_instance
    mock_live_instance.__exit__.return_value = None
    mock_live_cls.return_value = mock_live_instance

    printer = Printer(config={}, console=mock_console, verbose=True)
    stream_iterator = [
        {"type": "content", "chunk": "Part 1."}, # Some content before error
        {"type": "error", "message": "API limit reached"},
        {"type": "content", "chunk": " Part 2."}, # Content after error
        {"type": "finish", "reason": "error_handled"}
    ]

    result = printer.display_stream(iter(stream_iterator))

    assert result == "Part 1. Part 2."

    # Check Live updates
    update_calls = mock_live_instance.update.call_args_list
    # Expect 2 content updates inside loop + 1 final update = 3 total
    assert len(update_calls) == 3

    # Check verbose output for error
    mock_console.print.assert_any_call("[dim]Stream encountered an error: API limit reached[/dim]")
    # Check verbose output for finish
    mock_console.print.assert_any_call("[dim]Stream finished. Reason: error_handled[/dim]")
    mock_live_instance.stop.assert_called_once()


@patch("yaicli.printer.Live")
@patch("yaicli.printer.time.sleep", return_value=None)
@patch("traceback.print_exc") # Corrected patch target
def test_display_stream_exception_during_processing(mock_traceback, mock_sleep, mock_live_cls, mock_console):
    """Test display_stream when an exception occurs during iteration (verbose=True)."""
    mock_live_instance = MagicMock(spec=Live)
    mock_live_instance.__enter__.return_value = mock_live_instance
    mock_live_instance.__exit__.return_value = None
    mock_live_cls.return_value = mock_live_instance

    printer = Printer(config={}, console=mock_console, verbose=True)

    def side_effect_iterator():
        yield {"type": "content", "chunk": "OK so far."}
        yield {"type": "error", "message": "Ignore me"}
        raise ValueError("Something broke!")

    result = printer.display_stream(side_effect_iterator())

    assert result is None

    mock_console.print.assert_any_call("[red]An error occurred during stream display: Something broke![/red]")

    # Check Live updates
    update_calls = mock_live_instance.update.call_args_list
    # Expect 1 content update inside loop + 1 update in except block = 2 total
    assert len(update_calls) == 2

    # Check the first update (content)
    args, kwargs = update_calls[0]
    assert args[0].markup == "OK so far._"

    # Check the second update (exception handling)
    args, kwargs = update_calls[1]
    assert isinstance(args[0], Markdown)
    assert args[0].markup == "OK so far. [Display Error]"
    assert kwargs["refresh"] is True

    mock_traceback.assert_called_once()
    mock_live_instance.stop.assert_called_once()

@patch("yaicli.printer.Live")
@patch("yaicli.printer.time.sleep", return_value=None)
@patch("traceback.print_exc") # Corrected patch target
def test_display_stream_exception_during_processing_not_verbose(mock_traceback, mock_sleep, mock_live_cls, mock_console):
    """Test display_stream when an exception occurs during iteration (verbose=False)."""
    mock_live_instance = MagicMock(spec=Live)
    mock_live_instance.__enter__.return_value = mock_live_instance
    mock_live_instance.__exit__.return_value = None
    mock_live_cls.return_value = mock_live_instance

    printer = Printer(config={}, console=mock_console, verbose=False) # Verbose is False

    def side_effect_iterator():
        yield {"type": "content", "chunk": "Content."}
        raise RuntimeError("Processing failed")

    result = printer.display_stream(side_effect_iterator())

    assert result is None
    mock_console.print.assert_any_call("[red]An error occurred during stream display: Processing failed[/red]")

    # Check Live updates
    update_calls = mock_live_instance.update.call_args_list
    # Expect 1 content update inside loop + 1 update in except block = 2 total
    assert len(update_calls) == 2

    # Check the exception handling update
    args, kwargs = update_calls[1]
    assert isinstance(args[0], Markdown)
    assert args[0].markup == "Content. [Display Error]"

    mock_traceback.assert_not_called()
    mock_live_instance.stop.assert_called_once() 