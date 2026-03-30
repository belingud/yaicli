from typing import Any, Dict, List, Tuple, cast

from json_repair import repair_json
from rich.panel import Panel

from ..config import cfg
from ..console import get_console
from ..exceptions import MCPToolsError
from ..schemas import ToolCall
from .function import get_function, list_functions

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


console = get_console()

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


def execute_tool_call(tool_call: ToolCall) -> Tuple[str, bool]:
    """Execute a tool call and return the result

    Args:
        tool_call: The tool call to execute

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

    console.print(f"@{_type.title()} call: {tool_call.name}({tool_call.arguments})", style="blue")
    # 1. Get the tool
    try:
        tool = get_tool_func(tool_call.name)
    except ValueError as e:
        error_msg = f"{_type.title()} '{tool_call.name!r}' not exists: {e}"
        console.print(error_msg, style="red")
        return error_msg, False

    # 2. Parse tool arguments
    try:
        arguments = repair_json(tool_call.arguments, return_objects=True)
        if not isinstance(arguments, dict):
            error_msg = f"Invalid arguments type: {arguments!r}, should be JSON object"
            console.print(error_msg, style="red")
            return error_msg, False
        arguments = cast(dict, arguments)
    except Exception as e:
        error_msg = f"Invalid arguments from llm: {e}\nRaw arguments: {tool_call.arguments!r}"
        console.print(error_msg, style="red")
        return error_msg, False

    # 3. Execute the tool
    try:
        result = tool.execute(**arguments)
        if show_output:
            panel = Panel(
                result,
                title=f"{_type.title()} output",
                title_align="left",
                expand=False,
                border_style="blue",
                style="dim",
            )
            console.print(panel)
        return result, True
    except Exception as e:
        error_msg = f"Call {_type} error: {e}\n{_type} name: {tool_call.name!r}\nArguments: {arguments!r}"
        console.print(error_msg, style="red")
        return error_msg, False
