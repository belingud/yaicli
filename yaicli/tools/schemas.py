"""Tool declarations, selection and the single owner of mode-dependent caches."""

import fnmatch
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import cfg
from ..console import get_error_console
from ..exceptions import MCPToolsError
from .function import list_functions
from .mcp import MCP_TOOL_NAME_PREFIX

_plan_mode: Optional[str] = None
_PLAN_TOOL_MODES = ("plan", "execution")
_openai_schemas_cache: List[Dict[str, Any]] | None = None
_anthropic_schemas_cache: List[Dict[str, Any]] | None = None
_filtered_schemas_cache: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
_warned_tool_patterns: set = set()


def get_mcp_manager():
    """Lazy import and return MCP manager"""
    from .mcp import get_mcp_manager as _get_mcp_manager

    return _get_mcp_manager()


def set_plan_tool_mode(mode: Optional[str]) -> None:
    """Select the plan tool mode and invalidate the mode-dependent schema caches.

    Args:
        mode: ``None`` for the normal tool set, ``"plan"`` while planning
            (read-only allowlist + ``submit_plan``) or ``"execution"`` while
            executing an approved plan (normal tool set + ``todo_write``).
    """
    global _plan_mode
    _plan_mode = mode if mode in _PLAN_TOOL_MODES else None
    _filtered_schemas_cache.clear()
    try:
        from .function import reset_gemini_schema_cache

        reset_gemini_schema_cache()
    except Exception:  # pragma: no cover - cache invalidation must never raise
        pass


def get_plan_tool_mode() -> Optional[str]:
    """Return the current plan tool mode (``None`` outside the plan workflow)."""
    return _plan_mode


def plan_allows_readonly_shell(config: Any = cfg) -> bool:
    """Read ``PLAN_ALLOW_READONLY_SHELL`` defensively (default: enabled)."""
    try:
        return bool(config.get("PLAN_ALLOW_READONLY_SHELL", True))
    except (AttributeError, TypeError):  # pragma: no cover - exotic config mappings
        return True


def parse_enabled_tools(value: Any) -> Tuple[str, ...]:
    """Normalize ``ENABLED_TOOLS``/``--tools`` into an ordered pattern tuple.

    Accepts the config string (comma or whitespace separated), a sequence of
    strings, ``None``/empty (meaning "everything"). Duplicates are dropped while
    order is preserved; matching is case-sensitive like the tool names themselves.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        raw_items: Sequence[Any] = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:  # pragma: no cover - exotic configuration mappings
        return ()
    patterns: List[str] = []
    for item in raw_items:
        pattern = str(item).strip()
        if pattern and pattern not in patterns:
            patterns.append(pattern)
    return tuple(patterns)


def enabled_tool_patterns() -> Tuple[str, ...]:
    """Return the pattern tuple configured for this process (``()`` = all tools)."""
    try:
        raw = cfg.get("ENABLED_TOOLS", "")
    except (AttributeError, TypeError):  # pragma: no cover - exotic config mappings
        return ()
    return parse_enabled_tools(raw)


def tool_name_matches(name: str, pattern: str) -> bool:
    """True when ``pattern`` (``fnmatch`` glob) matches a builtin or MCP tool name."""
    if not pattern:
        return True
    if fnmatch.fnmatchcase(name, pattern):
        return True
    if name.startswith(MCP_TOOL_NAME_PREFIX):
        return fnmatch.fnmatchcase(name.removeprefix(MCP_TOOL_NAME_PREFIX), pattern)
    return False


def tool_enabled(name: str, patterns: Sequence[str] | None = None) -> bool:
    """True when ``name`` is offered by the current ``ENABLED_TOOLS`` selection.

    ``patterns=None`` resolves the process configuration; pass an explicit tuple
    for tests or embedders. An empty selection always returns ``True``.
    """
    selection = enabled_tool_patterns() if patterns is None else tuple(patterns)
    if not selection:
        return True
    return any(tool_name_matches(name, pattern) for pattern in selection)


def filter_schemas(
    schemas: Sequence[Dict[str, Any]],
    patterns: Sequence[str],
    *,
    name_getter,
) -> List[Dict[str, Any]]:
    """Filter a schema list, keeping only tools matched by at least one pattern."""
    if not patterns:
        return list(schemas)
    return [schema for schema in schemas if tool_enabled(name_getter(schema), patterns)]


def _openai_schema_name(schema: Dict[str, Any]) -> str:
    function = schema.get("function") if isinstance(schema, dict) else None
    return str(function.get("name", "")) if isinstance(function, dict) else ""


def _anthropic_schema_name(schema: Dict[str, Any]) -> str:
    return str(schema.get("name", "")) if isinstance(schema, dict) else ""


def _warn_unknown_tool_patterns(patterns: Sequence[str], known_names: Sequence[str]) -> None:
    """Warn once about literal tool names that match no known builtin tool.

    Glob patterns and ``_mcp__`` names are skipped: MCP tools are only known after
    a server connection, so a name that looks like an MCP tool is not "unknown".
    """
    if not patterns:
        return
    key = tuple(patterns)
    if key in _warned_tool_patterns:
        return
    unknown = [
        pattern
        for pattern in patterns
        if not any(char in pattern for char in "*?[]")
        and not pattern.startswith(MCP_TOOL_NAME_PREFIX)
        and pattern not in known_names
    ]
    if not unknown:
        return
    _warned_tool_patterns.add(key)
    get_error_console().print(
        f"Ignoring unknown tool name(s) in ENABLED_TOOLS/--tools: {', '.join(unknown)}. "
        "Pass a builtin tool name or a glob (e.g. fs_*); MCP tools use the _mcp__ prefix.",
        style="yellow",
    )


def _build_openai_schemas() -> List[Dict[str, Any]]:
    """Build the full OpenAI-format schema list (unfiltered)."""
    transformed_schemas = []
    for function in list_functions():
        schema = {
            "type": "function",
            "function": function.func_cls.openai_schema,
        }
        transformed_schemas.append(schema)
    return transformed_schemas


def _build_anthropic_schemas() -> List[Dict[str, Any]]:
    """Build the full Anthropic-format schema list (unfiltered)."""
    return [function.func_cls.anthropic_schema for function in list_functions()]


def _mode_schema_list(
    schemas: Sequence[Dict[str, Any]], mode: Optional[str], *, anthropic: bool
) -> List[Dict[str, Any]]:
    """Apply the plan tool mode to a full builtin schema list.

    * ``plan``: keep only the read-only allowlist and append ``submit_plan``;
    * ``execution``: keep every builtin and append ``todo_write``;
    * ``None``: unchanged (the caller never reaches this for the default path).
    """
    if not mode:
        return list(schemas)
    from . import session_tools

    base = list(schemas)
    if mode == "plan":
        from ..planning.model import plan_tool_allowlist

        allowed = plan_tool_allowlist(plan_allows_readonly_shell())
        name_getter = _anthropic_schema_name if anthropic else _openai_schema_name
        base = [schema for schema in base if name_getter(schema) in allowed]
        extra = session_tools.anthropic_schemas("plan") if anthropic else session_tools.openai_schemas("plan")
    else:
        extra = session_tools.anthropic_schemas("execution") if anthropic else session_tools.openai_schemas("execution")
    return base + list(extra)


def get_openai_schemas() -> List[Dict[str, Any]]:
    """Get OpenAI-compatible function schemas (optionally narrowed).

    The unfiltered list keeps the v0.19 cache identity; filtered/mode variants are
    cached per ``(mode, plan shell switch, pattern set)``. The plan tool mode
    (``set_plan_tool_mode``) filters the builtin list to the read-only allowlist
    and appends ``submit_plan`` / ``todo_write``; ``ENABLED_TOOLS`` is applied
    last, exactly like the normal path.

    Returns:
        List of function schemas in OpenAI format
    """
    global _openai_schemas_cache
    patterns = enabled_tool_patterns()
    mode = _plan_mode
    if mode is None and not patterns:
        if _openai_schemas_cache is not None:
            return _openai_schemas_cache
        _openai_schemas_cache = _build_openai_schemas()
        return _openai_schemas_cache

    cache_key: Tuple[Any, ...] = ("openai", mode, plan_allows_readonly_shell() if mode == "plan" else None, patterns)
    cached = _filtered_schemas_cache.get(cache_key)
    if cached is not None:
        return cached

    full = _openai_schemas_cache
    if full is None:
        full = _build_openai_schemas()
        _openai_schemas_cache = full
    schemas = _mode_schema_list(full, mode, anthropic=False)
    known_names = [_openai_schema_name(schema) for schema in schemas]
    _warn_unknown_tool_patterns(patterns, known_names)
    filtered = filter_schemas(schemas, patterns, name_getter=_openai_schema_name)
    _filtered_schemas_cache[cache_key] = filtered
    return filtered


def get_anthropic_schemas() -> List[Dict[str, Any]]:
    """Get Anthropic-compatible function schemas (optionally narrowed).

    Mirrors :func:`get_openai_schemas`, including the plan-mode filtering and the
    ``submit_plan`` / ``todo_write`` append.

    Returns:
        List of function schemas in Anthropic format
    """
    global _anthropic_schemas_cache
    patterns = enabled_tool_patterns()
    mode = _plan_mode
    if mode is None and not patterns:
        if _anthropic_schemas_cache is not None:
            return _anthropic_schemas_cache
        _anthropic_schemas_cache = _build_anthropic_schemas()
        return _anthropic_schemas_cache

    cache_key: Tuple[Any, ...] = (
        "anthropic",
        mode,
        plan_allows_readonly_shell() if mode == "plan" else None,
        patterns,
    )
    cached = _filtered_schemas_cache.get(cache_key)
    if cached is not None:
        return cached

    full = _anthropic_schemas_cache
    if full is None:
        full = _build_anthropic_schemas()
        _anthropic_schemas_cache = full
    schemas = _mode_schema_list(full, mode, anthropic=True)
    known_names = [_anthropic_schema_name(schema) for schema in schemas]
    _warn_unknown_tool_patterns(patterns, known_names)
    filtered = filter_schemas(schemas, patterns, name_getter=_anthropic_schema_name)
    _filtered_schemas_cache[cache_key] = filtered
    return filtered


def _filter_mcp_tools(tools: List[Dict[str, Any]], name_getter) -> List[Dict[str, Any]]:
    """Apply ``ENABLED_TOOLS`` to MCP tool schemas (empty selection = all)."""
    return filter_schemas(tools, enabled_tool_patterns(), name_getter=name_getter)


def get_openai_mcp_tools() -> list[dict[str, Any]]:
    """Get OpenAI-compatible MCP tool schemas (narrowed by ENABLED_TOOLS).

    Returns:
        List of function schemas in OpenAI format
    Raises:
        MCPToolsError: If error getting MCP tools
        ValueError: If error getting MCP tools
        FileNotFoundError: If MCP config file not found
    """
    if _plan_mode == "plan":
        # Plan mode offers no MCP tools (v1): never connect to an MCP server while
        # planning just to build a schema list.
        return []
    try:
        tools = get_mcp_manager().to_openai_tools()
    except Exception as e:
        raise MCPToolsError(f"Error getting MCP tools: {e}") from e
    return _filter_mcp_tools(tools, _openai_schema_name)


def get_anthropic_mcp_tools() -> list[dict[str, Any]]:
    """Get Anthropic-compatible MCP tool schemas (narrowed by ENABLED_TOOLS).

    Returns:
        List of function schemas in Anthropic format
    Raises:
        MCPToolsError: If error getting MCP tools
        ValueError: If error getting MCP tools
        FileNotFoundError: If MCP config file not found
    """
    if _plan_mode == "plan":
        return []
    try:
        tools = get_mcp_manager().to_anthropic_tools()
    except Exception as e:
        raise MCPToolsError(f"Error getting MCP tools for Anthropic: {e}") from e
    return _filter_mcp_tools(tools, _anthropic_schema_name)
