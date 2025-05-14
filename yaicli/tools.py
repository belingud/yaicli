import importlib.util
import sys
from typing import Any, Dict, List, NewType, Optional

from instructor import OpenAISchema

from .console import get_console
from .const import FUNCTIONS_DIR

console = get_console()


class Function:
    """Function description class"""

    def __init__(self, function: type[OpenAISchema]):
        self.name = function.openai_schema["name"]
        self.description = function.openai_schema.get("description", "")
        self.parameters = function.openai_schema.get("parameters", {})
        self.execute = function.execute  # type: ignore


FunctionName = NewType("FunctionName", str)

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
