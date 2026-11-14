import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from rich.table import Table

from .config import cfg
from .console import YaiConsole, get_console, safe_text, untrusted_text
from .const import DEFAULT_CHAT_HISTORY_DIR, get_project_sessions_dir, get_sessions_dir
from .exceptions import ChatDeleteError, ChatLoadError, ChatSaveError
from .redaction import is_redaction_enabled, redact_message_dict
from .schemas import ChatMessage, ImageData, ToolCall
from .utils import option_callback

console: YaiConsole = get_console()

#: Session dirs are private (they contain full conversations); files are 0600.
SESSION_DIR_MODE = 0o700
SESSION_FILE_MODE = 0o600


def _chmod_quietly(path: Path, mode: int) -> None:
    """Best-effort POSIX mode change (no-op on platforms without chmod)."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def resolve_default_chat_dir() -> Path:
    """Resolve the session directory used when no explicit one is given.

    v0.21 K13: sessions are isolated per project under
    ``~/.yaicli/sessions/<sha256(resolved cwd)[:16]>``. An explicit
    ``CHAT_HISTORY_DIR`` override (config file or ``YAI_CHAT_HISTORY_DIR``) that
    differs from the built-in default keeps the previous flat-directory
    behaviour, so scripts/tests pinning that directory are unaffected.
    """
    configured = str(cfg.get("CHAT_HISTORY_DIR") or "").strip()
    if configured and configured != str(DEFAULT_CHAT_HISTORY_DIR):
        return Path(configured).expanduser()
    return get_project_sessions_dir()


def _tool_call_to_dict(tool_call: ToolCall) -> Dict:
    """Serialize a ToolCall into a JSON friendly dict."""
    return {"id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments}


def _image_to_dict(image: ImageData) -> Dict:
    """Serialize an ImageData into a JSON friendly dict."""
    return {"data": image.data, "media_type": image.media_type, "is_url": image.is_url}


def _message_to_dict(message: ChatMessage) -> Dict:
    """Serialize a ChatMessage, including optional fields only when set.

    Old sessions only stored ``role``/``content``; keeping unset optional fields
    out of the JSON keeps newly written files compact while staying a superset
    of the legacy format.
    """
    data: Dict = {"role": message.role, "content": message.content}
    if message.name:
        data["name"] = message.name
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        data["tool_calls"] = [_tool_call_to_dict(tool_call) for tool_call in message.tool_calls]
    if message.reasoning:
        data["reasoning"] = message.reasoning
    if message.images:
        data["images"] = [_image_to_dict(image) for image in message.images]
    return data


def _tool_call_from_dict(data: Dict) -> ToolCall:
    """Rebuild a ToolCall from a saved dict, tolerating missing fields."""
    return ToolCall(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or ""),
        arguments=str(data.get("arguments") or ""),
    )


def _image_from_dict(data: Dict) -> ImageData:
    """Rebuild an ImageData from a saved dict, tolerating missing fields."""
    return ImageData(
        data=str(data.get("data") or ""),
        media_type=str(data.get("media_type") or ""),
        is_url=bool(data.get("is_url", False)),
    )


def _message_from_dict(data: Dict) -> ChatMessage:
    """Rebuild a ChatMessage from a saved dict.

    Works for both the legacy ``{"role", "content"}`` format and the current
    format with tool calls / images / reasoning. Non-dict entries and missing
    fields fall back to safe defaults so a damaged entry can not raise KeyError.
    """
    if not isinstance(data, dict):
        return ChatMessage(role="user", content=None)

    raw_tool_calls = data.get("tool_calls")
    tool_calls = []
    if isinstance(raw_tool_calls, list):
        tool_calls = [_tool_call_from_dict(item) for item in raw_tool_calls if isinstance(item, dict)]

    raw_images = data.get("images")
    images = []
    if isinstance(raw_images, list):
        images = [_image_from_dict(item) for item in raw_images if isinstance(item, dict)]

    return ChatMessage(
        role=str(data.get("role") or "user"),
        content=data.get("content"),
        name=data.get("name") or None,
        tool_call_id=data.get("tool_call_id") or None,
        tool_calls=tool_calls,
        reasoning=data.get("reasoning") or None,
        images=images,
    )


@dataclass
class Chat:
    """Single chat session"""

    idx: Optional[str] = None
    title: str = field(default_factory=lambda: f"Chat {datetime.now().strftime('%Y%m%d-%H%M%S')}")
    history: List[ChatMessage] = field(default_factory=list)
    date: str = field(default_factory=lambda: datetime.now().isoformat())
    path: Optional[Path] = None
    # ---- v0.21 K13 session metadata (all optional: legacy files lack them) ----
    #: Model the session was recorded with (``cfg["MODEL"]`` at save time).
    model: str = ""
    #: Provider the session was recorded with (``cfg["PROVIDER"]`` at save time).
    provider: str = ""
    #: Assistant role name the session was recorded with.
    role: str = ""
    #: Absolute working directory the session belongs to.
    cwd: str = ""
    #: ISO creation timestamp (falls back to ``date`` for legacy sessions).
    created_at: str = ""
    #: ISO timestamp of the last save.
    updated_at: str = ""
    #: v0.24 K23: active plan pointer + todo state (JSON payload built by
    #: ``plan_mode.PlanSession.to_session_dict()``). Empty for sessions without a
    #: plan; legacy files simply lack the key.
    plan: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str) -> None:
        """Add message to the session"""
        self.history.append(ChatMessage(role=role, content=content))

    def update_metadata(
        self,
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        role: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> None:
        """Record session metadata, keeping already-known values when omitted.

        Called by the CLI before every save (K13): model/provider/role/cwd make a
        resumed session self-describing. Legacy sessions (empty metadata) get
        backfilled on their next save.
        """
        if model is not None:
            self.model = str(model)
        if provider is not None:
            self.provider = str(provider)
        if role is not None:
            self.role = str(role)
        if cwd is not None:
            self.cwd = str(cwd)
        if not self.created_at:
            self.created_at = self.date or datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

    def _raw_dict(self) -> Dict:
        """Build the session payload from the raw in-memory history.

        This is the untouched representation (what the model and the display
        see). It is never written to disk directly: :meth:`to_dict` adds the
        on-disk redaction (v0.22 K20).
        """
        data: Dict = {
            "title": self.title,
            "date": self.date,
            "model": self.model,
            "provider": self.provider,
            "role": self.role,
            "cwd": self.cwd,
            "created_at": self.created_at or self.date,
            "updated_at": self.updated_at,
            "history": [_message_to_dict(msg) for msg in self.history],
        }
        # v0.24 K23: only sessions that actually carry a plan store the key, so
        # plan-less sessions stay byte-compatible with the previous format.
        if self.plan:
            data["plan"] = self.plan
        return data

    def to_dict(self) -> Dict:
        """Build the persisted (on-disk) representation of this session.

        The in-memory :attr:`history` stays raw; only this serialized payload is
        redacted. With ``REDACT_SECRETS`` enabled (default) every message's
        ``content``/``reasoning``/``name`` and tool-call ``arguments`` have known
        secret shapes replaced by ``[redacted]``; with it disabled the payload is
        byte-identical to :meth:`_raw_dict`. Keys and structure are unchanged, so
        :meth:`from_dict`/:meth:`load` keep working with redacted files.
        """
        data = self._raw_dict()
        if not is_redaction_enabled():
            return data
        data["history"] = [redact_message_dict(payload) for payload in data["history"]]
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "Chat":
        """Create Chat instance from dictionary (legacy files without metadata work)"""
        raw_plan = data.get("plan")
        plan: Dict[str, Any] = dict(raw_plan) if isinstance(raw_plan, dict) else {}
        chat = cls(
            idx=data.get("idx", None),
            title=data.get("title", "Untitled Chat"),
            date=data.get("date", datetime.now().isoformat()),
            path=data.get("path", None),
            model=str(data.get("model") or ""),
            provider=str(data.get("provider") or ""),
            role=str(data.get("role") or ""),
            cwd=str(data.get("cwd") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            plan=plan,
        )

        for msg_data in data.get("history", []):
            chat.history.append(_message_from_dict(msg_data))

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
                self.model = str(data.get("model") or "")
                self.provider = str(data.get("provider") or "")
                self.role = str(data.get("role") or "")
                self.cwd = str(data.get("cwd") or "")
                self.created_at = str(data.get("created_at") or "")
                self.updated_at = str(data.get("updated_at") or "")
                raw_plan = data.get("plan")
                self.plan = dict(raw_plan) if isinstance(raw_plan, dict) else {}
                self.history = [_message_from_dict(msg) for msg in data.get("history", [])]
            return True
        except (json.JSONDecodeError, OSError) as e:
            raise ChatLoadError(f"Error loading chat: {e}") from e

    def save(self, chat_dir: Path) -> bool:
        """Save chat to file atomically

        The chat is written to a temporary file in the same directory and then
        moved into place with :func:`os.replace`, so a failed or interrupted
        save never truncates a previously saved session file. The payload comes
        from :meth:`to_dict`, so known secret shapes are redacted before the
        bytes hit the disk (``REDACT_SECRETS``, default on) while the in-memory
        history stays raw.

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
        now = datetime.now().isoformat()
        if not self.date:
            self.date = now
        # v0.21 K13 metadata: created_at is fixed at creation (or first save for
        # legacy sessions), updated_at advances on every save.
        if not self.created_at:
            self.created_at = self.date or now
        self.updated_at = now

        # Create a descriptive filename with timestamp and title
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-title-{self.title}.json"
        chat_path = chat_dir / filename
        # Sibling temporary file: same filesystem, hidden from the "*.json"
        # session listing, and unique per process to survive concurrent saves.
        temp_path = chat_dir / f".{filename}.{os.getpid()}.tmp"

        try:
            # Write the full payload first, then atomically swap it into place.
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            # Sessions are private (K13): chmod the temp file *before* it becomes
            # the visible session file so no moment exposes a 0644 session.
            _chmod_quietly(temp_path, SESSION_FILE_MODE)
            os.replace(temp_path, chat_path)
            _chmod_quietly(chat_path, SESSION_FILE_MODE)

            # Update chat's path to the new file only after a successful replace
            self.path = chat_path
            return True
        except Exception as e:
            error_msg = f"Error saving chat '{self.title}': {e}"
            raise ChatSaveError(error_msg) from e
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


@dataclass
class FileChatManager:
    """File system chat manager"""

    #: Per-project session store by default (v0.21 K13); an explicit
    #: ``CHAT_HISTORY_DIR`` override keeps the old flat directory.
    chat_dir: Path = field(default_factory=resolve_default_chat_dir)
    max_saved_chats: int = field(default_factory=lambda: cfg["MAX_SAVED_CHATS"])
    current_chat: Optional[Chat] = None
    _chats_map: Optional[Dict[str, Dict[str, Chat]]] = None

    def __post_init__(self) -> None:
        # Directory creation is lazy and best effort (v0.19 K21): importing
        # ``yaicli.chat`` / constructing ``chat_mgr`` must not touch the disk so
        # read-only HOMEs and meta commands stay write-free. The directory is
        # created on the first save.
        if not isinstance(self.chat_dir, Path):
            self.chat_dir = Path(self.chat_dir)

    def _ensure_chat_dir(self) -> bool:
        """Create the session directory if needed. Best effort, never raises."""
        try:
            self.chat_dir.mkdir(parents=True, exist_ok=True)
            # v0.21 K13: session dirs are private (they contain conversations).
            _chmod_quietly(self.chat_dir, SESSION_DIR_MODE)
            self._harden_sessions_store()
            return True
        except OSError as e:
            console.print(
                f"Warning: could not create chat directory {safe_text(str(self.chat_dir))}: {safe_text(str(e))}",
                style="yellow",
            )
            return False

    def _harden_sessions_store(self) -> None:
        """Best-effort 0700 for the managed session store root(s).

        Only paths under ``~/.yaicli/sessions`` are touched: a user-provided
        ``CHAT_HISTORY_DIR`` override may point at a shared directory whose
        modes are not ours to change.
        """
        try:
            sessions_root = get_sessions_dir()
        except OSError:  # pragma: no cover - HOME resolution edge
            return
        try:
            if self.chat_dir != sessions_root and sessions_root not in self.chat_dir.parents:
                return
            if sessions_root.exists():
                _chmod_quietly(sessions_root, SESSION_DIR_MODE)
        except OSError:  # pragma: no cover - permission edge
            pass

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

        The new session file is written (atomically) *before* any older file with
        the same title is removed, so a failed save keeps the previous session
        intact instead of losing both.

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

        # First write into this manager: create the session directory lazily.
        self._ensure_chat_dir()

        # Write the replacement first: this is what makes /save safe. Chat.save()
        # uses a temp file + os.replace, so the new file only appears when complete.
        chat.save(self.chat_dir)

        # The replacement is safely on disk; now remove the older session(s) with
        # the same title so /save still behaves as "replace". Never touch the file
        # that was just written.
        if chat.title:
            self._delete_existing_chat_with_title(chat.title, exclude_path=chat.path)

        # If we get here, the save was successful
        # Clean up old chats if we exceed the maximum
        self._cleanup_old_chats()

        # Reset the chats map to force a refresh on next access
        self._chats_map = None

        return chat.title

    def _delete_existing_chat_with_title(self, title: str, exclude_path: Optional[Path] = None) -> None:
        """Delete existing chats with the given title, except ``exclude_path``.

        The chat directory is scanned instead of relying on ``chats_map`` (which can
        be stale when files were written by a previous process or session).
        """
        if not title:
            return

        keep_path: Optional[Path] = None
        if exclude_path is not None:
            try:
                keep_path = Path(exclude_path).resolve()
            except OSError:
                keep_path = None

        candidates: List[Path] = []
        for chat_file in self.chat_dir.glob("*.json"):
            try:
                parsed_title = self._parse_filename(chat_file).title
            except Exception:
                continue
            if parsed_title == title:
                candidates.append(chat_file)

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            if keep_path is not None and resolved == keep_path:
                continue
            try:
                resolved.unlink()
            except FileNotFoundError:
                continue
            except OSError as e:
                raise ChatDeleteError(f"Warning: Failed to delete existing chat file {resolved}: {e}") from e
            # Reset the chats map to force a refresh
            self._chats_map = None

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

    def latest_chat(self) -> Optional[Chat]:
        """Load the most recently saved session in this project (v0.21 K13).

        ``chats_map["index"]`` is ordered newest-first (session files are sorted
        by mtime), so index ``"1"`` is the most recent session. Returns ``None``
        when the project has no saved session (or the newest file cannot be
        parsed), so ``--resume`` can print an explicit notice instead of silently
        starting a new session.
        """
        chats = self.list_chats()
        if not chats:
            return None

        newest = chats[0]
        if newest.path is None or not newest.path.exists():
            return None
        try:
            if not newest.load():
                return None
        except ChatLoadError:
            return None
        self.current_chat = newest
        return newest

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
            # Session titles come from filenames/user input: render literally.
            table.add_row(str(i + 1), safe_text(created_at), str(len(chat.history)), untrusted_text(chat.title))

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
            console.print(f"{i + 1}. {safe_text(chat.title)} ({safe_text(created_at)})")
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
