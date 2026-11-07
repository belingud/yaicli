import os
import sys
from typing import Any, Dict, List, Tuple, cast

from json_repair import repair_json
from rich.panel import Panel

from ..config import cfg
from ..console import get_console, get_error_console, safe_text, strip_control_chars, untrusted_text
from ..exceptions import MCPToolsError
from ..schemas import ToolCall
from . import output_history, workspace
from .function import get_function, list_functions
from .limits import (
    build_preview_marker,
    make_display_preview,
    summarize_arguments,
    truncate_tool_output_meta,
)

# Lazy import MCP-related items to improve startup time
# These constants are safe to define without importing fastmcp
MCP_TOOL_NAME_PREFIX = "_mcp__"


def parse_mcp_tool_name(name: str) -> str:
    """Parse MCP tool name - remove the prefix _mcp__ from the tool name."""
    return name.removeprefix(MCP_TOOL_NAME_PREFIX)


def get_mcp_manager():
    """Lazy import and return MCP manager"""
    from .mcp import get_mcp_manager as _get_mcp_manager

    return _get_mcp_manager()


def get_mcp(name: str):
    """Lazy import and get MCP tool"""
    from .mcp import get_mcp as _get_mcp

    return _get_mcp(name)


def _stdout_is_tty() -> bool:
    """Best-effort ``sys.stdout.isatty()`` that never raises."""
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - exotic stdout wrappers
        return False


# Tool announcements and output panels are diagnostics: when stdout is piped/headless
# they belong on stderr so machine-readable stdout (``--output-format json``) stays
# clean. The CLI re-points this to its own console once the output mode is known.
console = get_console() if _stdout_is_tty() else get_error_console()

#: Config keys that standalone tool modules read from the environment. They are
#: propagated from ``cfg`` right before a shell call or a filesystem mutation so
#: config.ini / ``--cwd`` control the guardrails (standalone modules cannot see cfg).
_SHELL_GUARDRAIL_ENV = (
    ("TOOL_TIMEOUT", "YAI_TOOL_TIMEOUT"),
    ("TOOL_ENV_INHERIT", "YAI_TOOL_ENV_INHERIT"),
    ("WORKSPACE_ROOT", "YAI_WORKSPACE_ROOT"),
    ("TOOL_OUTPUT_MAX_CHARS", "YAI_TOOL_OUTPUT_MAX_CHARS"),
)

#: Last tool result executed in this process is tracked in ``output_history`` so the
#: Ctrl+O viewer can list all outputs of the current turn and fall back to the last
#: turn when the current one has no tool calls yet.


def get_last_tool_output() -> Dict[str, Any] | None:
    """Return the last tool result as a dict (compatibility helper).

    The dict has ``type`` (``"function"``/``"mcp"``), ``name``, ``text`` (the
    model-visible result after truncation/spill), plus ``total_chars``,
    ``spill_path`` and ``truncated`` metadata.
    """
    entry = output_history.last_output()
    if entry is None:
        return None
    return {
        "type": entry.kind,
        "name": entry.name,
        "text": entry.text,
        "total_chars": entry.total_chars,
        "spill_path": entry.spill_path,
        "truncated": entry.truncated,
    }


def show_last_tool_output(target_console: Any) -> bool:
    """Print the last tool result in full (inline fallback); ``False`` when none."""
    entry = output_history.last_output()
    if entry is None:
        target_console.print("No tool output in this session yet.", style="dim")
        return False
    title = f"Last {entry.kind.title()} output: {entry.name}"
    if entry.truncated:
        title += f" ({entry.total_chars:,} chars, truncated)"
    target_console.print(
        Panel(
            untrusted_text(entry.text),
            title=safe_text(title),
            title_align="left",
            expand=False,
            border_style="blue",
            style="dim",
        )
    )
    return True


def _sync_shell_guardrail_env() -> None:
    """Best-effort: expose config tool guardrails via environment variables.

    The shell tool and the workspace write guard (``tools/workspace.py``) run as
    standalone code that cannot import ``cfg``; the only way to pass configuration
    is the environment. ``cfg`` is env-first (``YAI_*`` > config.ini > defaults):
    for a user-exported variable the value written back is the same one that was
    loaded from the environment. When the CLI overrides configuration at runtime —
    notably ``--cwd``, which writes the resolved directory to
    ``cfg["WORKSPACE_ROOT"]`` — the config value deliberately wins over a stale
    environment variable. Empty/unset values are skipped so the tool's own defaults
    apply.
    """
    try:
        for config_key, env_key in _SHELL_GUARDRAIL_ENV:
            try:
                value = cfg.get(config_key)
            except Exception:  # pragma: no cover - mocked/broken config mapping
                continue
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                value = "true" if value else "false"
            try:
                os.environ[env_key] = str(value)
            except (OSError, ValueError):  # pragma: no cover - exotic environments
                continue
    except Exception:  # pragma: no cover - env propagation must never block tool calls
        pass


_openai_schemas_cache: List[Dict[str, Any]] | None = None
_anthropic_schemas_cache: List[Dict[str, Any]] | None = None


def get_openai_schemas() -> List[Dict[str, Any]]:
    """Get OpenAI-compatible function schemas

    Returns:
        List of function schemas in OpenAI format
    """
    global _openai_schemas_cache
    if _openai_schemas_cache is not None:
        return _openai_schemas_cache
    transformed_schemas = []
    for function in list_functions():
        schema = {
            "type": "function",
            "function": function.func_cls.openai_schema,
        }
        transformed_schemas.append(schema)
    _openai_schemas_cache = transformed_schemas
    return transformed_schemas


def get_anthropic_schemas() -> List[Dict[str, Any]]:
    """Get Anthropic-compatible function schemas

    Returns:
        List of function schemas in Anthropic format
    """
    global _anthropic_schemas_cache
    if _anthropic_schemas_cache is not None:
        return _anthropic_schemas_cache
    transformed_schemas = []
    for function in list_functions():
        transformed_schemas.append(function.func_cls.anthropic_schema)
    _anthropic_schemas_cache = transformed_schemas
    return transformed_schemas


def get_openai_mcp_tools() -> list[dict[str, Any]]:
    """Get OpenAI-compatible function schemas

    Returns:
        List of function schemas in OpenAI format
    Raises:
        MCPToolsError: If error getting MCP tools
        ValueError: If error getting MCP tools
        FileNotFoundError: If MCP config file not found
    """
    try:
        return get_mcp_manager().to_openai_tools()
    except Exception as e:
        raise MCPToolsError(f"Error getting MCP tools: {e}") from e


def get_anthropic_mcp_tools() -> list[dict[str, Any]]:
    """Get Anthropic-compatible function schemas

    Returns:
        List of function schemas in Anthropic format
    Raises:
        MCPToolsError: If error getting MCP tools
        ValueError: If error getting MCP tools
        FileNotFoundError: If MCP config file not found
    """
    try:
        return get_mcp_manager().to_anthropic_tools()
    except Exception as e:
        raise MCPToolsError(f"Error getting MCP tools for Anthropic: {e}") from e


#: Arguments that best identify a tool call in lists (first match wins).
_CAPTION_ARGUMENT_KEYS = ("command", "file_path", "path", "url", "query", "pattern", "title")


def _tool_call_caption(arguments: Dict[str, Any]) -> str:
    """Return a short one-line caption for the viewer list (command/path/url...)."""
    for key in _CAPTION_ARGUMENT_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.strip().split())[:160]
    return ""


def _emit_tool_result(
    result_text: Any,
    *,
    kind: str,
    name: str,
    preview_arguments: str,
    caption: str,
    show_output: bool,
) -> str:
    """Truncate, record and display one tool result (successful or guard-denied).

    Returns the model-visible text. Guard denials go through the same pipeline as
    successful results, so the terminal/``Ctrl+O`` view and the model context stay
    consistent.
    """
    result_meta = truncate_tool_output_meta(result_text, name)
    # K02: bound what enters the conversation. The same truncated text is shown
    # in the terminal panel, so a huge result can not flood either channel.
    result = result_meta.text
    # Terminal display is head-only and independent from the model-facing cap;
    # Ctrl+O opens the full-screen viewer with every output of the current turn.
    display_text = strip_control_chars(result)
    output_history.record_output(
        kind=kind,
        name=name,
        arguments=preview_arguments,
        text=display_text,
        caption=caption,
        total_chars=result_meta.total_chars,
        spill_path=result_meta.spill_path,
        truncated=result_meta.truncated,
    )
    if show_output:
        preview = make_display_preview(display_text)
        content = untrusted_text(preview.text)
        if preview.truncated:
            content.append("\n\n")
            content.append(build_preview_marker(preview), style="dim")
        title = f"{kind.title()} output"
        if preview.truncated:
            title = f"{title} ({preview.label})"
        panel = Panel(
            content,
            title=title,
            title_align="left",
            expand=False,
            border_style="blue",
            style="dim",
        )
        console.print(panel)
    return result


def execute_tool_call(tool_call: ToolCall, announce: bool = True) -> Tuple[str, bool]:
    """Execute a tool call and return the result

    Args:
        tool_call: The tool call to execute
        announce: Whether to print the "@... call" line. Set False when the call was
            already shown to the user (e.g., by a confirmation prompt) to avoid duplication.

    Returns:
        Tuple[str, bool]: (result text, success flag)
    """
    is_function_call = not tool_call.name.startswith(MCP_TOOL_NAME_PREFIX)
    if is_function_call:
        get_tool_func = get_function
        show_output = cfg["SHOW_FUNCTION_OUTPUT"]
        _type = "function"
    else:
        tool_call.name = parse_mcp_tool_name(tool_call.name)
        get_tool_func = get_mcp
        show_output = cfg["SHOW_MCP_OUTPUT"]
        _type = "mcp"

    # Tool name/arguments are model output: never let them act as Rich markup
    # or emit terminal control sequences here. Arguments are compacted as well:
    # a single huge content/command value must not wrap over several screens.
    preview_arguments = summarize_arguments(tool_call.arguments)

    if announce:
        console.print(
            f"@{_type.title()} call: {safe_text(tool_call.name)}({safe_text(preview_arguments)})",
            style="blue",
        )
    # 1. Get the tool
    try:
        tool = get_tool_func(tool_call.name)
    except ValueError as e:
        error_msg = f"{_type.title()} '{tool_call.name!r}' not exists: {e}"
        console.print(safe_text(error_msg), style="red")
        return error_msg, False

    # 2. Parse tool arguments
    try:
        arguments = repair_json(tool_call.arguments, return_objects=True)
        if not isinstance(arguments, dict):
            error_msg = f"Invalid arguments type: {arguments!r}, should be JSON object"
            console.print(safe_text(error_msg), style="red")
            return error_msg, False
        arguments = cast(dict, arguments)
    except Exception as e:
        error_msg = f"Invalid arguments from llm: {e}\nRaw arguments: {tool_call.arguments!r}"
        console.print(safe_text(error_msg), style="red")
        return error_msg, False

    caption = _tool_call_caption(arguments)

    # 3. Execute the tool
    try:
        # K03/K11 integration: the standalone shell tool and the workspace write
        # guard both read their configuration from the environment. Propagate the
        # (env-first) config values right before a shell call or a filesystem
        # mutation so config.ini / ``--cwd`` control them.
        if is_function_call and (
            tool_call.name == "execute_shell_command" or tool_call.name in workspace.MUTATING_TOOL_NAMES
        ):
            _sync_shell_guardrail_env()
        guard_plan = None
        if is_function_call and tool_call.name in workspace.MUTATING_TOOL_NAMES:
            # K11: workspace confinement + protected paths + pre-mutation backups.
            # A denial is an in-band result (ok=True below): the call reached the
            # tool path, the model reads actionable JSON and the filesystem is
            # untouched. The guard never raises and never prints.
            guard_plan = workspace.prepare_mutation(tool_call.name, arguments)
        if guard_plan is not None and guard_plan.denial is not None:
            result_text = guard_plan.denial
        else:
            result_text = tool.execute(**arguments)
            # Only record an undo entry when the mutation really happened: the fs_*
            # tools report expected failures in-band as {"success": false, ...}.
            if guard_plan is not None and guard_plan.has_originals and workspace.tool_result_succeeded(result_text):
                workspace.push_undo(guard_plan.build_undo_entry())
        result = _emit_tool_result(
            result_text,
            kind=_type,
            name=tool_call.name,
            preview_arguments=preview_arguments,
            caption=caption,
            show_output=show_output,
        )
        return result, True
    except Exception as e:
        error_msg = f"Call {_type} error: {e}\n{_type} name: {tool_call.name!r}\nArguments: {arguments!r}"
        console.print(safe_text(error_msg), style="red")
        return error_msg, False
