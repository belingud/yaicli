import json
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, Union

from rich.console import Console

from yaicli.console import get_console
from yaicli.config import Config, cfg
from yaicli.utils import option_callback


class ChatFileInfo(TypedDict):
    """Chat info, parse chat filename and store metadata"""

    index: int
    path: str
    title: str
    date: str
    timestamp: int


class ChatsMap(TypedDict):
    """Chat info cache for chat manager"""

    title: Dict[str, ChatFileInfo]
    index: Dict[int, ChatFileInfo]


class ChatManager(ABC):
    """Abstract base class that defines the chat manager interface"""

    @abstractmethod
    def make_chat_title(self, prompt: Optional[str] = None) -> str:
        """Make a chat title from a given full prompt"""
        pass

    @abstractmethod
    def save_chat(self, history: List[Dict[str, Any]], title: Optional[str] = None) -> str:
        """Save a chat and return the chat title"""
        pass

    @abstractmethod
    def list_chats(self) -> List[ChatFileInfo]:
        """List all saved chats and return the chat list"""
        pass

    @abstractmethod
    def refresh_chats(self) -> None:
        """Force refresh the chat list"""
        pass

    @abstractmethod
    def load_chat_by_index(self, index: int) -> Union[ChatFileInfo, Dict]:
        """Load a chat by index and return the chat data"""
        pass

    @abstractmethod
    def load_chat_by_title(self, title: str) -> Union[ChatFileInfo, Dict]:
        """Load a chat by title and return the chat data"""
        pass

    @abstractmethod
    def delete_chat(self, index: int) -> bool:
        """Delete a chat by index and return success status"""
        pass

    @abstractmethod
    def validate_chat_index(self, index: int) -> bool:
        """Validate a chat index and return success status"""
        pass


class FileChatManager(ChatManager):
    """File system based chat manager implementation"""

    console: Console = get_console()
    config: Config = cfg
    chat_dir = Path(config["CHAT_HISTORY_DIR"])
    max_saved_chats = config["MAX_SAVED_CHATS"]
    chat_dir.mkdir(parents=True, exist_ok=True)

    def __init__(self):
        self._chats_map: Optional[ChatsMap] = None  # Cache for chat map

    @property
    def chats_map(self) -> ChatsMap:
        """Get the map of chats, loading from disk only when needed"""
        if self._chats_map is None:
            self._load_chats()
        return self._chats_map or {"index": {}, "title": {}}

    @classmethod
    @option_callback
    def print_list_option(cls, _: Any):
        """Print the list of chats"""
        cls.console.print("Finding Chats...")
        c = -1
        for c, file in enumerate(sorted(cls.chat_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)):
            info: ChatFileInfo = cls._parse_filename(file, c + 1)
            cls.console.print(f"{c + 1}. {info['title']} ({info['date']})")
        if c == -1:
            cls.console.print("No chats found", style="dim")

    def make_chat_title(self, prompt: Optional[str] = None) -> str:
        """Make a chat title from a given full prompt"""
        if prompt:
            return prompt[:100]
        else:
            return f"Chat-{int(time.time())}"

    def validate_chat_index(self, index: int) -> bool:
        """Validate a chat index and return success status"""
        return index > 0 and index in self.chats_map["index"]

    def refresh_chats(self) -> None:
        """Force refresh the chat list from disk"""
        self._load_chats()

    @staticmethod
    def _parse_filename(chat_file: Path, index: int) -> ChatFileInfo:
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

            # Calculate timestamp from date parts
            try:
                date_time_str = f"{date_}{time_}"
                timestamp = int(datetime.strptime(date_time_str, "%Y%m%d%H%M%S").timestamp())
            except ValueError:
                timestamp = 0
        else:
            # Fallback for files that don't match expected format
            title = filename
            date_str = ""
            timestamp = 0

        # The actual title is stored in the JSON file, so we'll use that when loading
        # This is just for the initial listing before the file is opened
        return {
            "index": index,
            "path": str(chat_file),
            "title": title,
            "date": date_str,
            "timestamp": timestamp,
        }

    def _load_chats(self) -> None:
        """Load chats from disk into memory"""
        chat_files = sorted(list(self.chat_dir.glob("*.json")), reverse=True)
        chats_map: ChatsMap = {"title": {}, "index": {}}

        for i, chat_file in enumerate(chat_files[: self.max_saved_chats]):
            try:
                info = self._parse_filename(chat_file, i + 1)
                chats_map["title"][info["title"]] = info
                chats_map["index"][i + 1] = info
            except Exception as e:
                # Log the error but continue processing other files
                self.console.print(f"Error parsing session file {chat_file}: {e}", style="dim")
                continue

        self._chats_map = chats_map

    def list_chats(self) -> List[ChatFileInfo]:
        """List all saved chats and return the chat list"""
        return list(self.chats_map["index"].values())

    def save_chat(self, history: List[Dict[str, Any]], title: Optional[str] = None) -> str:
        """Save chat history to the file system, overwriting existing chats with the same title.

        If no title is provided, the chat will be saved with a default title.
        The default title is "Chat-{current timestamp}".

        Args:
            history (List[Dict[str, Any]]): The chat history to save
            title (Optional[str]): The title of the chat provided by the user

        Returns:
            str: The title of the saved chat
        """
        history = history or []

        save_title = title or f"Chat-{int(time.time())}"
        save_title = self.make_chat_title(save_title)

        # Check for existing session with the same title and delete it
        existing_chat = self.chats_map["title"].get(save_title)
        if existing_chat:
            try:
                existing_path = Path(existing_chat["path"])
                existing_path.unlink()
            except OSError as e:
                self.console.print(
                    f"Warning: Could not delete existing chat file {existing_chat['path']}: {e}",
                    style="dim",
                )

        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-title-{save_title}.json"
        filepath = self.chat_dir / filename

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({"history": history, "title": save_title}, f, ensure_ascii=False, indent=2)
            # Force refresh the chat list after saving
            self.refresh_chats()
            return save_title
        except Exception as e:
            self.console.print(f"Error saving chat '{save_title}': {e}", style="dim")
            return ""

    def _load_chat_data(self, chat_info: Optional[ChatFileInfo]) -> Union[ChatFileInfo, Dict]:
        """Common method to load chat data from a chat info dict"""
        if not chat_info:
            return {}

        try:
            chat_file = Path(chat_info["path"])
            with open(chat_file, "r", encoding="utf-8") as f:
                chat_data = json.load(f)

            return {
                "title": chat_data.get("title", chat_info["title"]),
                "timestamp": chat_info["timestamp"],
                "history": chat_data.get("history", []),
            }
        except FileNotFoundError:
            self.console.print(f"Chat file not found: {chat_info['path']}", style="dim")
            return {}
        except json.JSONDecodeError as e:
            self.console.print(f"Invalid JSON in chat file {chat_info['path']}: {e}", style="dim")
            return {}
        except Exception as e:
            self.console.print(f"Error loading chat from {chat_info['path']}: {e}", style="dim")
            return {}

    def load_chat_by_index(self, index: int) -> Union[ChatFileInfo, Dict]:
        """Load a chat by index and return the chat data"""
        if not self.validate_chat_index(index):
            return {}
        chat_info = self.chats_map.get("index", {}).get(index)
        return self._load_chat_data(chat_info)

    def load_chat_by_title(self, title: str) -> Union[ChatFileInfo, Dict]:
        """Load a chat by title and return the chat data"""
        chat_info = self.chats_map.get("title", {}).get(title)
        return self._load_chat_data(chat_info)

    def delete_chat(self, index: int) -> bool:
        """Delete a chat by index and return success status"""
        if not self.validate_chat_index(index):
            return False

        chat_info = self.chats_map["index"].get(index)
        if not chat_info:
            return False

        try:
            chat_file = Path(chat_info["path"])
            chat_file.unlink()
            # Force refresh the chat list
            self.refresh_chats()
            return True
        except FileNotFoundError:
            self.console.print(f"Chat file not found: {chat_info['path']}", style="dim")
            return False
        except Exception as e:
            self.console.print(f"Error deleting chat {index}: {e}", style="dim")
            return False
