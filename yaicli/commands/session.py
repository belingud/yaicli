"""Conversation and human checkpoint commands with explicit session dependencies."""

from rich.markdown import Markdown
from rich.padding import Padding

from ..console import safe_text, strip_control_chars
from ..const import CHAT_MODE, CMD_DELETE_CHAT, CMD_LOAD_CHAT
from ..runtime import bind_config
from ..tools import workspace
from .registry import CMD_CHECKPOINTS, CMD_FORK, CMD_REWIND


class SessionCommands:
    def __init__(self, sessions, console, config):
        self.sessions = sessions
        self.console = console
        self.config = config

    def _handle_checkpoint_command(self, command_input: str) -> bool:
        """Interactive, human-confirmed checkpoint operations (never model tools)."""
        with bind_config(self.config):
            from ..checkpoints import CheckpointError, display_text
            from ..console import get_error_console

            parts = command_input.split(maxsplit=2)
            command = parts[0].lower()
            usage = {
                CMD_CHECKPOINTS: "Usage: /checkpoints",
                CMD_REWIND: "Usage: /rewind [id]",
                CMD_FORK: "Usage: /fork [id] [title]",
            }[command]
            error_console = get_error_console()
            fork_saved = False
            title = ""
            try:
                if (command == CMD_CHECKPOINTS and len(parts) != 1) or (command == CMD_REWIND and len(parts) > 2):
                    raise CheckpointError(usage)
                if len(parts) > 1 and (not parts[1].isdigit()):
                    raise CheckpointError(usage)
                if not self.config.get("CHECKPOINT_ENABLED", True):
                    raise CheckpointError("Checkpoints are disabled (CHECKPOINT_ENABLED=false).")
                if not self.sessions.state.interactive or self.sessions.state.machine_output:
                    raise CheckpointError("Checkpoints require an interactive terminal.")
                if self.sessions.is_temp_session:
                    if command == CMD_CHECKPOINTS:
                        self.console.print("No checkpoints for this session.", markup=False)
                        return True
                    raise CheckpointError("Save this chat with /save before using checkpoints.")
                if command != CMD_CHECKPOINTS and str(self.config.get("TOOL_POLICY", "standard")).lower() == "readonly":
                    raise CheckpointError("Rewind and fork are unavailable in readonly mode.")
                store = self.sessions.checkpoint_store()
                if store is None:
                    raise CheckpointError("No checkpoints for this session.")
                chat = self.sessions.chat
                records = store.list_records(chat.checkpoint_head)
                if not records:
                    if command != CMD_CHECKPOINTS:
                        if len(parts) > 1:
                            raise CheckpointError(f"Checkpoint #{int(parts[1])} is unavailable.")
                        raise CheckpointError("No earlier checkpoint is available.")
                    self.console.print("No checkpoints for this session.", markup=False)
                    return True
                if command == CMD_CHECKPOINTS:
                    self.console.print("ID  Time      Turn  Paths  Status", markup=False)
                    for record in reversed(records):
                        status = "current" if record["id"] == chat.checkpoint_head else ""
                        self.console.print(
                            f"#{record['id']}  {record['ts'][11:19]}  {record['turn']:4}  {len({item['path'] for item in record['files']}):5}  {status}",
                            markup=False,
                        )
                    return True
                if len(parts) > 1:
                    target = int(parts[1])
                elif len(records) > 1:
                    target = int(records[-2]["id"])
                else:
                    raise CheckpointError("No earlier checkpoint is available.")
                preview = store.preview(target, chat.checkpoint_head)
                title = parts[2] if len(parts) == 3 else ""
                if command == CMD_FORK:
                    from datetime import datetime

                    title = title or f"Fork-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                    self.sessions.chat_manager.refresh_chats()
                    if len(parts) < 3:
                        base_title = title
                        suffix = 1
                        while any(item.title == title for item in self.sessions.chat_manager.list_chats()):
                            suffix += 1
                            title = f"{base_title}-{suffix}"
                    if len(parts) == 3 and any(item.title == title for item in self.sessions.chat_manager.list_chats()):
                        raise CheckpointError(f"Chat title already exists: {title}.")
                    self.console.print(
                        display_text(f'Save the current chat as "{title}" and rewind to checkpoint #{target}?'),
                        markup=False,
                    )
                else:
                    self.console.print(
                        f"Rewind to checkpoint #{target} and drop {preview['dropped_turns']} turn?", markup=False
                    )
                for name in preview["restore"]:
                    self.console.print(display_text(f"  Restore: {name}"), markup=False)
                for name in preview["remove"]:
                    self.console.print(display_text(f"  Remove:  {name}"), markup=False)
                if command == CMD_FORK:
                    self.console.print(
                        f"  Drop:    {preview['dropped_turns']} turn from the current chat", markup=False
                    )
                try:
                    answer = self.console.input("Proceed? [y/N]: ")
                except (KeyboardInterrupt, EOFError):
                    answer = ""
                if answer.strip().lower() != "y":
                    self.console.print("Cancelled.", markup=False)
                    return True
                # Recheck after confirmation before saving a fork or modifying paths.
                store.preview(target, chat.checkpoint_head)
                source = chat.to_dict()

                def archive():
                    nonlocal fork_saved, title
                    from ..chat import Chat

                    self.sessions.chat_manager.refresh_chats()
                    if any(item.title == title for item in self.sessions.chat_manager.list_chats()):
                        raise CheckpointError(f"Chat title already exists: {title}.")
                    fork_payload = dict(source)
                    fork_payload.pop("checkpoint_session_id", None)
                    fork_payload.pop("checkpoint_head", None)
                    fork_payload.pop("plan", None)
                    fork_chat = Chat.from_dict(fork_payload)
                    fork_chat.title = title
                    try:
                        title = self.sessions.chat_manager.save_chat_exclusive(fork_chat, auto_title=len(parts) < 3)
                        fork_saved = True
                    except Exception as exc:
                        if str(exc).startswith("Chat title already exists:"):
                            raise CheckpointError(str(exc)) from exc
                        raise CheckpointError("Cannot fork: the current chat could not be saved.") from exc

                def commit(snapshot):
                    from ..chat import Chat

                    loaded = Chat.from_dict(snapshot)
                    chat.history = loaded.history
                    chat.checkpoint_head = loaded.checkpoint_head
                    chat.save(self.sessions.chat_history_dir)

                result = store.rewind(
                    target,
                    chat.checkpoint_head,
                    commit,
                    source_snapshot=source,
                    before_apply=archive if command == CMD_FORK else None,
                )
                workspace.reset_undo()
                from ..tools.output_history import reset

                reset()
                self.sessions.clear_retry_snapshot()
                self.sessions.history_changed()
                self.sessions.chat_manager.refresh_chats()
                from ..checkpoints import checkpoint_audit

                checkpoint_audit(
                    command.lstrip("/"),
                    chat.checkpoint_session_id,
                    target,
                    "committed",
                    len(result["restore"]),
                    len(result["remove"]),
                )
                if command == CMD_FORK:
                    self.console.print(display_text(f'Chat saved as "{title}". Rewound to #{target}.'), markup=False)
                else:
                    self.console.print(
                        f"Rewound to #{target}. Restored {len(result['restore'])} path, removed {len(result['remove'])} path, dropped {result['dropped_turns']} turn.",
                        markup=False,
                    )
            except (CheckpointError, OSError, ValueError) as exc:
                if fork_saved:
                    self.console.print(display_text(f'Chat saved as "{title}".'), markup=False)
                error_console.print(display_text(str(exc)), markup=False)
            return True

    def handle_clear(self) -> bool:
        """Clear chat history.

        Returns:
            True to continue the REPL loop
        """
        if self.sessions.state.current_mode == CHAT_MODE:
            self.sessions.chat.history.clear()
            self.sessions.checkpoint_reset()
            self.console.print("Chat history cleared", style="bold yellow")
            # A cleared conversation has no turn to retry and no context to report.
            self.sessions.clear_retry_snapshot()
            self.sessions.history_changed()
        return True

    def handle_history(self) -> bool:
        """Show chat history.

        Returns:
            True to continue the REPL loop
        """
        if not self.sessions.chat.history:
            self.console.print("History is empty.", style="yellow")
        else:
            self.console.print("Chat History:", style="bold underline")
            message_count = 1
            for msg in self.sessions.chat.history:
                if msg.role == "user" and msg.content:
                    self.console.print(
                        f"[dim]{message_count}[/dim] [bold blue]User:[/bold blue] {safe_text(msg.content)}"
                    )
                    message_count += 1
                elif msg.role == "assistant" and (msg.content or msg.tool_calls):
                    content = strip_control_chars(msg.content or "")
                    if msg.tool_calls:
                        content += "\n" if content else ""  # Add newline if there's assistant content before tool calls
                        for t in msg.tool_calls:
                            content += (
                                f">Tool Call: {strip_control_chars(t.name)}({strip_control_chars(t.arguments)})\n"
                            )
                    md = Markdown(content, code_theme=self.config["CODE_THEME"])
                    padded_md = Padding(md, (0, 0, 0, 4))
                    self.console.print("    Assistant:", style="bold green")
                    self.console.print(padded_md)
                # Skip other roles (like "tool") and empty messages - they are not displayed
        return True

    def handle_list(self) -> bool:
        """List saved chats.

        Returns:
            True to continue the REPL loop
        """
        self.sessions.list_chats()
        return True

    def handle_save(self, command_input: str = "") -> bool:
        """Save current chat.

        Args:
            command_input: Raw command input that may contain a title

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.split(maxsplit=1)
        title = parts[1] if len(parts) > 1 else self.sessions.chat.title
        self.sessions.save_chat(title)
        return True

    def handle_load(self, command_input: str = "") -> bool:
        """Load saved chat.

        Args:
            command_input: Raw command input that should contain an index

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.split(maxsplit=1)
        if len(parts) == 2 and parts[1].isdigit():
            self.sessions.load_chat_by_index(index=parts[1])
        else:
            self.console.print(f"Usage: {CMD_LOAD_CHAT} <index>", style="yellow")
            self.sessions.list_chats()
        return True

    def handle_delete(self, command_input: str = "") -> bool:
        """Delete saved chat.

        Args:
            command_input: Raw command input that should contain an index

        Returns:
            True to continue the REPL loop
        """
        parts = command_input.split(maxsplit=1)
        if len(parts) == 2 and parts[1].isdigit():
            self.sessions.delete_chat_by_index(index=parts[1])
        else:
            self.console.print(f"Usage: {CMD_DELETE_CHAT} <index>", style="yellow")
            self.sessions.list_chats()
        return True
