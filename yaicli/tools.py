import importlib.util
import sys
from typing import Any, Dict, List, NewType, Optional, Tuple, cast

from instructor import OpenAISchema
from json_repair import repair_json
from rich.panel import Panel

from .config import cfg
from .console import get_console
from .const import FUNCTIONS_DIR
from .schemas import ToolCall

console = get_console()

FunctionName = NewType("FunctionName", str)


class Function:
    """Function description class"""

    def __init__(self, function: type[OpenAISchema]):
        self.name = function.openai_schema["name"]
        self.description = function.openai_schema.get("description", "")
        self.parameters = function.openai_schema.get("parameters", {})
        self.execute = function.execute  # type: ignore


_func_name_map: Optional[dict[FunctionName, Function]] = None


def get_func_name_map() -> dict[FunctionName, Function]:
    """Get function name map"""
    global _func_name_map
    if _func_name_map:
        return _func_name_map
    if not FUNCTIONS_DIR.exists():
        FUNCTIONS_DIR.mkdir(parents=True, exist_ok=True)
        return {}
    functions = []
    for file in FUNCTIONS_DIR.glob("*.py"):
        if file.name.startswith("_"):
            continue
        module_name = str(file).replace("/", ".").rstrip(".py")
        spec = importlib.util.spec_from_file_location(module_name, str(file))
        module = importlib.util.module_from_spec(spec)  # type: ignore
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore

        if not issubclass(module.Function, OpenAISchema):
            raise TypeError(f"Function {module_name} must be a subclass of instructor.OpenAISchema")
        if not hasattr(module.Function, "execute"):
            raise TypeError(f"Function {module_name} must have an 'execute' classmethod")

        # Add to function list
        functions.append(Function(function=module.Function))

    # Cache the function list
    _func_name_map = {FunctionName(func.name): func for func in functions}
    return _func_name_map


def list_functions() -> list[Function]:
    """List all available buildin functions"""
    global _func_name_map
    if not _func_name_map:
        _func_name_map = get_func_name_map()

    return list(_func_name_map.values())


def get_function(name: FunctionName) -> Function:
    """Get a function by name

    Args:
        name: Function name

    Returns:
        Function execute method

    Raises:
        ValueError: If function not found
    """
    func_map = get_func_name_map()
    if name in func_map:
        return func_map[FunctionName(name)]
    raise ValueError(f"Function {name!r} not found")


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


def execute_tool_call(tool_call: ToolCall) -> Tuple[str, bool]:
    """Execute a tool call and return the result

    Args:
        tool_call: The tool call to execute

    Returns:
        Tuple[str, bool]: (result text, success flag)
    """
    console.print(f"@Function call: {tool_call.name}({tool_call.arguments})", style="blue")

    # 1. Get the function
    try:
        function = get_function(FunctionName(tool_call.name))
    except ValueError as e:
        error_msg = f"Function '{tool_call.name!r}' not exists: {e}"
        console.print(error_msg, style="red")
        return error_msg, False

    # 2. Parse function arguments
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

    # 3. Execute the function
    try:
        function_result = function.execute(**arguments)
        if cfg["SHOW_FUNCTION_OUTPUT"]:
            panel = Panel(
                function_result,
                title="Function output",
                title_align="left",
                expand=False,
                border_style="blue",
                style="dim",
            )
            console.print(panel)
        return function_result, True
    except Exception as e:
        error_msg = f"Call function error: {e}\nFunction name: {tool_call.name!r}\nArguments: {arguments!r}"
        console.print(error_msg, style="red")
        return error_msg, False
