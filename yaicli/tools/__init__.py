from typing import Any, Dict, List, Tuple, cast

from json_repair import repair_json
from mcp import types
from rich.panel import Panel

from ..config import cfg
from ..console import get_console
from ..schemas import ToolCall
from .function import get_function, list_functions
from .mcp import MCP_TOOL_NAME_PREFIX, get_mcp, get_mcp_manager, parse_mcp_tool_name

console = get_console()


def get_openai_schemas() -> List[Dict[str, Any]]:
    """Get OpenAI-compatible function schemas

    Returns:
        List of function schemas in OpenAI format
    """
    transformed_schemas = []
    for function in list_functions():
        schema = {
            "type": "function",
            "function": {
                "name": function.name,
                "description": function.description,
                "parameters": function.parameters,
            },
        }
        transformed_schemas.append(schema)
    return transformed_schemas


def get_openai_mcp_tools() -> list[dict[str, Any]]:
    """Get OpenAI-compatible function schemas

    Returns:
        List of function schemas in OpenAI format
    """
    return get_mcp_manager().to_openai_tools()


def execute_mcp_tool(tool_name: str, tool_kwargs: dict) -> str:
    """Execute an MCP tool

    Args:
        tool_name: The name of the tool to execute
        tool_kwargs: The arguments to pass to the tool
    """
    manager = get_mcp_manager()
    tool = manager.get_tool(tool_name)
    try:
        result = tool.execute(**tool_kwargs)
        if isinstance(result, list) and len(result) > 0:
            result = result[0]
        if isinstance(result, types.TextContent):
            return result.text
        else:
            return str(result)
    except Exception as e:
        error_msg = f"Call MCP tool error:\nTool name: {tool_name!r}\nArguments: {tool_kwargs!r}\nError: {e}"
        console.print(error_msg, style="red")
        return error_msg


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
