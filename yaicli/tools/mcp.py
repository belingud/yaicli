import inspect
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from ..const import MCP_JSON_PATH
from ..utils import get_or_create_event_loop

# Lazy import fastmcp to improve startup time (saves ~1.6s)
# These imports are only needed when MCP is actually used
if TYPE_CHECKING:
    from fastmcp.client import Client
    from fastmcp.client.client import CallToolResult
    from mcp.types import TextContent, Tool


def _import_fastmcp():
    """Lazy import fastmcp modules"""
    from fastmcp.client import Client
    from fastmcp.client.client import CallToolResult
    from mcp.types import TextContent, Tool

    return Client, CallToolResult, TextContent, Tool

MCP_TOOL_NAME_PREFIX = "_mcp__"


def gen_mcp_tool_name(name: str) -> str:
    """Generate MCP tool name
    Add the prefix _mcp__ to the tool name.

    <original_tool_name> ==> _mcp__<original_tool_name>

    Args:
        name: Original tool name
    Returns:
        str
    """
    if not name.startswith(MCP_TOOL_NAME_PREFIX):
        name = f"{MCP_TOOL_NAME_PREFIX}{name}"
    return name


def parse_mcp_tool_name(name: str) -> str:
    """Parse MCP tool name
    Remove the prefix _mcp__ from the tool name.

    _mcp__<original_tool_name> ==> <original_tool_name>

    Args:
        name: MCP tool name
    Returns:
        str
    """
    return name.removeprefix(MCP_TOOL_NAME_PREFIX)


@dataclass
class MCPConfig:
    """MCP config class"""

    servers: Dict[str, Any]

    @classmethod
    def from_file(cls, config_path: Path) -> "MCPConfig":
        """Load config from file

        Args:
            config_path: Path to MCP config file
        Returns:
            MCPConfig
        Raises:
            FileNotFoundError: If the MCP config file is not found
        """
        if not config_path.exists():
            raise FileNotFoundError(f"MCP config file not found: {config_path}")

        config_data = json.loads(config_path.read_text(encoding="utf-8"))

        # Convert config format (type -> transport)
        for server_config in config_data.get("mcpServers", {}).values():
            if "type" in server_config:
                server_config["transport"] = server_config.pop("type")

        return cls(servers=config_data)


class MCP:
    """MCP tool wrapper"""

    def __init__(self, name: str, description: str, parameters: Dict[str, Any]):
        self.name = gen_mcp_tool_name(name)
        self.description = description
        self.parameters = parameters

    def execute(self, **kwargs) -> str:
        """Execute tool
        This function will execute the tool and return the result.
        It will return the formatted result.

        Args:
            **kwargs: Tool parameters
        Returns:
            str
        """
        try:
            client = get_mcp_manager().client
            result = client.call_tool(self.name, **kwargs)
            return self._format_result(result)
        except Exception as e:
            return f"Tool '{self.name}' execution failed: {e}"

    def _format_result(self, result: Any) -> str:
        """Format result to string
        This function is used to format the result to string.
        It will return the text of the first result if the result is a TextContent.
        It will return the string representation of the first result if the result is not a TextContent.

        Args:
            result: CallToolResult (from fastmcp)
        Returns:
            str
        """
        # Lazy import to avoid loading fastmcp at module level
        _, _, TextContent, _ = _import_fastmcp()

        if not result or not result.content:
            return ""

        first_result = result.content[0]
        if isinstance(first_result, TextContent):
            return first_result.text
        return str(first_result)

    def __repr__(self) -> str:
        return f"MCP(name='{self.name}', description='{self.description}', parameters={self.parameters})"


class MCPClient:
    """MCP client (thread-safe singleton)"""

    _instance: Optional["MCPClient"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "MCPClient":
        """Thread-safe singleton implementation"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[MCPConfig] = None):
        """Initialize MCP client

        Convert async functions to sync functions.
        This is a workaround to make the MCP client thread-safe.
        """
        if getattr(self, "_initialized", False):
            return
        if not config:
            config = MCPConfig.from_file(MCP_JSON_PATH)

        self.config = config
        # Lazy import Client only when creating the MCP client
        Client, _, _, _ = _import_fastmcp()
        self._client = Client(self.config.servers)

        # _tools_map: "_mcp__<original_tool_name>" -> MCP
        self._tools_map: Optional[Dict[str, MCP]] = None
        self._tools: Optional[List[Any]] = None  # List[Tool] from mcp.types
        self._initialized = True

    def ping(self) -> None:
        """Test connection"""
        loop = get_or_create_event_loop()
        loop.run_until_complete(self._ping_async())

    async def _ping_async(self) -> None:
        """Async ping implementation"""
        async with self._client:
            await self._client.ping()

    def list_tools(self) -> List[Any]:
        """Get tool list
        This function will list all tools from the MCP server.
        Returns:
            List[Tool]: Tool object list from mcp.types.Tool
        """
        if self._tools is None:
            loop = get_or_create_event_loop()
            self._tools = loop.run_until_complete(self._list_tools_async())
        return self._tools

    async def _list_tools_async(self) -> List[Any]:
        """Async get tool list"""
        async with self._client:
            return await self._client.list_tools()

    def call_tool(self, tool_name: str, **kwargs) -> Any:
        """Call tool"""
        tool_name = parse_mcp_tool_name(tool_name)
        loop = get_or_create_event_loop()
        return loop.run_until_complete(self._call_tool_async(tool_name, **kwargs))

    async def _call_tool_async(self, tool_name: str, **kwargs) -> Any:
        """Async call tool"""
        async with self._client:
            return await self._client.call_tool(tool_name, kwargs)

    @property
    def tools(self) -> List[Any]:
        """Get tool list
        This property will be lazy loaded.
        Returns:
            List[Tool]: Tool object list from mcp.types.Tool
        Raises:
            ValueError: If error getting MCP tools
            FileNotFoundError: If MCP config file not found
            RuntimeError: If called while the client is not connected.
        """
        if self._tools is None:
            self._tools = self.list_tools()
        return self._tools

    @property
    def tools_map(self) -> Dict[str, MCP]:
        """Get MCP tool object mapping
        key: _mcp__<original_tool_name>
        value: MCP tool object
        This property will be lazy loaded.
        Returns:
            Dict[str, MCP]: MCP tool object mapping
        Raises:
            ValueError: If error getting MCP tools
            FileNotFoundError: If MCP config file not found
            RuntimeError: If called while the client is not connected.
        """
        if self._tools_map is None:
            self._tools_map = {}
            for tool in self.tools:
                self._tools_map[gen_mcp_tool_name(tool.name)] = MCP(tool.name, tool.description or "", tool.inputSchema)
        return self._tools_map

    def get_tool(self, name: str) -> MCP:
        """Get MCP tool object

        This function will ensure the tool name is prefixed with _mcp__<original_tool_name>
        and raise an error if the tool name is not found.

        Args:
            name: _mcp__<original_tool_name>
        Returns:
            MCP tool object
        Raises:
            ValueError: If the tool name is not found
        """
        name = gen_mcp_tool_name(name)
        if name not in self.tools_map:
            available_tools = list(self.tools_map.keys())
            raise ValueError(f"MCP tool '{name}' not found. Available tools: {available_tools}")
        return self.tools_map[name]

    def __del__(self):
        """Close client"""
        loop = get_or_create_event_loop()
        loop.run_until_complete(self._client.close())


class MCPToolConverter:
    """Tool format converter"""

    def __init__(self, client: MCPClient):
        self.client = client

    def to_openai_format(self) -> List[Dict[str, Any]]:
        """Convert to OpenAI function call format"""
        openai_tools = []

        for tool in self.client.tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": gen_mcp_tool_name(tool.name),
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            openai_tools.append(openai_tool)

        return openai_tools

    def to_anthropic_format(self) -> List[Dict[str, Any]]:
        """Convert to Anthropic function call format"""
        anthropic_tools = []

        for tool in self.client.tools:
            anthropic_tool = {
                "name": gen_mcp_tool_name(tool.name),
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            anthropic_tools.append(anthropic_tool)

        return anthropic_tools

    def _create_parameter_from_schema(
        self, name: str, prop_info: Dict[str, Any], required: List[str]
    ) -> inspect.Parameter:
        """Create inspect.Parameter from JSON schema property

        This function is used to create inspect.Parameter from JSON schema property.
        'array' ==> List[T]
        'enum' ==> Literal[T]
        'string' ==> str
        'integer' ==> int
        'number' ==> float | int (if default is int, it will be converted to int)
        'boolean' ==> bool
        'object' ==> dict

        Args:
            name: Parameter name
            prop_info: Property info
            required: Required parameters
        Returns:
            inspect.Parameter
        """
        # Ensure parameter type
        param_type = prop_info.get("type", "string")

        # Type mapping
        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        # Update annotation based on type and default value
        annotation = type_mapping.get(param_type, str)
        if annotation == float:
            default = prop_info.get("default", None)
            if default is not None:
                annotation = int if isinstance(default, int) else float

        # Handle array type
        if param_type == "array" and "items" in prop_info:
            item_type = prop_info["items"].get("type", "string")
            item_annotation = type_mapping.get(item_type, str)
            annotation = List[item_annotation]

        # Handle enum type
        if "enum" in prop_info:
            from typing import Literal

            annotation = Literal[tuple(prop_info["enum"])]  # type: ignore

        # Handle optional parameter
        if name not in required:
            from typing import Optional

            annotation = Optional[annotation]

        # Ensure default value
        if name in required:
            default = inspect.Parameter.empty
        else:
            default = prop_info.get("default", None)

        return inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default, annotation=annotation)

    def _create_dynamic_function(self, tool_obj: MCP) -> Callable:
        """Create dynamic function with proper signature and type annotations

        This function is used to create a dynamic function with proper signature and type annotations.
        It will create a dynamic function that can be used as a tool in the LLM.
        Callable.__signature__ = inspect.Signature(parameters=inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default, annotation=annotation))
        Callable.__name__ = _mcp__<original_tool_name>
        Callable.__doc__ = tool_obj.description
        Callable.__annotations__ = {param.name: param.annotation for param in params}
        Callable.__annotations__["return"] = str  # MCP tools return string

        Args:
            tool_obj: MCP tool object
        Returns:
            Callable
        """
        properties = tool_obj.parameters.get("properties", {})
        required = tool_obj.parameters.get("required", [])

        # Create parameter list
        params = [
            self._create_parameter_from_schema(name, prop_info, required) for name, prop_info in properties.items()
        ]

        # Dynamic function
        def dynamic_function(**kwargs):
            print(f"\033[94m@MCP call: {dynamic_function.__name__}({json.dumps(kwargs)})\033[0m")
            return tool_obj.execute(**kwargs)

        # Set function attributes
        dynamic_function.__signature__ = inspect.Signature(parameters=params)
        dynamic_function.__name__ = gen_mcp_tool_name(tool_obj.name)
        dynamic_function.__doc__ = tool_obj.description

        # Set type annotations (simulate get_type_hints result)
        annotations = {param.name: param.annotation for param in params}
        annotations["return"] = str  # MCP tools return string
        dynamic_function.__annotations__ = annotations

        return dynamic_function

    def to_gemini_format(self) -> List[Callable]:
        """Convert to Gemini function call format
        Gemini automatic function calling parses the function signature and type annotations to generate the function declaration.
        So we need to create a dynamic function with proper signature and type annotations.
        """
        return [self._create_dynamic_function(tool) for tool in self.client.tools_map.values()]


class MCPManager:
    """MCP manager - provide unified API interface"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or MCP_JSON_PATH
        self._client: Optional[MCPClient] = None
        self._converter: Optional[MCPToolConverter] = None

    @property
    def client(self) -> MCPClient:
        """Lazy load client"""
        if self._client is None:
            config = MCPConfig.from_file(self.config_path)
            self._client = MCPClient(config)
        return self._client

    @property
    def converter(self) -> MCPToolConverter:
        """Lazy load converter"""
        if self._converter is None:
            self._converter = MCPToolConverter(self.client)
        return self._converter

    def ping(self) -> None:
        """Test connection"""
        self.client.ping()

    def list_tools(self) -> List[Any]:
        """Get tool name list"""
        return self.client.tools

    def get_tool(self, name: str) -> MCP:
        """Get tool"""
        # Verify tool exists
        name = gen_mcp_tool_name(name)
        return self.client.get_tool(name)

    def execute_tool(self, name: str, **kwargs) -> str:
        """Execute tool"""
        tool = self.get_tool(name)
        return tool.execute(**kwargs)

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        """Convert to OpenAI tool format"""
        return self.converter.to_openai_format()

    def to_gemini_tools(self) -> List[Callable]:
        """Convert to Gemini tool format"""
        return self.converter.to_gemini_format()

    def to_anthropic_tools(self) -> List[Dict[str, Any]]:
        """Convert to Anthropic tool format"""
        return self.converter.to_anthropic_format()


# Global instance
_mcp_manager: Optional[MCPManager] = None


def get_mcp_manager(config_path: Optional[Path] = None) -> MCPManager:
    """Get MCP manager instance

    Args:
        config_path: Path to MCP config file
    Returns:
        MCPManager
    Raises:
        FileNotFoundError: If the MCP config file is not found
    """
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager(config_path)
    return _mcp_manager


def get_mcp(name: str) -> MCP:
    """Get MCP tool - compatible with original API"""
    return get_mcp_manager().get_tool(name)
