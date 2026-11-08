import asyncio
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastmcp.client.client import CallToolResult
from mcp.types import EmbeddedResource, ImageContent, TextContent, TextResourceContents, Tool

from yaicli.const import MCP_JSON_PATH
from yaicli.tools.mcp import (
    MCP,
    MCP_DESCRIPTION_MAX_CHARS,
    MCP_SOURCE_LABEL,
    MCPClient,
    MCPConfig,
    MCPConfigError,
    MCPManager,
    MCPToolConverter,
    gen_mcp_tool_name,
    get_mcp,
    get_mcp_manager,
    parse_mcp_tool_name,
    sanitize_description,
)


@pytest.fixture(autouse=True)
def _reset_mcp_state():
    """Isolate module-level state: warning dedupe set and the client singleton."""
    import yaicli.tools.mcp as mcp_module

    mcp_module._WARNED_KEYS.clear()
    MCPClient._instance = None
    yield
    mcp_module._WARNED_KEYS.clear()
    MCPClient._instance = None


@pytest.fixture
def mcp_cfg(monkeypatch):
    """Patch the config mapping read by the MCP_TIMEOUT / MCP_MAX_TOOLS helpers."""
    values = {"MCP_TIMEOUT": 30, "MCP_MAX_TOOLS": 64}
    monkeypatch.setattr("yaicli.config.cfg", values)
    return values


@pytest.fixture
def error_console():
    """Capture the stderr console used for one-warning-per-process diagnostics."""
    console = Mock()
    with patch("yaicli.tools.mcp.get_error_console", return_value=console):
        yield console


def _mock_transport_client():
    """Create an isolated MCPClient whose fastmcp transport is fully mocked."""
    with patch("fastmcp.client.Client"), patch("yaicli.tools.mcp.MCPConfig.from_file", return_value=Mock()):
        return MCPClient()


def _tools(*names):
    """Build real mcp.types.Tool objects for the max-tools tests."""
    return [Tool(name=name, description=f"{name} description", inputSchema={"type": "object"}) for name in names]


class _SlowAsyncClient:
    """Minimal transport stand-in whose list/call operations never finish in time."""

    def __init__(self, delay: float = 5.0):
        self.delay = delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def close(self):
        return None

    async def list_tools(self):
        await asyncio.sleep(self.delay)
        return []

    async def call_tool(self, name, arguments):
        await asyncio.sleep(self.delay)
        return None


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
        # K16: descriptions are sanitized and source-labelled for the prompt.
        assert tool.description.startswith(MCP_SOURCE_LABEL)
        assert "Test description" in tool.description
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

        # Verify repr string (description is sanitized/source-labelled, K16)
        expected_description = sanitize_description("Test description")
        assert (
            repr(tool)
            == f"MCP(name='_mcp__test_tool', description='{expected_description}', parameters={{'type': 'object'}})"
        )


class TestMCPClient:
    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("fastmcp.client.Client")
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
    @patch("fastmcp.client.Client")
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
    @patch("fastmcp.client.Client")
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
    @patch("fastmcp.client.Client")
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
    @patch("fastmcp.client.Client")
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
    @patch("fastmcp.client.Client")
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
        assert result["_mcp__tool1"].description.startswith(MCP_SOURCE_LABEL)
        assert "Tool 1" in result["_mcp__tool1"].description

    @patch("yaicli.tools.mcp.MCPConfig.from_file")
    @patch("fastmcp.client.Client")
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
        assert result[0]["function"]["description"].startswith(MCP_SOURCE_LABEL)
        assert "Tool 1" in result[0]["function"]["description"]
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
        assert func.__doc__ == sanitize_description("Tool 1")
        assert MCP_SOURCE_LABEL in func.__doc__
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


class TestSanitizeDescription:
    def test_strips_ansi_escape_sequences(self):
        """K16: ANSI/terminal escape sequences never reach model-facing schemas."""
        result = sanitize_description("\x1b[31mDanger\x1b[0m and \x1b]0;title\x07ok")

        assert "\x1b" not in result
        assert "[31m" not in result
        assert "Danger" in result
        assert "ok" in result

    def test_strips_control_chars_and_collapses_whitespace(self):
        result = sanitize_description("line1\n\n\tline2   line3\x07")

        assert "line1 line2 line3" in result
        assert "\n" not in result
        assert "\x07" not in result

    def test_caps_length_with_ellipsis(self):
        result = sanitize_description("A" * 5000)

        assert len(result) == MCP_DESCRIPTION_MAX_CHARS
        assert result.endswith("…")
        assert result.startswith(MCP_SOURCE_LABEL)

    def test_adds_stable_source_label(self):
        result = sanitize_description("Read a file from disk")

        assert result.startswith(MCP_SOURCE_LABEL)
        assert result == f"{MCP_SOURCE_LABEL} Read a file from disk"

    def test_empty_or_none_returns_label_only(self):
        assert sanitize_description(None) == MCP_SOURCE_LABEL
        assert sanitize_description("   \n\t ") == MCP_SOURCE_LABEL

    def test_is_idempotent(self):
        once = sanitize_description("Read a file")

        assert sanitize_description(once) == once


class TestMCPConfigValidation:
    """K16: malformed mcp.json raises a clear error instead of AttributeError."""

    def _write(self, tmp_path, payload: str) -> Path:
        path = tmp_path / "mcp.json"
        path.write_text(payload, encoding="utf-8")
        return path

    def test_malformed_json_raises_mcp_config_error(self, tmp_path):
        path = self._write(tmp_path, "{not json")

        with pytest.raises(MCPConfigError, match="invalid JSON"):
            MCPConfig.from_file(path)

    def test_top_level_not_object(self, tmp_path):
        path = self._write(tmp_path, "[]")

        with pytest.raises(MCPConfigError, match="top-level value must be a JSON object"):
            MCPConfig.from_file(path)

    def test_mcp_servers_not_object(self, tmp_path):
        path = self._write(tmp_path, '{"mcpServers": null}')

        with pytest.raises(MCPConfigError, match="'mcpServers' must be a JSON object"):
            MCPConfig.from_file(path)

    def test_server_entry_not_object(self, tmp_path):
        path = self._write(tmp_path, '{"mcpServers": {"s": "oops"}}')

        with pytest.raises(MCPConfigError, match="server 's' must be a JSON object"):
            MCPConfig.from_file(path)

    def test_valid_config_converts_type_to_transport(self, tmp_path):
        path = self._write(tmp_path, '{"mcpServers": {"s": {"type": "http", "url": "http://localhost"}}}')

        config = MCPConfig.from_file(path)

        server = config.servers["mcpServers"]["s"]
        assert server["transport"] == "http"
        assert "type" not in server


class TestMCPManagerDegradation:
    """K16: a broken config / missing fastmcp never raises into a provider/turn."""

    def test_missing_config_degrades_to_empty_with_one_warning(self, tmp_path, error_console):
        manager = MCPManager(tmp_path / "missing-mcp.json")

        assert manager.list_tools() == []
        assert manager.to_openai_tools() == []
        assert manager.to_anthropic_tools() == []
        assert manager.to_gemini_tools() == []

        # Exactly one actionable warning per process, not one per call.
        assert error_console.print.call_count == 1
        message = str(error_console.print.call_args_list[0].args[0])
        assert "MCP tools are disabled for this session" in message
        assert "mcp.json" in message

    def test_malformed_config_degrades_to_empty(self, tmp_path, error_console):
        path = tmp_path / "mcp.json"
        path.write_text('{"mcpServers": []}', encoding="utf-8")
        manager = MCPManager(path)

        assert manager.to_openai_tools() == []
        message = str(error_console.print.call_args_list[0].args[0])
        assert "invalid MCP config" in message

    def test_missing_fastmcp_degrades_with_install_hint(self, tmp_path, error_console):
        path = tmp_path / "mcp.json"
        path.write_text('{"mcpServers": {}}', encoding="utf-8")
        manager = MCPManager(path)

        with patch("yaicli.tools.mcp._import_fastmcp", side_effect=ImportError("No module named 'fastmcp'")):
            assert manager.to_openai_tools() == []

        message = str(error_console.print.call_args_list[0].args[0])
        assert "pip install fastmcp" in message

    def test_execute_tool_returns_in_band_error(self, tmp_path, error_console):
        manager = MCPManager(tmp_path / "missing-mcp.json")

        result = manager.execute_tool("clock")

        assert isinstance(result, str)
        assert "could not be executed" in result
        assert "MCP config file is missing" in result

    def test_get_tool_unavailable_raises_value_error_for_executor(self, tmp_path, error_console):
        """execute_tool_call already turns ValueError into an in-band tool error."""
        manager = MCPManager(tmp_path / "missing-mcp.json")

        with pytest.raises(ValueError, match="MCP is unavailable"):
            manager.get_tool("clock")

    def test_execute_broken_config_returns_in_band_error(self, tmp_path, error_console):
        manager = MCPManager(tmp_path / "missing-mcp.json")
        with patch("yaicli.tools.mcp.get_mcp_manager", return_value=manager):
            result = MCP("clock", "Clock tool", {}).execute()

        assert "is unavailable" in result
        assert "mcp.json" in result
        assert error_console.print.call_count == 1


class TestMCPMaxTools:
    """K16: MCP_MAX_TOOLS caps injected tools deterministically (0 = unlimited)."""

    def _client(self, names):
        client = _mock_transport_client()
        client._tools = _tools(*names)
        client._tools_map = None
        return client

    def test_tools_sorted_and_capped_with_one_notice(self, mcp_cfg, error_console):
        mcp_cfg["MCP_MAX_TOOLS"] = 2
        client = self._client(["tool_c", "tool_a", "tool_d", "tool_b"])

        assert [tool.name for tool in client.tools] == ["tool_a", "tool_b"]
        assert error_console.print.call_count == 1
        message = str(error_console.print.call_args_list[0].args[0])
        assert "MCP_MAX_TOOLS=2" in message

    def test_converters_share_the_same_cap(self, mcp_cfg):
        mcp_cfg["MCP_MAX_TOOLS"] = 2
        client = self._client(["tool_c", "tool_a", "tool_b"])
        converter = MCPToolConverter(client)

        assert [tool["function"]["name"] for tool in converter.to_openai_format()] == ["_mcp__tool_a", "_mcp__tool_b"]
        assert [tool["name"] for tool in converter.to_anthropic_format()] == ["_mcp__tool_a", "_mcp__tool_b"]
        assert [func.__name__ for func in converter.to_gemini_format()] == ["_mcp__tool_a", "_mcp__tool_b"]

    def test_manager_converters_respect_the_cap(self, mcp_cfg):
        mcp_cfg["MCP_MAX_TOOLS"] = 1
        manager = MCPManager()
        manager._client = self._client(["tool_b", "tool_a"])

        assert [tool["function"]["name"] for tool in manager.to_openai_tools()] == ["_mcp__tool_a"]

    def test_zero_means_unlimited(self, mcp_cfg):
        mcp_cfg["MCP_MAX_TOOLS"] = 0
        client = self._client(["tool_c", "tool_a", "tool_d", "tool_b"])

        assert [tool.name for tool in client.tools] == ["tool_a", "tool_b", "tool_c", "tool_d"]
        assert len(client.tools_map) == 4
        assert len(MCPToolConverter(client).to_openai_format()) == 4

    def test_cached_tools_can_not_bypass_the_cap(self, mcp_cfg, error_console):
        mcp_cfg["MCP_MAX_TOOLS"] = 0
        client = self._client(["tool_c", "tool_a", "tool_d", "tool_b"])

        # Populate the caches while the cap is disabled...
        assert len(client.tools) == 4
        assert len(client.tools_map) == 4

        # ...then tighten it: the properties apply the cap on every access.
        mcp_cfg["MCP_MAX_TOOLS"] = 2
        assert len(client.tools) == 2
        assert len(client.tools_map) == 2
        assert error_console.print.call_count == 1


class TestMCPTimeout:
    """K16: MCP_TIMEOUT bounds list_tools/call_tool (0 = no bound)."""

    def test_timeout_config_is_read_defensively(self, mcp_cfg):
        from yaicli.tools.mcp import _mcp_timeout

        mcp_cfg["MCP_TIMEOUT"] = 7
        assert _mcp_timeout() == 7
        mcp_cfg["MCP_TIMEOUT"] = 0
        assert _mcp_timeout() == 0
        mcp_cfg["MCP_TIMEOUT"] = "not-an-int"
        assert _mcp_timeout() == 30

    def test_call_tool_timeout_returns_actionable_string(self, mcp_cfg):
        mcp_cfg["MCP_TIMEOUT"] = 1
        client = _mock_transport_client()
        client._client = _SlowAsyncClient(delay=5)
        loop = asyncio.new_event_loop()
        try:
            with patch("yaicli.tools.mcp.get_or_create_event_loop", return_value=loop):
                result = client.call_tool("_mcp__slow")
        finally:
            loop.close()

        assert isinstance(result, str)
        assert "MCP tool 'slow' timed out after 1s" in result
        assert "MCP_TIMEOUT" in result

    def test_list_tools_timeout_returns_empty_and_warns_once(self, mcp_cfg, error_console):
        mcp_cfg["MCP_TIMEOUT"] = 1
        client = _mock_transport_client()
        client._client = _SlowAsyncClient(delay=5)

        assert asyncio.run(client._list_tools_async()) == []
        assert error_console.print.call_count == 1
        message = str(error_console.print.call_args_list[0].args[0])
        assert "timed out after 1s" in message
        assert "MCP_TIMEOUT" in message

    def test_timeout_zero_skips_wait_for(self, mcp_cfg):
        mcp_cfg["MCP_TIMEOUT"] = 0
        client = _mock_transport_client()
        client._client = _SlowAsyncClient(delay=0)

        with patch("yaicli.tools.mcp.asyncio.wait_for") as mock_wait_for:
            assert asyncio.run(client._call_tool_async("tool")) is None

        mock_wait_for.assert_not_called()


class TestResultFormatting:
    """K16: every content block is joined, is_error is marked, empty handled."""

    def _mcp(self):
        return MCP("test_tool", "Test description", {})

    def test_joins_all_text_blocks_in_order(self):
        result = CallToolResult(
            content=[
                TextContent(type="text", text="first"),
                TextContent(type="text", text="second"),
            ],
            structured_content=None,
        )

        assert self._mcp()._format_result(result) == "first\nsecond"

    def test_image_block_becomes_compact_placeholder(self):
        result = CallToolResult(
            content=[
                TextContent(type="text", text="see"),
                ImageContent(type="image", data="aGk=", mimeType="image/png"),
            ],
            structured_content=None,
        )

        assert self._mcp()._format_result(result) == "see\n[image: image/png]"

    def test_resource_block_becomes_compact_placeholder(self):
        block = EmbeddedResource(
            type="resource",
            resource=TextResourceContents(uri="file:///tmp/a.txt", text="hi"),
        )
        result = CallToolResult(content=[block], structured_content=None)

        assert self._mcp()._format_result(result) == "[resource: file:///tmp/a.txt]"

    def test_is_error_is_marked_while_text_is_kept(self):
        result = CallToolResult(
            content=[TextContent(type="text", text="boom")],
            structured_content=None,
            is_error=True,
        )

        assert self._mcp()._format_result(result) == "[MCP error] boom"

    def test_error_without_content_is_marked(self):
        result = CallToolResult(content=[], structured_content=None, is_error=True)

        assert self._mcp()._format_result(result) == "[MCP error] MCP tool reported an error with no content."

    def test_empty_result_returns_empty_string(self):
        result = CallToolResult(content=[], structured_content=None)

        assert self._mcp()._format_result(result) == ""

    def test_structured_content_is_json_dumped_when_no_text_blocks(self):
        result = CallToolResult(content=[], structured_content={"count": 2, "items": ["a"]})

        formatted = self._mcp()._format_result(result)
        assert json.loads(formatted) == {"count": 2, "items": ["a"]}

    def test_execute_returns_timeout_string_in_band(self):
        timeout_message = "MCP tool 'slow' timed out after 1s. The MCP server may be slow or unresponsive."
        mock_client = Mock()
        mock_client.call_tool.return_value = timeout_message
        mock_manager = Mock()
        mock_manager.client = mock_client
        with patch("yaicli.tools.mcp.get_mcp_manager", return_value=mock_manager):
            assert MCP("test_tool", "Test description", {}).execute() == timeout_message
