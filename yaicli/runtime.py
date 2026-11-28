"""Session-owned dependencies and a scoped effective configuration binding.

This module is deliberately independent from configuration loading and planning.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Iterator, Optional

if TYPE_CHECKING:
    from .planning.model import PlanSession

_config: ContextVar[Optional[Any]] = ContextVar("yaicli_effective_config", default=None)


def current_config(default: Any) -> Any:
    """Return the bound mapping, or the caller's compatible default."""
    config = _config.get()
    return default if config is None else config


@contextmanager
def bind_config(config: Any) -> Iterator[None]:
    """Bind a mapping for this call/context, restoring the previous binding."""
    token = _config.set(config)
    try:
        yield
    finally:
        _config.reset(token)


class SessionContext:
    """Keep one effective mapping and one lazily constructed plan session."""

    __slots__ = ("config", "_plan_session")

    def __init__(self, config: Any):
        self.config = config
        self._plan_session: Optional["PlanSession"] = None

    def peek_plan_session(self) -> Optional["PlanSession"]:
        return self._plan_session

    def get_plan_session(self) -> "PlanSession":
        if self._plan_session is None:
            from .planning.model import PlanSession

            self._plan_session = PlanSession()
        return self._plan_session

    def set_plan_session(self, session: Optional["PlanSession"]) -> None:
        self._plan_session = session

    @property
    def tool_mode(self) -> Optional[str]:
        mode = getattr(self._plan_session, "mode", None)
        if mode in ("researching", "revising"):
            return "plan"
        return "execution" if mode == "executing" else None
