import json
import os
from pathlib import Path
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from rich.table import Table

from yaicli.config import cfg
from yaicli.console import YaiConsole, get_console
from yaicli.providers.base import Message
from yaicli.utils import option_callback

console: YaiConsole = get_console()


@dataclass
class Chat:
    """Single chat session"""

    idx: Optional[str] = None
    title: str = field(default_factory=lambda: f"Chat {datetime.now().strftime('%Y%m%d-%H%M%S')}")
    history: List[Message] = field(default_factory=list)
    date: str = field(default_factory=lambda: datetime.now().isoformat())
    path: Optional[Path] = None

    def add_message(self, role: str, content: str) -> None:
        """Add message to the session"""
        self.history.append(Message(role=role, content=content))

    def to_dict(self) -> Dict:
        """Convert to dictionary representation"""
        return {
            "title": self.title,
            "date": self.date,
            "history": [{"role": msg.role, "content": msg.content} for msg in self.history],
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Chat":
        """Create Chat instance from dictionary"""
        chat = cls(
            idx=data.get("idx", None),
            title=data.get("title", None),
            date=data.get("date", datetime.now().isoformat()),
            path=data.get("path", None),
        )

        for msg_data in data.get("history", []):
            chat.add_message(msg_data["role"], msg_data["content"])

        return chat


@dataclass
class FileChatManager:
    """File system chat manager"""

    chat_dir: Path = field(default_factory=lambda: Path(cfg["CHAT_HISTORY_DIR"]))
    max_saved_chats: int = field(default_factory=lambda: cfg["MAX_SAVED_CHATS"])
    current_chat: Optional[Chat] = None
    _chats_map: Optional[Dict[str, Dict[str, Chat]]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.chat_dir, Path):
            self.chat_dir = Path(self.chat_dir)
        if not self.chat_dir.exists():
            self.chat_dir.mkdir(parents=True, exist_ok=True)

    @property
    def chats_map(self) -> Dict[str, Dict[str, Chat]]:
        """Get the map of chats, loading from disk only when needed"""
        if self._chats_map is None:
            self._load_chats()
        return self._chats_map or {"index": {}, "title": {}}

    def _load_chats(self) -> None:
        """Load chats from disk into memory"""
        chat_files = sorted(list(self.chat_dir.glob("*.json")), key=lambda f: f.stat().st_mtime, reverse=True)
        chats_map = {"title": {}, "index": {}}

        for i, chat_file in enumerate(chat_files[: self.max_saved_chats]):
            try:
                # Parse basic chat info from filename
                chat = self._parse_filename(chat_file)

                # Add to maps
                chats_map["title"][chat.title] = chat
                chats_map["index"][str(i + 1)] = chat
            except Exception as e:
                # Log the error but continue processing other files
                console.print(f"Error parsing session file {chat_file}: {e}", style="dim")
                continue

        self._chats_map = chats_map

    def new_chat(self, title: str = "") -> Chat:
        """Create a new chat session"""
        chat_id = f"chat_{int(time.time())}"
        self.current_chat = Chat(idx=chat_id, title=title)
        return self.current_chat

    def make_chat_title(self, prompt: Optional[str] = None) -> str:
        """Make a chat title from a given full prompt"""
        if prompt:
            return prompt[:100]
        else:
            return f"Chat-{int(time.time())}"

    def save_chat(self, chat: Optional[Chat] = None) -> str:
        """Save chat session to file
        1. Check for existing chat with the same title and delete it
        2. Update chat's idx to match new filename
        3. Save the chat to file
        4. If over the maximum number of saved chats, delete the oldest chat

        Args:
            chat (Optional[Chat], optional): The chat to save. If None, uses current_chat.

        Returns:
            str: The title of the saved chat, or empty string if failed
        """
        if chat is None:
            chat = self.current_chat

        if chat is None:
            return ""

        save_title = chat.title or f"Chat-{int(time.time())}"

        # Check for existing chat with the same title and delete it
        for filename in self.chat_dir.glob("*.json"):
            try:
                with open(filename, "r") as f:
                    file_data = json.load(f)
                    if file_data.get("title") == save_title and file_data.get("idx") != chat.idx:
                        try:
                            filename.unlink()
                        except OSError as e:
                            console.print(f"Warning: Failed to delete existing chat file {filename}: {e}", style="dim")
            except (json.JSONDecodeError, OSError):
                pass

        # Create a more descriptive filename with timestamp and title
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-title-{save_title}.json"
        chat_path = self.chat_dir / filename

        try:
            with open(chat_path, "w", encoding="utf-8") as f:
                json.dump(chat.to_dict(), f, indent=2, ensure_ascii=False)

            # If over the maximum number of saved chats, delete the oldest chat
            self._cleanup_old_chats()

            # Reset the chats map to force a refresh on next access
            self._chats_map = None

            return save_title
        except Exception as e:
            console.print(f"Error saving chat '{save_title}': {e}", style="dim")
            return ""

    def _cleanup_old_chats(self) -> None:
        """Clean up expired chat files"""
        chat_files = []

        for filename in self.chat_dir.glob("*.json"):
            chat_files.append((os.path.getmtime(filename), filename))

        # Sort, the oldest is in the front
        chat_files.sort()

        # If over the maximum number, delete the oldest
        while len(chat_files) > self.max_saved_chats:
            _, oldest_file = chat_files.pop(0)
            try:
                oldest_file.unlink()
            except (OSError, IOError):
                pass

    def load_chat(self, chat_id: str) -> Optional[Chat]:
        """Load a chat session by ID"""
        chat_path = self.chat_dir / f"{chat_id}.json"

        if not chat_path.exists():
            return None

        try:
            with open(chat_path, "r") as f:
                chat_data = json.load(f)

            self.current_chat = Chat.from_dict(chat_data)
            return self.current_chat
        except (json.JSONDecodeError, KeyError):
            return None

    def load_chat_by_index(self, index: str) -> Optional[Chat]:
        """Load a chat session by index"""
        if index not in self.chats_map["index"]:
            return None

        chat = self.chats_map["index"][index]
        if chat.idx is None:
            return None
        return self.load_chat(chat.idx)

    def load_chat_by_title(self, title: str) -> Optional[Chat]:
        """Load a chat session by title"""
        if title not in self.chats_map["title"]:
            return None

        chat = self.chats_map["title"][title]
        if chat.idx is None:
            return None
        return self.load_chat(chat.idx)

    def validate_chat_index(self, index: str) -> bool:
        """Validate a chat index and return success status"""
        return index in self.chats_map["index"]

    def refresh_chats(self) -> None:
        """Force refresh the chat list from disk"""
        self._chats_map = None
        # This will trigger a reload on next access

    def list_chats(self) -> List[Chat]:
        """List all saved chat sessions"""
        return list(self.chats_map["index"].values())

    def delete_chat(self, chat_id: str) -> bool:
        """Delete a chat session by ID"""
        chat_path = self.chat_dir / f"{chat_id}.json"

        if not chat_path.exists():
            return False

        try:
            chat_path.unlink()

            # If the current chat is deleted, set it to None
            if self.current_chat and self.current_chat.idx == chat_id:
                self.current_chat = None

            # Reset the chats map to force a refresh on next access
            self._chats_map = None

            return True
        except (OSError, IOError):
            return False

    def delete_chat_by_index(self, index: str) -> bool:
        """Delete a chat session by index"""
        if not self.validate_chat_index(index):
            return False

        chat = self.chats_map["index"][index]
        if chat.idx is None:
            return False
        return self.delete_chat(chat.idx)

    def print_chats(self) -> None:
        """Print all saved chat sessions"""
        chats = self.list_chats()

        if not chats:
            console.print("No saved chats found.", style="yellow")
            return

        table = Table("ID", "Created At", "Messages", "Title", title="Saved Chats")

        for i, chat in enumerate(chats):
            created_at = datetime.fromisoformat(chat.date).strftime("%Y-%m-%d %H:%M:%S") if chat.date else "Unknown"
            table.add_row(str(i + 1), created_at, str(len(chat.history)), chat.title)

        console.print(table)

    @classmethod
    @option_callback
    def print_list_option(cls, value: bool) -> bool:
        """Print all chat sessions as a typer option callback"""
        if not value:
            return value

        chat_manager = FileChatManager()
        chats = chat_manager.list_chats()
        if not chats:
            console.print("No saved chats found.", style="yellow")
            return value

        for i, chat in enumerate(chats):
            created_at = datetime.fromisoformat(chat.date).strftime("%Y-%m-%d %H:%M:%S") if chat.date else "Unknown"
            console.print(f"{i + 1}. {chat.title} ({created_at})")
        return value

    @staticmethod
    def _parse_filename(chat_file: Path) -> Chat:
        """Parse a chat filename and extract metadata"""
        # filename: "20250421-214005-title-meaning of life"
        filename = chat_file.stem
        parts = filename.split("-")
        title_str_len = 6  # "title-" marker length

        # Check if the filename has the expected format
        if len(parts) >= 4 and "title" in parts:
            str_title_index = filename.find("title")
            if str_title_index == -1:
                # If "title" is not found, use full filename as the title
                # Just in case, fallback to use fullname, but this should never happen when `len(parts) >= 4 and "title" in parts`
                str_title_index = 0
                title_str_len = 0

            # "20250421-214005-title-meaning of life" ==> "meaning of life"
            title = filename[str_title_index + title_str_len :]
            date_ = parts[0]
            time_ = parts[1]
            # Format date
            date_str = f"{date_[:4]}-{date_[4:6]}-{date_[6:]} {time_[:2]}:{time_[2:4]}"

        else:
            # Fallback for files that don't match expected format
            title = filename
            date_str = ""
            # timestamp = 0

        # Create a minimal Chat object with the parsed info
        return Chat(idx=chat_file.stem, title=title, date=date_str, path=chat_file)


# Create a global chat manager instance
chat_mgr = FileChatManager()
