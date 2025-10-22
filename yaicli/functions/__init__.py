import json
import shutil
from pathlib import Path
from typing import Any, Iterable, Optional

import typer
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..console import get_console
from ..const import FUNCTIONS_DIR, MCP_JSON_PATH
from ..tools.mcp import MCPConfig, get_mcp_manager, parse_mcp_tool_name
from ..utils import option_callback

console = get_console()

MCP_DETAILS_ALL_FLAG = "__yaicli_mcp_all__"


def _format_config_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _build_config_table(server_config: dict[str, Any]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, collapse_padding=True)
    table.add_column(style="bold cyan", width=16)
    table.add_column(overflow="fold")
    if not server_config:
        table.add_row("—", "No server configuration provided.")
        return table
    for key, value in server_config.items():
        table.add_row(key, _format_config_value(value))
    return table


def _summarize_parameters(parameters: Any) -> tuple[str, bool]:
    if not isinstance(parameters, dict):
        return "—", False
    props = parameters.get("properties") or {}
    if not isinstance(props, dict) or not props:
        return "—", False
    required = set(parameters.get("required") or [])
    has_required = bool(required)
    entries = []
    for name, details in props.items():
        type_name = "any"
        if isinstance(details, dict):
            type_name = details.get("type") or "any"
        marker = "*" if name in required else ""
        entries.append(f"{name}{marker} ({type_name})")
    return ", ".join(entries), has_required


def _build_tools_table(tool_entries: Iterable[tuple[str, Any]]) -> tuple[Table, bool]:
    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Tool", style="bold magenta")
    table.add_column("Description", overflow="fold")
    table.add_column("Parameters", style="dim", overflow="fold")
    has_required = False
    for display_name, tool in sorted(tool_entries, key=lambda item: item[0]):
        params_summary, required_present = _summarize_parameters(getattr(tool, "parameters", {}))
        has_required = has_required or required_present
        description = getattr(tool, "description", "") or "-"
        table.add_row(display_name, description, params_summary)
    return table, has_required


def _render_mcp_panel(
    name: str,
    server_config: dict[str, Any],
    tool_entries: Iterable[tuple[str, Any]],
    tool_error: Optional[str],
) -> Panel:
    sections: list[Any] = []
    sections.append(Text("Configuration", style="bold cyan"))
    sections.append(_build_config_table(server_config))
    sections.append(Text(""))
    sections.append(Text("Available Tools", style="bold cyan"))
    if tool_error:
        sections.append(Text(f"Failed to load tools: {tool_error}", style="bold red"))
    else:
        entries_list = list(tool_entries)
        if not entries_list:
            sections.append(Text("No tools reported by this MCP.", style="dim"))
        else:
            tools_table, has_required = _build_tools_table(entries_list)
            sections.append(tools_table)
            if has_required:
                sections.append(Text("* Required parameter", style="dim"))
    return Panel(Group(*sections), title=f"MCP: {name}", title_align="left", border_style="cyan", expand=False)


@option_callback
def print_mcp_details(cls, value: Optional[str]) -> None:
    filter_name: Optional[str] = None
    if isinstance(value, str):
        filter_name = None if value == MCP_DETAILS_ALL_FLAG else value.strip() or None

    if not MCP_JSON_PATH.exists():
        console.print("No mcp config found, please add your mcp config in ~/.config/yaicli/mcp.json")
        return

    try:
        config = MCPConfig.from_file(MCP_JSON_PATH)
    except FileNotFoundError:
        console.print("No mcp config found, please add your mcp config in ~/.config/yaicli/mcp.json")
        return
    except json.JSONDecodeError as exc:
        console.print(f"Failed to parse MCP config: {exc}", style="bold red")
        raise typer.Exit(code=1)

    servers = config.servers.get("mcpServers", {})
    if not servers:
        console.print("No MCP servers configured.")
        return

    normalized_servers = {name: details for name, details in servers.items()}
    if filter_name:
        matched_name = next((name for name in normalized_servers if name.lower() == filter_name.lower()), None)
        if not matched_name:
            console.print(f"MCP '{filter_name}' not found in config.", style="bold red")
            raise typer.Exit(code=1)
        target_servers = {matched_name: normalized_servers[matched_name]}
    else:
        target_servers = normalized_servers

    multi_server = len(normalized_servers) > 1
    tools_by_server: dict[str, list[tuple[str, Any]]] = {name: [] for name in normalized_servers}
    unassigned: list[str] = []
    tool_error: Optional[str] = None

    try:
        manager = get_mcp_manager()
        client = manager.client
        tools_map = client.tools_map
        for tool in tools_map.values():
            tool_name = getattr(tool, "name", "")
            base_name = parse_mcp_tool_name(tool_name) if tool_name else ""
            server_name = None
            display_name = base_name
            if multi_server:
                prefix, _, remainder = base_name.partition("_")
                if prefix in normalized_servers and remainder:
                    server_name = prefix
                    display_name = remainder
            if server_name is None:
                if not multi_server and normalized_servers:
                    server_name = next(iter(normalized_servers))
                else:
                    unassigned.append(base_name or tool_name)
                    continue
            tools_by_server.setdefault(server_name, []).append((display_name or base_name or tool_name, tool))
    except FileNotFoundError:
        tool_error = "MCP config file not found."
    except Exception as exc:  # pragma: no cover - defensive against runtime issues
        tool_error = str(exc)

    for server_name, server_config in target_servers.items():
        panel = _render_mcp_panel(server_name, server_config or {}, tools_by_server.get(server_name, []), tool_error)
        console.print(panel)

    if unassigned and not tool_error and filter_name is None:
        console.print(
            f"[yellow]Warning:[/] Unable to determine MCP association for tools: {', '.join(unassigned)}"
        )


@option_callback
def install_functions(cls, _: Any) -> None:
    """Install buildin functions"""
    cur_dir = Path(__file__).absolute().parent
    buildin_dir = cur_dir / "buildin"
    buildin_funcs = [Path(path) for path in buildin_dir.glob("*.py")]
    console.print("Installing buildin functions...")
    if not FUNCTIONS_DIR.exists():
        FUNCTIONS_DIR.mkdir(parents=True)
    for file in buildin_funcs:
        if (FUNCTIONS_DIR / file.name).exists():
            # Skip if function already exists
            console.print(f"Function {file.name} already exists, skipping.")
            continue
        shutil.copy(file, FUNCTIONS_DIR, follow_symlinks=True)
        console.print(f"Installed {FUNCTIONS_DIR}/{file.name}")


@option_callback
def print_functions(cls, _: Any) -> None:
    """List all available buildin functions"""
    if not FUNCTIONS_DIR.exists():
        console.print("No installed functions found.")
        return
    for file in FUNCTIONS_DIR.glob("*.py"):
        if file.name.startswith("_"):
            continue
        console.print(file)


@option_callback
def print_mcp(cls, _: Any) -> None:
    """List all available mcp"""
    if not MCP_JSON_PATH.exists():
        console.print("No mcp config found, please add your mcp config in ~/.config/yaicli/mcp.json")
        return
    with open(MCP_JSON_PATH, "r") as f:
        mcp_config = json.load(f)
    console.print_json(data=mcp_config)
