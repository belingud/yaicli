"""Threaded bridge between a completion generator and the UI thread (v0.19.1).

Background generation: run the streaming completion generator (provider calls,
tool execution, confirmations) on a worker thread while the REPL's main thread
stays responsive (rendering, Ctrl+O viewer). This module is deliberately free of
console/UI imports so it can be unit-tested in isolation.

Usage sketch::

    adapter = ThreadedStream(self.client.completion_with_tools(...), on_console=print)
    result = self.printer.display_stream(adapter)   # main thread
    ...
    adapter.close()

The adapter implements the generator protocol ``__next__``/``send`` that
``Printer.display_stream()`` expects. Worker console prints are queued as
``console`` events and replayed (in order) by the main thread while it waits for
the next chunk. ``abort()`` cancels the worker at its next chunk boundary.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Generator, Optional

from .schemas import ConfirmToolCall

#: Sentinel used by the worker when it has no value to send into the generator.
_MISSING = object()
#: Internal decision value that unblocks a worker waiting for a confirmation.
_ABORT = object()


class ThreadedStream:
    """Run a completion generator on a worker thread; feed its UI thread.

    Events travel through one FIFO queue so the ordering of streamed chunks and
    worker console output is preserved:

    * ``("chunk", <LLMResponse|RefreshLive|ConfirmToolCall>)``
    * ``("console", (args, kwargs))`` — drained via ``on_console`` in ``__next__``
    * ``("done", None)`` — becomes ``StopIteration``
    * ``("error", <exception>)`` — re-raised in the UI thread

    A ``ConfirmToolCall`` chunk pauses the worker until the UI thread calls
    ``send(decision)``. ``abort()`` marks the bridge dead (late console writes are
    dropped) and asks the worker to stop; a worker blocked inside ``next(gen)``
    cannot be interrupted synchronously (documented trade-off).
    """

    def __init__(
        self,
        stream_iterator: Generator[Any, Any, Any],
        *,
        on_console: Optional[Callable[..., None]] = None,
    ):
        self._generator = stream_iterator
        self._on_console = on_console
        self._queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._decisions: "queue.Queue[Any]" = queue.Queue()
        self._cancel = threading.Event()
        self._awaiting_decision = False
        #: True after abort(): late console events are dropped, no new turn reuses us.
        self.dead = False
        self._thread = threading.Thread(target=self._run, name="yaicli-stream-bridge", daemon=True)
        self._thread.start()

    # -- worker thread -----------------------------------------------------
    def _run(self) -> None:
        value: Any = _MISSING
        try:
            while not self._cancel.is_set():
                try:
                    chunk = (
                        self._generator.send(value) if value is not _MISSING else next(self._generator)
                    )
                except StopIteration:
                    break
                except BaseException as exc:  # noqa: BLE001 - forwarded to the UI thread
                    self._queue.put(("error", exc))
                    return
                value = _MISSING
                if self._cancel.is_set():
                    break
                self._queue.put(("chunk", chunk))
                if isinstance(chunk, ConfirmToolCall):
                    decision = self._decisions.get()
                    if decision is _ABORT or self._cancel.is_set():
                        break
                    value = decision
            self._queue.put(("done", None))
        finally:
            try:
                self._generator.close()
            except Exception:  # pragma: no cover - closing must never mask the outcome
                pass

    def put_console(self, *args: Any, **kwargs: Any) -> None:
        """Queue a console print produced by the worker for replay on the UI thread."""
        if not self.dead:
            self._queue.put(("console", (args, kwargs)))

    # -- UI thread (generator protocol) ------------------------------------
    def __iter__(self) -> "ThreadedStream":
        return self

    def __next__(self) -> Any:
        while True:
            kind, payload = self._queue.get()
            if kind == "console":
                if self._on_console is not None:
                    args, kwargs = payload
                    self._on_console(*args, **kwargs)
                continue
            if kind == "done":
                raise StopIteration
            if kind == "error":
                raise payload
            if isinstance(payload, ConfirmToolCall):
                self._awaiting_decision = True
            return payload

    def send(self, value: Any) -> Any:
        """Hand a ``ConfirmToolCall`` decision to the worker, then wait for the next chunk."""
        if not self._awaiting_decision:
            raise TypeError("send() called without a pending ConfirmToolCall")
        self._awaiting_decision = False
        self._decisions.put(value)
        return self.__next__()

    # -- lifecycle ---------------------------------------------------------
    def abort(self) -> None:
        """Ask the worker to stop; late console output is dropped."""
        self.dead = True
        self._cancel.set()
        # Unblock a worker waiting for a confirmation decision.
        self._decisions.put(_ABORT)

    def close(self, timeout: float = 1.0) -> None:
        """Abort and join the worker thread (bounded wait)."""
        self.abort()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)

    @property
    def alive(self) -> bool:
        """Whether the worker thread is still running."""
        return self._thread.is_alive()
