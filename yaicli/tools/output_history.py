"""Turn-tagged history of tool outputs for the Ctrl+O full-screen viewer.

The REPL only stores the *display* copy of each tool result here; the source of
truth for large outputs remains ``TOOL_OUTPUT_DIR`` (see
``yaicli/tools/limits.py``). Entries are grouped by turn (one user input may run
many tool rounds) so the viewer can show "this turn's outputs" by default and
fall back to the most recent turn when the current one has no tools yet.
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

#: Maximum number of tool outputs kept in memory per process.
MAX_ENTRIES = 100


@dataclass(frozen=True)
class ToolOutputEntry:
    """One recorded tool result (the model-visible, already truncated text)."""

    #: Monotonic sequence number across the session (1-based); also the viewer id.
    index: int
    #: Turn number (incremented for every user input processed).
    turn: int
    #: ``"function"`` or ``"mcp"``.
    kind: str
    #: Tool name as reported by the LLM.
    name: str
    #: Compact argument summary (same text shown on the call line).
    arguments: str
    #: Result text that was sent to the model (``TOOL_OUTPUT_MAX_CHARS`` cap).
    text: str
    #: Length of the original, untruncated tool result.
    total_chars: int
    #: Path of the spilled full output, when truncation produced one.
    spill_path: Optional[str]
    #: Whether the result was truncated for the model context.
    truncated: bool


_entries: Deque[ToolOutputEntry] = deque(maxlen=MAX_ENTRIES)
_sequence = 0
_turn = 0


def begin_turn() -> int:
    """Start a new conversation turn and return its number."""
    global _turn
    _turn += 1
    return _turn


def current_turn() -> int:
    """Return the current turn number (``0`` before the first input)."""
    return _turn


def record_output(
    *,
    kind: str,
    name: str,
    arguments: str,
    text: str,
    total_chars: int,
    spill_path: Optional[str] = None,
    truncated: bool = False,
) -> ToolOutputEntry:
    """Append one tool result to the in-memory history."""
    global _sequence
    _sequence += 1
    entry = ToolOutputEntry(
        index=_sequence,
        turn=_turn,
        kind=kind,
        name=name,
        arguments=arguments,
        text=text,
        total_chars=total_chars,
        spill_path=spill_path,
        truncated=truncated,
    )
    _entries.append(entry)
    return entry


def all_outputs() -> List[ToolOutputEntry]:
    """Return every recorded output, oldest first."""
    return list(_entries)


def last_output() -> Optional[ToolOutputEntry]:
    """Return the most recent output, or ``None``."""
    return _entries[-1] if _entries else None


def _entries_for_turn(turn: int) -> List[ToolOutputEntry]:
    return [entry for entry in _entries if entry.turn == turn]


def viewer_outputs() -> Tuple[List[ToolOutputEntry], str]:
    """Return ``(entries, label)`` for the Ctrl+O viewer.

    The current turn's outputs are preferred (``label == "this turn"``); when the
    current turn has no tool calls yet (e.g. Ctrl+O right after a slash command),
    fall back to the most recent turn that has some (``label == "last turn"``).
    """
    current = _entries_for_turn(_turn) if _turn else []
    if current:
        return current, "this turn"
    if not _entries:
        return [], ""
    last_turn = _entries[-1].turn
    return _entries_for_turn(last_turn), "last turn"


def reset() -> None:
    """Clear the history (tests / a fresh session)."""
    global _sequence, _turn
    _entries.clear()
    _sequence = 0
    _turn = 0
