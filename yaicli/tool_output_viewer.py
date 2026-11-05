"""Full-screen tool-output viewer for ``Ctrl+O`` / ``/show-output``.

The viewer lists every tool result of the current conversation turn on the left
and shows the selected result on the right. It runs on the terminal's alternate
screen, so closing it (``q`` / ``Esc`` / ``Ctrl+O``) restores the REPL exactly as
it was — unlike printing the full output into the scrollback, which cannot be
collapsed afterwards.

By default the right pane shows what the model saw (``TOOL_OUTPUT_MAX_CHARS``
capped). When truncation spilled the original output to disk, pressing ``f``
loads that full file (capped at :data:`MAX_FULL_TEXT_CHARS` for responsiveness);
pressing ``f`` again returns to the model-visible text.
"""

import sys
from typing import Any, Dict, List, Optional

from .debug_log import debug_log
from .tools.output_history import ToolOutputEntry, viewer_outputs

#: Safety cap when loading a spilled full output into the viewer.
MAX_FULL_TEXT_CHARS = 1_000_000

_HELP_LINE = (
    " ↑/↓ select · Tab switch pane · PgUp/PgDn scroll · f full text · q/Esc/Ctrl+O close "
)


class ToolOutputViewerRequested(Exception):
    """Signal raised through ``Application.exit`` when the user presses Ctrl+O."""


def _is_tty() -> bool:
    """Best-effort TTY check; a fake/redirected terminal falls back to inline."""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - exotic stream wrappers
        return False


def _entry_header(entry: ToolOutputEntry, position: int, total: int) -> str:
    parts = [f"[{position}/{total}] {entry.name}"]
    parts.append("MCP" if entry.kind == "mcp" else "function")
    parts.append(f"{entry.total_chars:,} chars")
    if entry.truncated:
        parts.append("truncated")
    return " · ".join(parts)


def _body_text(entry: ToolOutputEntry, full_text: Optional[str] = None) -> str:
    """Build the right-pane document: call header, result, spill hint."""
    lines = [
        f"@ {entry.kind.title()} call: {entry.name}",
        f"arguments: {entry.arguments}",
        "",
    ]
    if full_text is not None:
        lines.append(f"[full spilled output · {len(full_text):,} chars shown]")
        lines.append("")
        lines.append(full_text)
    else:
        lines.append(entry.text)
    if entry.spill_path:
        lines.extend(["", f"… full output saved to {entry.spill_path}"])
    return "\n".join(lines)


def _load_full_text(entry: ToolOutputEntry) -> Optional[str]:
    """Read the spilled full output; ``None`` when there is no usable file."""
    if not entry.spill_path:
        return None
    try:
        with open(entry.spill_path, encoding="utf-8", errors="replace") as handle:
            data = handle.read()
    except OSError:
        return None
    if len(data) > MAX_FULL_TEXT_CHARS:
        data = data[:MAX_FULL_TEXT_CHARS] + (
            f"\n\n...[viewer capped at {MAX_FULL_TEXT_CHARS:,} chars; "
            f"full file: {entry.spill_path}]..."
        )
    return data


def _left_fragments(entries: List[ToolOutputEntry], position: int) -> List[Any]:
    """Formatted text for the entry list (selected row reversed)."""
    fragments: List[Any] = []
    for index, entry in enumerate(entries):
        selected = index == position
        marker = "▸ " if selected else "  "
        text = f"{marker}{index + 1:>2}. {entry.name}  ({entry.total_chars:,}c)\n"
        fragments.append(("class:selected" if selected else "", text))
    return fragments


def build_viewer_app(
    entries: List[ToolOutputEntry],
    label: str = "",
    *,
    input: Any = None,
    output: Any = None,
) -> Any:
    """Build the prompt_toolkit application for the viewer (input/output injectable for tests)."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.styles import Style

    state: Dict[str, Any] = {"pos": 0, "pane": "list", "full": {}, "notice": ""}
    body = Buffer(read_only=True, document=Document(_body_text(entries[0])))

    list_control = FormattedTextControl(
        lambda: _left_fragments(entries, state["pos"]),
        focusable=True,
        show_cursor=False,
    )
    list_window = Window(
        list_control,
        width=Dimension(min=26, max=44),
        wrap_lines=False,
        style="class:pane",
    )
    body_window = Window(BufferControl(buffer=body), wrap_lines=True, style="class:pane")

    def selected() -> ToolOutputEntry:
        return entries[state["pos"]]

    def header_text() -> str:
        entry = selected()
        suffix = " · showing full file" if entry.index in state["full"] else ""
        return f" Tool outputs · {label or 'session'} · {len(entries)} result(s){suffix} "

    def footer_text() -> str:
        return state["notice"] or _HELP_LINE

    header_window = Window(FormattedTextControl(header_text), height=1, style="class:header")
    footer_window = Window(FormattedTextControl(footer_text), height=1, style="class:footer")

    def refresh(reset_cursor: bool = True) -> None:
        entry = selected()
        body.set_document(Document(_body_text(entry, state["full"].get(entry.index))), bypass_readonly=True)
        if reset_cursor:
            body.cursor_position = 0

    keyboard = KeyBindings()

    def close(event: Any) -> None:
        event.app.exit()

    def move(event: Any, delta: int) -> None:
        if state["pane"] == "list":
            target = max(0, min(len(entries) - 1, state["pos"] + delta))
            if target != state["pos"]:
                state["pos"] = target
                state["notice"] = ""
                refresh()
        elif delta < 0:
            body.cursor_up(-delta)
        else:
            body.cursor_down(delta)
        event.app.invalidate()

    def focus_pane(event: Any, pane: str) -> None:
        state["pane"] = pane
        state["notice"] = ""
        event.app.layout.focus(body_window if pane == "body" else list_window)
        event.app.invalidate()

    for key in ("q", "escape", "c-o", "c-c"):
        keyboard.add(key)(close)

    keyboard.add("up")(lambda event: move(event, -1))
    keyboard.add("down")(lambda event: move(event, 1))
    keyboard.add("pageup")(lambda event: (body.cursor_up(15), event.app.invalidate()))
    keyboard.add("pagedown")(lambda event: (body.cursor_down(15), event.app.invalidate()))
    keyboard.add("home")(lambda event: (setattr(body, "cursor_position", 0), event.app.invalidate()))
    keyboard.add("end")(lambda event: (setattr(body, "cursor_position", len(body.text)), event.app.invalidate()))
    keyboard.add("tab")(lambda event: focus_pane(event, "body"))
    keyboard.add("s-tab")(lambda event: focus_pane(event, "list"))
    keyboard.add("left")(lambda event: focus_pane(event, "list"))
    keyboard.add("right")(lambda event: focus_pane(event, "body"))

    def toggle_full(event: Any) -> None:
        entry = selected()
        if entry.index in state["full"]:
            state["full"].pop(entry.index, None)
            state["notice"] = "Showing the model-visible result. Press f to load the full file."
        else:
            full = _load_full_text(entry)
            if full is None:
                state["notice"] = "No spilled full output for this entry (it was not truncated)."
            else:
                state["full"][entry.index] = full
                state["notice"] = "Showing the full spilled output. Press f to go back."
        refresh()
        event.app.invalidate()

    keyboard.add("f")(toggle_full)

    layout = Layout(
        HSplit(
            [
                header_window,
                VSplit(
                    [
                        list_window,
                        Window(width=1, char="│", style="class:separator"),
                        body_window,
                    ]
                ),
                footer_window,
            ]
        ),
        focused_element=list_window,
    )
    style = Style.from_dict(
        {
            "header": "reverse",
            "footer": "reverse",
            "pane": "",
            "selected": "reverse",
            "separator": "fg:#666666",
        }
    )
    return Application(
        layout=layout,
        key_bindings=keyboard,
        style=style,
        full_screen=True,
        input=input,
        output=output,
        mouse_support=False,
    )


def open_tool_output_viewer(console: Any) -> None:
    """Open the Ctrl+O viewer; falls back to the inline panel when there is no TTY."""
    from .tools import show_last_tool_output

    entries, label = viewer_outputs()
    if not entries:
        debug_log("viewer.skip", reason="no-entries")
        console.print("No tool output in this session yet.", style="dim")
        return
    debug_log("viewer.open", entries=len(entries), tty=_is_tty(), label=label)
    if not _is_tty():
        console.print("The tool-output viewer needs an interactive terminal; showing the latest output.", style="dim")
        show_last_tool_output(console)
        return
    try:
        app = build_viewer_app(entries, label)
        debug_log("viewer.run.begin")
        app.run()
        debug_log("viewer.run.end")
    except Exception as exc:  # noqa: BLE001 - a broken terminal must not kill the REPL
        debug_log("viewer.run.error", error=repr(exc))
        console.print(f"Could not open the tool-output viewer: {exc}", style="dim")
        show_last_tool_output(console)
