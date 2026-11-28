"""Model, role and retry commands over named application operations."""

from typing import Optional

from ..console import safe_text
from ..const import CHAT_MODE, EXEC_MODE, DefaultRoleNames
from .registry import CMD_MODEL, CMD_ROLE


class RuntimeCommands:
    def __init__(self, config, state, role_manager, console, *, set_role, invalidate_client, refresh_context, retry):
        self.config = config
        self.state = state
        self.role_manager = role_manager
        self.console = console
        self.set_role = set_role
        self.invalidate_client = invalidate_client
        self.refresh_context = refresh_context
        self.retry = retry

    def _invalidate_client(self):
        self.invalidate_client()

    def _refresh_context_percent(self):
        self.refresh_context()

    def _cfg_value(self, key: str, default=""):
        """Read a config value defensively (never raise on mock/legacy config)."""
        try:
            if hasattr(self.config, "get"):
                value = self.config.get(key, default)
                return value if value is not None else default
        except Exception:  # pragma: no cover - config lookups must never break a command
            return default
        return default

    def _set_cfg_value(self, key: str, value) -> bool:
        """Write one config value for this session (returns False when unsupported)."""
        try:
            self.config[key] = value
            return True
        except Exception:  # pragma: no cover - read-only/legacy config objects
            return False

    def _current_role_name(self) -> str:
        """Return the active role name (``""`` when unknown)."""
        value = self.state.role_name
        return value if isinstance(value, str) else ""

    def _available_role_names(self) -> list:
        """Return the registered role ids/names (empty when the manager cannot list)."""
        manager = self.role_manager
        lister = getattr(manager, "list_roles", None)
        if not callable(lister):
            return []
        try:
            entries = lister()
        except Exception:  # pragma: no cover - listing must never break the command
            return []
        if not isinstance(entries, (list, tuple)):
            return []
        names: list = []
        for entry in entries:
            if isinstance(entry, dict):
                name = entry.get("id") or entry.get("name")
            else:
                name = getattr(entry, "name", None)
            if isinstance(name, str) and name and name not in names:
                names.append(name)
        return names

    def _resolve_role_name(self, requested: str) -> Optional[str]:
        """Resolve a role name exactly, then case-insensitively; ``None`` if unknown."""
        names = self._available_role_names()
        if requested in names:
            return requested
        folded = requested.casefold()
        for name in names:
            if name.casefold() == folded:
                return name
        if names:
            return None
        # A manager that cannot list roles may still resolve the exact name.
        manager = self.role_manager
        getter = getattr(manager, "get_role", None)
        if not callable(getter):  # pragma: no cover - lightweight CLI stand-ins
            return None
        try:
            role = getter(requested)
        except Exception:
            return None
        name = getattr(role, "name", None)
        return name if isinstance(name, str) and name else requested

    def handle_model(self, command_input: str = "") -> bool:
        """Handle ``/model [name]``: show or switch the model for this session.

        Switching writes ``self.config["MODEL"]``, drops the lazily-created provider client
        so the next request rebuilds it, and keeps the chat history. The change is
        session-only; the notice names the previous model so it can be restored.

        Args:
            command_input: "/model" or "/model <name>"

        Returns:
            True to continue the REPL loop
        """
        console = self.console
        current = self._cfg_value("MODEL")
        provider = self._cfg_value("PROVIDER")
        parts = command_input.split(maxsplit=1)
        requested = parts[1].strip() if len(parts) > 1 else ""

        if not requested:
            console.print(f"Model    : {safe_text(str(current or 'unknown'))}")
            console.print(f"Provider : {safe_text(str(provider or 'unknown'))}")
            console.print(
                f"[dim]  Use {CMD_MODEL} <name> to switch the model for this session; "
                f"changes are not written to the config file.[/dim]"
            )
            return True

        if requested == current:
            console.print(f"Already using model '{safe_text(requested)}'.", style="yellow")
            return True

        if not self._set_cfg_value("MODEL", requested):
            console.print("Could not update the session model for this CLI.", style="red")
            return True

        # The provider/client captured the old model at construction: rebuild it on
        # the next request so the switch takes effect without touching the history.
        self._invalidate_client()
        self._refresh_context_percent()
        old = str(current) if current else "unknown"
        console.print(
            f"Model switched: {safe_text(old)} -> {safe_text(requested)} (session only).",
            style="bold green",
        )
        console.print(
            f"[dim]  Chat history is kept and the provider client is rebuilt on the next request. "
            f"Revert with {CMD_MODEL} {safe_text(old)}, or restart to use the configured model.[/dim]"
        )
        return True

    def handle_role(self, command_input: str = "") -> bool:
        """Handle ``/role [name]``: show or switch the assistant role.

        Role names resolve exactly first, then case-insensitively. An unknown role
        prints the available names instead of raising. Switching keeps the prompt
        in sync (``CLI.set_role`` updates the role prompt); a non-shell role returns
        the session to chat mode.

        Args:
            command_input: "/role" or "/role <name>"

        Returns:
            True to continue the REPL loop
        """
        console = self.console
        current = self._current_role_name()
        available = self._available_role_names()
        parts = command_input.split(maxsplit=1)
        requested = parts[1].strip() if len(parts) > 1 else ""

        if not requested:
            console.print(f"Role: {safe_text(current or 'unknown')}", style="bold")
            if available:
                console.print(f"[dim]  Available: {safe_text(', '.join(available))}[/dim]")
            console.print(f"[dim]  Use {CMD_ROLE} <name> to switch the assistant role.[/dim]")
            return True

        resolved = self._resolve_role_name(requested)
        if resolved is None:
            console.print(f"Unknown role: {safe_text(requested)}", style="yellow")
            if available:
                console.print(f"Available roles: {safe_text(', '.join(available))}")
                console.print("[dim]  Use --list-roles outside the REPL for role details.[/dim]")
            else:  # pragma: no cover - a manager without a role list
                console.print("Use --list-roles outside the REPL to see the available roles.", style="dim")
            return True

        if resolved == current:
            console.print(f"Already using role '{safe_text(resolved)}'.", style="yellow")
            return True

        setter = self.set_role
        if not callable(setter):  # pragma: no cover - lightweight CLI stand-ins
            console.print("This CLI cannot switch roles in the current session.", style="yellow")
            return True

        setter(resolved)
        # Keep Shift+Tab/mode switching consistent with the newly selected role.
        try:
            self.state.init_role = resolved
        except (AttributeError, TypeError):  # pragma: no cover - bare/legacy CLI objects
            pass
        if resolved != DefaultRoleNames.SHELL and self.state.current_mode == EXEC_MODE:
            self.state.current_mode = CHAT_MODE
        self._refresh_context_percent()
        old = current or "unknown"
        console.print(f"Role switched: {safe_text(old)} -> {safe_text(resolved)}.", style="bold green")
        console.print(f"[dim]  Revert with {CMD_ROLE} {safe_text(old)}, or restart to use the configured role.[/dim]")
        return True

    def handle_retry(self) -> bool:
        """Handle ``/retry``: re-run the last user turn from its pre-turn snapshot.

        The CLI snapshots history + input + images before each turn, so a turn
        that failed (e.g. an API error) can be replayed without duplicating the
        partial assistant/tool messages it produced.

        Returns:
            True to continue the REPL loop
        """
        retry = self.retry
        if not callable(retry):
            self.console.print("Nothing to retry: this CLI has no turn snapshot.", style="yellow")
            return True
        try:
            retry()
        except Exception as e:  # the REPL must survive a failed retry
            self.console.print(f"Retry failed: {safe_text(e)}", style="red")
        return True
