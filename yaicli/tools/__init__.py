"""Public tool API, preserving application-selected configuration and console routing."""

import sys
from typing import Tuple

from ..config import cfg
from ..console import get_console, get_error_console
from ..runtime import current_config
from ..schemas import ToolCall
from . import executor
from .display import get_last_tool_output as get_last_tool_output
from .display import show_last_tool_output as show_last_tool_output
from .executor import get_mcp as get_mcp
from .executor import parse_mcp_tool_name as parse_mcp_tool_name
from .function import get_function as get_function
from .function import list_functions as list_functions
from .schemas import MCP_TOOL_NAME_PREFIX as MCP_TOOL_NAME_PREFIX
from .schemas import enabled_tool_patterns as enabled_tool_patterns
from .schemas import filter_schemas as filter_schemas
from .schemas import get_anthropic_mcp_tools as get_anthropic_mcp_tools
from .schemas import get_anthropic_schemas as get_anthropic_schemas
from .schemas import get_mcp_manager as get_mcp_manager
from .schemas import get_openai_mcp_tools as get_openai_mcp_tools
from .schemas import get_openai_schemas as get_openai_schemas
from .schemas import get_plan_tool_mode as get_plan_tool_mode
from .schemas import parse_enabled_tools as parse_enabled_tools
from .schemas import set_plan_tool_mode as set_plan_tool_mode
from .schemas import tool_enabled as tool_enabled
from .schemas import tool_name_matches as tool_name_matches


def _stdout_is_tty() -> bool:
    """Best-effort ``sys.stdout.isatty()`` that never raises."""
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - exotic stdout wrappers
        return False


# The CLI and worker-console router set this supported runtime injection point.
console = get_console() if _stdout_is_tty() else get_error_console()


def execute_tool_call(tool_call: ToolCall, announce: bool = True, *, runtime=None) -> Tuple[str, bool]:
    """Execute through the guarded dispatcher with the current runtime dependencies."""
    config = runtime.config if runtime is not None else current_config(cfg)
    return executor.execute_tool_call(tool_call, announce, config=config, console=console, runtime=runtime)
