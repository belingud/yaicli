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

#: The bridge currently driving a generation, if any. ``WorkerConsole`` reads this
#: to route prints made from the worker thread to the UI thread for replay.
_active_bridge: Optional["ThreadedStream"] = None
_active_bridge_lock = threading.Lock()


def set_active_bridge(bridge: Optional["ThreadedStream"]) -> None:
    """Mark ``bridge`` as the active generation bridge (or clear it with None)."""
    global _active_bridge
    with _active_bridge_lock:
        _active_bridge = bridge


def get_active_bridge() -> Optional["ThreadedStream"]:
    """Return the active generation bridge, if a generation is running."""
    with _active_bridge_lock:
        return _active_bridge


def clear_active_bridge(bridge: Optional["ThreadedStream"] = None) -> None:
    """Clear the active bridge (only if it is still ``bridge`` when given)."""
    global _active_bridge
    with _active_bridge_lock:
        if bridge is None or _active_bridge is bridge:
            _active_bridge = None


#: Worker-thread ident -> bridge. Lets ``WorkerConsole`` keep routing (or dropping)
#: late output of an *abandoned* worker even after the next generation starts.
_thread_bridges: "dict[int, ThreadedStream]" = {}
_thread_bridges_lock = threading.Lock()


def get_bridge_for_current_thread() -> Optional["ThreadedStream"]:
    """Return the bridge driving the current thread (``None`` outside a generation)."""
    with _thread_bridges_lock:
        return _thread_bridges.get(threading.get_ident())


def _register_worker_thread(bridge: "ThreadedStream") -> None:
    with _thread_bridges_lock:
        _thread_bridges[threading.get_ident()] = bridge


def _unregister_worker_thread(bridge: "ThreadedStream") -> None:
    with _thread_bridges_lock:
        if _thread_bridges.get(threading.get_ident()) is bridge:
            _thread_bridges.pop(threading.get_ident(), None)


class ThreadedStream:
    """Run a completion generator on a worker thread; feed its UI thread.

    Events travel through one FIFO queue so the ordering of streamed chunks and
    worker console output is preserved:

    * ``("chunk", <LLMResponse|RefreshLive|ConfirmToolCall>)``
    * ``("console", (stderr, args, kwargs))`` — drained via ``on_console`` in ``__next__``
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
        self._thread: Optional[threading.Thread] = None
        self._started = False

    # -- worker thread -----------------------------------------------------
    def start(self) -> None:
        """Start the worker thread (also started lazily by the first ``__next__``).

        Lazy start lets the caller install console routing and register the bridge
        as active *before* the generator starts producing output.
        """
        if self._started:
            return
        self._thread = threading.Thread(target=self._run, name="yaicli-stream-bridge", daemon=True)
        self._thread.start()
        self._started = True

    def _run(self) -> None:
        _register_worker_thread(self)
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
            _unregister_worker_thread(self)

    def put_console(self, *args: Any, stderr: bool = False, **kwargs: Any) -> None:
        """Queue a console print produced by the worker for replay on the UI thread."""
        if not self.dead:
            self._queue.put(("console", (stderr, args, kwargs)))

    # -- UI thread (generator protocol) ------------------------------------
    def __iter__(self) -> "ThreadedStream":
        return self

    def __next__(self) -> Any:
        self.start()
        while True:
            kind, payload = self._queue.get()
            if kind == "console":
                if self._on_console is not None:
                    stderr, args, kwargs = payload
                    self._on_console(stderr, args, kwargs)
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

    def close(self, timeout: float = 1.0) -> bool:
        """Abort and join the worker (bounded wait); returns True when still alive.

        A ``True`` return means the worker is blocked in a provider read or tool
        execution and will finish later (abandoned); the caller must keep the
        console routing in place so its late output is dropped instead of
        corrupting the next turn.
        """
        self.abort()
        clear_active_bridge(self)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        return self.alive

    @property
    def alive(self) -> bool:
        """Whether the worker thread is still running."""
        thread = self._thread
        return thread is not None and thread.is_alive()
