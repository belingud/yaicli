"""Saved conversations and checkpoint coordination, with explicit runtime inputs."""

import os
import time
from pathlib import Path
from typing import List, Optional, Union

from ..chat import Chat, resolve_default_chat_dir
from ..console import get_error_console, safe_text
from ..const import TEMP_MODE
from ..exceptions import ChatLoadError, ChatSaveError
from ..schemas import ImageData
from .state import RunState


class SessionController:
    """Own the current chat and its persistence; terminal worker lifecycle remains in CLI."""

    def __init__(self, config, manager, state: RunState, console, *, history_changed=None):
        self.config = config
        self.chat_manager = manager
        self.state = state
        self.console = console
        self.history_changed = history_changed or (lambda: None)
        self.chat = Chat(title="", history=[])
        self.is_temp_session = True
        self.chat_start_time = None
        directory = getattr(manager, "chat_dir", None)
        self.chat_history_dir = Path(directory) if isinstance(directory, (str, Path)) else resolve_default_chat_dir()
        self.retry_snapshot = None
        self.capture = None
        self.worker = None

    def clear_retry_snapshot(self):
        self.retry_snapshot = None

    def save_chat(self, title: Union[str, None] = None) -> None:
        """Serialize a saved checkpoint identity before replacing its chat file."""
        lock = None
        try:
            store = self.checkpoint_store() if self.chat.checkpoint_session_id else None
            if store is not None:
                lock = store.session_lock()
                if not lock.acquire():
                    raise OSError("Workspace is busy. Try again when its file operations finish.")
                store._fresh(store._load())
            old_path = self.chat.path
            if store is not None and title and title != self.chat.title:
                self.chat.path = None
            self.save_chat_inner(title)
            if store is not None and self.chat.path != old_path:
                data = store._load()
                data["session_path"] = str(self.chat.path.resolve())
                store._save(data)
                if old_path is not None:
                    old_path.unlink(missing_ok=True)
        except Exception as exc:
            get_error_console().print(safe_text(f"Failed to save chat: {exc}"), markup=False)
            return
        finally:
            if lock is not None:
                lock.release()
        self.checkpoint_reset(only_if_new=True)

    def save_chat_inner(self, title: Union[str, None] = None) -> None:
        """Save current chat history to a file using session manager."""
        # Update title if provided
        if title:
            self.chat.title = title
        if not self.config.get("CHECKPOINT_ENABLED", True):
            self.chat.checkpoint_head = -1

        # v0.21 K13: persist model/provider/role/cwd/created_at/updated_at.
        try:
            self.apply_session_metadata(self.chat)
        except AttributeError:
            # Legacy/bare Chat-like object (tests/integrations): keep saving it.
            pass

        # Save chat and get the saved title back
        try:
            saved_title = self.chat_manager.save_chat(self.chat)
        except ChatSaveError as e:
            self.console.print(f"Failed to save chat: {safe_text(e)}", style="red")
            return

        # Session list will be refreshed automatically by the save method
        self.console.print(f"Chat saved as: {safe_text(saved_title)}", style="bold green")

        # Mark session as persistent if it was temporary
        if self.is_temp_session:
            self.is_temp_session = False
            self.chat_start_time = int(time.time())
            self.console.print(
                "Session is now marked as persistent and will be auto-saved on exit.", style="bold green"
            )

    def list_chats(self) -> None:
        """List all saved chat sessions using session manager."""
        chats: list[Chat] = self.chat_manager.list_chats()

        if not chats:
            self.console.print("No saved chats found.", style="yellow")
            return

        self.console.print("Saved Chats:", style="bold underline")
        for chat in chats:
            index = chat.idx
            title = chat.title
            date = chat.date

            if date:
                self.console.print(
                    f"[dim]{safe_text(index)}.[/dim] [bold blue]{safe_text(title)}[/bold blue] - {safe_text(date)}"
                )
            else:
                self.console.print(f"[dim]{safe_text(index)}.[/dim] [bold blue]{safe_text(title)}[/bold blue]")

    def refresh_chats(self) -> None:
        """Force refresh the chat list."""
        self.chat_manager.refresh_chats()

    def load_chat_by_index(self, index: str) -> bool:
        """Load a chat session by its index using session manager."""
        if not self.chat_manager.validate_chat_index(index):
            self.console.print("Invalid chat index.", style="bold red")
            return False

        chat_data = self.chat_manager.load_chat_by_index(index)

        if not chat_data:
            self.console.print("Invalid chat index or chat not found.", style="bold red")
            return False

        self.chat = chat_data
        self.chat_start_time = chat_data.date
        self.is_temp_session = False
        # the loaded conversation has its own turn history — forget the old
        # /retry snapshot and refresh the prompt's context percentage immediately.
        self.retry_snapshot = None
        self.history_changed()

        self.console.print(f"Loaded chat: {safe_text(self.chat.title)}", style="bold green")
        return True

    def delete_chat_by_index(self, index: str) -> bool:
        """Delete a chat session by its index using session manager."""
        if not self.chat_manager.validate_chat_index(index):
            self.console.print("Invalid chat index.", style="bold red")
            return False

        chat_data = self.chat_manager.load_chat_by_index(index)

        if not chat_data:
            self.console.print("Invalid chat index or chat not found.", style="bold red")
            return False

        if chat_data.path is None:
            self.console.print(f"Chat has no associated file to delete: {safe_text(chat_data.title)}", style="bold red")
            return False

        if self.chat_manager.delete_chat(chat_data.path):
            self.console.print(f"Deleted chat: {safe_text(chat_data.title)}", style="bold green")
            return True
        else:
            self.console.print(f"Failed to delete chat: {safe_text(chat_data.title)}", style="bold red")
            return False

    def apply_session_metadata(self, chat: Chat) -> None:
        """Record model/provider/role/cwd on a session before it is saved.

        Resumed sessions keep their recorded values (they describe how the
        conversation was produced); new/legacy sessions get the current config.
        """
        model = str(self.config.get("MODEL", "") or "")
        provider = str(self.config.get("PROVIDER", "") or "")
        try:
            cwd = os.getcwd()
        except OSError:  # pragma: no cover - deleted cwd
            cwd = ""
        if not chat.model:
            chat.model = model
        if not chat.provider:
            chat.provider = provider
        chat.role = chat.role or str(self.state.role_name or "")
        if not chat.cwd:
            chat.cwd = cwd
        chat.update_metadata()

    @staticmethod
    def session_notice(chat: Chat) -> str:
        """One-line description of a resumed session (title + recorded metadata)."""
        model = chat.model or "unknown"
        provider = chat.provider or "unknown"
        role = chat.role or "unknown"
        return (
            f'Resumed session "{chat.title}" '
            f"(model={model}, provider={provider}, role={role}, messages={len(chat.history)})"
        )

    def resume_latest_session(self) -> bool:
        """Make the newest saved session of this project the active one (--resume).

        Returns:
            bool: True when an existing session was resumed, False when a new
            session was started after printing an explicit notice.
        """
        try:
            latest = self.chat_manager.latest_chat()
        except ChatLoadError as e:
            get_error_console().print(f"Could not load the latest session: {safe_text(e)}", style="yellow")
            latest = None

        if latest is None:
            get_error_console().print(
                "No saved session found for this project; starting a new session.",
                style="yellow",
            )
            self.chat = Chat(title="", history=[])
            self.apply_session_metadata(self.chat)
            self.is_temp_session = True
            return False

        self.chat = latest
        self.is_temp_session = False
        self.chat_start_time = latest.date
        self.console.print(self.session_notice(latest), style="bold green")
        return True

    def start_chat_by_title(self, title: str) -> None:
        """Load the session named ``title`` or explicitly start a new one.

        v0.21 K13: a missed title must never silently create a session; print
        one explicit notice instead (the old behaviour made the user believe
        they were resuming a saved conversation).
        """
        loaded: Optional[Chat] = None
        try:
            loaded = self.chat_manager.load_chat_by_title(title)
        except ChatLoadError as e:
            get_error_console().print(f"Could not load session '{safe_text(title)}': {safe_text(e)}", style="yellow")

        if loaded is not None and loaded.path is not None:
            self.chat = loaded
            self.is_temp_session = False
            self.chat_start_time = loaded.date
            return

        self.chat = loaded if loaded is not None else Chat(title=title, history=[])
        self.is_temp_session = False
        get_error_console().print(
            f'No saved session titled "{safe_text(title)}" for this project; starting a new session.',
            style="yellow",
        )

    def checkpoint_store(self):
        """Resolve the current saved-chat store only for a real interactive REPL."""
        if (
            not self.state.interactive
            or self.state.machine_output
            or self.state.quiet
            or self.is_temp_session
            or self.state.current_mode == TEMP_MODE
            or not self.config.get("CHECKPOINT_ENABLED", True)
        ):
            return None
        import uuid

        from ..checkpoints import CheckpointError, CheckpointStore
        from ..const import project_sessions_key
        from ..tools.workspace import resolve_workspace_root

        worker = self.worker
        if worker is not None:
            if worker.alive:
                raise CheckpointError("Workspace is busy. Try again when its file operations finish.")
            capture = self.capture
            if capture is not None:
                capture.store.abandon_turn(capture)
            self.worker = None
            self.capture = None
        chat = self.chat
        if (
            not chat.checkpoint_session_id
            or len(chat.checkpoint_session_id) != 32
            or any(char not in "0123456789abcdef" for char in chat.checkpoint_session_id)
        ):
            chat.checkpoint_session_id = uuid.uuid4().hex
            chat.checkpoint_head = -1
        root = resolve_workspace_root(self.config.get("WORKSPACE_ROOT") or Path.cwd())
        if chat.path is None:
            self.chat_manager.save_chat(chat)
        directory = (
            self.chat_history_dir.resolve() / "checkpoints" / project_sessions_key() / chat.checkpoint_session_id
        )
        store = CheckpointStore(
            directory,
            root,
            chat.checkpoint_session_id,
            self.config.get("CHECKPOINT_KEEP", 20),
            self.config.get("CHECKPOINT_MAX_MB", 50),
            session_path=chat.path.resolve(),
            expected_head=chat.checkpoint_head,
        )
        if not store.belongs_to_path():
            # A copied session shares its conversation, never another file's journal.
            chat.checkpoint_session_id = uuid.uuid4().hex
            chat.checkpoint_head = -1
            return self.checkpoint_store()
        try:
            data = store._load()
            if chat.checkpoint_head < 0 and data["head"] >= 0 and not store.pending_path.exists():
                chat.checkpoint_session_id = uuid.uuid4().hex
                return self.checkpoint_store()
        except CheckpointError as exc:
            if (
                str(exc)
                not in ("Checkpoint data is corrupt.", "Checkpoint data does not match this session or workspace.")
                or store.has_recovery()
            ):
                raise
            get_error_console().print(safe_text(f"Checkpoint unavailable: {exc}"), markup=False)
            chat.checkpoint_session_id = uuid.uuid4().hex
            chat.checkpoint_head = -1
            return self.checkpoint_store()
        store.reconcile()
        return store

    def checkpoint_reset(self, only_if_new: bool = False) -> None:
        capture = self.capture
        if capture is not None and not capture.finished:
            capture.barrier = True
            return
        try:
            store = self.checkpoint_store()
            if store is None:
                return
            if only_if_new:
                self.chat.checkpoint_head = store.ensure_base(self.chat.to_dict())
            else:
                self.chat.checkpoint_head = store.reset(self.chat.to_dict())
            self.chat.save(self.chat_history_dir)
            if store.warning:
                get_error_console().print(store.warning, markup=False)
        except Exception as exc:
            get_error_console().print(safe_text(f"Checkpoint unavailable: {exc}"), markup=False)

    def remember_turn_for_retry(self, user_input: str, images: Optional[List[ImageData]] = None) -> None:
        """Snapshot the conversation + input *before* a turn so ``/retry`` can replay it.

        The snapshot is restored by :meth:`_retry_last_turn`, which drops any
        partial/duplicated assistant or tool messages a failed turn produced
        before sending the same input again.
        """
        try:
            history = getattr(getattr(self, "chat", None), "history", None)
            history_snapshot = list(history) if isinstance(history, list) else []
        except (AttributeError, TypeError):  # pragma: no cover - bare/legacy CLI objects
            history_snapshot = []
        self.retry_snapshot = {
            "input": user_input,
            "images": list(images or []),
            "history": history_snapshot,
        }
