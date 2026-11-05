import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional, Tuple, Union

from rich.console import Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt

from .config import Config, get_config
from .console import YaiConsole, get_console, strip_control_chars, untrusted_text
from .render import Markdown, plain_formatter
from .schemas import ConfirmToolCall, LLMResponse, RefreshLive, ToolConfirmDecision
from .tools.approval import canonical_arguments, parse_tool_arguments
from .tools.risk import classify_shell_command, get_tool_risk

#: Bounds for the faithful confirmation preview (K06): the prompt must stay readable
#: even for a 1 MB file write or a multi-edit call.
_PREVIEW_MAX_CHARS = 4000
_PREVIEW_DIFF_MAX_LINES = 40
_PREVIEW_DIFF_CONTEXT = 2
_PREVIEW_WRITE_MAX_LINES = 10
_PREVIEW_LINE_MAX_CHARS = 200
_PREVIEW_READ_MAX_CHARS = 200_000


def _clip_line(text: Any, limit: int = _PREVIEW_LINE_MAX_CHARS) -> str:
    """One preview line: no control characters, no unbounded length."""
    line = strip_control_chars(text).rstrip()
    if len(line) > limit:
        line = line[: max(limit - 3, 0)] + "..."
    return line


def _resolve_preview_path(raw: Any) -> Optional[Path]:
    """Resolve a tool path argument like the fs tools do (``expanduser().resolve()``)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):  # pragma: no cover - exotic paths
        try:
            return Path(raw).expanduser()
        except (OSError, RuntimeError, ValueError):
            return None


def _read_text_preview(path: Optional[Path]) -> Optional[str]:
    """Best-effort read of the target file for a diff/write preview (bounded)."""
    if path is None:
        return None
    try:
        if not path.is_file():
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(_PREVIEW_READ_MAX_CHARS)
    except (OSError, ValueError):
        return None


def _unified_diff_lines(before: str, after: str, *, max_lines: int = _PREVIEW_DIFF_MAX_LINES) -> List[str]:
    """Render ``difflib.unified_diff`` head ``max_lines`` lines, indented and clipped."""
    diff = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="current",
            tofile="proposed",
            lineterm="",
            n=_PREVIEW_DIFF_CONTEXT,
        )
    )
    if not diff:
        return ["  (no textual changes)"]
    lines = [f"  {_clip_line(line)}" for line in diff[:max_lines]]
    if len(diff) > max_lines:
        lines.append(f"  ... ({len(diff) - max_lines} more diff line(s))")
    return lines


def _as_int(value: Any) -> Optional[int]:
    """Best-effort integer conversion for line-number based edits."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _simulate_replace_edits(current: str, edits: Any) -> Optional[str]:
    """Exact in-memory replay of fs_edit_file when every edit is a ``replace``.

    Returns ``None`` when the call is not a pure ``replace`` list (or would fail), so
    the caller falls back to per-edit old/new snippets instead of pretending a diff.
    """
    if not isinstance(edits, list) or not edits:
        return None
    text = current
    for edit in edits:
        if not isinstance(edit, dict) or edit.get("type", "") != "replace":
            return None
        old = edit.get("old")
        new = edit.get("new")
        if not isinstance(old, str) or not old or not isinstance(new, str) or old == new:
            return None
        if old not in text:
            return None
        text = text.replace(old, new)
    return text


def _edit_snippet_diff(edits: List[Any], current: Optional[str]) -> List[str]:
    """Per-edit old/new snippet preview used when a full-file diff is not feasible."""
    current_lines = current.splitlines() if current else []
    out: List[str] = []
    for index, edit in enumerate(edits, start=1):
        if not isinstance(edit, dict):
            out.append(f"  edit {index}: invalid ({type(edit).__name__}); execution will fail in-band")
            continue
        edit_type = edit.get("type", "")
        out.append(f"  edit {index} ({edit_type or 'no type'}):")
        if edit_type == "replace":
            old, new = edit.get("old"), edit.get("new")
            if isinstance(old, str) and isinstance(new, str):
                diff = list(
                    difflib.unified_diff(
                        old.splitlines(), new.splitlines(), fromfile="old", tofile="new", lineterm="", n=1
                    )
                )
                out.extend(f"    {_clip_line(line)}" for line in diff[:_PREVIEW_DIFF_MAX_LINES])
            else:
                out.append("    (invalid replace arguments; execution will fail in-band)")
        elif edit_type == "replace_line":
            line_number = _as_int(edit.get("line_number"))
            if line_number is not None and 1 <= line_number <= len(current_lines):
                out.append(f"    -{_clip_line(current_lines[line_number - 1])}")
            out.append(f"    +{_clip_line(edit.get('new', ''))}")
        elif edit_type == "insert_line":
            out.append(f"    +{_clip_line(edit.get('content', ''))}  (insert at line {edit.get('line_number')})")
        elif edit_type == "delete_line":
            line_number = _as_int(edit.get("line_number"))
            if line_number is not None and 1 <= line_number <= len(current_lines):
                out.append(f"    -{_clip_line(current_lines[line_number - 1])}")
            else:
                out.append(f"    (delete line {edit.get('line_number')})")
        elif edit_type == "append":
            out.append(f"    +{_clip_line(edit.get('content', ''))}  (append)")
        else:
            out.append("    (unknown edit type; execution will fail in-band)")
        if len(out) >= _PREVIEW_DIFF_MAX_LINES:
            out.append("  ... (preview truncated)")
            break
    return out


@dataclass
class Printer:
    """Render LLM output to the terminal.

    ``machine`` selects the v0.19 headless contract: no Rich ``Live`` region, no
    Markdown formatting/justification and no label/panel output. Content is only
    returned to the caller (the CLI decides what reaches stdout), and structured
    ``events`` (``--output-format stream-json``) are forwarded to the sink
    instead of being rendered.
    """

    console: YaiConsole = field(default_factory=get_console)
    config: Config = field(default_factory=get_config)
    content_markdown: bool = True
    machine: bool = False
    events: Optional[Callable[[Dict[str, Any]], None]] = None

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

    def _emit_event(self, event: Dict[str, Any]) -> None:
        """Forward one structured event to the configured sink (stream-json)."""
        if self.events is not None:
            self.events(event)

    def _display_stream_machine(
        self,
        stream_iterator: Generator[
            Union["LLMResponse", RefreshLive, ConfirmToolCall], Optional[ToolConfirmDecision], None
        ],
    ) -> tuple[str, str]:
        """Headless variant of :meth:`display_stream`.

        No Rich ``Live`` region and no console output: content is accumulated and
        returned so the CLI can decide what reaches stdout (plain text, one JSON
        object or NDJSON events). Confirmation requests are auto-denied so a
        headless run can never block waiting for a prompt.
        """
        self._reset_state()
        full_content = full_reasoning = ""
        turn = 0
        self._emit_event({"type": "turn_start", "turn": turn})
        send_value: Optional[ToolConfirmDecision] = None

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
                # Never block in a headless run; the client denies such calls
                # already when non-interactive, this is a defensive fallback.
                self._emit_event(
                    {
                        "type": "tool_call",
                        "name": chunk.tool_call.name,
                        "arguments": chunk.tool_call.arguments,
                    }
                )
                send_value = ToolConfirmDecision.DENY
                continue

            if isinstance(chunk, RefreshLive):
                # A tool round ended and a new completion starts.
                turn += 1
                self._emit_event({"type": "turn_start", "turn": turn})
                full_content = full_reasoning = ""
                self._reset_state()
                continue

            previous_len = len(full_content)
            full_content, full_reasoning = self._process_chunk(
                getattr(chunk, "content", "") or "",
                getattr(chunk, "reasoning", "") or "",
                full_content,
                "",
            )
            delta = full_content[previous_len:]
            if delta:
                self._emit_event({"type": "text_delta", "delta": delta})

        return full_content, full_reasoning

    def _display_normal_machine(self, content_iterator: Iterator[Union["LLMResponse", RefreshLive]]):
        """Headless variant of :meth:`display_normal`."""
        self._reset_state()
        full_content = full_reasoning = ""
        for chunk in content_iterator:
            if not isinstance(chunk, LLMResponse):
                continue
            previous_len = len(full_content)
            full_content, full_reasoning = self._process_chunk(
                chunk.content or "", chunk.reasoning or "", full_content, ""
            )
            delta = full_content[previous_len:]
            if delta:
                self._emit_event({"type": "text_delta", "delta": delta})
        return full_content, full_reasoning

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
        if self.machine:
            return self._display_normal_machine(content_iterator)

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

    # ------------------- faithful confirmation preview (v0.19 K06) -------------------
    def _format_tool_preview(self, tool_call) -> str:
        """Build the confirmation preview from the *canonical* arguments.

        Arguments are parsed with the same ``json_repair`` normalization the execution
        path uses, so the preview shows what will actually run (duplicate JSON keys,
        decoded ``\\u003b`` escapes, ...). Specialized formats: decoded shell command +
        danger reasons, file-write target/mode/content head, file-edit unified diff.
        """
        name = str(getattr(tool_call, "name", "") or "")
        raw_arguments = getattr(tool_call, "arguments", "")
        parsed = parse_tool_arguments(raw_arguments)
        risk = get_tool_risk(name)

        if parsed is None:
            raw_text = strip_control_chars(raw_arguments)
            if len(raw_text) > _PREVIEW_MAX_CHARS:
                raw_text = raw_text[:_PREVIEW_MAX_CHARS] + "..."
            return (
                f"{name}({raw_text})\nrisk: {risk.value}\narguments are not a JSON object; execution will fail in-band"
            )

        if name == "execute_shell_command" and isinstance(parsed.get("command"), str):
            lines = self._preview_shell(parsed, risk)
        elif name == "fs_write_file" and isinstance(parsed.get("file_path"), str):
            lines = self._preview_fs_write(parsed, risk)
        elif name == "fs_edit_file" and isinstance(parsed.get("file_path"), str):
            lines = self._preview_fs_edit(parsed, risk)
        else:
            lines = [f"{name}({canonical_arguments(parsed)})", f"risk: {risk.value}"]

        preview = "\n".join(lines)
        if len(preview) > _PREVIEW_MAX_CHARS:
            preview = preview[:_PREVIEW_MAX_CHARS] + "\n... (preview truncated)"
        return preview

    @staticmethod
    def _preview_shell(parsed: Dict[str, Any], risk) -> List[str]:
        """Decoded shell command + danger classification summary."""
        command = parsed["command"]
        lines = ["execute_shell_command", f"risk: {risk.value}", f"command: {command}"]
        timeout = parsed.get("timeout")
        if timeout is not None:
            lines.append(f"timeout: {timeout}s")
        cwd = parsed.get("cwd")
        if isinstance(cwd, str) and cwd:
            lines.append(f"cwd: {cwd}")
        shell_risk = classify_shell_command(command)
        lines.append(f"dangerous: {'yes' if shell_risk.dangerous else 'no'}")
        if shell_risk.reasons:
            lines.append("reasons:")
            lines.extend(f"  - {_clip_line(reason)}" for reason in shell_risk.reasons)
        return lines

    @staticmethod
    def _preview_fs_write(parsed: Dict[str, Any], risk) -> List[str]:
        """Target path, create/overwrite/append mode and a content head."""
        path = _resolve_preview_path(parsed.get("file_path"))
        append = bool(parsed.get("append", False))
        if append:
            mode = "append (create if the file does not exist)"
        else:
            try:
                exists = bool(path is not None and path.exists())
            except OSError:  # pragma: no cover - exotic path errors
                exists = False
            mode = "overwrite existing file" if exists else "create new file"
        lines = ["fs_write_file", f"risk: {risk.value}", f"path: {path or parsed.get('file_path')}", f"mode: {mode}"]
        encoding = parsed.get("encoding")
        if isinstance(encoding, str) and encoding and encoding != "utf-8":
            lines.append(f"encoding: {encoding}")
        content = parsed.get("content", "")
        if isinstance(content, str):
            content_lines = content.splitlines()
            lines.append(f"content: {len(content)} chars, {len(content_lines)} line(s); head:")
            for number, line in enumerate(content_lines[:_PREVIEW_WRITE_MAX_LINES], start=1):
                lines.append(f"  {number:>3} | {_clip_line(line)}")
            if not content_lines:
                lines.append("  (empty content)")
            elif len(content_lines) > _PREVIEW_WRITE_MAX_LINES:
                lines.append(f"  ... ({len(content_lines) - _PREVIEW_WRITE_MAX_LINES} more line(s))")
        else:
            lines.append(f"content: {content!r} (not a string; execution will fail in-band)")
        return lines

    @staticmethod
    def _preview_fs_edit(parsed: Dict[str, Any], risk) -> List[str]:
        """Target path + a unified diff head (or per-edit old/new snippets)."""
        path = _resolve_preview_path(parsed.get("file_path"))
        edits = parsed.get("edits", [])
        lines = ["fs_edit_file", f"risk: {risk.value}", f"path: {path or parsed.get('file_path')}"]
        if parsed.get("dry_run"):
            lines.append("dry-run: yes (the file will not be modified)")
        if not isinstance(edits, list):
            lines.append(f"edits: {edits!r} (not a list; execution will fail in-band)")
            return lines
        lines.append(f"edits: {len(edits)}")
        current = _read_text_preview(path)
        if current is not None:
            simulated = _simulate_replace_edits(current, edits)
            if simulated is not None:
                lines.append("diff (head):")
                lines.extend(_unified_diff_lines(current, simulated))
                return lines
        lines.append("diff (per edit):")
        lines.extend(_edit_snippet_diff(edits, current))
        return lines

    def _confirm_tool_call(self, tool_call) -> ToolConfirmDecision:
        """Prompt the user to confirm a pending tool call.

        The preview is built from the normalized arguments that will execute (K06), so
        the operator approves exactly what the tool receives. Returns a
        ToolConfirmDecision. Interruptions (Ctrl-C / EOF) are treated as deny so they
        never propagate as an unhandled error through the stream pump.
        """
        self.console.print(
            Panel(
                # Tool name/arguments come from the model: render them literally so
                # a "[/...]" can neither raise MarkupError nor restyle/hide the
                # command the operator is being asked to approve.
                untrusted_text(self._format_tool_preview(tool_call)),
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
            # Strip control chars: reasoning is model text and must not inject
            # ANSI/OSC sequences even though markup is already disabled.
            sanitized = strip_control_chars(text)
            prefixed = self._REASONING_PREFIX + sanitized.replace("\n", f"\n{self._REASONING_PREFIX}")
            # markup/highlight off: reasoning is arbitrary model text, not Rich markup.
            self.console.print(prefixed, style="dim", markup=False, highlight=False)
        return printed_len + emitted, header_shown

    def display_stream(
        self,
        stream_iterator: Generator[
            Union["LLMResponse", RefreshLive, ConfirmToolCall], Optional[ToolConfirmDecision], None
        ],
        pause_requested: Optional[Callable[[], bool]] = None,
        on_pause: Optional[Callable[[], None]] = None,
    ) -> tuple[str, str]:
        """Process and display an LLM stream.

        Reasoning is streamed as append-only text; only the content is rendered in the
        live region. Driven with next()/send() so a ConfirmToolCall signal can pause the
        live, prompt the user, and resume the generator with the user's decision.

        ``pause_requested``/``on_pause`` implement the generation-time Ctrl+O toggle:
        between chunks the caller is asked whether the user requested the viewer; when
        so the live region is stopped, ``on_pause()`` runs (the viewer), and a fresh live
        region redraws the accumulated content before streaming resumes.
        """
        if self.machine:
            return self._display_stream_machine(stream_iterator)

        self._reset_state()
        full_content = full_reasoning = ""
        printed_reasoning = 0
        reasoning_header_shown = False
        live = self._create_and_start_live()
        send_value: Optional[ToolConfirmDecision] = None

        try:
            while True:
                if pause_requested is not None and on_pause is not None and pause_requested():
                    # Generation-time viewer request: stop the live region, run the
                    # callback (full-screen viewer), then redraw and keep streaming.
                    self._safe_stop_live(live)
                    try:
                        on_pause()
                    finally:
                        live = self._create_and_start_live()
                        if full_content:
                            live.update(self._format_display_text(full_content, ""), refresh=True)
                    continue
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
