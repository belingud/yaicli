import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import typer
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent, Tool
from rich.console import Console

from yaicli.const import MCP_JSON_PATH
from yaicli.functions import print_mcp_details
from yaicli.tools.mcp import (
    MCP,
    MCPClient,
    MCPConfig,
    MCPManager,
    MCPToolConverter,
    gen_mcp_tool_name,
    get_mcp,
    get_mcp_manager,
    parse_mcp_tool_name,
)


class TestMCPNameFunctions:
    def test_gen_mcp_tool_name(self):
        """Test gen_mcp_tool_name function adds prefix correctly."""
        # Test adding prefix to tool name
        assert gen_mcp_tool_name("test_tool") == "_mcp__test_tool"

        # Test with name that already has prefix
        assert gen_mcp_tool_name("_mcp__test_tool") == "_mcp__test_tool"

    def test_parse_mcp_tool_name(self):
        """Test parse_mcp_tool_name function removes prefix correctly."""
        # Test removing prefix from tool name
        assert parse_mcp_tool_name("_mcp__test_tool") == "test_tool"

        # Test with name that doesn't have prefix
        assert parse_mcp_tool_name("test_tool") == "test_tool"


class TestMCPConfig:
    @patch("json.loads")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.read_text")
    def test_from_file(self, mock_read_text, mock_exists, mock_loads):
        """Test MCPConfig.from_file method loads config correctly."""
        # Setup mocks
        mock_exists.return_value = True
        mock_read_text.return_value = "{}"
        mock_loads.return_value = {"mcpServers": {"server1": {"type": "http"}}}

        # Call method
        config = MCPConfig.from_file(Path("/fake/path"))

        # Verify calls
        mock_exists.assert_called_once()
        mock_read_text.assert_called_once_with(encoding="utf-8")
        mock_loads.assert_called_once_with("{}")

        # Verify type to transport conversion
        assert config.servers["mcpServers"]["server1"]["transport"] == "http"
        assert "type" not in config.servers["mcpServers"]["server1"]

    @patch("pathlib.Path.exists")
    def test_from_file_not_found(self, mock_exists):
        """Test MCPConfig.from_file raises FileNotFoundError when file doesn't exist."""
        # Setup mock
        mock_exists.return_value = False

        # Verify exception is raised
        with pytest.raises(FileNotFoundError):
            MCPConfig.from_file(Path("/fake/path"))


class TestMCP:
    def test_init(self):
        """Test MCP initialization."""
        # Create MCP object
        tool = MCP("test_tool", "Test description", {"type": "object"})

        # Verify attributes
        assert tool.name == "_mcp__test_tool"
        assert tool.description == "Test description"
        assert tool.parameters == {"type": "object"}

    @patch("yaicli.tools.mcp.get_mcp_manager")
    def test_execute_success(self, mock_get_manager):
        """Test MCP.execute method with successful execution."""
        # Setup mock
        mock_client = Mock()
        mock_text_content = Mock(spec=TextContent)
        mock_text_content.text = "Test result"
        mock_client.call_tool.return_value = CallToolResult(content=[mock_text_content], structured_content=None)
        mock_manager = Mock()
        mock_manager.client = mock_client
        mock_get_manager.return_value = mock_manager

        # Create MCP object and execute
        tool = MCP("test_tool", "Test description", {})
        result = tool.execute(param1="value1")

        # Verify
        mock_client.call_tool.assert_called_once_with("_mcp__test_tool", param1="value1")
        assert result == "Test result"

    @patch("yaicli.tools.mcp.get_mcp_manager")
    def test_execute_exception(self, mock_get_manager):
        """Test MCP.execute method handles exceptions gracefully."""
        # Setup mock to raise exception
        mock_client = Mock()
        mock_client.call_tool.side_effect = Exception("Test error")
        mock_manager = Mock()
        mock_manager.client = mock_client
        mock_get_manager.return_value = mock_manager

        # Create MCP object and execute
        tool = MCP("test_tool", "Test description", {})
        result = tool.execute()

        # Verify
        assert "execution failed: Test error" in result

    def test_format_result_text_content(self):
        """Test MCP._format_result with TextContent."""
        # Create MCP object
        tool = MCP("test_tool", "Test description", {})

        # Create a mock TextContent
        mock_text_content = Mock(spec=TextContent)
        mock_text_content.text = "Test result"

        # Test with TextContent
        result = tool._format_result(CallToolResult(content=[mock_text_content], structured_content=None))
        assert result == "Test result"

    def test_format_result_other_content(self):
        """Test MCP._format_result with non-TextContent."""
        # Create MCP object
        tool = MCP("test_tool", "Test description", {})

        # Create a mock content object
        mock_content = Mock()
        mock_content.__str__ = Mock(return_value="Mock content")

        # Test with non-TextContent
        result = tool._format_result(CallToolResult(content=[mock_content], structured_content=None))
        assert result == "Mock content"

    def test_format_result_empty(self):
        """Test MCP._format_result with empty list."""
        # Create MCP object
        tool = MCP("test_tool", "Test description", {})

        # Test with empty list
        result = tool._format_result(CallToolResult(content=[], structured_content=None))
        assert result == ""

    def test_repr(self):
        """Test MCP.__repr__ method."""
        # Create MCP object
        tool = MCP("test_tool", "Test description", {"type": "object"})

        # Verify repr string
        assert (
            repr(tool) == "MCP(name='_mcp__test_tool', description='Test description', parameters={'type': 'object'})"
        )


class TestMCPClient:
    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("yaicli.tools.mcp.Client")
    def test_singleton(self, mock_client_class, mock_from_file):
        """Test MCPClient is a thread-safe singleton."""
        # Setup mock config
        mock_config = Mock()
        mock_from_file.return_value = mock_config

        # Reset the singleton instance to ensure clean test
        MCPClient._instance = None

        # Create two instances
        client1 = MCPClient()
        client2 = MCPClient()

        # Verify they are the same object
        assert client1 is client2

        # Verify initialization only happened once (client creation happens only during first instantiation)
        mock_client_class.assert_called_once_with(mock_config.servers)

    @patch("yaicli.tools.mcp.get_or_create_event_loop")
    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("yaicli.tools.mcp.Client")
    def test_ping(self, mock_client_class, mock_from_file, mock_get_loop):
        """Test MCPClient.ping method."""
        # Setup mocks
        mock_loop = Mock()
        mock_get_loop.return_value = mock_loop
        mock_config = Mock()
        mock_from_file.return_value = mock_config
        mock_client_instance = Mock()
        mock_client_class.return_value = mock_client_instance

        # Create client and call ping
        client = MCPClient()
        # Replace the _ping_async method with a mock to avoid coroutine warning
        client._ping_async = Mock()
        client.ping()

        # Verify
        mock_loop.run_until_complete.assert_called_once()

    @patch("yaicli.tools.mcp.get_or_create_event_loop")
    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("yaicli.tools.mcp.Client")
    def test_list_tools(self, mock_client_class, mock_from_file, mock_get_loop):
        """Test MCPClient.list_tools method."""
        # Setup mocks
        mock_loop = Mock()
        mock_tools = [
            Tool(name="tool1", description="Tool 1", inputSchema={"type": "object"}),
            Tool(name="tool2", description="Tool 2", inputSchema={"type": "object"}),
        ]
        mock_loop.run_until_complete.return_value = mock_tools
        mock_get_loop.return_value = mock_loop

        # Mock the async methods to return regular Mock objects instead of coroutines
        mock_client_instance = Mock()
        mock_client_class.return_value = mock_client_instance

        # Create client and call list_tools
        client = MCPClient()
        # Replace the _list_tools_async method with a mock that doesn't return a coroutine
        client._list_tools_async = Mock()
        client._tools = None  # Reset cache
        result = client.list_tools()

        # Verify
        assert result == mock_tools
        assert client._tools == mock_tools
        mock_loop.run_until_complete.assert_called_once()

        # Call again and verify cache is used
        mock_loop.reset_mock()
        result = client.list_tools()
        assert result == mock_tools
        mock_loop.run_until_complete.assert_not_called()

    @patch("yaicli.tools.mcp.get_or_create_event_loop")
    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("yaicli.tools.mcp.Client")
    def test_call_tool(self, mock_client_class, mock_from_file, mock_get_loop):
        """Test MCPClient.call_tool method."""
        # Setup mocks
        mock_loop = Mock()
        mock_text_content = Mock(spec=TextContent)
        mock_text_content.text = "Test result"
        mock_content = [mock_text_content]
        mock_loop.run_until_complete.return_value = mock_content
        mock_get_loop.return_value = mock_loop

        # Create client and call tool
        client = MCPClient()
        # Replace the _call_tool_async method with a mock to avoid coroutine warning
        client._call_tool_async = Mock()
        result = client.call_tool("_mcp__test_tool", param1="value1")

        # Verify
        assert result == mock_content
        mock_loop.run_until_complete.assert_called_once()

    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("yaicli.tools.mcp.Client")
    def test_tools_property(self, mock_client_class, mock_from_file):
        """Test MCPClient.tools property."""
        # Setup mocks
        mock_tools = [
            Tool(name="tool1", description="Tool 1", inputSchema={"type": "object"}),
            Tool(name="tool2", description="Tool 2", inputSchema={"type": "object"}),
        ]

        # Create client
        client = MCPClient()

        # Mock list_tools method
        client.list_tools = Mock(return_value=mock_tools)

        # Test property
        client._tools = None  # Reset cache
        result = client.tools

        # Verify
        assert result == mock_tools
        client.list_tools.assert_called_once()

        # Call again and verify cache is used
        client.list_tools.reset_mock()
        result = client.tools
        assert result == mock_tools
        client.list_tools.assert_not_called()

    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("yaicli.tools.mcp.Client")
    def test_tools_map_property(self, mock_client_class, mock_from_file):
        """Test MCPClient.tools_map property."""
        # Setup mocks
        mock_tools = [
            Tool(name="tool1", description="Tool 1", inputSchema={"type": "object"}),
            Tool(name="tool2", description="Tool 2", inputSchema={"type": "object"}),
        ]

        # Create client
        client = MCPClient()
        client._tools = mock_tools

        # Test property
        client._tools_map = None  # Reset cache
        result = client.tools_map

        # Verify
        assert "_mcp__tool1" in result
        assert "_mcp__tool2" in result
        assert isinstance(result["_mcp__tool1"], MCP)
        assert result["_mcp__tool1"].name == "_mcp__tool1"
        assert result["_mcp__tool1"].description == "Tool 1"

    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("yaicli.tools.mcp.Client")
    def test_get_tool(self, mock_client_class, mock_from_file):
        """Test MCPClient.get_tool method."""
        # Create client
        client = MCPClient()

        # Mock tools_map property
        mock_tool = Mock()
        client._tools_map = {"_mcp__tool1": mock_tool}

        # Test get_tool
        result = client.get_tool("tool1")
        assert result == mock_tool

        # Test with nonexistent tool
        client._tools_map = {"_mcp__tool1": mock_tool}
        with pytest.raises(ValueError):
            client.get_tool("nonexistent")


class TestMCPToolConverter:
    def test_to_openai_format(self):
        """Test MCPToolConverter.to_openai_format method."""
        # Setup mock
        mock_client = Mock()
        mock_client.tools = [
            Tool(name="tool1", description="Tool 1", inputSchema={"type": "object"}),
            Tool(name="tool2", description="Tool 2", inputSchema={"type": "object"}),
        ]

        # Create converter and convert
        converter = MCPToolConverter(mock_client)
        result = converter.to_openai_format()

        # Verify
        assert len(result) == 2
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "_mcp__tool1"
        assert result[0]["function"]["description"] == "Tool 1"
        assert result[0]["function"]["parameters"] == {"type": "object"}

    def test_create_parameter_from_schema(self):
        """Test MCPToolConverter._create_parameter_from_schema method."""
        # Create converter
        mock_client = Mock()
        converter = MCPToolConverter(mock_client)

        # Test string type for required parameter
        param = converter._create_parameter_from_schema("param1", {"type": "string"}, ["param1"])
        assert param.name == "param1"
        assert param.annotation == str
        assert param.default == param.empty

        # Test string type for optional parameter
        param = converter._create_parameter_from_schema("param1", {"type": "string"}, [])
        assert param.name == "param1"
        # Optional[str] is expected here, so we just verify it's not str
        assert param.annotation != str
        assert param.default is None

        # Test with default value
        param = converter._create_parameter_from_schema("param1", {"type": "string", "default": "default"}, [])
        assert param.default == "default"

        # Test array type
        param = converter._create_parameter_from_schema(
            "param1", {"type": "array", "items": {"type": "string"}}, ["param1"]
        )
        # For required parameter, it should be just List[str]
        assert "List" in str(param.annotation)
        assert "str" in str(param.annotation)

        # Test enum type - for non-required parameter, it will be Optional[Literal[...]]
        param = converter._create_parameter_from_schema("param1", {"type": "string", "enum": ["a", "b"]}, [])
        assert "Literal" in str(param.annotation)

    def test_create_dynamic_function(self):
        """Test MCPToolConverter._create_dynamic_function method."""
        # Setup mock
        mock_tool = Mock()
        mock_tool.name = "tool1"
        mock_tool.description = "Tool 1"
        mock_tool.parameters = {
            "properties": {"param1": {"type": "string"}, "param2": {"type": "integer", "default": 42}},
            "required": ["param1"],
        }
        mock_tool.execute = Mock(return_value="Test result")

        # Create converter and dynamic function
        mock_client = Mock()
        converter = MCPToolConverter(mock_client)
        func = converter._create_dynamic_function(mock_tool)

        # Verify function attributes
        assert func.__name__ == "_mcp__tool1"
        assert func.__doc__ == "Tool 1"
        assert "param1" in func.__annotations__
        assert "param2" in func.__annotations__
        assert "return" in func.__annotations__
        assert func.__annotations__["return"] == str

    def test_to_gemini_format(self):
        """Test MCPToolConverter.to_gemini_format method."""
        # Setup mock
        mock_client = Mock()
        mock_tool1 = Mock()
        mock_tool2 = Mock()
        mock_client.tools_map = {"_mcp__tool1": mock_tool1, "_mcp__tool2": mock_tool2}

        # Create converter
        converter = MCPToolConverter(mock_client)

        # Mock create_dynamic_function
        converter._create_dynamic_function = Mock(side_effect=lambda t: f"dynamic_func_{t.name}")

        # Test
        result = converter.to_gemini_format()

        # Verify
        assert len(result) == 2
        assert converter._create_dynamic_function.call_count == 2
        assert mock_tool1 in [call[0][0] for call in converter._create_dynamic_function.call_args_list]
        assert mock_tool2 in [call[0][0] for call in converter._create_dynamic_function.call_args_list]


class TestMCPManager:
    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("yaicli.tools.mcp.MCPClient")
    def test_init(self, mock_client_class, mock_from_file):
        """Test MCPManager initialization."""
        # Create manager
        manager = MCPManager(Path("/fake/path"))

        # Verify
        assert manager.config_path == Path("/fake/path")
        assert manager._client is None
        assert manager._converter is None

    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("yaicli.tools.mcp.MCPClient")
    def test_client_property(self, mock_client_class, mock_from_file):
        """Test MCPManager.client property."""
        # Setup mocks
        mock_config = Mock()
        mock_from_file.return_value = mock_config
        mock_client_instance = Mock()
        mock_client_class.return_value = mock_client_instance

        # Create manager
        manager = MCPManager()

        # Test property
        result = manager.client

        # Verify
        assert result == mock_client_instance
        mock_from_file.assert_called_once_with(MCP_JSON_PATH)
        mock_client_class.assert_called_once_with(mock_config)

    @patch("yaicli.tools.mcp.MCPToolConverter")
    def test_converter_property(self, mock_converter_class):
        """Test MCPManager.converter property."""
        # Setup mock
        mock_converter_instance = Mock()
        mock_converter_class.return_value = mock_converter_instance

        # Create manager
        manager = MCPManager()
        manager._client = Mock()

        # Test property
        result = manager.converter

        # Verify
        assert result == mock_converter_instance
        mock_converter_class.assert_called_once_with(manager._client)

    def test_ping(self):
        """Test MCPManager.ping method."""
        # Create manager
        manager = MCPManager()

        # Mock client
        manager._client = Mock()

        # Test
        manager.ping()

        # Verify
        manager._client.ping.assert_called_once()

    def test_list_tools(self):
        """Test MCPManager.list_tools method."""
        # Create manager
        manager = MCPManager()

        # Mock client
        mock_tools = [Mock(), Mock()]
        manager._client = Mock()
        manager._client.tools = mock_tools

        # Test
        result = manager.list_tools()

        # Verify
        assert result == mock_tools

    def test_get_tool(self):
        """Test MCPManager.get_tool method."""
        # Create manager
        manager = MCPManager()

        # Mock client
        mock_tool = Mock()
        manager._client = Mock()
        manager._client.get_tool.return_value = mock_tool

        # Test
        result = manager.get_tool("test_tool")

        # Verify
        assert result == mock_tool
        manager._client.get_tool.assert_called_once_with("_mcp__test_tool")

    def test_execute_tool(self):
        """Test MCPManager.execute_tool method."""
        # Create manager
        manager = MCPManager()

        # Mock
        mock_tool = Mock()
        mock_tool.execute.return_value = "Test result"
        manager.get_tool = Mock(return_value=mock_tool)

        # Test
        result = manager.execute_tool("test_tool", param1="value1")

        # Verify
        assert result == "Test result"
        manager.get_tool.assert_called_once_with("test_tool")
        mock_tool.execute.assert_called_once_with(param1="value1")

    def test_to_openai_tools(self):
        """Test MCPManager.to_openai_tools method."""
        # Create manager
        manager = MCPManager()

        # Mock converter
        mock_tools = [{"type": "function"}]
        manager._converter = Mock()
        manager._converter.to_openai_format.return_value = mock_tools

        # Test
        result = manager.to_openai_tools()

        # Verify
        assert result == mock_tools
        manager._converter.to_openai_format.assert_called_once()

    def test_to_gemini_tools(self):
        """Test MCPManager.to_gemini_tools method."""
        # Create manager
        manager = MCPManager()

        # Mock converter
        mock_tools = [Mock(), Mock()]
        manager._converter = Mock()
        manager._converter.to_gemini_format.return_value = mock_tools

        # Test
        result = manager.to_gemini_tools()

        # Verify
        assert result == mock_tools
        manager._converter.to_gemini_format.assert_called_once()


class TestGlobalFunctions:
    @patch("yaicli.tools.mcp.MCPManager")
    def test_get_mcp_manager(self, mock_manager_class):
        """Test get_mcp_manager function."""
        # Setup mock
        mock_manager_instance = Mock()
        mock_manager_class.return_value = mock_manager_instance

        # Reset global state
        import yaicli.tools.mcp

        yaicli.tools.mcp._mcp_manager = None

        # Test
        result = get_mcp_manager()

        # Verify
        assert result == mock_manager_instance
        mock_manager_class.assert_called_once_with(None)

        # Test with config_path
        mock_manager_class.reset_mock()
        config_path = Path("/fake/path")
        result = get_mcp_manager(config_path)

        # Verify singleton is returned without creating a new instance
        mock_manager_class.assert_not_called()
        assert result == mock_manager_instance

    @patch("yaicli.tools.mcp.get_mcp_manager")
    def test_get_mcp(self, mock_get_manager):
        """Test get_mcp function."""
        # Setup mock
        mock_tool = Mock()
        mock_manager = Mock()
        mock_manager.get_tool.return_value = mock_tool
        mock_get_manager.return_value = mock_manager

        # Test
        result = get_mcp("test_tool")

        # Verify
        assert result == mock_tool
        mock_manager.get_tool.assert_called_once_with("test_tool")


class TestPrintMCPDetails:
    @staticmethod
    def _create_config(tmp_path: Path, data: dict) -> Path:
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps(data))
        return path

    @staticmethod
    def _make_manager(tools_map):
        class FakeClient:
            def __init__(self, mapping):
                self._mapping = mapping

            @property
            def tools_map(self):
                return self._mapping

        return SimpleNamespace(client=FakeClient(tools_map))

    def test_print_mcp_details_missing_config(self, tmp_path):
        console = Console(record=True)
        fake_path = tmp_path / "mcp.json"
        with patch("yaicli.functions.console", console), patch("yaicli.functions.MCP_JSON_PATH", fake_path):
            with pytest.raises(typer.Exit):
                print_mcp_details(None, "")
        assert "No mcp config found" in console.export_text()

    def test_print_mcp_details_with_tools(self, tmp_path):
        config_path = self._create_config(
            tmp_path,
            {"mcpServers": {"notes": {"transport": "stdio", "command": "notes-cli"}}},
        )
        tool = SimpleNamespace(
            name=gen_mcp_tool_name("create_note"),
            description="Create note",
            parameters={"properties": {"title": {"type": "string"}}, "required": ["title"]},
        )
        manager = self._make_manager({tool.name: tool})
        console = Console(record=True)
        with patch("yaicli.functions.console", console), patch("yaicli.functions.MCP_JSON_PATH", config_path), patch(
            "yaicli.functions.get_mcp_manager", return_value=manager
        ):
            with pytest.raises(typer.Exit):
                print_mcp_details(None, "")
        output = console.export_text()
        assert "MCP: notes" in output
        assert "create_note" in output
        assert "title* (string)" in output

    def test_print_mcp_details_filter_not_found(self, tmp_path):
        config_path = self._create_config(tmp_path, {"mcpServers": {"notes": {"transport": "stdio"}}})
        console = Console(record=True)
        with patch("yaicli.functions.console", console), patch("yaicli.functions.MCP_JSON_PATH", config_path):
            with pytest.raises(typer.Exit) as exc_info:
                print_mcp_details(None, "unknown")
        assert exc_info.value.exit_code == 1
        assert "not found" in console.export_text()
