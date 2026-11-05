"""Opt-in diagnostics for hard-to-reproduce terminal/REPL issues.

The Ctrl+O viewer depends on terminal state (raw/cbreak mode, stdin ownership,
alternate screen) that cannot be unit-tested in a normal CI environment. When
``YAI_DEBUG_LOG`` is set, the generation/viewer path appends short, secret-free
breadcrumbs to a log file so a user-reported freeze can be diagnosed from the
outside:

* ``YAI_DEBUG_LOG=1`` -> ``<config-dir>/debug.log`` (e.g. ``~/.config/yaicli/debug.log``)
* ``YAI_DEBUG_LOG=/path/to/file`` -> that file

Unset (the default) means the helper returns immediately and never touches the
filesystem. Log lines contain only event names and small scalars (counts, booleans,
thread names) — never prompts, command output or model content.
"""

import os
import threading
import time
from pathlib import Path

_TRUE_VALUES = {"1", "true", "yes", "on"}


def debug_log(event: str, **fields: object) -> None:
    """Append one diagnostic line when ``YAI_DEBUG_LOG`` is enabled."""
    target = os.environ.get("YAI_DEBUG_LOG", "").strip()
    if not target:
        return
    try:
        if target.lower() in _TRUE_VALUES:
            from .const import CONFIG_DIR

            path = CONFIG_DIR / "debug.log"
        else:
            path = Path(target).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = " ".join(f"{key}={value!r}" for key, value in fields.items())
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{stamp} [{threading.current_thread().name}] {event} {payload}\n")
    except (OSError, ValueError):  # never let diagnostics break the REPL
        pass
