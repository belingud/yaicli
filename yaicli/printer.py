from dataclasses import dataclass, field
from typing import Generator, Iterator, List, Optional, Tuple, Union

from rich.console import Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt

from .config import Config, get_config
from .console import YaiConsole, get_console
from .render import Markdown, plain_formatter
from .schemas import ConfirmToolCall, LLMResponse, RefreshLive, ToolConfirmDecision


@dataclass
class Printer:
    console: YaiConsole = field(default_factory=get_console)
    config: Config = field(default_factory=get_config)
    content_markdown: bool = True

    _REASONING_PREFIX: str = "> "

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

    def _create_and_start_live(self) -> Live:
        """Create and start a new Live instance.

        auto_refresh is disabled so all drawing happens synchronously on the main
        thread (via explicit refresh on each update). This avoids the background
        refresh thread racing with direct console prints (e.g., large tool-output
        panels), which otherwise leaves duplicated/misaligned frames behind.
        """
        live = Live(console=self.console, auto_refresh=False)
        live.start()
        return live

    def _safe_stop_live(self, live: Live) -> None:
        """Safely stop a Live instance if it's running."""
        if live.is_started:
            live.stop()

    def _confirm_tool_call(self, tool_call) -> ToolConfirmDecision:
        """Prompt the user to confirm a pending tool call.

        Returns a ToolConfirmDecision. Interruptions (Ctrl-C / EOF) are treated as deny
        so they never propagate as an unhandled error through the stream pump.
        """
        self.console.print(
            Panel(
                f"{tool_call.name}({tool_call.arguments})",
                title="Confirm tool call",
                title_align="left",
                border_style="bold magenta",
                expand=False,
            )
        )
        choice_map = {
            "y": ToolConfirmDecision.ONCE,
            "a": ToolConfirmDecision.SESSION,
            "A": ToolConfirmDecision.PERSIST,
            "n": ToolConfirmDecision.DENY,
        }
        try:
            choice = Prompt.ask(
                r"Execute tool? \[y]once, \[a]session, \[A]always, \[n]o",
                choices=list(choice_map.keys()),
                default="y",
                case_sensitive=True,
                show_choices=False,
                console=self.console,
            )
        except (KeyboardInterrupt, EOFError):
            self.console.print("\nTool call denied.", style="yellow")
            return ToolConfirmDecision.DENY
        return choice_map[choice]

    def _emit_reasoning(
        self, full_reasoning: str, printed_len: int, header_shown: bool, *, flush: bool
    ) -> Tuple[int, bool]:
        """Stream newly-arrived reasoning as append-only text.

        Reasoning is printed rather than re-rendered in the live region, so a tall
        reasoning block never sits in a live that cannot be overwritten cleanly when it
        overflows the screen. Without ``flush`` only whole lines are emitted; the partial
        trailing line is buffered until its newline (or a flush) arrives.

        Returns the updated (printed_len, header_shown).
        """
        if not self.show_reasoning:
            return len(full_reasoning), header_shown
        pending = full_reasoning[printed_len:]
        if not pending:
            return printed_len, header_shown
        if flush:
            emitted = len(pending)
        else:
            nl = pending.rfind("\n")
            if nl == -1:
                return printed_len, header_shown  # no complete line yet; keep buffering
            pending = pending[: nl + 1]
            emitted = len(pending)
        text = pending.strip("\n")
        if text:
            if not header_shown:
                self.console.print("Thinking:")
                header_shown = True
            prefixed = self._REASONING_PREFIX + text.replace("\n", f"\n{self._REASONING_PREFIX}")
            # markup/highlight off: reasoning is arbitrary model text, not Rich markup.
            self.console.print(prefixed, style="dim", markup=False, highlight=False)
        return printed_len + emitted, header_shown

    def display_stream(
        self,
        stream_iterator: Generator[
            Union["LLMResponse", RefreshLive, ConfirmToolCall], Optional[ToolConfirmDecision], None
        ],
    ) -> tuple[str, str]:
        """Process and display an LLM stream.

        Reasoning is streamed as append-only text; only the content is rendered in the
        live region. Driven with next()/send() so a ConfirmToolCall signal can pause the
        live, prompt the user, and resume the generator with the user's decision.
        """
        self._reset_state()
        full_content = full_reasoning = ""
        printed_reasoning = 0
        reasoning_header_shown = False
        live = self._create_and_start_live()
        send_value: Optional[ToolConfirmDecision] = None

        try:
            while True:
                try:
                    if send_value is None:
                        chunk = next(stream_iterator)
                    else:
                        chunk = stream_iterator.send(send_value)
                        send_value = None
                except StopIteration:
                    break

                if isinstance(chunk, ConfirmToolCall):
                    # Pause the live region so the prompt does not fight its refresh.
                    self._safe_stop_live(live)
                    send_value = self._confirm_tool_call(chunk.tool_call)
                    # Fresh live for subsequent tool output / streaming.
                    live = self._create_and_start_live()
                    continue

                if isinstance(chunk, RefreshLive):
                    # Flush buffered reasoning, then transition to a new live session.
                    printed_reasoning, reasoning_header_shown = self._emit_reasoning(
                        full_reasoning, printed_reasoning, reasoning_header_shown, flush=True
                    )
                    self._safe_stop_live(live)
                    live = self._create_and_start_live()

                    # Reset state for next completion
                    full_content = full_reasoning = ""
                    printed_reasoning = 0
                    reasoning_header_shown = False
                    self._reset_state()
                    continue

                # Process chunk and update content/reasoning
                full_content, full_reasoning = self._process_chunk(
                    chunk.content or "", chunk.reasoning or "", full_content, full_reasoning
                )

                if full_content:
                    # Content has started: flush any remaining reasoning above it, then
                    # render the content in the live region.
                    printed_reasoning, reasoning_header_shown = self._emit_reasoning(
                        full_reasoning, printed_reasoning, reasoning_header_shown, flush=True
                    )
                    live.update(self._format_display_text(full_content, ""), refresh=True)
                else:
                    # Reasoning only so far: stream it append-only (whole lines).
                    printed_reasoning, reasoning_header_shown = self._emit_reasoning(
                        full_reasoning, printed_reasoning, reasoning_header_shown, flush=False
                    )

        except Exception as e:
            self._safe_stop_live(live)
            raise e from None
        finally:
            # Flush any trailing reasoning that never received a newline.
            self._emit_reasoning(full_reasoning, printed_reasoning, reasoning_header_shown, flush=True)
            self._safe_stop_live(live)

        return full_content, full_reasoning
