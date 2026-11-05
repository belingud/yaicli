"""Truncation and spill-to-disk of large tool outputs (v0.19 K02).

A single tool result (a log file, a directory tree, a web page) can be larger
than the model context window. Every tool result therefore goes through
:func:`truncate_tool_output` before it enters the conversation or the terminal
panel:

* the per-tool character cap is applied (head + tail window);
* the middle is replaced by a marker that explains the truncation and points at
  the spilled full text;
* the full text is written to ``TOOL_OUTPUT_DIR`` (best effort) so the model can
  page through it with ``fs_read_file(offset=..., limit=...)``.

If the spill file cannot be written (read-only disk, permissions), truncation
still happens and the marker simply omits the path. ``TOOL_OUTPUT_MAX_CHARS=0``
disables truncation entirely.

The *terminal* preview is a separate, much tighter limit (v0.19.1): tool results
are rendered head-only (first ``TOOL_DISPLAY_MAX_LINES`` lines / chars) with a
``Ctrl+O to expand`` hint, while the model still receives the text capped by
``TOOL_OUTPUT_MAX_CHARS``. :func:`make_display_preview` and
:func:`summarize_arguments` implement that display-only layer.

Standard library only: this module runs inside the tool-call path.
"""

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..config import cfg
from ..const import (
    DEFAULT_TOOL_CALL_PREVIEW_MAX_CHARS,
    DEFAULT_TOOL_DISPLAY_MAX_CHARS,
    DEFAULT_TOOL_DISPLAY_MAX_LINES,
    DEFAULT_TOOL_OUTPUT_DIR,
    DEFAULT_TOOL_OUTPUT_MAX_CHARS,
)

#: Default cap (characters) when neither the tool nor the config overrides it.
DEFAULT_OUTPUT_MAX_CHARS = DEFAULT_TOOL_OUTPUT_MAX_CHARS
#: Per-tool caps: big reads may keep more, chatty tools less.
TOOL_OUTPUT_CAPS = {
    "execute_shell_command": 32000,
    "fs_read_file": 64000,
    "fs_search_files": 48000,
    "fs_list_directory": 48000,
    "fetch_webpage": 100000,
}
#: Minimum room needed for a useful head+tail window next to the marker.
MIN_MARKER_BUDGET = 32
#: Marker tail shared by both the spilled and non-spilled variants.
_READ_MORE_HINT = "use fs_read_file with offset/limit to read more"
_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# ---------------------------------------------------------------------------
# Terminal display preview (v0.19.1)
# ---------------------------------------------------------------------------
#: Default head-only display limits (characters/lines); ``0`` = unlimited.
DEFAULT_DISPLAY_MAX_LINES = DEFAULT_TOOL_DISPLAY_MAX_LINES
DEFAULT_DISPLAY_MAX_CHARS = DEFAULT_TOOL_DISPLAY_MAX_CHARS
#: Default cap for the ``@Function call:`` argument line (``0`` = raw arguments).
DEFAULT_CALL_PREVIEW_MAX_CHARS = DEFAULT_TOOL_CALL_PREVIEW_MAX_CHARS
#: Hint appended to a truncated terminal preview.
DISPLAY_EXPAND_HINT = "Ctrl+O to expand"
#: First characters of a long argument value kept in the call-line summary.
_ARGUMENT_VALUE_HEAD_CHARS = 60
#: Argument values longer than this are summarized as ``<N chars>``.
_ARGUMENT_VALUE_SUMMARY_OVER = 80


def _config_int(key: str, default: int) -> int:
    """Read an integer config value, tolerating mocks/strings/None."""
    try:
        raw = cfg.get(key) if hasattr(cfg, "get") else None
    except Exception:  # pragma: no cover - defensive: broken config mapping
        return default
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _config_str(key: str, default: str) -> str:
    try:
        raw = cfg.get(key) if hasattr(cfg, "get") else None
    except Exception:  # pragma: no cover - defensive: broken config mapping
        return default
    if raw is None or raw == "":
        return default
    return str(raw)


def resolve_output_cap(tool_name: str, max_chars: Optional[int] = None) -> int:
    """Return the character cap for one tool result (``0`` = unlimited).

    Resolution order:

    1. explicit ``max_chars`` argument;
    2. a user-configured ``TOOL_OUTPUT_MAX_CHARS`` (when it differs from the
       shipped default) applies to every tool;
    3. the per-tool cap for ``tool_name`` (``fetch_webpage`` 100k,
       ``fs_read_file`` 64k, search/list 48k, shell 32k);
    4. :data:`DEFAULT_OUTPUT_MAX_CHARS`.
    """
    if max_chars is not None:
        try:
            return max(0, int(max_chars))
        except (TypeError, ValueError):
            pass
    configured = _config_int("TOOL_OUTPUT_MAX_CHARS", DEFAULT_OUTPUT_MAX_CHARS)
    if configured != DEFAULT_OUTPUT_MAX_CHARS:
        return max(0, configured)
    return TOOL_OUTPUT_CAPS.get(tool_name, DEFAULT_OUTPUT_MAX_CHARS)


def spill_tool_output(text: str, tool_name: str) -> Optional[Path]:
    """Write the full ``text`` to ``TOOL_OUTPUT_DIR``; return the path or ``None``.

    The file is created with mode ``0600`` (best effort): tool output may contain
    secrets read from files, the environment or command output, so it must not be
    world-readable just because of the process umask.

    Every failure path (missing/read-only directory, permission error, bad
    config value) returns ``None``: truncation then proceeds without a path.
    """
    directory_value = _config_str("TOOL_OUTPUT_DIR", str(DEFAULT_TOOL_OUTPUT_DIR))
    try:
        directory = Path(directory_value).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = _FILENAME_UNSAFE_RE.sub("_", str(tool_name or "tool")).strip("_")[:48] or "tool"
        filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_name}-{uuid.uuid4().hex[:8]}.txt"
        path = directory / filename
        path.write_text(text, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - Windows / exotic filesystems
            pass
        return path
    except (OSError, ValueError):
        return None


def _build_marker(removed_chars: int, spill_path: Optional[Path]) -> str:
    if spill_path is not None:
        return f"...[truncated {removed_chars} chars; full output saved to {spill_path}; {_READ_MORE_HINT}]..."
    return f"...[truncated {removed_chars} chars; {_READ_MORE_HINT}]..."


def _split_around_marker(text: str, cap: int, spill_path: Optional[Path]) -> Optional[str]:
    """Build ``head + marker + tail`` so the result fits in ``cap`` characters."""
    removed = max(0, len(text) - cap)
    marker = _build_marker(removed, spill_path)
    # The marker contains the removed count, whose digit count depends on the
    # window size: two fixed-point iterations are enough in practice.
    for _ in range(3):
        budget = cap - len(marker)
        if budget < MIN_MARKER_BUDGET:
            return None
        head_len = budget * 3 // 5
        tail_len = budget - head_len
        new_removed = len(text) - head_len - tail_len
        new_marker = _build_marker(new_removed, spill_path)
        if new_marker == marker:
            break
        marker = new_marker
    budget = cap - len(marker)
    if budget < 2:
        return None
    head_len = budget * 3 // 5
    tail_len = budget - head_len
    return f"{text[:head_len]}{marker}{text[len(text) - tail_len :] if tail_len else ''}"


@dataclass(frozen=True)
class TruncatedOutput:
    """Model-facing result of one tool call plus truncation metadata."""

    text: str
    total_chars: int
    #: Spilled full-output path when truncation wrote one (string for JSON/UI use).
    spill_path: Optional[str] = None
    truncated: bool = False


def truncate_tool_output_meta(
    text: Any, tool_name: str, max_chars: Optional[int] = None
) -> TruncatedOutput:
    """Truncate one tool result to its cap and return the result with metadata.

    The metadata (original length, spill path, truncation flag) feeds the Ctrl+O
    viewer so it can show what the model saw and point at the full output.
    """
    if text is None:
        return TruncatedOutput("", 0)
    if not isinstance(text, str):
        text = str(text)
    total_chars = len(text)
    cap = resolve_output_cap(tool_name, max_chars=max_chars)
    if cap <= 0 or total_chars <= cap:
        return TruncatedOutput(text, total_chars)

    spill_path = spill_tool_output(text, tool_name)
    spill_str = str(spill_path) if spill_path is not None else None
    window = _split_around_marker(text, cap, spill_path)
    if window is not None:
        return TruncatedOutput(window, total_chars, spill_str, True)

    # Tiny cap (smaller than the marker): plain truncation is all that fits.
    if spill_path is not None:
        suffix = f"\n...[truncated {total_chars - cap} chars; full output saved to {spill_path}]..."
        keep = cap - len(suffix)
        if keep > 0:
            return TruncatedOutput(text[:keep] + suffix, total_chars, spill_str, True)
    return TruncatedOutput(text[:cap], total_chars, spill_str, True)


def truncate_tool_output(text: Any, tool_name: str, max_chars: Optional[int] = None) -> str:
    """Truncate one tool result to its cap, spilling the full text to disk.

    Returns ``text`` unchanged when it fits (or truncation is disabled). When it
    does not fit, the full text is spilled to ``TOOL_OUTPUT_DIR`` and replaced by
    a head/tail window with a marker pointing at the spill file; if spilling
    fails the marker just omits the path (plain truncation still succeeds).
    """
    return truncate_tool_output_meta(text, tool_name, max_chars=max_chars).text


@dataclass(frozen=True)
class DisplayPreview:
    """Head-only terminal preview of one tool result (display layer only)."""

    text: str
    truncated: bool = False
    total_lines: int = 0
    total_chars: int = 0
    shown_lines: int = 0
    shown_chars: int = 0
    omitted_lines: int = 0
    omitted_chars: int = 0
    #: Which limit cut the preview: ``"lines"``, ``"chars"`` or ``"none"``.
    limit: str = "none"

    @property
    def label(self) -> str:
        """Short ``first x / y`` label for the panel title."""
        if not self.truncated:
            return ""
        if self.limit == "chars":
            return f"first {self.shown_chars:,} / {self.total_chars:,} chars"
        return f"first {self.shown_lines:,} / {self.total_lines:,} lines"


def _display_limit(value: Optional[int], key: str, default: int) -> int:
    """Resolve a display limit: explicit value > config > default (negative => 0)."""
    if value is None:
        value = _config_int(key, default)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, default)


def make_display_preview(
    text: Any,
    max_lines: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> DisplayPreview:
    """Build the compact head-only preview rendered in the terminal.

    Only the first ``max_lines`` lines and ``max_chars`` characters are kept;
    the caller appends :func:`build_preview_marker` when ``truncated`` is set.
    The model-facing text is produced separately by :func:`truncate_tool_output`,
    so tightening these limits never reduces what the model can see.

    ``max_lines``/``max_chars`` default to ``TOOL_DISPLAY_MAX_LINES`` /
    ``TOOL_DISPLAY_MAX_CHARS`` (``0`` = unlimited for that dimension).
    """
    raw = "" if text is None else str(text)
    line_limit = _display_limit(max_lines, "TOOL_DISPLAY_MAX_LINES", DEFAULT_DISPLAY_MAX_LINES)
    char_limit = _display_limit(max_chars, "TOOL_DISPLAY_MAX_CHARS", DEFAULT_DISPLAY_MAX_CHARS)

    total_chars = len(raw)
    lines = raw.splitlines()
    total_lines = len(lines)

    head = lines if line_limit == 0 else lines[:line_limit]
    preview = "\n".join(head)
    limit = "none"
    if line_limit and len(head) < total_lines:
        limit = "lines"
    if char_limit and len(preview) > char_limit:
        preview = preview[:char_limit]
        limit = "chars"

    truncated = limit != "none"
    if limit == "lines":
        shown_lines = len(head)
    else:
        shown_lines = (preview.count("\n") + 1) if preview else 0
    shown_chars = len(preview)
    return DisplayPreview(
        text=preview,
        truncated=truncated,
        total_lines=total_lines,
        total_chars=total_chars,
        shown_lines=shown_lines,
        shown_chars=shown_chars,
        omitted_lines=max(0, total_lines - shown_lines),
        omitted_chars=max(0, total_chars - shown_chars),
        limit=limit,
    )


def build_preview_marker(preview: DisplayPreview) -> str:
    """Return the one-line ``… +N lines · Ctrl+O to expand`` marker (or ``""``)."""
    if not preview.truncated:
        return ""
    if preview.limit == "chars":
        omitted = f"+{preview.omitted_chars:,} chars"
    else:
        omitted = f"+{preview.omitted_lines:,} lines"
    return f"… {omitted} · {DISPLAY_EXPAND_HINT}"


def _summarize_argument_value(value: Any) -> str:
    """Render one argument value, summarizing large strings/collections."""
    if isinstance(value, str):
        if "\n" not in value and len(value) <= _ARGUMENT_VALUE_SUMMARY_OVER:
            return json.dumps(value, ensure_ascii=False)
        first_line = value.split("\n", 1)[0]
        clipped = first_line[: _ARGUMENT_VALUE_HEAD_CHARS - 1].rstrip() + "…"
        return f"{json.dumps(clipped, ensure_ascii=False)} <{len(value):,} chars>"
    if isinstance(value, (list, dict)):
        rendered = json.dumps(value, ensure_ascii=False)
        if len(rendered) <= _ARGUMENT_VALUE_SUMMARY_OVER:
            return rendered
        return f"<{len(rendered):,} chars>"
    return json.dumps(value, ensure_ascii=False)


def _clip_with_ellipsis(text: str, limit: int) -> str:
    """Clip ``text`` to at most ``limit`` characters, ending with ``…``."""
    if limit <= 0:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def summarize_arguments(arguments: Any, max_chars: Optional[int] = None) -> str:
    """Return a compact one-line preview of tool-call arguments for the console.

    Short arguments stay close to their original form (whitespace collapsed).
    Large values are replaced by their first line plus ``<N chars>`` so a
    ``fs_write_file`` call can no longer flood the terminal. ``max_chars``
    defaults to ``TOOL_CALL_PREVIEW_MAX_CHARS``; ``0`` keeps the raw arguments.
    """
    raw = "" if arguments is None else str(arguments)
    limit = _display_limit(max_chars, "TOOL_CALL_PREVIEW_MAX_CHARS", DEFAULT_CALL_PREVIEW_MAX_CHARS)
    if limit == 0:
        return raw

    collapsed = " ".join(raw.split())
    if len(collapsed) <= limit:
        return collapsed

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict) and parsed:
        pieces = [
            f"{json.dumps(str(key), ensure_ascii=False)}: {_summarize_argument_value(value)}"
            for key, value in parsed.items()
        ]
        summarized = "{" + ", ".join(pieces) + "}"
        if len(summarized) <= limit:
            return summarized
        return _clip_with_ellipsis(summarized, limit)
    return _clip_with_ellipsis(collapsed, limit)


def get_output_cap(tool_name: str) -> int:
    """Convenience accessor: the effective cap for ``tool_name`` (``0`` = none)."""
    return resolve_output_cap(tool_name)


__all__ = [
    "DEFAULT_CALL_PREVIEW_MAX_CHARS",
    "DEFAULT_DISPLAY_MAX_CHARS",
    "DEFAULT_DISPLAY_MAX_LINES",
    "DEFAULT_OUTPUT_MAX_CHARS",
    "DISPLAY_EXPAND_HINT",
    "DisplayPreview",
    "MIN_MARKER_BUDGET",
    "TOOL_OUTPUT_CAPS",
    "TruncatedOutput",
    "build_preview_marker",
    "make_display_preview",
    "resolve_output_cap",
    "get_output_cap",
    "spill_tool_output",
    "summarize_arguments",
    "truncate_tool_output",
    "truncate_tool_output_meta",
]
