from os.path import exists

from prompt_toolkit.history import FileHistory, _StrOrBytesPath


class LimitedFileHistory(FileHistory):
    """Limited file history.

    This class extends the FileHistory class from prompt_toolkit.history.
    It adds a limit to the number of entries in the history file.
    """

    def __init__(self, filename: _StrOrBytesPath, max_entries: int = 500, trim_every: int = 2):
        """Initialize the LimitedFileHistory object.

        Args:
            filename: Path to the history file
            max_entries: Maximum number of entries to keep
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

        Call the original method to deposit a new record.
        """
        super().store_string(string)

        self._append_count += 1
        if self._append_count >= self._trim_every:
            self._trim_history()
            self._append_count = 0

    def _trim_history(self):
        """Trim the history file to the specified maximum number of entries."""
        if not exists(self.filename):
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
