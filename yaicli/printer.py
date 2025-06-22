import time
from dataclasses import dataclass, field
from typing import Iterator, List, Tuple, Union

from rich.console import Group, RenderableType
from rich.live import Live

from .config import Config, get_config
from .console import YaiConsole, get_console
from .render import Markdown, plain_formatter
from .schemas import LLMResponse, RefreshLive


@dataclass
class Printer:
    console: YaiConsole = field(default_factory=get_console)
    config: Config = field(default_factory=get_config)
    content_markdown: bool = True

    _REASONING_PREFIX: str = "> "
    _UPDATE_INTERVAL: float = 0.01

    def __post_init__(self):
        self.code_theme: str = self.config["CODE_THEME"]
        self.show_reasoning: bool = self.config["SHOW_REASONING"]
        # Set formatter for reasoning and content
        self.reasoning_formatter = Markdown
        self.content_formatter = Markdown if self.content_markdown else plain_formatter
        # Track if we're currently processing reasoning content
        self.in_reasoning: bool = False

    def _reset_state(self) -> None:
        """Reset printer state for a new stream."""
        self.in_reasoning = False

    def _check_and_update_think_tags(self, content: str, reasoning: str) -> Tuple[str, str]:
        """Check for <think> tags in the accumulated content and reasoning.

        This function checks the entire accumulated text for <think> tags
        and updates state accordingly.

        Args:
            content: Current accumulated content text
            reasoning: Current accumulated reasoning text

        Returns:
            Updated content and reasoning after tag processing
        """
        # First, check if we have a <think> opener in content
        if "<think>" in content and not self.in_reasoning:
            parts = content.split("<think>", 1)
            new_content = parts[0]
            new_reasoning = parts[1]
            self.in_reasoning = True

            # Check if the new reasoning has a </think> closer
            if "</think>" in new_reasoning:
                closer_parts = new_reasoning.split("</think>", 1)
                reasoning += closer_parts[0]
                new_content += closer_parts[1]
                self.in_reasoning = False
                return new_content, reasoning
            else:
                # No closer yet
                reasoning += new_reasoning
                return new_content, reasoning

        # Check if we have a </think> closer in reasoning
        if "</think>" in reasoning and self.in_reasoning:
            parts = reasoning.split("</think>", 1)
            new_reasoning = parts[0]
            content += parts[1]
            self.in_reasoning = False
            return content, new_reasoning

        return content, reasoning

    def _process_chunk(self, chunk_content: str, chunk_reasoning: str, content: str, reasoning: str) -> Tuple[str, str]:
        """Process a single chunk and update content and reasoning.

        Args:
            chunk_content: Content from the current chunk
            chunk_reasoning: Reasoning from the current chunk
            content: Current accumulated content
            reasoning: Current accumulated reasoning

        Returns:
            Updated content and reasoning
        """
        # Process reasoning field first (if present)
        if chunk_reasoning:
            reasoning += chunk_reasoning

        # Then process content field (if present)
        if chunk_content:
            if self.in_reasoning:
                # In reasoning mode, append to reasoning
                reasoning += chunk_content
            else:
                # Normal content mode
                content += chunk_content

        # Check for any <think> tags in the updated content/reasoning
        return self._check_and_update_think_tags(content, reasoning)

    def _format_display_text(self, content: str, reasoning: str) -> RenderableType:
        """Format the text for display, combining content and reasoning if needed.

        Args:
            content: The content text.
            reasoning: The reasoning text.

        Returns:
            The formatted text ready for display as a Rich renderable.
        """
        # Create list of display elements to avoid type issues with concatenation
        display_elements: List[RenderableType] = []

        # Format reasoning with proper formatting if it exists
        if reasoning and self.show_reasoning:
            raw_reasoning = reasoning.replace("\n", f"\n{self._REASONING_PREFIX}")
            if not raw_reasoning.startswith(self._REASONING_PREFIX):
                raw_reasoning = self._REASONING_PREFIX + raw_reasoning

            # Format the reasoning section
            reasoning_header = "\nThinking:\n"
            formatted_reasoning = self.reasoning_formatter(reasoning_header + raw_reasoning, code_theme=self.code_theme)
            display_elements.append(formatted_reasoning)

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

    def display_normal(self, content_iterator: Iterator[Union["LLMResponse", RefreshLive]]) -> tuple[str, str]:
        """Process and display non-stream LLMContent, including reasoning and content parts."""
        self._reset_state()
        full_content = full_reasoning = ""

        for chunk in content_iterator:
            if not isinstance(chunk, LLMResponse):
                continue

            # Process chunk and update content/reasoning
            full_content, full_reasoning = self._process_chunk(
                chunk.content or "", chunk.reasoning or "", full_content, full_reasoning
            )

            # Display reasoning
            if self.show_reasoning and full_reasoning:
                reasoning = full_reasoning.replace("\n", f"\n{self._REASONING_PREFIX}")
                self.console.print("Thinking:")
                self.console.print(self.reasoning_formatter(reasoning))

            # Display content
            if full_content:
                self.console.print()
                self.console.print(self.content_formatter(full_content))

        return full_content, full_reasoning

    def display_stream(self, stream_iterator: Iterator[Union["LLMResponse", RefreshLive]]) -> tuple[str, str]:
        """Process and display LLMContent stream, including reasoning and content parts."""
        self._reset_state()
        full_content = full_reasoning = ""
        live = Live(console=self.console)
        live.start()

        for chunk in stream_iterator:
            if isinstance(chunk, RefreshLive):
                # Refresh live display when in next completion
                live.stop()
                live = Live(console=self.console)
                live.start()
                # Initialize full_content and full_reasoning for the next completion
                full_content = full_reasoning = ""
                self._reset_state()
                continue

            # Process chunk and update content/reasoning
            full_content, full_reasoning = self._process_chunk(
                chunk.content or "", chunk.reasoning or "", full_content, full_reasoning
            )

            # Update display
            formatted_display = self._format_display_text(full_content, full_reasoning)
            live.update(formatted_display)
            time.sleep(self._UPDATE_INTERVAL)

        live.stop()
        return full_content, full_reasoning
