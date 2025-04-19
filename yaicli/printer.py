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

from yaicli.api import EventTypeEnum


class Printer:
    """Handles printing responses to the console, including stream processing."""

    def __init__(self, config: Dict[str, Any], console: Console, verbose: bool = False):
        self.config = config
        self.console = console or get_console()
        self.verbose = verbose
        self.code_theme = config.get("CODE_THEME", "monokai")

    def _process_reasoning_chunk(self, chunk: str, full_completion: str, in_reasoning: bool) -> Tuple[str, bool]:
        """Adds a reasoning chunk to the full completion text.
        This method handles the processing of reasoning chunks, and update the reasoning state
        when <think> tag is closed.

        Args:
            chunk (str): The reasoning chunk to process.
            full_completion (str): The current full completion text.
            in_reasoning (bool): Whether the assistant is currently in reasoning mode.

        Returns:
            Tuple[str, bool]: The updated full completion text and the updated reasoning state.
        """
        if not in_reasoning:
            in_reasoning = True
            full_completion = "> Reasoning:\n> "
        tmp = chunk.replace("\n", "\n> ")
        tmp_completion = full_completion + tmp
        if tmp_completion.find("</think>") != -1:
            in_reasoning = False
            full_completion += chunk
            full_completion = full_completion.replace("\n> </think>", "\n\n", 1).replace("</think>", "\n\n", 1)
        else:
            full_completion += chunk.replace("\n", "\n> ")
        return full_completion, in_reasoning

    def _process_content_chunk(self, chunk: str, full_completion: str, in_reasoning: bool) -> Tuple[str, bool]:
        """Adds a content chunk to the full completion text.
        This method handles the processing of content chunks, and update the reasoning state
        when <think> tag is opened.

        Args:
            chunk (str): The content chunk to process.
            full_completion (str): The current full completion text.
            in_reasoning (bool): Whether the assistant is currently in reasoning mode.

        Returns:
            Tuple[str, bool]: The updated full completion text and the updated reasoning state.
        """
        if full_completion == "":
            chunk = chunk.lstrip()  # Remove leading whitespace from first chunk
        if in_reasoning:
            in_reasoning = False
            full_completion += "\n\n"
        full_completion += chunk
        if full_completion.startswith("<think>"):
            if not in_reasoning:
                in_reasoning = True
                full_completion = "> Reasoning:\n> " + full_completion[7:].lstrip()
        return full_completion, in_reasoning

    def _handle_event(self, event: Dict[str, Any], full_content: str, in_reasoning: bool) -> Tuple[str, bool]:
        """Process a single stream event and return the updated content and inference state.

        Args:
            event (Dict[str, Any]): The stream event to process.
            full_content (str): The current full completion text.
            in_reasoning (bool): Whether the assistant is currently in reasoning mode.
        Returns:
            Tuple[str, bool]: The updated full completion text and the updated reasoning state.
        """
        event_type = event.get("type")
        chunk = event.get("chunk")

        if event_type == EventTypeEnum.ERROR and self.verbose:
            self.console.print(f"Stream error: {event.get('message')}", style="dim")
            return full_content, in_reasoning

        # Handle explicit reasoning end event
        if event_type == EventTypeEnum.REASONING_END:
            if in_reasoning:
                in_reasoning = False
                full_content += "\n\n"  # Add spacing after reasoning ends
            return full_content, in_reasoning

        if event_type in (EventTypeEnum.REASONING, EventTypeEnum.CONTENT) and chunk:
            if event_type == EventTypeEnum.REASONING or in_reasoning:
                return self._process_reasoning_chunk(str(chunk), full_content, in_reasoning)
            return self._process_content_chunk(str(chunk), full_content, in_reasoning)

        return full_content, in_reasoning

    def _update_live_display(self, live: Live, content: str, in_reasoning: bool, cursor: Iterator[str]) -> None:
        """Update live display content and execute cursor animation
        Sleep for a short duration to control the cursor animation speed.

        Args:
            live (Live): The live display object.
            content (str): The current content to display.
            in_reasoning (bool): Whether the assistant is currently in reasoning mode.
            cursor (Iterator[str]): The cursor animation iterator.
        """
        display = content.rstrip("> ") if in_reasoning else content
        markdown = Markdown(f"{display}{next(cursor)}", code_theme=self.code_theme)
        live.update(markdown, refresh=True)
        time.sleep(0.005)

    def display_stream(self, stream_iterator: Iterator[Dict[str, Any]]) -> Optional[str]:
        """Display streaming response content
        Handle stream events and update the live display accordingly.
        This method also handle <think> blocks and display them in a separate section.

        Args:
            stream_iterator (Iterator[Dict[str, Any]]): The stream iterator to process.
        Returns:
            Optional[str]: The final full completion text if successful, None otherwise.
        """
        self.console.print("Assistant:", style="bold green")
        full_content = ""
        in_reasoning = False
        cursor = itertools.cycle(["_", " "])
        # TODO: 区分 reasoning 和 content
        with Live(console=self.console) as live:
            try:
                for event in stream_iterator:
                    full_content, in_reasoning = self._handle_event(event, full_content, in_reasoning)

                    if event.get("type") in (
                        EventTypeEnum.CONTENT,
                        EventTypeEnum.REASONING,
                        EventTypeEnum.REASONING_END,
                    ):
                        self._update_live_display(live, full_content, in_reasoning, cursor)

                # Remove cursor and finalize display
                live.update(Markdown(full_content, code_theme=self.code_theme), refresh=True)
                return full_content

            except Exception as e:
                self.console.print(f"An error occurred during stream display: {e}", style="red")
                live.update(
                    Markdown(markup=full_content + " [Display Error]", code_theme=self.code_theme), refresh=True
                )
                if self.verbose:
                    traceback.print_exc()
                return None

    def display_normal(self, content: Optional[str], reasoning: Optional[str] = None) -> None:
        """Display a complete, non-streamed response.

        Args:
            content (Optional[str]): The content to display.
        """
        self.console.print("Assistant:", style="bold green")
        if content and isinstance(content, str):
            if reasoning:
                reasoning = reasoning.replace("\n", "\n> ")
                if not reasoning.startswith("> "):
                    reasoning = "> " + reasoning
                self.console.print(Markdown(f"> Reasoning:\n{reasoning}", code_theme=self.code_theme))
                self.console.print()  # Add a newline for spacing
            self.console.print(Markdown(content, code_theme=self.code_theme))
            self.console.print()  # Add a newline for spacing
        elif content:  # Handle case where content might be non-string from API parsing fallback
            if reasoning:
                reasoning = reasoning.replace("\n", "\n> ")
                if not reasoning.startswith("> "):
                    reasoning = "> " + reasoning
                self.console.print(Markdown(f"> Reasoning:\n{reasoning}", code_theme=self.code_theme))
                self.console.print()  # Add a newline for spacing
            self.console.print(Markdown(str(content), code_theme=self.code_theme))
            self.console.print()  # Add a newline for spacing
        else:
            self.console.print("Assistant did not provide any content.", style="yellow")
