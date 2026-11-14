"""Loading and schema discovery for function-calling tools.

Two sources are merged into one tool map:

1. the builtin templates bundled inside the package (``yaicli/functions/buildin/``)
   are imported directly, so a fresh install has all tools with zero manual steps;
2. any ``*.py`` file in ``FUNCTIONS_DIR`` (``~/.config/yaicli/functions/``) is loaded
   afterwards and overrides a builtin with the same schema function name.

A single broken/legacy file must never take down the other tools (K15): every file is
imported inside its own ``try/except`` and failures only produce one stderr warning.
"""

import hashlib
import importlib.util
import itertools
import json
import sys
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from yaicli.function_schema import OpenAISchema

from ..console import get_error_console
from ..const import FUNCTIONS_DIR

# Builtin templates shipped inside the yaicli package. Loaded directly so the 12
# bundled tools work without `ai --install-functions` (K01).
BUILDIN_DIR = Path(__file__).resolve().parent.parent / "functions" / "buildin"

_deprecated_warned: set[str] = set()
_module_counter = itertools.count()


def wrap_gemini_function(func: Callable) -> Callable:
    """Wrap a function to add a name and docstring"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Diagnostics go to stderr: stdout is reserved for results (headless JSON).
        # This wrapper is used by the Gemini function-calling path; never let a
        # non-serializable argument or a closed pipe break the actual call.
        try:
            payload = json.dumps(kwargs) if kwargs else repr(args)
            get_error_console().print(f"@Function call: {wrapper.__name__}({payload})", style="blue")
        except Exception:  # noqa: BLE001 - diagnostics must never break the call
            pass
        return func(*args, **kwargs)

    return wrapper


def _resolve_tool_risk(name: str):
    """Return the risk class for ``name`` from :mod:`yaicli.tools.risk`, when available.

    The risk module is optional: when it is missing (or fails) the tool simply has no
    risk class (``None``) and nothing else changes.
    """
    try:
        from .risk import get_tool_risk
    except ImportError:  # pragma: no cover - exercised only when risk.py is absent
        return None
    try:
        return get_tool_risk(name)
    except Exception:  # pragma: no cover - risk classification must never block loading
        return None


class Function:
    """Function description class"""

    def __init__(self, function: type["OpenAISchema"], source: str = "user", file_path: Optional[Path] = None):
        self.name = function.openai_schema["name"]
        self.description = function.openai_schema.get("description", "")
        self.parameters = function.openai_schema.get("parameters", {})
        self.execute = function.execute  # type: ignore
        self.func_cls = function
        # Where the function came from: "builtin" (bundled with the package) or "user".
        self.source = source
        self.file_path = file_path
        # Optional risk class (read/write/network/exec) used by the approval gate (K06).
        self.risk = _resolve_tool_risk(self.name)


_func_name_map: Optional[dict[str, Function]] = None


def _warn(message: str) -> None:
    """Write one diagnostic line to stderr; never let diagnostics break tool loading."""
    try:
        get_error_console().print(message, markup=False, soft_wrap=True)
    except Exception:  # pragma: no cover - stderr console is always available
        pass


def _check_deprecated_import(file_path) -> None:
    """Check if a function file uses the deprecated instructor import and print a warning."""
    path = Path(file_path)
    name = path.name
    if name in _deprecated_warned:
        return
    try:
        source = path.read_text(encoding="utf-8")
    except Exception:
        return
    if "from instructor import" in source:
        _deprecated_warned.add(name)
        _warn(
            f"WARNING: {name}: 'from instructor import OpenAISchema' is deprecated "
            f"and will be removed in a future version. "
            f"Please change to 'from yaicli.function_schema import OpenAISchema'. "
            f"Run ai --reinstall-functions to update builtin functions."
        )


def _warn_broken_file(path: Path, exc: Exception) -> None:
    """One warning per broken file; the rest of the tools keep loading (K15)."""
    _warn(f"WARNING: Skipping function file {path}: {type(exc).__name__}: {exc}")


def _iter_py_files(directory: Path) -> List[Path]:
    """Return the loadable ``*.py`` files of ``directory`` (deterministic order)."""
    try:
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.glob("*.py") if not path.name.startswith("_"))
    except OSError:
        return []


def _unique_module_name(path: Path, source: str) -> str:
    """Build a unique module name so reloads/duplicates never collide in ``sys.modules``."""
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"yaicli_function_{source}_{path.stem}_{digest}_{next(_module_counter)}"


def _load_module(path: Path, source: str):
    """Import one function file as a standalone module."""
    module_name = _unique_module_name(path, source)
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _load_function_file(path: Path, source: str) -> Function:
    """Import and validate one function file, returning its :class:`Function` wrapper."""
    module = _load_module(path, source)
    func_cls = getattr(module, "Function", None)
    if func_cls is None:
        raise TypeError(f"{path.name} must define a 'Function' class")
    if not hasattr(func_cls, "openai_schema") or not hasattr(func_cls, "anthropic_schema"):
        raise TypeError(f"Function {path.name} must be a subclass of yaicli.function_schema.OpenAISchema")
    if not hasattr(func_cls, "execute"):
        raise TypeError(f"Function {path.name} must have an 'execute' classmethod")
    return Function(function=func_cls, source=source, file_path=path)


def _load_functions(directory: Path, source: str) -> Dict[str, Function]:
    """Load every valid function file in ``directory``; skip and warn on broken ones."""
    loaded: Dict[str, Function] = {}
    for file in _iter_py_files(directory):
        if source == "user":
            _check_deprecated_import(file)
        try:
            function = _load_function_file(file, source)
        except Exception as exc:
            _warn_broken_file(file, exc)
            continue
        loaded[function.name] = function
    return loaded


def _warn_stale_builtin_copies() -> None:
    """One-line stderr warning when user copies come from an older package release.

    Detection needs the install manifest (version + sha256 recorded by
    ``--install-functions``/``--reinstall-functions``); a missing manifest simply means
    "nothing known to be stale" and never blocks loading.
    """
    try:
        from ..functions import warn_stale_copies_once
    except Exception:  # pragma: no cover - the functions package is always importable
        return
    try:
        warn_stale_copies_once(functions_dir=FUNCTIONS_DIR, buildin_dir=BUILDIN_DIR)
    except Exception:  # pragma: no cover - stale-copy detection must never block loading
        pass


def get_func_name_map() -> dict[str, Function]:
    """Get the map of loaded functions keyed by their schema function name.

    Package builtins are loaded first; a user file whose schema name matches a builtin
    replaces it. Neither lookup nor import creates ``FUNCTIONS_DIR`` (a fresh config dir
    simply means "builtins only").
    """
    global _func_name_map
    if _func_name_map is not None:
        return _func_name_map

    func_map = _load_functions(BUILDIN_DIR, "builtin")
    func_map.update(_load_functions(FUNCTIONS_DIR, "user"))
    _func_name_map = func_map

    _warn_stale_builtin_copies()
    return _func_name_map


def list_functions() -> list[Function]:
    """List all available functions (builtins + user copies)"""
    return list(get_func_name_map().values())


def get_function(name: str) -> Function:
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
        return func_map[name]
    raise ValueError(f"Function {name!r} not found")


#: Gemini declarations cache, keyed by plan tool mode (``""`` = normal run).
_gemini_functions_cache: Optional[Dict[str, List[Callable]]] = None


def reset_gemini_schema_cache() -> None:
    """Drop the Gemini declaration cache (called when the plan tool mode changes)."""
    global _gemini_functions_cache
    _gemini_functions_cache = None


def _plan_tool_mode() -> Optional[str]:
    """Return the plan tool mode from :mod:`yaicli.tools` (lazy import, no cycle)."""
    try:
        from . import get_plan_tool_mode
    except ImportError:  # pragma: no cover - partial package import / embedders
        return None
    try:
        return get_plan_tool_mode()
    except Exception:  # pragma: no cover - defensive
        return None


def _gemini_plan_allowlist() -> Optional[frozenset]:
    """Read the plan-mode allowlist for Gemini declarations (``None`` outside plan mode).

    ``yaicli.plan_mode`` and the config singleton are imported lazily so the normal
    (non-plan) path never pays for them.
    """
    try:
        from .. import plan_mode
        from ..config import cfg

        allow_shell = bool(cfg.get("PLAN_ALLOW_READONLY_SHELL", True))
        return plan_mode.plan_tool_allowlist(allow_shell)
    except Exception:  # pragma: no cover - defensive: never break tool advertisement
        return frozenset()


def get_functions_gemini_format() -> List[Callable]:
    """Get functions in gemini format.

    Mode-aware (v0.24 K23): in plan mode only the read-only allowlist is declared
    and ``submit_plan`` is appended; in execution mode the normal builtin set is
    declared plus ``todo_write``. Declarations are cached per mode.
    """
    global _gemini_functions_cache
    mode = _plan_tool_mode()
    if mode not in ("plan", "execution"):
        mode = None
    cache = _gemini_functions_cache
    if cache is None:
        cache = {}
        _gemini_functions_cache = cache
    cache_key = mode or ""
    if cache_key in cache:
        return cache[cache_key]
    allowed = _gemini_plan_allowlist() if mode == "plan" else None
    gemini_functions = []
    for func_name, func in get_func_name_map().items():
        if allowed is not None and func_name not in allowed:
            continue
        wrapped_func = wrap_gemini_function(func.execute)
        wrapped_func.__name__ = func_name
        wrapped_func.__doc__ = func.description
        gemini_functions.append(wrapped_func)
    if mode in ("plan", "execution"):
        from . import session_tools

        gemini_functions.extend(session_tools.gemini_functions(mode))
    cache[cache_key] = gemini_functions
    return gemini_functions
