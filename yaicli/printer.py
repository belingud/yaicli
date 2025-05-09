from dataclasses import dataclass, field
from typing import Iterator, List, Tuple

from rich.console import Group
from rich.console import RenderableType
from rich.live import Live

from .providers.base import LLMContent
from .config import Config, get_config
from .console import YaiConsole, get_console
from .render import Markdown, plain_formatter
from .const import EventTypeEnum


@dataclass
class Printer:
    console: YaiConsole = field(default_factory=get_console)
    config: Config = field(default_factory=get_config)

    _REASONING_PREFIX: str = "> "
    _UPDATE_INTERVAL: float = 0.01
    _CURSOR_ANIMATION_SLEEP: float = 0.01

    def __post_init__(self):
        self.code_theme: str = self.config["CODE_THEME"]
        self.show_reasoning: bool = self.config["SHOW_REASONING"]
        self.reasoning_markdown = self.config.get("REASONING_MARKDOWN", True)
        self.content_markdown = self.config.get("CONTENT_MARKDOWN", True)
        self.in_reasoning = False
        self.reasoning_formatter = Markdown if self.reasoning_markdown else plain_formatter
        self.content_formatter = Markdown if self.content_markdown else plain_formatter

    def _format_reasoning(self, text: str, content_buffer: str, reasoning_buffer: str) -> Tuple[str, str]:
        """Format reasoning text, add header if it's a new block."""
        if not self.show_reasoning or not text:
            return content_buffer, reasoning_buffer
        reasoning_buffer += text
        return content_buffer, reasoning_buffer

    def _format_content(self, text: str, content_buffer: str, reasoning_buffer: str) -> Tuple[str, str]:
        """Format content text."""
        if content_buffer == "":
            text = text.lstrip()  # Remove leading whitespace from first chunk
        content_buffer += text
        return content_buffer, reasoning_buffer

    def process_stream_event(self, llm_content: LLMContent, content: str, reasoning: str) -> Tuple[str, str]:
        """Process a single LLMContent event and return updated content and reasoning."""
        reasoning_out = reasoning
        content_out = content

        if llm_content.event_type == EventTypeEnum.REASONING:
            if not self.in_reasoning: # Start of a new reasoning block
                self.in_reasoning = True
            reasoning_out += llm_content.content # content field now holds reasoning text for REASONING event
        elif llm_content.event_type == EventTypeEnum.REASONING_END:
            self.in_reasoning = False
        elif llm_content.event_type == EventTypeEnum.CONTENT:
            if self.in_reasoning : # Should not happen if REASONING_END is always sent
                self.in_reasoning = False # Safety: exit reasoning mode if content arrives
            if content_out == "":
                content_out = llm_content.content.lstrip()
            else:
                content_out += llm_content.content
        elif llm_content.reasoning is not None: # Deprecated path
            content_out, reasoning_out = self._process_reasoning_chunk(llm_content.reasoning, content_out, reasoning_out)
        elif llm_content.content:
            content_out, reasoning_out = self._process_content_chunk(llm_content.content, content_out, reasoning_out)

        return content_out, reasoning_out

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

    def display_normal(self, content_iterator: Iterator[LLMContent]) -> None:
        """Process and display non-stream LLMContent, including reasoning and content parts."""
        content_buffer = ""
        reasoning_buffer = ""
        self.in_reasoning = False # Reset state for normal display
        
        for chunk in content_iterator:
            # Use the new process_stream_event logic for normal display as well
            content_buffer, reasoning_buffer = self.process_stream_event(chunk, content_buffer, reasoning_buffer)
                
        self.console.print(self._format_display_text(content_buffer, reasoning_buffer))

    def display_stream(self, stream_iterator: Iterator[LLMContent]) -> None:
        """Process and display LLMContent stream, including reasoning and content parts."""
        content_buffer = ""
        reasoning_buffer = ""

        with Live(console=self.console) as live:
            for chunk in stream_iterator:
                content_buffer, reasoning_buffer = self.process_stream_event(chunk, content_buffer, reasoning_buffer)
                live.update(self._format_display_text(content_buffer, reasoning_buffer))

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

        reasoning += chunk
        if "</think>" in reasoning:
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

