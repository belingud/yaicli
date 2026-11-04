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

Standard library only: this module runs inside the tool-call path.
"""

import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from ..config import cfg
from ..const import DEFAULT_TOOL_OUTPUT_DIR, DEFAULT_TOOL_OUTPUT_MAX_CHARS

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


def truncate_tool_output(text: Any, tool_name: str, max_chars: Optional[int] = None) -> str:
    """Truncate one tool result to its cap, spilling the full text to disk.

    Returns ``text`` unchanged when it fits (or truncation is disabled). When it
    does not fit, the full text is spilled to ``TOOL_OUTPUT_DIR`` and replaced by
    a head/tail window with a marker pointing at the spill file; if spilling
    fails the marker just omits the path (plain truncation still succeeds).
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    cap = resolve_output_cap(tool_name, max_chars=max_chars)
    if cap <= 0 or len(text) <= cap:
        return text

    spill_path = spill_tool_output(text, tool_name)
    window = _split_around_marker(text, cap, spill_path)
    if window is not None:
        return window

    # Tiny cap (smaller than the marker): plain truncation is all that fits.
    if spill_path is not None:
        suffix = f"\n...[truncated {len(text) - cap} chars; full output saved to {spill_path}]..."
        keep = cap - len(suffix)
        if keep > 0:
            return text[:keep] + suffix
    return text[:cap]


def get_output_cap(tool_name: str) -> int:
    """Convenience accessor: the effective cap for ``tool_name`` (``0`` = none)."""
    return resolve_output_cap(tool_name)


__all__ = [
    "DEFAULT_OUTPUT_MAX_CHARS",
    "MIN_MARKER_BUDGET",
    "TOOL_OUTPUT_CAPS",
    "resolve_output_cap",
    "get_output_cap",
    "spill_tool_output",
    "truncate_tool_output",
]
