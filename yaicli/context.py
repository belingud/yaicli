from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from rich.table import Table

from .console import get_console
from .schemas import ChatMessage

console = get_console()


@dataclass
class ContextItem:
    """Item in the context (file or directory)"""

    path: str
    type: str  # "file" or "dir"
    content: Optional[str] = None
    ignored_patterns: List[str] = field(default_factory=list)


class ContextManager:
    """Manages the context for the AI session"""

    def __init__(self):
        self.items: Dict[str, ContextItem] = {}
        # Default ignored patterns when adding directories
        self.default_ignores = {
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
            ".idea",
            ".vscode",
            ".DS_Store",
        }

    def add(self, path_str: str) -> bool:
        """Add a file or directory to context.

        Args:
            path_str: Path to file or directory

        Returns:
            bool: True if added successfully
        """
        path = Path(path_str).expanduser().resolve()

        if not path.exists():
            console.print(f"Error: Path does not exist: {path}", style="bold red")
            return False

        if str(path) in self.items:
            console.print(f"Path already in context: {path}", style="yellow")
            return True

        if path.is_file():
            self.items[str(path)] = ContextItem(path=str(path), type="file")
            console.print(f"Added file to context: {path}", style="green")
            return True
        elif path.is_dir():
            self.items[str(path)] = ContextItem(path=str(path), type="dir")
            console.print(f"Added directory to context: {path}", style="green")
            return True
        else:
            console.print(f"Error: Unsupported path type: {path}", style="bold red")
            return False

    def remove(self, path_str: str) -> bool:
        """Remove a path from context.

        Args:
            path_str: Path can be partial match or full path

        Returns:
            bool: True if removed successfully
        """
        # Try exact match first
        path = Path(path_str).expanduser().resolve()
        if str(path) in self.items:
            del self.items[str(path)]
            console.print(f"Removed from context: {path}", style="green")
            return True

        # Try matching by name
        matches = [p for p in self.items.keys() if path_str in p or Path(p).name == path_str]

        if len(matches) == 1:
            del self.items[matches[0]]
            console.print(f"Removed from context: {matches[0]}", style="green")
            return True
        elif len(matches) > 1:
            console.print(f"Multiple matches found for '{path_str}':", style="yellow")
            for m in matches:
                console.print(f"  - {m}")
            console.print("Please specify unique path.", style="yellow")
            return False
        else:
            console.print(f"Path not found in context: {path_str}", style="yellow")
            return False

    def clear(self) -> None:
        """Clear all context items"""
        self.items.clear()
        console.print("Context cleared.", style="green")

    def list_items(self) -> None:
        """Print current context items"""
        if not self.items:
            console.print("Context is empty.", style="yellow")
            return

        table = Table(title="Current Context")
        table.add_column("Type", style="cyan", width=8)
        table.add_column("Path", style="green")

        for item in self.items.values():
            # Show formatted path relative to cwd if possible for readability
            try:
                display_path = Path(item.path).relative_to(Path.cwd())
            except ValueError:
                display_path = item.path

            table.add_row(item.type.upper(), str(display_path))

        console.print(table)

    def get_context_messages(self) -> List[ChatMessage]:
        """Get context items as format of ChatMessage list"""
        if not self.items:
            return []

        messages = []
        context_content = ["The following files are added to the context:\n"]

        for item in self.items.values():
            path = Path(item.path)
            if item.type == "file":
                content = self._read_file(path)
                if content is not None:
                    context_content.append(f"## File: {path.name}\nPath: {path}\n```\n{content}\n```\n")
            elif item.type == "dir":
                # For directories, valid recursively (with limit)
                # For now, let's just go 2 levels deep to avoid massive context
                self._read_dir_recursive(path, context_content, 0, 2)

        full_content = "\n".join(context_content)
        messages.append(ChatMessage(role="system", content=full_content))
        return messages

    def parse_at_references(self, text: str) -> tuple[str, str]:
        """Parse @ file references from text and read their content.

        This method extracts @path references from the input text, reads the file
        contents, and returns both the file contents as a formatted message and
        the original text with @ references replaced by file names.

        Args:
            text: Input text potentially containing @path references

        Returns:
            Tuple of (file_contents_message, cleaned_text)
        """
        import re

        # Find all @path patterns, supporting quoted paths
        # Group 1: Double/Single quoted path (e.g. @"foo bar.txt" or @'foo bar.txt')
        # Group 2: Unquoted path (e.g. @foo.txt)
        pattern = r'@(?:["\']([^"\']+)["\']|([\w\-_./]+(?:\.\w+)?))'
        matches = re.finditer(pattern, text)

        if not matches:
            return "", text

        file_contents = ["Referenced files for this query:\n"]
        cleaned_text = text

        # Collect all matches first to avoid modification issues during iteration
        for match in matches:
            # Get the path from either group 1 (quoted) or group 2 (unquoted)
            path_str = match.group(1) or match.group(2)
            if not path_str:
                continue

            full_match = match.group(0)  # e.g. @"foo bar.txt"
            try:
                path = Path(path_str).expanduser().resolve()
                if not path.exists():
                    # Try relative to current directory
                    path = Path.cwd() / path_str

                if path.exists() and path.is_file():
                    content = self._read_file(path)
                    # Check if content is valid text (not an error/warning message starting with [)
                    if content and not content.strip().startswith("["):
                        file_contents.append(f"\n## File: {path.name}\nPath: {path}\n```\n{content}\n```\n")
                        cleaned_text = cleaned_text.replace(full_match, f"'{path.name}'")
                    else:
                        # File exists but has issues (binary, too large, error)
                        console.print(f"Warning: Cannot include @{path_str}: {content}", style="yellow")
                        cleaned_text = cleaned_text.replace(full_match, f"'{path.name}'")
            except Exception as e:
                console.print(f"Warning: Could not read @{path_str}: {e}", style="yellow")

        if len(file_contents) > 1:
            return "\n".join(file_contents), cleaned_text
        return "", cleaned_text

    def _read_file(self, path: Path) -> Optional[str]:
        """Safely read file content"""
        try:
            # Skip binary files roughly
            # This is a simple check, could be improved
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar", ".gz", ".pyc"}:
                return "[Binary file omitted]"

            # Skip if file is too large (e.g. > 1MB)
            if path.stat().st_size > 1_000_000:
                return f"[File too large: {path.stat().st_size} bytes - omitted]"

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            console.print(f"Error reading file {path}: {e}", style="red")
            return f"[Error reading file: {e}]"

    def _read_dir_recursive(self, dir_path: Path, content_list: List[str], current_depth: int, max_depth: int):
        """Recursively read directory content"""
        if current_depth > max_depth:
            return

        try:
            for child in dir_path.iterdir():
                if child.name in self.default_ignores:
                    continue
                if child.name.startswith("."):
                    continue

                if child.is_file():
                    file_content = self._read_file(child)
                    if file_content:
                        content_list.append(f"## File: {child.name}\nPath: {child}\n```\n{file_content}\n```\n")
                elif child.is_dir():
                    self._read_dir_recursive(child, content_list, current_depth + 1, max_depth)
        except Exception as e:
            console.print(f"Error scanning directory {dir_path}: {e}", style="red")


# Global instance
ctx_mgr = ContextManager()
