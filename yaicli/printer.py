import itertools
import time
import traceback
from typing import (
    Any,
    Dict,
    Iterator,
    Optional,
    Tuple,
)

from rich import get_console
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from yaicli.const import DEFAULT_CODE_THEME, EventTypeEnum


class Printer:
    """Handles printing responses to the console, including stream processing."""

    def __init__(self, config: Dict[str, Any], console: Console, verbose: bool = False):
        self.config = config
        self.console = console or get_console()
        self.verbose = verbose
        self.code_theme = config.get("CODE_THEME", DEFAULT_CODE_THEME)

    def _process_reasoning_chunk(
        self, chunk: str, content: str, reasoning: str, in_reasoning: bool
    ) -> Tuple[str, str, bool]:
        """Adds a reasoning chunk to the reasoning text.
        This method handles the processing of reasoning chunks, and update the reasoning state
        when <think> tag is closed.

        Args:
            chunk (str): The reasoning chunk to process.
            content (str): The current content text.
            reasoning (str): The current reasoning text.
            in_reasoning (bool): Whether the assistant is currently in reasoning mode.

        Returns:
            Tuple[str, str, bool]: The updated content text, reasoning text and updated reasoning state.
        """
        if not in_reasoning:
            in_reasoning = True
            reasoning = ""

        tmp = chunk.replace("\n", "\n> ")
        tmp_reasoning = reasoning + tmp

        reasoning += chunk
        if "</think>" in tmp_reasoning:
            in_reasoning = False
            reasoning, content = reasoning.split("</think>", maxsplit=1)
        return content, reasoning, in_reasoning

    def _process_content_chunk(
        self, chunk: str, content: str, reasoning: str, in_reasoning: bool
    ) -> Tuple[str, str, bool]:
        """Adds a content chunk to the content text.
        This method handles the processing of content chunks, and update the reasoning state
        when <think> tag is opened.

        Args:
            chunk (str): The content chunk to process.
            content (str): The current content text.
            reasoning (str): The current reasoning text.
            in_reasoning (bool): Whether the assistant is currently in reasoning mode.

        Returns:
            Tuple[str, str, bool]: The updated content text, reasoning text and updated reasoning state.
        """
        if content == "":
            chunk = chunk.lstrip()  # Remove leading whitespace from first chunk

        if in_reasoning:
            in_reasoning = False
        content += chunk

        if content.startswith("<think>"):
            # Remove <think> tag and leading whitespace
            in_reasoning = True
            reasoning = content[7:].lstrip()

        return content, reasoning, in_reasoning

    def _handle_event(
        self, event: Dict[str, Any], content: str, reasoning: str, in_reasoning: bool
    ) -> Tuple[str, str, bool]:
        """Process a single stream event and return the updated content, reasoning and inference state.

        Args:
            event (Dict[str, Any]): The stream event to process.
            content (str): The current content text (non-reasoning).
            reasoning (str): The current reasoning text.
            in_reasoning (bool): Whether the assistant is currently in reasoning mode.
        Returns:
            Tuple[str, str, bool]: The updated content text, reasoning text and updated reasoning state.
        """
        event_type = event.get("type")
        chunk = event.get("chunk")

        if event_type == EventTypeEnum.ERROR and self.verbose:
            self.console.print(f"Stream error: {event.get('message')}", style="dim")
            return content, reasoning, in_reasoning

        # Handle explicit reasoning end event
        if event_type == EventTypeEnum.REASONING_END:
            if in_reasoning:
                in_reasoning = False
            return content, reasoning, in_reasoning

        if event_type in (EventTypeEnum.REASONING, EventTypeEnum.CONTENT) and chunk:
            if event_type == EventTypeEnum.REASONING or in_reasoning:
                return self._process_reasoning_chunk(str(chunk), content, reasoning, in_reasoning)
            return self._process_content_chunk(str(chunk), content, reasoning, in_reasoning)

        return content, reasoning, in_reasoning

    def _format_display_text(self, content: str, reasoning: str) -> str:
        """Format the text for display, combining content and reasoning if needed.

        Args:
            content (str): The content text.
            reasoning (str): The reasoning text.

        Returns:
            str: The formatted text for display.
        """
        display_text = ""

        # Add reasoning with proper formatting if it exists
        if reasoning:
            formatted_reasoning = reasoning.replace("\n", "\n> ")
            if not formatted_reasoning.startswith("> "):
                formatted_reasoning = "> " + formatted_reasoning
            display_text += f"> Reasoning:\n{formatted_reasoning}"

            # Only add newlines if there is content following the reasoning
            if content:
                display_text += "\n\n"

        # Add content
        display_text += content

        return display_text

    def _update_live_display(
        self, live: Live, content: str, reasoning: str, in_reasoning: bool, cursor: Iterator[str]
    ) -> None:
        """Update live display content and execute cursor animation
        Sleep for a short duration to control the cursor animation speed.

        Args:
            live (Live): The live display object.
            content (str): The current content text.
            reasoning (str): The current reasoning text.
            in_reasoning (bool): Whether the assistant is currently in reasoning mode.
            cursor (Iterator[str]): The cursor animation iterator.
        """
        # Format display text without cursor first
        display_text = self._format_display_text(content, reasoning)
        cursor_char = next(cursor)

        # Add cursor at the end of reasoning or content depending on current state
        if in_reasoning:
            # Add cursor at the end of reasoning content
            if reasoning:
                display_text += cursor_char
            else:
                # If reasoning just started and no content yet
                display_text = "> Reasoning:" + cursor_char
        else:
            # Add cursor at the end of normal content
            display_text += cursor_char

        markdown = Markdown(display_text, code_theme=self.code_theme)
        live.update(markdown)
        time.sleep(0.005)

    def display_stream(self, stream_iterator: Iterator[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
        """Display streaming response content
        Handle stream events and update the live display accordingly.
        This method separates content and reasoning blocks for display and further processing.

        Args:
            stream_iterator (Iterator[Dict[str, Any]]): The stream iterator to process.
        Returns:
            Tuple[Optional[str], Optional[str]]: The final content and reasoning texts if successful, None otherwise.
        """
        self.console.print("Assistant:", style="bold green")
        content = ""
        reasoning = ""
        in_reasoning = False
        cursor = itertools.cycle(["_", " "])

        with Live(console=self.console) as live:
            try:
                for event in stream_iterator:
                    content, reasoning, in_reasoning = self._handle_event(event, content, reasoning, in_reasoning)

                    if event.get("type") in (
                        EventTypeEnum.CONTENT,
                        EventTypeEnum.REASONING,
                        EventTypeEnum.REASONING_END,
                    ):
                        self._update_live_display(live, content, reasoning, in_reasoning, cursor)

                # Remove cursor and finalize display
                display_text = self._format_display_text(content, reasoning)
                live.update(Markdown(display_text, code_theme=self.code_theme))
                return content, reasoning

            except Exception as e:
                self.console.print(f"An error occurred during stream display: {e}", style="red")
                display_text = self._format_display_text(content, reasoning) + " [Display Error]"
                live.update(Markdown(markup=display_text, code_theme=self.code_theme))
                if self.verbose:
                    traceback.print_exc()
                return None, None

    def display_normal(self, content: Optional[str], reasoning: Optional[str] = None) -> None:
        """Display a complete, non-streamed response.

        Args:
            content (Optional[str]): The main content to display.
            reasoning (Optional[str]): The reasoning content to display.
        """
        self.console.print("Assistant:", style="bold green")

        if content or reasoning:
            display_text = self._format_display_text(content or "", reasoning or "")
            self.console.print(Markdown(display_text, code_theme=self.code_theme))
            self.console.print()  # Add a newline for spacing
        else:
            self.console.print("Assistant did not provide any content.", style="yellow")
