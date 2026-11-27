"""Small, process-safe locks shared by workspace writes and checkpoints."""

import os
import threading
from pathlib import Path

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


class SessionLock:
    """Serialize YAICLI writers of one saved conversation across processes."""

    def __init__(self, path: Path):
        self.path = path
        self.file = None
        self.thread_lock = None

    def acquire(self) -> bool:
        key = str(self.path.resolve())
        with _LOCKS_GUARD:
            self.thread_lock = _LOCKS.setdefault(key, threading.Lock())
        if not self.thread_lock.acquire(blocking=False):
            return False
        try:
            _private_dir(self.path.parent)
            if self.path.is_symlink():
                raise OSError("Lock path is a symbolic link")
            self.file = self.path.open("a+b")
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            try:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except ImportError:  # pragma: no cover - Windows fallback
                import msvcrt

                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (OSError, BlockingIOError):
            if self.file is not None:
                self.file.close()
            self.file = None
            self.thread_lock.release()
            self.thread_lock = None
            return False

    def release(self) -> None:
        if self.file is not None:
            try:
                try:
                    import fcntl

                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
                except ImportError:  # pragma: no cover - Windows fallback
                    import msvcrt

                    self.file.seek(0)
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.file.close()
            self.file = None
        if self.thread_lock is not None:
            self.thread_lock.release()
            self.thread_lock = None
