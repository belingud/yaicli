import time
import traceback
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
)

from rich.console import Console, Group, RenderableType
from rich.live import Live

from yaicli.console import get_console
from yaicli.const import EventTypeEnum
from yaicli.render import JustifyMarkdown as Markdown, plain_formatter


def cursor_animation() -> Iterator[str]:
    """Generate a cursor animation for the console."""
    cursors = ["_", " "]
    while True:
        # Use current time to determine cursor state (changes every 0.5 seconds)
        current_time = time.time()
        # Alternate between cursors based on time
        yield cursors[int(current_time * 2) % 2]


class Printer:
    """Handles printing responses to the console, including stream processing."""

    _REASONING_PREFIX = "> "
    _CURSOR_ANIMATION_SLEEP = 0.005

    def __init__(
        self,
        config: Dict[str, Any],
        console: Console,
        verbose: bool = False,
        markdown: bool = True,
        reasoning_markdown: Optional[bool] = None,
        content_markdown: Optional[bool] = None,
    ):
        """Initialize the Printer class.

        Args:
            config (Dict[str, Any]): The configuration dictionary.
            console (Console): The console object.
            verbose (bool): Whether to print verbose output.
            markdown (bool): Whether to use Markdown formatting for all output (legacy).
            reasoning_markdown (Optional[bool]): Whether to use Markdown for reasoning sections.
            content_markdown (Optional[bool]): Whether to use Markdown for content sections.
        """
        self.config = config
        self.console = console or get_console()
        self.verbose = verbose
        self.code_theme = config["CODE_THEME"]
        self.in_reasoning: bool = False
        # Print reasoning content or not
        self.show_reasoning = config["SHOW_REASONING"]

        # Use explicit settings if provided, otherwise fall back to the global markdown setting
        self.reasoning_markdown = reasoning_markdown if reasoning_markdown is not None else markdown
        self.content_markdown = content_markdown if content_markdown is not None else markdown

        # Set formatters for reasoning and content
        self.reasoning_formatter = Markdown if self.reasoning_markdown else plain_formatter
        self.content_formatter = Markdown if self.content_markdown else plain_formatter

    def _reset_state(self) -> None:
        """Resets the printer state for a new stream."""
        self.in_reasoning = False

    def _process_reasoning_chunk(self, chunk: str, content: str, reasoning: str) -> Tuple[str, str]:
        """Adds a reasoning chunk to the reasoning text.
        This method handles the processing of reasoning chunks, and update the reasoning state
        when <think> tag is closed.

        Args:
            chunk (str): The reasoning chunk to process.
            content (str): The current content text.
            reasoning (str): The current reasoning text.

        Returns:
            Tuple[str, str]: The updated content text and reasoning text.
        """
        if not self.in_reasoning:
            self.in_reasoning = True
            reasoning = ""

        tmp = chunk.replace("\n", f"\n{self._REASONING_PREFIX}")
        tmp_reasoning = reasoning + tmp

        reasoning += chunk
        if "</think>" in tmp_reasoning:
            self.in_reasoning = False
            reasoning, content = reasoning.split("</think>", maxsplit=1)
        return content, reasoning

    def _process_content_chunk(self, chunk: str, content: str, reasoning: str) -> Tuple[str, str]:
        """Adds a content chunk to the content text.
        This method handles the processing of content chunks, and update the reasoning state
        when <think> tag is opened.

        Args:
            chunk (str): The content chunk to process.
            content (str): The current content text.
            reasoning (str): The current reasoning text.

        Returns:
            Tuple[str, str]: The updated content text and reasoning text.
        """
        if content == "":
            chunk = chunk.lstrip()  # Remove leading whitespace from first chunk

        if self.in_reasoning:
            self.in_reasoning = False
        content += chunk

        if content.startswith("<think>"):
            # Remove <think> tag and leading whitespace
            self.in_reasoning = True
            reasoning = content[7:].lstrip()
            content = ""  # Content starts after the initial <think> tag

        return content, reasoning

    def _handle_event(self, event: Dict[str, Any], content: str, reasoning: str) -> Tuple[str, str]:
        """Process a single stream event and return the updated content and reasoning.

        Args:
            event (Dict[str, Any]): The stream event to process.
            content (str): The current content text (non-reasoning).
            reasoning (str): The current reasoning text.
        Returns:
            Tuple[str, str]: The updated content text and reasoning text.
        """
        event_type = event.get("type")
        chunk = event.get("chunk")

        if event_type == EventTypeEnum.ERROR and self.verbose:
            self.console.print(f"Stream error: {event.get('message')}", style="dim")
            return content, reasoning

        # Handle explicit reasoning end event
        if event_type == EventTypeEnum.REASONING_END:
            if self.in_reasoning:
                self.in_reasoning = False
            return content, reasoning

        if event_type in (EventTypeEnum.REASONING, EventTypeEnum.CONTENT) and chunk:
            if event_type == EventTypeEnum.REASONING or self.in_reasoning:
                return self._process_reasoning_chunk(str(chunk), content, reasoning)
            return self._process_content_chunk(str(chunk), content, reasoning)

        return content, reasoning

    def _format_display_text(self, content: str, reasoning: str) -> RenderableType:
        """Format the text for display, combining content and reasoning if needed.

        Args:
            content (str): The content text.
            reasoning (str): The reasoning text.

        Returns:
            RenderableType: The formatted text ready for display as a Rich renderable.
        """
        # Create list of display elements to avoid type issues with concatenation
        display_elements: List[RenderableType] = []

        reasoning = reasoning.strip()
        # Format reasoning with proper formatting if it exists
        if reasoning and self.show_reasoning:
            raw_reasoning = reasoning.replace("\n", f"\n{self._REASONING_PREFIX}")
            if not raw_reasoning.startswith(self._REASONING_PREFIX):
                raw_reasoning = self._REASONING_PREFIX + raw_reasoning

            # Format the reasoning section
            reasoning_header = "\nThinking:\n"
            formatted_reasoning = self.reasoning_formatter(reasoning_header + raw_reasoning, code_theme=self.code_theme)
            display_elements.append(formatted_reasoning)

        content = content.strip()
        # Format content if it exists
        if content:
            formatted_content = self.content_formatter(content, code_theme=self.code_theme)

            # Add spacing between reasoning and content if both exist
            if reasoning and self.show_reasoning:
                display_elements.append("")

            display_elements.append(formatted_content)

        # Return based on what we have
        if not display_elements:
            return ""
        # Use Rich Group to combine multiple renderables
        return Group(*display_elements)

    def _update_live_display(self, live: Live, content: str, reasoning: str, cursor: Iterator[str]) -> None:
        """Update live display content and execute cursor animation
        Sleep for a short duration to control the cursor animation speed.

        Args:
            live (Live): The live display object.
            content (str): The current content text.
            reasoning (str): The current reasoning text.
            cursor (Iterator[str]): The cursor animation iterator.
        """

        cursor_char = next(cursor)

        # Handle cursor placement based on current state
        if self.in_reasoning and self.show_reasoning:
            # For reasoning, add cursor in plaintext to reasoning section
            if reasoning:
                if reasoning.endswith("\n"):
                    cursor_line = f"\n{self._REASONING_PREFIX}{cursor_char}"
                else:
                    cursor_line = cursor_char

                # Re-format with cursor added
                raw_reasoning = reasoning + cursor_line.replace(self._REASONING_PREFIX, "")
                formatted_display = self._format_display_text(content, raw_reasoning)
            else:
                # If reasoning just started with no content yet
                reasoning_header = f"\nThinking:\n{self._REASONING_PREFIX}{cursor_char}"
                formatted_reasoning = self.reasoning_formatter(reasoning_header, code_theme=self.code_theme)
                formatted_display = Group(formatted_reasoning)
        else:
            # For content, add cursor to content section
            formatted_content_with_cursor = content + cursor_char
            formatted_display = self._format_display_text(formatted_content_with_cursor, reasoning)

        live.update(formatted_display)
        time.sleep(self._CURSOR_ANIMATION_SLEEP)

    def display_stream(
        self, stream_iterator: Iterator[Dict[str, Any]], with_assistant_prefix: bool = True
    ) -> Tuple[Optional[str], Optional[str]]:
        """Display streaming response content
        Handle stream events and update the live display accordingly.
        This method separates content and reasoning blocks for display and further processing.

        Args:
            stream_iterator (Iterator[Dict[str, Any]]): The stream iterator to process.
            with_assistant_prefix (bool): Whether to display the "Assistant:" prefix.
        Returns:
            Tuple[Optional[str], Optional[str]]: The final content and reasoning texts if successful, None otherwise.
        """
        if with_assistant_prefix:
            self.console.print("Assistant:", style="bold green")
        self._reset_state()  # Reset state for the new stream
        content = ""
        reasoning = ""
        cursor = cursor_animation()

        with Live(console=self.console) as live:
            try:
                for event in stream_iterator:
                    content, reasoning = self._handle_event(event, content, reasoning)

                    if event.get("type") in (
                        EventTypeEnum.CONTENT,
                        EventTypeEnum.REASONING,
                        EventTypeEnum.REASONING_END,
                    ):
                        self._update_live_display(live, content, reasoning, cursor)

                # Remove cursor and finalize display
                live.update(self._format_display_text(content, reasoning))
                return content, reasoning

            except Exception as e:
                self.console.print(f"An error occurred during stream display: {e}", style="red")
                if self.verbose:
                    traceback.print_exc()
                return None, None

    def display_normal(
        self, content: Optional[str], reasoning: Optional[str] = None, with_assistant_prefix: bool = True
    ) -> None:
        """Display a complete, non-streamed response.

        Args:
            content (Optional[str]): The main content to display.
            reasoning (Optional[str]): The reasoning content to display.
            with_assistant_prefix (bool): Whether to display the "Assistant:" prefix.
        """
        if with_assistant_prefix:
            self.console.print("Assistant:", style="bold green")
        if content or reasoning:
            # Use the existing _format_display_text method
            formatted_display = self._format_display_text(content or "", reasoning or "")
            self.console.print(formatted_display)
            self.console.print()  # Add a newline for spacing
        else:
            self.console.print("Assistant did not provide any content.", style="yellow")
