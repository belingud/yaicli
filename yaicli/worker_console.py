"""Thread-aware console routing for background generation (T2).

The generation worker thread must never write to the terminal directly: the main
thread owns the Rich ``Live`` region and may be inside the full-screen viewer.
:class:`WorkerConsole` wraps a real Rich console and dispatches ``print`` calls:

* main thread -> the real console (rendering and ``Live`` stay exactly as before);
* worker thread + active live bridge -> ``bridge.put_console(...)`` so the UI
  thread replays it in order between stream chunks;
* worker thread without an active bridge -> the real console (legacy behaviour
  for threads spawned outside a generation);
* worker thread while the bridge is dead (aborted generation) -> dropped, so a
  lingering worker cannot corrupt the next turn's screen.

:func:`install_worker_console_routing` swaps the module-level consoles captured by
the generation path (``yaicli.tools.console`` and the lazy
``yaicli.console.get_error_console()`` singleton) and returns the wrappers for the
client/provider consoles plus a :class:`WorkerConsoleRouting` restore handle.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from .stream_bridge import get_active_bridge


class WorkerConsole:
    """Console proxy that routes worker-thread prints to the active stream bridge."""

    def __init__(self, real: Any, *, stderr: bool = False):
        # ``object.__setattr__`` keeps ``__getattr__`` delegation simple.
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_stderr", stderr)

    @property
    def real(self) -> Any:
        """The wrapped Rich console."""
        return self._real

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Print on the main thread; queue worker-thread prints for replay."""
        bridge = get_active_bridge()
        if bridge is not None and threading.current_thread() is not threading.main_thread():
            if bridge.dead:  # aborted generation: drop late worker output
                return
            bridge.put_console(*args, stderr=self._stderr, **kwargs)
            return
        self._real.print(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # Width/file/style helpers and Rich internals keep working on the main
        # thread; only ``print`` needs dispatch.
        return getattr(self._real, name)


class WorkerConsoleRouting:
    """Handle for the consoles installed by :func:`install_worker_console_routing`."""

    def __init__(self, main: WorkerConsole, error: WorkerConsole, saved: Dict[str, Any]):
        self.main = main
        self.error = error
        self._saved = saved
        self._restored = False

    def restore(self) -> None:
        """Put the original module-level consoles back (idempotent)."""
        if self._restored:
            return
        self._restored = True
        # Imported lazily to avoid import cycles at module load.
        import yaicli.console as console_mod
        import yaicli.tools as tools_mod

        tools_mod.console = self._saved.get("tools_console")
        console_mod._error_console = self._saved.get("error_console")

    @property
    def restored(self) -> bool:
        return self._restored


def install_worker_console_routing(
    main_console: Any,
    error_console: Optional[Any] = None,
) -> WorkerConsoleRouting:
    """Wrap the consoles used by the generation path and return the restore handle.

    ``main_console`` is the CLI/REPL console (main-thread output); ``error_console``
    defaults to the process-wide stderr console. The caller is responsible for
    assigning ``routing.main`` to the client/provider consoles (T3).
    """
    import yaicli.console as console_mod
    import yaicli.tools as tools_mod

    if error_console is None:
        error_console = console_mod.get_error_console()
    main = WorkerConsole(main_console)
    error = WorkerConsole(error_console, stderr=True)
    saved = {
        "tools_console": getattr(tools_mod, "console", None),
        "error_console": getattr(console_mod, "_error_console", None),
    }
    tools_mod.console = main
    console_mod._error_console = error
    return WorkerConsoleRouting(main, error, saved)
