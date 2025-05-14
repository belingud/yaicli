import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from rich.table import Table

from .config import cfg
from .console import YaiConsole, get_console
from .schemas import ChatMessage
from .exceptions import ChatDeleteError, ChatLoadError, ChatSaveError
from .utils import option_callback

console: YaiConsole = get_console()


@dataclass
class Chat:
    """Single chat session"""

    idx: Optional[str] = None
    title: str = field(default_factory=lambda: f"Chat {datetime.now().strftime('%Y%m%d-%H%M%S')}")
    history: List[ChatMessage] = field(default_factory=list)
    date: str = field(default_factory=lambda: datetime.now().isoformat())
    path: Optional[Path] = None

    def add_message(self, role: str, content: str) -> None:
        """Add message to the session"""
        self.history.append(ChatMessage(role=role, content=content))

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

    def load(self) -> bool:
        """Load chat history from file

        Returns:
            bool: True if successful, False otherwise
        """
        if self.path is None or not self.path.exists():
            return False

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.title = data.get("title", self.title)
                self.date = data.get("date", self.date)
                self.history = [ChatMessage(role=msg["role"], content=msg["content"]) for msg in data.get("history", [])]
            return True
        except (json.JSONDecodeError, OSError) as e:
            raise ChatLoadError(f"Error loading chat: {e}") from e

    def save(self, chat_dir: Path) -> bool:
        """Save chat to file

        Args:
            chat_dir: Directory to save chat file

        Returns:
            bool: True if successful, False otherwise

        Raises:
            ChatSaveError: If there's an error saving the chat
        """
        if not self.history:
            raise ChatSaveError("No history in chat to save")

        # Ensure chat has a title
        if not self.title:
            self.title = f"Chat-{int(time.time())}"

        # Update timestamp if not set
        if not self.date:
            self.date = datetime.now().isoformat()

        # Create a descriptive filename with timestamp and title
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-title-{self.title}.json"
        chat_path = chat_dir / filename

        try:
            # Save the chat as JSON
            with open(chat_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

            # Update chat's path to the new file
            self.path = chat_path
            return True
        except Exception as e:
            error_msg = f"Error saving chat '{self.title}': {e}"
            raise ChatSaveError(error_msg) from e


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
                chat.idx = str(i + 1)

                # Add to maps
                chats_map["title"][chat.title] = chat
                chats_map["index"][str(i + 1)] = chat
            except Exception as e:
                # Log the error but continue processing other files
                raise ChatLoadError(f"Error parsing session file {chat_file}: {e}") from e

        self._chats_map = chats_map

    def new_chat(self, title: str = "") -> Chat:
        """Create a new chat session"""
        chat_id = str(int(time.time()))
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

        Args:
            chat (Optional[Chat], optional): The chat to save. If None, uses current_chat.

        Returns:
            str: The title of the saved chat

        Raises:
            ChatSaveError: If there's an error saving the chat
        """
        if chat is None:
            chat = self.current_chat

        if chat is None:
            raise ChatSaveError("No chat found")

        # Check for existing chat with the same title and delete it
        if chat.title:
            self._delete_existing_chat_with_title(chat.title)

        # Save the chat using its own method - this will throw ChatSaveError if it fails
        chat.save(self.chat_dir)

        # If we get here, the save was successful
        # Clean up old chats if we exceed the maximum
        self._cleanup_old_chats()

        # Reset the chats map to force a refresh on next access
        self._chats_map = None

        return chat.title

    def _delete_existing_chat_with_title(self, title: str) -> None:
        """Delete any existing chat with the given title"""
        if not title:
            return

        # Use chats_map to find the chat by title
        if title in self.chats_map["title"]:
            chat = self.chats_map["title"][title]
            if chat.path and chat.path.exists():
                try:
                    chat.path.unlink()
                    # Reset the chats map to force a refresh
                    self._chats_map = None
                except OSError as e:
                    raise ChatDeleteError(f"Warning: Failed to delete existing chat file {chat.path}: {e}") from e

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

    def load_chat(self, chat_id: str) -> Chat:
        """Load a chat session by ID"""
        chat_path = self.chat_dir / f"{chat_id}.json"

        if not chat_path.exists():
            return Chat(idx=chat_id)

        # Create a chat object with the path and load its history
        chat = Chat(idx=chat_id, path=chat_path)
        if chat.load():
            self.current_chat = chat
            return chat
        else:
            return Chat(idx=chat_id)

    def load_chat_by_index(self, index: str) -> Chat:
        """Load a chat session by index"""
        if index not in self.chats_map["index"]:
            return Chat(idx=index)

        chat = self.chats_map["index"][index]
        if chat.path is None:
            return chat

        # Load the chat history using the Chat class's load method
        if chat.load():
            self.current_chat = chat
        return chat

    def load_chat_by_title(self, title: str) -> Chat:
        """Load a chat session by title"""
        if title not in self.chats_map["title"]:
            return Chat(title=title)

        chat = self.chats_map["title"][title]
        if chat.path is None:
            return chat

        # Load the chat history using the Chat class's load method
        if chat.load():
            self.current_chat = chat
        return chat

    def validate_chat_index(self, index: Union[str, int]) -> bool:
        """Validate a chat index and return success status"""
        return index in self.chats_map["index"]

    def refresh_chats(self) -> None:
        """Force refresh the chat list from disk"""
        self._chats_map = None
        # This will trigger a reload on next access

    def list_chats(self) -> List[Chat]:
        """List all saved chat sessions"""
        return list(self.chats_map["index"].values())

    def delete_chat(self, chat_path: os.PathLike) -> bool:
        """Delete a chat session by path"""
        path = Path(chat_path)
        if not path.exists():
            return False

        try:
            path.unlink()

            # If the current chat is deleted, set it to None
            if self.current_chat and self.current_chat.path == path:
                self.current_chat = None

            # Reset the chats map to force a refresh on next access
            self._chats_map = None

            return True
        except (OSError, IOError) as e:
            raise ChatDeleteError(f"Error deleting chat: {e}") from e

    def delete_chat_by_index(self, index: str) -> bool:
        """Delete a chat session by index"""
        if not self.validate_chat_index(index):
            return False

        chat = self.chats_map["index"][index]
        if chat.path is None:
            return False

        return self.delete_chat(chat.path)

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
        return Chat(title=title, date=date_str, path=chat_file)


# Create a global chat manager instance
chat_mgr = FileChatManager()
