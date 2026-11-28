"""Terminal rendering of tool calls and results; no execution or truncation."""

from typing import Any, Dict

from rich.panel import Panel

from ..console import safe_text, untrusted_text
from . import output_history
from .limits import build_preview_marker, make_display_preview

_CAPTION_ARGUMENT_KEYS = ("command", "file_path", "path", "url", "query", "pattern", "title")


def get_last_tool_output() -> Dict[str, Any] | None:
    """Return the last tool result as a dict (compatibility helper).

    The dict has ``type`` (``"function"``/``"mcp"``), ``name``, ``text`` (the
    model-visible result after truncation/spill), plus ``total_chars``,
    ``spill_path`` and ``truncated`` metadata.
    """
    entry = output_history.last_output()
    if entry is None:
        return None
    return {
        "type": entry.kind,
        "name": entry.name,
        "text": entry.text,
        "total_chars": entry.total_chars,
        "spill_path": entry.spill_path,
        "truncated": entry.truncated,
    }


def show_last_tool_output(target_console: Any) -> bool:
    """Print the last tool result in full (inline fallback); ``False`` when none."""
    entry = output_history.last_output()
    if entry is None:
        target_console.print("No tool output in this session yet.", style="dim")
        return False
    title = f"Last {entry.kind.title()} output: {entry.name}"
    if entry.truncated:
        title += f" ({entry.total_chars:,} chars, truncated)"
    target_console.print(
        Panel(
            untrusted_text(entry.text),
            title=safe_text(title),
            title_align="left",
            expand=False,
            border_style="blue",
            style="dim",
        )
    )
    return True


def _tool_call_caption(arguments: Dict[str, Any]) -> str:
    """Return a short one-line caption for the viewer list (command/path/url...)."""
    for key in _CAPTION_ARGUMENT_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.strip().split())[:160]
    return ""


def announce_tool_call(console: Any, kind: str, name: str, arguments: str) -> None:
    """Announce a call on the console selected by the current application."""
    console.print(f"@{kind.title()} call: {safe_text(name)}({safe_text(arguments)})", style="blue")


def display_tool_result(console: Any, text: str, kind: str) -> None:
    """Render a bounded preview without changing the model-facing result."""
    preview = make_display_preview(text)
    content = untrusted_text(preview.text)
    if preview.truncated:
        content.append("\n\n")
        content.append(build_preview_marker(preview), style="dim")
    title = f"{kind.title()} output"
    if preview.truncated:
        title = f"{title} ({preview.label})"
    console.print(Panel(content, title=title, title_align="left", expand=False, border_style="blue", style="dim"))
