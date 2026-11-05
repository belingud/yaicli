"""Ctrl+O detection while the assistant is generating (v0.19.1).

During a streaming turn there is no ``prompt_toolkit`` prompt reading the
keyboard: the terminal is in cooked mode (where ``^O`` is usually ``VDISCARD``)
and the REPL is busy pulling provider chunks. :class:`GenerationKeyWatcher`
installs a tiny cbreak key watcher for the duration of the generation so
``Ctrl+O`` can pause the stream and open the tool-output viewer. ``ISIG`` stays
enabled in cbreak mode, so ``Ctrl+C`` still raises ``SIGINT`` and cancels the
turn. Other typed characters are collected and handed to the next prompt as its
initial text (best effort).
"""

import os
import re
import select
import sys
import termios
import threading
import time
import tty
from typing import Any, Callable, Optional

#: The byte produced by Ctrl+O.
CTRL_O_BYTE = b"\x0f"
#: Backspace/delete bytes (best-effort editing of the pending prompt text).
_BACKSPACE_BYTES = (b"\x7f", b"\x08")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
_POLL_SECONDS = 0.1
_THREAD_JOIN_SECONDS = 1.0
_PAUSE_ACK_SECONDS = 2.0


class GenerationKeyWatcher:
    """Read stdin in cbreak mode while a generation runs; restore it on stop.

    ``fd``/``tty_check`` are injectable so the state machine can be tested with
    a pipe instead of a real terminal. On a non-TTY stdin ``start()`` returns
    ``False`` and the caller simply skips the feature.
    """

    def __init__(self, fd: Optional[int] = None, *, tty_check: Optional[Callable[[int], bool]] = None):
        self._fd = fd
        self._tty_check = tty_check or os.isatty
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._pause_ack = threading.Event()
        self._viewer_requested = threading.Event()
        self._pending = bytearray()
        self._thread: Optional[threading.Thread] = None
        self._old_attrs: Optional[Any] = None
        self._started = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> bool:
        """Start watching stdin; returns ``False`` when stdin is not a TTY."""
        if self._started:
            return True
        fd = self._fd if self._fd is not None else self._stdin_fd()
        if fd is None:
            return False
        try:
            if not self._tty_check(fd):
                return False
        except (OSError, ValueError, AttributeError):
            return False
        self._fd = fd
        try:
            self._old_attrs = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except (OSError, termios.error):
            # Not a real tty in tests/containers: keep the watcher functional,
            # only the terminal-mode change is unavailable.
            self._old_attrs = None
        self._stop.clear()
        self._paused.clear()
        self._pause_ack.clear()
        self._viewer_requested.clear()
        self._pending.clear()
        self._thread = threading.Thread(target=self._loop, name="yaicli-generation-keys", daemon=True)
        self._thread.start()
        self._started = True
        return True

    def stop(self) -> str:
        """Stop watching, restore the terminal and return the pending typed text."""
        if not self._started:
            return self._pending_text()
        self._stop.set()
        self._paused.clear()
        self._pause_ack.clear()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=_THREAD_JOIN_SECONDS)
        if self._old_attrs is not None and self._fd is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_attrs)
            except (OSError, termios.error):  # pragma: no cover - terminal vanished
                pass
            self._old_attrs = None
        self._started = False
        return self._pending_text()

    @staticmethod
    def _stdin_fd() -> Optional[int]:
        try:
            return sys.stdin.fileno()
        except (AttributeError, ValueError, OSError):
            return None

    # -- control -----------------------------------------------------------
    def take_viewer_request(self) -> bool:
        """Return True once per Ctrl+O press (clears the flag)."""
        if self._viewer_requested.is_set():
            self._viewer_requested.clear()
            return True
        return False

    def pause(self) -> None:
        """Stop reading keys so another prompt_toolkit app can own the terminal."""
        self._paused.set()
        self._pause_ack.wait(timeout=_PAUSE_ACK_SECONDS)

    def resume(self) -> None:
        """Resume reading keys after the viewer closes."""
        self._paused.clear()
        self._pause_ack.clear()

    # -- internals ---------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                self._pause_ack.set()
                time.sleep(0.02)
                continue
            self._pause_ack.clear()
            try:
                readable, _, _ = select.select([self._fd], [], [], _POLL_SECONDS)
            except (OSError, ValueError, TypeError):
                break
            if not readable:
                continue
            try:
                data = os.read(self._fd, 1)
            except BlockingIOError:  # pragma: no cover - non-blocking fd
                continue
            except (OSError, TypeError):
                break
            if not data:
                break
            if data == CTRL_O_BYTE:
                self._viewer_requested.set()
            elif data in _BACKSPACE_BYTES:
                if self._pending:
                    self._pending.pop()
            else:
                self._pending.extend(data)

    def _pending_text(self) -> str:
        data = bytes(self._pending)
        self._pending.clear()
        if not data:
            return ""
        text = data.decode("utf-8", "ignore")
        text = _ANSI_RE.sub("", text)
        return "".join(char for char in text if char == " " or char.isprintable())
