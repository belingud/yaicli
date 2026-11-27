"""One definition for command dispatch, help and slash completion.

Only handler names live here: binding them to the current CmdHandler does not
require importing the CLI or constructing application services.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..const import (
    CHAT_MODE,
    CMD_ADD,
    CMD_CLEAR,
    CMD_CONTEXT,
    CMD_DELETE_CHAT,
    CMD_EXIT,
    CMD_HELP,
    CMD_HISTORY,
    CMD_LIST_CHATS,
    CMD_LOAD_CHAT,
    CMD_MODE,
    CMD_PLAN,
    CMD_SAVE_CHAT,
    CMD_TODO,
    EXEC_MODE,
)

CMD_COMPACT = "/compact"
CMD_PERMISSIONS = "/permissions"
CMD_SHOW_OUTPUT = "/show-output"
CMD_UNDO = "/undo"
CMD_COST = "/cost"
CMD_MODEL = "/model"
CMD_ROLE = "/role"
CMD_RETRY = "/retry"
CMD_CHECKPOINTS = "/checkpoints"
CMD_REWIND = "/rewind"
CMD_FORK = "/fork"
DEFAULT_COMPACT_KEEP_ROUNDS = 5


@dataclass(frozen=True)
class CommandInfo:
    """A command's spelling, presentation and dispatch policy.

    ``handler`` names a method on the current CmdHandler. When
    ``accepts_arguments`` is true, that method receives the unchanged input if
    the command has trailing text. Bare commands always call it without args.
    Non-slash aliases such as ``?`` are executable but omitted from completion.
    """

    command: str
    description: str
    usage: Optional[str] = None
    aliases: Tuple[str, ...] = ()
    handler: str = ""
    accepts_arguments: bool = False

    @property
    def help_text(self) -> str:
        """The usage column shown by ``CLI.print_help``."""
        return self.usage or self.command


COMMAND_INFO: Tuple[CommandInfo, ...] = (
    CommandInfo(
        CMD_HELP[0], "Show help message", usage="|".join(CMD_HELP), aliases=CMD_HELP[1:], handler="handle_help"
    ),
    CommandInfo(CMD_CLEAR, "Clear chat history", handler="handle_clear"),
    CommandInfo(CMD_HISTORY, "Show chat history", handler="handle_history"),
    CommandInfo(
        CMD_LIST_CHATS,
        "List saved chats",
        usage=f"{CMD_LIST_CHATS}|/chats",
        aliases=("/chats",),
        handler="handle_list",
    ),
    CommandInfo(
        CMD_SAVE_CHAT,
        "Save current chat",
        usage=f"{CMD_SAVE_CHAT} <title>",
        handler="handle_save",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_LOAD_CHAT,
        "Load a saved chat",
        usage=f"{CMD_LOAD_CHAT} <index>",
        handler="handle_load",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_DELETE_CHAT,
        "Delete a saved chat",
        usage=f"{CMD_DELETE_CHAT}|/delete <index>",
        aliases=("/delete",),
        handler="handle_delete",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_ADD,
        "Add @file/dir to context",
        usage=f"{CMD_ADD} <path>",
        handler="handle_add_context",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_CONTEXT[0],
        "Show context/token usage; manage context (list, add, remove, clear, budget)",
        usage="/context, /ctx",
        aliases=CMD_CONTEXT[1:],
        handler="handle_context",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_PLAN,
        "Plan mode: toggle, or plan a task; list/show/edit/review/resume/clear/abort",
        usage=f"{CMD_PLAN} [task|list [--all]|show [id]|edit|review [id]|resume [id]|clear [--done|--all]|abort]",
        handler="handle_plan",
        accepts_arguments=True,
    ),
    CommandInfo(CMD_TODO, "Show the current plan todos", handler="handle_todo"),
    CommandInfo(CMD_COST, "Show session token usage and estimated cost", handler="handle_cost"),
    CommandInfo(
        CMD_COMPACT,
        f"Compact history, keeping the last N turn groups (default {DEFAULT_COMPACT_KEEP_ROUNDS})",
        usage=f"{CMD_COMPACT} [keep_rounds]",
        handler="handle_compact",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_PERMISSIONS,
        "List/revoke tool permissions and session grants",
        usage=f"{CMD_PERMISSIONS} [revoke <tool-or-index>]",
        handler="handle_permissions",
        accepts_arguments=True,
    ),
    CommandInfo(CMD_SHOW_OUTPUT, "View this turn's tool outputs (same as Ctrl+O)", handler="handle_show_output"),
    CommandInfo(CMD_UNDO, "Undo the last file change made by a tool", handler="handle_undo"),
    CommandInfo(
        CMD_CHECKPOINTS,
        "List saved conversation checkpoints",
        handler="handle_checkpoints",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_REWIND,
        "Restore a previous conversation checkpoint",
        usage="/rewind [id]",
        handler="handle_rewind",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_FORK,
        "Save the current conversation and rewind",
        usage="/fork [id] [title]",
        handler="handle_fork",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_MODEL,
        "Show or switch the model for this session",
        usage=f"{CMD_MODEL} [name]",
        handler="handle_model",
        accepts_arguments=True,
    ),
    CommandInfo(
        CMD_ROLE,
        "Show or switch the assistant role",
        usage=f"{CMD_ROLE} [name]",
        handler="handle_role",
        accepts_arguments=True,
    ),
    CommandInfo(CMD_RETRY, "Re-run the last user turn (e.g. after an API error)", handler="handle_retry"),
    CommandInfo(CMD_EXIT, "Exit (Ctrl+D also exits)", usage=f"{CMD_EXIT}|Ctrl+D", handler="handle_exit"),
    CommandInfo(
        CMD_MODE,
        "Switch mode (Case insensitive)",
        usage=f"{CMD_MODE} {CHAT_MODE}|{EXEC_MODE}",
        handler="handle_mode",
        accepts_arguments=True,
    ),
)

COMMAND_BY_NAME: Dict[str, CommandInfo] = {
    name: info for info in COMMAND_INFO for name in (info.command, *info.aliases)
}


def command_completions() -> Tuple[Tuple[str, str], ...]:
    """Return canonical commands followed by their slash aliases in help order."""
    return tuple(
        (name, info.description)
        for info in COMMAND_INFO
        for name in (info.command, *info.aliases)
        if name.startswith("/")
    )
