"""Command handler for processing special commands in YAICLI."""

import shlex
import subprocess
from typing import Optional, Union

from .commands.registry import (
    CMD_CHECKPOINTS,
    CMD_COMPACT,
)
from .commands.registry import CMD_COST as CMD_COST
from .commands.registry import CMD_FORK
from .commands.registry import CMD_MODEL as CMD_MODEL
from .commands.registry import CMD_PERMISSIONS
from .commands.registry import CMD_RETRY as CMD_RETRY
from .commands.registry import CMD_REWIND
from .commands.registry import CMD_ROLE as CMD_ROLE
from .commands.registry import CMD_SHOW_OUTPUT as CMD_SHOW_OUTPUT
from .commands.registry import CMD_UNDO as CMD_UNDO
from .commands.registry import COMMAND_BY_NAME
from .commands.registry import COMMAND_INFO as COMMAND_INFO
from .commands.registry import DEFAULT_COMPACT_KEEP_ROUNDS
from .commands.registry import CommandInfo as CommandInfo
from .commands.registry import command_completions as command_completions
from .console import safe_text
from .const import (
    CHAT_MODE,
    CMD_ADD,
)
from .const import CMD_CLEAR as CMD_CLEAR
from .const import CMD_CONTEXT as CMD_CONTEXT
from .const import CMD_DELETE_CHAT as CMD_DELETE_CHAT
from .const import CMD_EXIT as CMD_EXIT
from .const import CMD_HELP as CMD_HELP
from .const import CMD_HISTORY as CMD_HISTORY
from .const import CMD_LIST_CHATS as CMD_LIST_CHATS
from .const import CMD_LOAD_CHAT as CMD_LOAD_CHAT
from .const import CMD_MODE
from .const import CMD_PLAN as CMD_PLAN
from .const import CMD_SAVE_CHAT as CMD_SAVE_CHAT
from .const import CMD_TODO as CMD_TODO
from .const import EXEC_MODE, DefaultRoleNames
from .tokens import ContextUsage, estimate_context_usage, trim_messages_to_budget
from .tools import workspace
from .tools.approval import PermissionRule

#: ``/context`` subcommands that print the estimated usage breakdown.
CONTEXT_BUDGET_SUBCOMMANDS = ("budget", "stats", "usage")


class CmdHandler:
    """Handler for special commands used in the CLI."""

    def __init__(self, cli):
        """Initialize command handler with reference to CLI instance.

        Args:
            cli: CLI instance to access methods and properties
        """
        self.cli = cli
        self.commands = {name: getattr(self, info.handler) for name, info in COMMAND_BY_NAME.items()}

    @property
    def session_commands(self):
        from .commands.session import SessionCommands

        return SessionCommands(self.cli.sessions, self.cli.console, self.cli.config)

    @property
    def plan_commands(self):
        from .commands.planning import PlanCommands

        return PlanCommands(self.cli.planning, self.cli.console, self.cli.config)

    @property
    def runtime_commands(self):
        from .commands.runtime import RuntimeCommands

        return RuntimeCommands(
            self.cli.config,
            getattr(self.cli, "run_state", None),
            getattr(self.cli, "role_manager", None),
            self.cli.console,
            set_role=getattr(self.cli, "set_role", None),
            invalidate_client=getattr(self.cli, "invalidate_client", lambda: None),
            refresh_context=getattr(self.cli, "refresh_context_percent", lambda: None),
            retry=getattr(self.cli, "retry_last_turn", None),
        )

    def handle_add_context(self, command_input: str = "") -> bool:
        """Handle /add command to add file/dir to context.

        Args:
            command_input: "/add path/to/file"

        Returns:
            True to continue REPL
        """
        try:
            parts = shlex.split(command_input)
        except ValueError as e:
            self.cli.console.print(f"Error parsing command: {safe_text(e)}", style="red")
            return True

        if len(parts) < 2:
            self.cli.console.print(f"Usage: {CMD_ADD} <path>", style="yellow")
            return True

        path = parts[1]
        if path.startswith("@"):
            path = path[1:]
        if self.cli.verbose:
            self.cli.console.print(f"[dim][DEBUG] Adding context: {safe_text(path)}[/dim]")
        self.cli.context_manager.add(path)
        return True

    # ------------------- context economy commands (v0.19 K02) -------------------
    def _history(self) -> list:
        """Return the conversation history as a list (defensive against mocks)."""
        chat = getattr(self.cli, "chat", None)
        history = getattr(chat, "history", None) if chat is not None else None
        return history if isinstance(history, list) else []

    def _role_prompt(self) -> str:
        """Return the active role prompt text (empty when unavailable)."""
        role = getattr(self.cli, "role", None)
        prompt = getattr(role, "prompt", "") if role is not None else ""
        return prompt if isinstance(prompt, str) else ""

    def _project_context(self) -> str:
        """Return the auto-loaded project instruction block (``""`` when unavailable)."""
        getter = getattr(self.cli, "_get_project_context", None)
        if not callable(getter):
            return ""
        try:
            project = getter()
        except Exception:  # defensive: /context must never fail on a project file
            return ""
        return project if isinstance(project, str) else ""

    def _persistent_context(self) -> list:
        """Return the persistent ``/add`` context messages (``[]`` when unavailable)."""
        manager = getattr(self.cli, "context_manager", None)
        getter = getattr(manager, "get_context_messages", None) if manager is not None else None
        if not callable(getter):
            return []
        try:
            messages = getter()
        except Exception:  # defensive: /context must never fail on a context file
            return []
        return messages if isinstance(messages, list) else []

    def _context_usage(self) -> "ContextUsage":
        """Estimate the current context usage for the ``/context`` command.

        Passes the parts the request assembler sends besides the role prompt
        (project instructions block + persistent ``/add`` context) so the shown
        total matches what the provider will actually receive.
        """
        config = self.cli.config if hasattr(self.cli.config, "get") else None
        provider = str(config.get("PROVIDER", "") or "") if config is not None else ""
        return estimate_context_usage(
            self._history(),
            config=config,
            system_text=self._role_prompt(),
            provider=provider,
            extra_system_text=self._project_context(),
            extra_messages=self._persistent_context(),
        )

    def _cfg_int(self, key: str, default: int = 0) -> int:
        """Read an integer config value, tolerating mocks/legacy strings."""
        config = self.cli.config if hasattr(self.cli.config, "get") else None
        if config is None:
            return default
        try:
            value = config.get(key)
        except Exception:  # defensive: a broken config mapping must not break /context
            return default
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _print_context_usage(self) -> None:
        """Print the estimated usage breakdown with the window source and reserve."""
        usage = self._context_usage()
        console = self.cli.console
        source = usage.source or "default"
        if source == "default":
            # An unknown model must say so and tell the user how to fix it.
            detail = usage.detail or "assumed for unknown model"
            source_text = f"{detail}; set MODEL_CONTEXT_WINDOWS to override"
        else:
            source_text = usage.detail or ""
        window_line = f"  window        : {usage.window_tokens:,} tokens (source: {source}"
        if source_text:
            window_line += f" · {source_text}"
        window_line += ")"
        console.print("Context usage (estimated):", style="bold")
        console.print(window_line)
        console.print(f"  role prompt   : {usage.system_tokens:,} tokens")
        console.print(f"  project ctx   : {usage.project_tokens:,} tokens")
        console.print(f"  /add context  : {usage.extra_tokens:,} tokens")
        console.print(f"  history       : {usage.history_tokens:,} tokens (tool output {usage.tool_output_tokens:,})")
        console.print(f"  overhead      : {usage.overhead_tokens:,} tokens")
        console.print(
            f"  total         : {usage.total_tokens:,} / {usage.budget_tokens:,} tokens ({usage.used_percent:.1f}%)"
        )
        console.print(f"  remaining     : {usage.remaining_tokens:,} tokens")
        max_tokens = self._cfg_int("MAX_TOKENS", 1024)
        safety_tokens = self._cfg_int("CONTEXT_SAFETY_TOKENS", 1024)
        console.print(
            f"  reserve       : {usage.reserve_tokens:,} (MAX_TOKENS {max_tokens:,} + safety {safety_tokens:,})"
        )
        # markup=False keeps the literal ``[keep_rounds]`` (Rich markup would eat it).
        console.print("  Use /compact [keep_rounds] to drop older turn groups.", style="dim", markup=False)

    def handle_compact(self, command_input: str = "") -> bool:
        """Handle ``/compact [keep_rounds]``: drop old whole turn groups from history.

        Only complete turn groups are removed, so the tool_call <-> tool pairing
        stays valid. Prints the estimated token counts before/after.

        Args:
            command_input: "/compact" or "/compact 3"

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.split()
        keep_rounds = DEFAULT_COMPACT_KEEP_ROUNDS
        if len(parts) > 1:
            try:
                keep_rounds = int(parts[1])
            except (TypeError, ValueError):
                keep_rounds = 0
            if keep_rounds < 1:
                self.cli.console.print(f"Usage: {CMD_COMPACT} [keep_rounds]", style="yellow")
                return True

        history = self._history()
        if not history:
            self.cli.console.print("Chat history is empty; nothing to compact.", style="yellow")
            return True

        result = trim_messages_to_budget(history, budget=0, keep_recent_groups=keep_rounds)
        if not result.removed_messages:
            self.cli.console.print(
                f"Nothing to compact: history already has at most {keep_rounds} turn groups.", style="dim"
            )
            return True

        self.cli.chat.history = result.messages
        self.cli.console.print(
            f"Compacted context: {result.tokens_before:,} -> {result.tokens_after:,} estimated tokens "
            f"({result.removed_count} message(s) removed, keeping the last {keep_rounds} turn groups).",
            style="bold green",
        )
        # The conversation moved on: refresh the prompt's context % and drop the
        # /retry snapshot (restoring it would undo the compaction).
        self._clear_retry_snapshot()
        self._refresh_context_percent()
        return True

    # ------------------- permission commands (v0.19 K06) -------------------
    def _approval_manager(self):
        """Return the ToolApprovalManager backing the current session, if any."""
        client = getattr(self.cli, "client", None)
        manager = getattr(client, "approval", None)
        if manager is None:
            manager = getattr(self.cli, "approval", None)
        return manager

    @staticmethod
    def _permission_names(value) -> list:
        """Normalize a session/persistent name collection to a sorted list."""
        if isinstance(value, (set, frozenset, list, tuple)):
            return sorted(str(item) for item in value)
        return []

    def _print_permissions(self, manager) -> None:
        """Print session approvals, persistent allowlist entries and indexed rules."""
        console = self.cli.console
        session = self._permission_names(getattr(manager, "session_allow", None))
        persisted = self._permission_names(getattr(manager, "persistent_allow", None))
        rules = [rule for rule in getattr(manager, "persistent_rules", None) or [] if isinstance(rule, PermissionRule)]
        path = getattr(manager, "permissions_path", "")

        console.print("Tool permissions:", style="bold")
        console.print(f"  Session approvals (this run only): {len(session)}")
        if session:
            for name in session:
                console.print(f"    - {safe_text(name)}")
        else:
            console.print("    (none)")
        console.print(f"  Persistent always_allow: {len(persisted)}  {safe_text(path)}")
        if persisted:
            for name in persisted:
                console.print(f"    - {safe_text(name)}")
        else:
            console.print("    (none)")
        console.print(f"  Persistent rules: {len(rules)}")
        if rules:
            for index, rule in enumerate(rules, start=1):
                console.print(f"    {index}. {safe_text(rule.describe())}")
        else:
            console.print("    (none)")
        console.print(f"[dim]  Use {CMD_PERMISSIONS} revoke <tool-or-index> to remove a persistent permission.[/dim]")

    def handle_permissions(self, command_input: str = "") -> bool:
        """Handle ``/permissions`` and ``/permissions revoke <tool-or-index>``.

        Lists the persistent rules and session approvals, or revokes one persistent
        allowlist entry / rule (by tool name or by the 1-based rule index shown by the
        listing) so the tool asks again. ``remove`` is accepted as an alias of
        ``revoke``.

        Args:
            command_input: "/permissions" or "/permissions revoke <tool-or-index>"

        Returns:
            True to continue the REPL loop
        """
        manager = self._approval_manager()
        if manager is None:
            self.cli.console.print("No tool permission store is available in this session.", style="yellow")
            return True
        try:
            parts = shlex.split(command_input)
        except ValueError as e:
            self.cli.console.print(f"Error parsing command: {safe_text(e)}", style="red")
            return True

        args = parts[1:] if parts else []
        if not args:
            self._print_permissions(manager)
            return True

        action = args[0].lower()
        if action in ("revoke", "remove", "rm"):
            if len(args) < 2:
                self.cli.console.print(f"Usage: {CMD_PERMISSIONS} revoke <tool-or-index>", style="yellow")
                return True
            target = args[1]
            revoke = getattr(manager, "revoke", None)
            if not callable(revoke):
                self.cli.console.print("This permission store does not support revocation.", style="yellow")
                return True
            try:
                revoked = revoke(target)
            except OSError as e:
                self.cli.console.print(f"Could not update the permission file: {safe_text(e)}", style="red")
                return True
            if revoked:
                self.cli.console.print(
                    f"Revoked {safe_text(revoked)}. The tool will ask for approval again.", style="bold green"
                )
            else:
                self.cli.console.print(f"No permission matched '{safe_text(target)}'.", style="yellow")
                self._print_permissions(manager)
            return True

        self.cli.console.print(f"Unknown sub-command: {safe_text(action)}", style="yellow")
        self.cli.console.print(safe_text(f"Usage: {CMD_PERMISSIONS} [revoke <tool-or-index>]"), style="dim")
        return True

    def handle_show_output(self) -> bool:
        """Handle /show-output: open the full-screen viewer for this turn's outputs.

        The viewer lists every tool result of the current turn; closing it
        restores the REPL. Same entry point as ``Ctrl+O``.

        Returns:
            True to continue the REPL loop
        """
        opener = getattr(self.cli, "_open_tool_output_viewer", None)
        if callable(opener):
            opener()
        else:  # pragma: no cover - bare/legacy CLI objects without the viewer
            from .tools import show_last_tool_output

            show_last_tool_output(self.cli.console)
        return True

    def handle_undo(self) -> bool:
        """Handle /undo: restore the last file mutation the agent made.

        The undo stack is populated by ``yaicli.tools.execute_tool_call`` (K11): an
        overwritten/edited/deleted/moved file is restored from its backup, and a
        file/directory the agent created is deleted. Prints what was done (or a
        friendly message when there is nothing to undo).

        Returns:
            True to continue the REPL loop
        """
        from .tools.environment import tool_environment

        with tool_environment(self.cli.config):
            outcome = workspace.undo_last()
        if outcome is not None:
            self.cli.sessions.checkpoint_reset()
        if outcome is None:
            self.cli.console.print(
                "Nothing to undo: no file changes were recorded in this session.",
                style="yellow",
            )
            return True

        verb = "restore" if outcome.restored else "remove"
        self.cli.console.print(
            f"Undid the last file change ({safe_text(outcome.tool)}): {verb} "
            f"{len(outcome.restored) + len(outcome.deleted)} path(s).",
            style="bold green" if not outcome.errors else "bold yellow",
        )
        for path in outcome.restored:
            self.cli.console.print(f"  restored: {safe_text(path)}", style="green")
        for path in outcome.deleted:
            self.cli.console.print(f"  deleted: {safe_text(path)}", style="green")
        for error in outcome.errors:
            self.cli.console.print(f"  failed: {safe_text(error)}", style="red")
        if outcome.errors:
            self.cli.console.print(
                "The undo was only partially applied; fix the reported errors and retry.",
                style="yellow",
            )
        return True

    def handle_checkpoints(self, command_input: str = "") -> bool:
        return self._handle_checkpoint_command(command_input or CMD_CHECKPOINTS)

    def handle_rewind(self, command_input: str = "") -> bool:
        return self._handle_checkpoint_command(command_input or CMD_REWIND)

    def handle_fork(self, command_input: str = "") -> bool:
        return self._handle_checkpoint_command(command_input or CMD_FORK)

    def _handle_checkpoint_command(self, command_input: str) -> bool:
        return self.session_commands._handle_checkpoint_command(command_input)

    # ------------------- usage / cost commands (v0.22 K17) -------------------
    @staticmethod
    def _usage_int(snapshot, key: str) -> int:
        """Read a non-negative integer field from a usage snapshot (never raises)."""
        if not isinstance(snapshot, dict):
            return 0
        value = snapshot.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return max(0, value)

    @staticmethod
    def _usage_cost(value):
        """Return a finite float cost or ``None`` (unknown pricing/invalid value)."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _cost_snapshot(self):
        """Return the live client's usage snapshot, or ``None`` when unavailable.

        Uses the private client slot: ``/cost`` must not construct the LLM client
        as a side effect (and must never raise on a mock/legacy client).
        """
        client = getattr(self.cli, "active_client", None)
        if client is None:
            return None
        getter = getattr(client, "usage_snapshot", None)
        if not callable(getter):
            return None
        try:
            snapshot = getter()
        except Exception:  # pragma: no cover - usage reporting must never break the REPL
            return None
        return snapshot if isinstance(snapshot, dict) else None

    def handle_cost(self) -> bool:
        """Handle ``/cost``: show session tokens, per-model usage and estimated cost.

        Reports provider-reported plus estimated usage, the estimated USD cost
        (``unknown model pricing`` when no price is known), tool call metrics and
        the last provider finish reason.

        Returns:
            True to continue the REPL loop
        """
        console = self.cli.console
        snapshot = self._cost_snapshot()
        if snapshot is None:
            console.print(
                "No token usage is available in this session yet; make a request, then run /cost again.",
                style="yellow",
            )
            return True

        prompt = self._usage_int(snapshot, "prompt_tokens")
        completion = self._usage_int(snapshot, "completion_tokens")
        total = self._usage_int(snapshot, "total_tokens") or (prompt + completion)
        requests = self._usage_int(snapshot, "requests")
        cached = self._usage_int(snapshot, "cached_tokens")
        reasoning = self._usage_int(snapshot, "reasoning_tokens")
        estimated = bool(snapshot.get("estimated"))
        models = snapshot.get("models")
        has_models = isinstance(models, dict) and bool(models)
        if requests == 0 and total == 0 and not has_models:
            console.print(
                "No usage recorded yet in this session. Make a request, then run /cost again.",
                style="yellow",
            )
            return True

        label = " (estimated)" if estimated else ""
        console.print("Session usage:", style="bold")
        console.print(f"  tokens    : {prompt:,} in / {completion:,} out ({total:,} total){label}")
        if cached:
            console.print(f"  cached    : {cached:,} tokens")
        if reasoning:
            console.print(f"  reasoning : {reasoning:,} tokens")
        console.print(f"  requests  : {requests:,}")

        cost = self._usage_cost(snapshot.get("cost_usd"))
        if cost is None:
            console.print("  cost      : unknown model pricing (set MODEL_PRICING for an estimate)")
        else:
            console.print(f"  cost      : ${cost:.4f} estimated USD")

        tools = snapshot.get("tools")
        if isinstance(tools, dict):
            tool_count = self._usage_int(tools, "count")
            duration = tools.get("duration_ms", 0)
            duration_text = f"{float(duration):.0f} ms" if self._usage_cost(duration) is not None else "0 ms"
            result_chars = self._usage_int(tools, "result_chars")
            console.print(f"  tools     : {tool_count:,} call(s), {duration_text}, {result_chars:,} result chars")

        client = getattr(self.cli, "active_client", None)
        finish = getattr(client, "last_finish_reason", None) if client is not None else None
        if isinstance(finish, str) and finish:
            console.print(f"  last stop : {safe_text(finish)}")

        if has_models:
            console.print("Per model:", style="bold")
            for name, data in models.items():
                if not isinstance(data, dict):
                    continue
                model_in = self._usage_int(data, "prompt_tokens")
                model_out = self._usage_int(data, "completion_tokens")
                model_cost = self._usage_cost(data.get("cost_usd"))
                cost_text = f"${model_cost:.4f}" if model_cost is not None else "unknown pricing"
                console.print(f"  {safe_text(str(name))}: {model_in:,} in / {model_out:,} out, {cost_text}")
        return True

    # ------------------- model / role / retry commands -------------------
    def _cfg_value(self, key: str, default=""):
        """Read a config value defensively (never raise on mock/legacy config)."""
        try:
            if hasattr(self.cli.config, "get"):
                value = self.cli.config.get(key, default)
                return value if value is not None else default
        except Exception:  # pragma: no cover - config lookups must never break a command
            return default
        return default

    def _set_cfg_value(self, key: str, value) -> bool:
        """Write one config value for this session (returns False when unsupported)."""
        try:
            self.cli.config[key] = value
            return True
        except Exception:  # pragma: no cover - read-only/legacy config objects
            return False

    def _invalidate_client(self) -> None:
        """Drop the lazily-created LLM client so the next request rebuilds it."""
        try:
            self.cli.invalidate_client()
        except (AttributeError, TypeError):  # pragma: no cover - bare/legacy CLI objects
            pass

    def _refresh_context_percent(self) -> None:
        """Refresh the CLI's cached context-usage percentage after a history change."""
        updater = getattr(self.cli, "refresh_context_percent", None)
        if not callable(updater):  # pragma: no cover - lightweight CLI stand-ins
            return
        try:
            updater()
        except Exception:  # pragma: no cover - prompt decoration must never break a command
            pass

    def _clear_retry_snapshot(self) -> None:
        """Forget the ``/retry`` snapshot: the conversation it belonged to moved on."""
        try:
            self.cli.clear_retry_snapshot()
        except (AttributeError, TypeError):  # pragma: no cover - bare/legacy CLI objects
            pass

    def _current_role_name(self) -> str:
        """Return the active role name (``""`` when unknown)."""
        value = getattr(self.cli, "role_name", "")
        return value if isinstance(value, str) else ""

    def _available_role_names(self) -> list:
        """Return the registered role ids/names (empty when the manager cannot list)."""
        manager = getattr(self.cli, "role_manager", None)
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
        manager = getattr(self.cli, "role_manager", None)
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
        return self.runtime_commands.handle_model(command_input)

    def handle_role(self, command_input: str = "") -> bool:
        return self.runtime_commands.handle_role(command_input)

    def handle_retry(self) -> bool:
        return self.runtime_commands.handle_retry()

    def handle_context(self, command_input: str = "") -> bool:
        """Handle /context (or /ctx) command.

        With no subcommand (or ``budget``/``stats``) it prints the estimated context
        usage; the file-context subcommands stay exactly as before.

        Subcommands:
            list: List context items
            clear: Clear context
            remove <path>: Remove item from context
            add <path>: Add item (same as /add)
            budget: Show the estimated usage breakdown (alias: stats/usage)

        Args:
            command_input: "/context <subcmd> [args]"
        """
        try:
            parts = shlex.split(command_input)
        except ValueError as e:
            self.cli.console.print(f"Error parsing command: {safe_text(e)}", style="red")
            return True

        if len(parts) < 2:
            # Bare ``/context`` = usage block + the legacy ``/add`` list. The
            # subcommand hint is not repeated here: it is long, already rendered
            # by ``/help``/the docstring, and belongs to the error path below.
            self._print_context_usage()
            self.cli.context_manager.list_items()
            return True

        subcmd = parts[1].lower()

        if subcmd in CONTEXT_BUDGET_SUBCOMMANDS:
            self._print_context_usage()
        elif subcmd == "list":
            self.cli.context_manager.list_items()
        elif subcmd == "clear":
            self.cli.context_manager.clear()
        elif subcmd == "add":
            if len(parts) < 3:
                self.cli.console.print("Usage: /context add <path>", style="yellow")
            else:
                path = parts[2]
                if path.startswith("@"):
                    path = path[1:]
                self.cli.context_manager.add(path)
        elif subcmd in ("remove", "rm", "delete", "del"):
            if len(parts) < 3:
                self.cli.console.print("Usage: /context remove <path>", style="yellow")
            else:
                self.cli.context_manager.remove(parts[2])
        else:
            self.cli.console.print(f"Unknown sub-command: {safe_text(subcmd)}", style="yellow")
            self.cli.console.print("Available: list, clear, add <path>, remove <path>, budget", style="dim")

        return True

    # ------------------- plan mode commands (v0.24 K23) -------------------
    def _plan_enabled(self) -> bool:
        """Whether persistent plan mode is enabled (``PLAN_ENABLED``; defaults on)."""
        try:
            return bool(self.cli.config.get("PLAN_ENABLED", True))
        except Exception:  # pragma: no cover - config lookups must never break a command
            return True

    def _print_plan_disabled(self) -> None:
        return self.plan_commands._print_plan_disabled()

    @staticmethod
    def _truncate_cell(value, limit: int = 48) -> str:
        """Bound a table cell width (Rich tables must stay readable in a terminal)."""
        text = str(value or "")
        return text if len(text) <= limit else text[: max(limit - 1, 0)] + "…"

    def _handle_plan_list(self, argument: str) -> None:
        return self.plan_commands._handle_plan_list(argument)

    def _handle_plan_show(self, plan_id: Optional[str]) -> None:
        return self.plan_commands._handle_plan_show(plan_id)

    def _handle_plan_clear(self, argument: str) -> None:
        return self.plan_commands._handle_plan_clear(argument)

    def _handle_plan_abort(self) -> None:
        return self.plan_commands._handle_plan_abort()

    def handle_plan(self, command_input: str = "") -> Union[bool, str]:
        return self.plan_commands.handle_plan(command_input)

    def handle_todo(self) -> bool:
        return self.plan_commands.handle_todo()

    def handle_command(self, user_input: str) -> Union[bool, str]:
        """Handle special command return: True-continue loop, False-exit loop, str-non-special command

        Args:
            user_input: Raw input from the user

        Returns:
            True if command handled and should continue loop
            False if should exit loop
            user_input if not a special command
        """
        lower_input = user_input.lower().strip()

        # Check if input starts with exclamation mark (both half-width ! and full-width ！)
        if user_input.startswith("!") or user_input.startswith("！"):
            cmd = user_input[1:].strip()
            return self.handle_shell_command(cmd)

        # Check for commands with exact command names
        if lower_input in self.commands:
            return self.commands[lower_input]()

        # Check for commands with parameters. Match the first whitespace-delimited
        # token (not a raw string prefix) so e.g. ``/model`` is never mistaken for
        # ``/mode`` and an unknown ``/modelx`` stays a normal prompt.
        parts = lower_input.split(maxsplit=1)
        if len(parts) == 2:
            command_token = parts[0]
            handler = self.commands.get(command_token)
            info = COMMAND_BY_NAME.get(command_token)
            if handler is not None and info is not None and info.accepts_arguments:
                return handler(user_input)

        # Not a special command
        return user_input

    def handle_shell_command(self, cmd: str) -> bool:
        """Execute a shell command directly with current environment variables.

        Args:
            cmd: Shell command to execute

        Returns:
            True to continue the REPL loop
        """
        if not cmd:
            return True

        self.cli.console.print(f"Executing: {safe_text(cmd)}", style="bold green")
        try:
            subprocess.call(cmd, shell=True)
        except Exception as e:
            self.cli.console.print(f"Failed to execute command: {safe_text(e)}", style="red")
        finally:
            self.cli.sessions.checkpoint_reset()
        return True

    def handle_help(self) -> bool:
        """Show help message.

        Returns:
            True to continue the REPL loop
        """
        self.cli.print_help()
        return True

    def handle_exit(self) -> bool:
        """Exit the REPL loop.

        Returns:
            False to exit the REPL loop
        """
        return False

    def handle_clear(self) -> bool:
        return self.session_commands.handle_clear()

    def handle_history(self) -> bool:
        return self.session_commands.handle_history()

    def handle_list(self) -> bool:
        return self.session_commands.handle_list()

    def handle_save(self, command_input: str = "") -> bool:
        return self.session_commands.handle_save(command_input)

    def handle_load(self, command_input: str = "") -> bool:
        return self.session_commands.handle_load(command_input)

    def handle_delete(self, command_input: str = "") -> bool:
        return self.session_commands.handle_delete(command_input)

    def handle_mode(self, command_input: str = "") -> bool:
        """Switch between chat and exec modes.

        Args:
            command_input: Raw command input that should contain the mode

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.lower().split(maxsplit=1)
        if len(parts) == 2 and parts[1] in [CHAT_MODE, EXEC_MODE]:
            new_mode = parts[1]
            if self.cli.current_mode != new_mode:
                self.cli.current_mode = new_mode
                self.cli.set_role(DefaultRoleNames.SHELL if self.cli.current_mode == EXEC_MODE else self.cli.init_role)
            else:
                self.cli.console.print(f"Already in {self.cli.current_mode} mode.", style="yellow")
        else:
            self.cli.console.print(f"Usage: {CMD_MODE} {CHAT_MODE}|{EXEC_MODE}", style="yellow")
        return True
