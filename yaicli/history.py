import os
from os.path import exists
from pathlib import Path
from typing import Optional, Union

from prompt_toolkit.history import FileHistory, _StrOrBytesPath

#: Prompt history holds everything the user typed, including pasted secrets:
#: keep the file private and the directories that lead to it private too.
HISTORY_FILE_MODE = 0o600
HISTORY_DIR_MODE = 0o700


def _chmod_quietly(path: Path, mode: int) -> None:
    """Best-effort POSIX mode change (no-op on platforms without chmod)."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def prepare_history_file(filename: Union[str, Path]) -> Optional[Path]:
    """Create the REPL history file/directories with private permissions (K13).

    ``~/.yaicli_history`` contains every prompt typed into the REPL (possibly
    including secrets), so it is created as ``0600`` and the directories the code
    creates for it (``~/.yaicli`` or ``$XDG_STATE_HOME/yaicli``) as ``0700``.
    Modes are best effort: filesystems without POSIX permissions keep working.

    Returns:
        The path when preparation was attempted, ``None`` for non-path inputs
        (defensive: test doubles implement ``__fspath__`` and would otherwise
        materialise mock-named directories in the current working directory).

    Raises:
        OSError: when the file/dir cannot be created (read-only HOME). Callers
            fall back to in-memory history; this helper never swallows it so the
            existing K21 tolerance path stays in control.
    """
    if not isinstance(filename, (str, Path)):
        return None
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_quietly(path.parent, HISTORY_DIR_MODE)
    path.touch(exist_ok=True)
    _chmod_quietly(path, HISTORY_FILE_MODE)
    return path


class LimitedFileHistory(FileHistory):
    """Limited file history.

    This class extends the FileHistory class from prompt_toolkit.history.
    It adds a limit to the number of entries in the history file.

    A non-positive ``max_entries`` disables history saving completely
    (the documented ``MAX_HISTORY=0`` behaviour).
    """

    def __init__(self, filename: _StrOrBytesPath, max_entries: int = 500, trim_every: int = 2):
        """Initialize the LimitedFileHistory object.

        Args:
            filename: Path to the history file
            max_entries: Maximum number of entries to keep; <= 0 disables saving
            trim_every: Trim history every `trim_every` appends

        Examples:
            >>> history = LimitedFileHistory("~/.yaicli_history", max_entries=500, trim_every=10)
            >>> history.append_string("echo hello")
            >>> history.append_string("echo world")
            >>> session = PromptSession(history=history)
        """
        self.max_entries = max_entries
        self._append_count = 0
        self._trim_every = trim_every
        super().__init__(filename)

    def store_string(self, string: str) -> None:
        """Store a string in the history file.

        Call the original method to deposit a new record. A non-positive
        ``max_entries`` limit disables saving, so nothing is written and the
        trim counter is not advanced.
        """
        if self.max_entries <= 0:
            return

        super().store_string(string)
        # prompt_toolkit may have created the file itself (first append): make
        # sure the on-disk history is private even when it predates K13.
        _chmod_quietly(Path(self.filename), HISTORY_FILE_MODE)

        self._append_count += 1
        if self._append_count >= self._trim_every:
            self._trim_history()
            self._append_count = 0

    def _trim_history(self):
        """Trim the history file to the specified maximum number of entries.

        With a non-positive ``max_entries`` no records are kept at all.
        """
        if not exists(self.filename):
            return

        if self.max_entries <= 0:
            with open(self.filename, "w", encoding="utf-8"):
                pass
            _chmod_quietly(Path(self.filename), HISTORY_FILE_MODE)
            return

        with open(self.filename, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # By record: each record starts with "# timestamp" followed by a number of "+lines".
        entries = []
        current_entry = []

        for line in lines:
            if line.startswith("# "):
                if current_entry:
                    entries.append(current_entry)
                current_entry = [line]
            elif line.startswith("+") or line.strip() == "":
                current_entry.append(line)

        if current_entry:
            entries.append(current_entry)

        # Keep the most recent max_entries row (the next row is newer)
        trimmed_entries = entries[-self.max_entries :]

        with open(self.filename, "w", encoding="utf-8") as f:
            for entry in trimmed_entries:
                f.writelines(entry)
        _chmod_quietly(Path(self.filename), HISTORY_FILE_MODE)
