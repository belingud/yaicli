"""Custom completers for yaicli (``@path`` references and slash commands)."""

from pathlib import Path
from typing import Iterable, Optional, Tuple

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from .cmd_handler import command_completions


class AtPathCompleter(Completer):
    """Path completer triggered by @ symbol or context commands."""

    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or Path.cwd()

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        """Generate path completions based on input."""
        text = document.text_before_cursor

        # Check if we're in a context command
        if self._is_context_command(text):
            yield from self._get_command_completions(document)
        # Check for @ trigger
        elif "@" in text:
            yield from self._get_at_completions(document)

    def _is_context_command(self, text: str) -> bool:
        """Check if text starts with a context command."""
        commands = ["/add ", "/context add ", "/ctx add ", "/context remove ", "/ctx remove "]
        return any(text.startswith(cmd) for cmd in commands)

    def _get_command_completions(self, document: Document) -> Iterable[Completion]:
        """Get completions for /add or /context commands."""
        text = document.text_before_cursor

        # Extract the part after the command
        for cmd in [
            "/add ",
            "/context add ",
            "/ctx add ",
            "/context remove ",
            "/ctx remove ",
            "/ctx rm ",
            "/context rm ",
        ]:
            if text.startswith(cmd):
                partial_path = text[len(cmd) :]
                partial_path = text[len(cmd) :]
                if partial_path.startswith("@"):
                    yield from self._generate_path_completions(partial_path[1:], start_offset=-len(partial_path) + 1)
                else:
                    yield from self._generate_path_completions(partial_path, start_offset=-len(partial_path))
                return

    def _get_at_completions(self, document: Document) -> Iterable[Completion]:
        """Get completions for @ trigger."""
        text = document.text_before_cursor
        at_index = text.rfind("@")

        if at_index == -1:
            return

        # Extract partial path after @
        partial_path = text[at_index + 1 :]

        # Generate completions with @ prefix in display
        for completion in self._generate_path_completions(partial_path, start_offset=-len(partial_path)):
            # Add @ to display text (keep as string)
            yield Completion(
                text=completion.text,
                start_position=completion.start_position,
                display=f"@{completion.text}",  # Use text instead of display
                display_meta=completion.display_meta,
            )

    def _generate_path_completions(self, partial_path: str, start_offset: int = 0) -> Iterable[Completion]:
        """Generate file/directory completions for a partial path."""
        try:
            # Expand user home directory
            if partial_path.startswith("~"):
                partial_path = str(Path(partial_path).expanduser())

            # Determine base directory and search pattern
            if partial_path.startswith("/"):
                # Absolute path
                search_path = Path(partial_path)
            elif partial_path.startswith("./") or partial_path.startswith("../"):
                # Relative path with ./ or ../
                search_path = self.base_dir / partial_path
            else:
                # Relative path without prefix
                search_path = self.base_dir / partial_path

            # Split into directory and partial filename
            if search_path.is_dir() and (partial_path.endswith("/") or not partial_path):
                dir_path = search_path
                partial_name = ""
            else:
                dir_path = search_path.parent
                partial_name = search_path.name

            # Ensure directory exists
            if not dir_path.exists():
                return

            # Generate completions
            for path in sorted(dir_path.iterdir()):
                name = path.name

                # Filter by partial name (case-insensitive for better UX)
                if not name.lower().startswith(partial_name.lower()):
                    continue

                # Calculate relative path from base_dir
                try:
                    relative = path.relative_to(self.base_dir)
                    display_path = str(relative)
                except ValueError:
                    # If not relative to base_dir, use absolute
                    display_path = str(path)

                # Add / suffix for directories
                if path.is_dir():
                    completion_text = display_path + "/"
                    meta = "[DIR]"
                else:
                    completion_text = display_path
                    # Show file extension as meta
                    meta = path.suffix or "[FILE]"

                # Quote path if it contains spaces
                if " " in completion_text:
                    completion_text = f'"{completion_text}"'

                yield Completion(
                    text=completion_text, start_position=start_offset, display=completion_text, display_meta=meta
                )

        except (OSError, PermissionError):
            # Silently ignore permission errors
            return


class SlashCommandCompleter(Completer):
    """Slash-command completer with a one-line description in the meta column.

    It fires only while the first token is being typed (text before the cursor
    starts with ``/`` and has no whitespace yet), so argument completion still
    belongs to :class:`AtPathCompleter` and the individual commands. The command
    list comes from ``cmd_handler.command_completions()`` — the same metadata
    source ``CLI.print_help()`` renders.
    """

    def __init__(self, commands: Optional[Iterable[Tuple[str, str]]] = None):
        self.commands: Tuple[Tuple[str, str], ...] = tuple(commands) if commands is not None else command_completions()

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        """Offer every registered command matching the typed ``/`` prefix."""
        text = document.text_before_cursor
        if not text.startswith("/") or any(char.isspace() for char in text):
            return
        lowered = text.lower()
        for command, description in self.commands:
            if command.lower().startswith(lowered):
                yield Completion(
                    text=command,
                    start_position=-len(text),
                    display=command,
                    display_meta=description,
                )


class ReplCompleter(Completer):
    """Composite REPL completer: slash commands plus the existing ``@path`` one.

    The two completers trigger on different input shapes (``/token`` vs ``@`` or
    the ``/add``/``/context add`` prefixes), so composing them keeps ``@path``
    completion intact while adding command completion.
    """

    def __init__(self, path_completer: Optional[Completer] = None, commands=None, base_dir: Optional[Path] = None):
        self.path_completer: Completer = (
            path_completer if path_completer is not None else AtPathCompleter(base_dir=base_dir)
        )
        self.slash_completer = SlashCommandCompleter(commands)

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        """Merge slash-command and path completions for the current input."""
        yield from self.slash_completer.get_completions(document, complete_event)
        yield from self.path_completer.get_completions(document, complete_event)
