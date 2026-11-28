"""Scoped environment bridge for standalone tools, ordered before workspace locks."""

import os
from contextlib import contextmanager
from threading import RLock

from ..runtime import bind_config

_MANAGED_ENV = (
    ("TOOL_TIMEOUT", "YAI_TOOL_TIMEOUT"),
    ("TOOL_ENV_INHERIT", "YAI_TOOL_ENV_INHERIT"),
    ("WORKSPACE_ROOT", "YAI_WORKSPACE_ROOT"),
    ("TOOL_OUTPUT_MAX_CHARS", "YAI_TOOL_OUTPUT_MAX_CHARS"),
)
_ENV_LOCK = RLock()


@contextmanager
def tool_environment(config):
    """Apply one effective mapping during execution and restore every managed key.

    Acquire this scope in the executing thread, before a workspace mutation lock.
    It must never wrap a request generator, confirmation wait or worker lifetime.
    """
    with _ENV_LOCK:
        previous = {name: os.environ.get(name) for _, name in _MANAGED_ENV}
        try:
            for key, name in _MANAGED_ENV:
                value = config.get(key)
                if value is None or value == "":
                    os.environ.pop(name, None)
                else:
                    if isinstance(value, bool):
                        value = "true" if value else "false"
                    os.environ[name] = str(value)
            with bind_config(config):
                yield
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
