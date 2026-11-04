"""Builtin function templates and their install / reinstall / list lifecycle.

The templates in ``yaicli/functions/buildin/`` are loaded directly from the package at
runtime (see :mod:`yaicli.tools.function`), so a fresh install has all bundled tools with
zero manual steps (K01). ``--install-functions`` merely *exports* editable copies into
``FUNCTIONS_DIR``; ``functions_manifest.json`` records the package version and the sha256
of every bundled file so an upgrade can point out stale copies without ever blocking
tool loading (K15).
"""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..console import get_console, get_error_console
from ..const import FUNCTIONS_DIR, FUNCTIONS_MANIFEST_PATH, MCP_JSON_PATH
from ..utils import option_callback

console = get_console()
error_console = get_error_console()

# Builtin templates bundled with the package (the historical directory name is `buildin`).
BUILDIN_DIR = Path(__file__).resolve().parent / "buildin"
MANIFEST_VERSION = 1

# The stale-copy hint is emitted at most once per process; the loader and
# `--list-functions` share this flag so a single run never duplicates it.
_stale_warned = False


def get_package_version() -> str:
    """Return the installed yaicli version (``"unknown"`` when metadata is unavailable)."""
    try:
        from importlib.metadata import version

        return version("yaicli")
    except Exception:  # pragma: no cover - metadata exists in normal installs
        return "unknown"


def sha256_file(path: Path, chunk_size: int = 65536) -> str:
    """Return the sha256 hex digest of ``path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_buildin_files(buildin_dir: Optional[Path] = None) -> List[Path]:
    """Return the bundled ``*.py`` function templates (sorted, private files skipped)."""
    directory = Path(buildin_dir) if buildin_dir is not None else BUILDIN_DIR
    try:
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.glob("*.py") if not path.name.startswith("_"))
    except OSError:  # pragma: no cover - unreadable install
        return []


def build_manifest(buildin_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Build the manifest describing the bundled functions of this package version."""
    builtins: Dict[str, Any] = {}
    for file in iter_buildin_files(buildin_dir):
        try:
            digest = sha256_file(file)
        except OSError:  # pragma: no cover - unreadable install
            continue
        builtins[file.name] = {"sha256": digest, "function": file.stem}
    return {
        "manifest_version": MANIFEST_VERSION,
        "package_version": get_package_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "builtins": builtins,
    }


def read_manifest(manifest_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Read the install manifest, returning ``None`` when missing or malformed."""
    path = Path(manifest_path) if manifest_path is not None else FUNCTIONS_MANIFEST_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("builtins"), dict):
        data["builtins"] = {}
    return data


def write_manifest(manifest: Dict[str, Any], manifest_path: Optional[Path] = None) -> bool:
    """Atomically write the install manifest; failures warn but never raise."""
    path = Path(manifest_path) if manifest_path is not None else FUNCTIONS_MANIFEST_PATH
    tmp_path: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".functions_manifest.", suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_path, path)
        return True
    except (OSError, TypeError, ValueError) as exc:
        _warn(f"WARNING: could not write functions manifest {path}: {exc}")
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return False


def _warn(message: str) -> None:
    """Write one diagnostic line to stderr."""
    try:
        error_console.print(message, markup=False, soft_wrap=True)
    except Exception:  # pragma: no cover - stderr console is always available
        pass


def _ensure_functions_dir() -> bool:
    """Create ``FUNCTIONS_DIR`` for the install callbacks; warn instead of raising."""
    try:
        FUNCTIONS_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        _warn(f"WARNING: cannot create functions directory {FUNCTIONS_DIR}: {exc}")
        return False


def detect_stale_copies(
    functions_dir: Optional[Path] = None,
    buildin_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
) -> List[str]:
    """Return filenames of user copies that are untouched but older than the package.

    A copy is stale when its sha256 still matches the hash recorded at the last
    ``--install-functions``/``--reinstall-functions`` *and* the bundled file changed
    since (or the builtin was removed from the package). Copies the user edited are
    intentional overrides and are never reported.
    """
    func_dir = Path(functions_dir) if functions_dir is not None else FUNCTIONS_DIR
    buildin = Path(buildin_dir) if buildin_dir is not None else BUILDIN_DIR
    manifest = read_manifest(manifest_path)
    if manifest is None:
        return []
    recorded = manifest.get("builtins")
    if not isinstance(recorded, dict) or not recorded:
        return []
    try:
        if not func_dir.is_dir():
            return []
    except OSError:  # pragma: no cover - unreadable config dir
        return []

    current_builtins = {file.name: file for file in iter_buildin_files(buildin)}
    stale: List[str] = []
    # Bundled files still shipped plus copies of builtins that were removed from the package.
    for name in sorted(set(current_builtins) | set(recorded)):
        user_copy = func_dir / name
        try:
            if not user_copy.is_file():
                continue
            copy_hash = sha256_file(user_copy)
            package_file = current_builtins.get(name)
            package_hash = sha256_file(package_file) if package_file is not None else None
        except OSError:  # pragma: no cover - unreadable copy
            continue
        entry = recorded.get(name)
        if not isinstance(entry, dict):
            continue
        if copy_hash == entry.get("sha256") and copy_hash != package_hash:
            stale.append(name)
    return stale


def warn_stale_copies_once(
    functions_dir: Optional[Path] = None,
    buildin_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
) -> List[str]:
    """Emit at most one stderr warning about stale installed copies; returns their names."""
    global _stale_warned
    if _stale_warned:
        return []
    try:
        stale = detect_stale_copies(functions_dir, buildin_dir, manifest_path)
    except Exception:  # pragma: no cover - a hint must never block tool loading
        return []
    if not stale:
        return []
    _stale_warned = True
    noun = "copy" if len(stale) == 1 else "copies"
    verb = "is" if len(stale) == 1 else "are"
    names = ", ".join(sorted(stale))
    _warn(
        f"WARNING: {len(stale)} installed function {noun} {verb} out of date with this yaicli release "
        f"({names}). Run 'ai --reinstall-functions' to refresh them."
    )
    return stale


@option_callback
def install_functions(cls, _: Any) -> None:
    """Install buildin functions as editable copies (existing files are never overwritten)"""
    buildin_funcs = iter_buildin_files()
    console.print("Installing buildin functions...")
    if not _ensure_functions_dir():
        return
    for file in buildin_funcs:
        if (FUNCTIONS_DIR / file.name).exists():
            # Skip if function already exists: this command only exports copies, it never
            # overwrites a user's (possibly customized) file.
            console.print(f"Function {file.name} already exists, skipping.")
            continue
        try:
            shutil.copy(file, FUNCTIONS_DIR, follow_symlinks=True)
        except OSError as exc:
            _warn(f"WARNING: failed to install {file.name}: {exc}")
            continue
        console.print(f"Installed {FUNCTIONS_DIR}/{file.name}")
    write_manifest(build_manifest())


def _remove_obsolete_copies(current_files: List[Path], previous_manifest: Optional[Dict[str, Any]]) -> None:
    """Remove untouched copies of builtins that no longer ship with the package."""
    if not previous_manifest:
        return
    recorded = previous_manifest.get("builtins")
    if not isinstance(recorded, dict) or not recorded:
        return
    current_names = {file.name for file in current_files}
    for name, entry in sorted(recorded.items()):
        if name in current_names:
            continue
        target = FUNCTIONS_DIR / name
        try:
            if not target.is_file():
                continue
            current_hash = sha256_file(target)
        except OSError:
            continue
        expected_hash = entry.get("sha256") if isinstance(entry, dict) else None
        if expected_hash and current_hash == expected_hash:
            try:
                target.unlink()
            except OSError as exc:
                _warn(f"WARNING: failed to remove stale function copy {target}: {exc}")
                continue
            console.print(f"Removed stale function copy {target}")
        else:
            console.print(f"Kept modified function copy {target} (no longer a builtin)")


@option_callback
def reinstall_functions(cls, _: Any) -> None:
    """Reinstall builtin functions (overwrites existing builtin files, preserves custom ones)"""
    buildin_funcs = iter_buildin_files()
    previous_manifest = read_manifest()
    console.print("Reinstalling builtin functions...")
    if not _ensure_functions_dir():
        return
    for file in buildin_funcs:
        dst = FUNCTIONS_DIR / file.name
        try:
            if dst.exists():
                dst.unlink()
            shutil.copy(file, dst, follow_symlinks=True)
        except OSError as exc:
            _warn(f"WARNING: failed to reinstall {dst}: {exc}")
            continue
        console.print(f"Reinstalled {dst}")
    _remove_obsolete_copies(buildin_funcs, previous_manifest)
    write_manifest(build_manifest())


@option_callback
def print_functions(cls, _: Any) -> None:
    """List all available functions and where each one is loaded from"""
    from ..tools.function import list_functions

    functions = list_functions()
    if not functions:
        console.print("No installed functions found.")
        return
    console.print(f"Found {len(functions)} function(s):")
    for function in sorted(functions, key=lambda item: item.name):
        source = getattr(function, "source", "user")
        console.print(f"{function.name} ({source})")
    console.print("Builtin functions load directly from yaicli; use --install-functions to export editable copies.")


@option_callback
def print_mcp(cls, _: Any) -> None:
    """List all available mcp"""
    if not MCP_JSON_PATH.exists():
        console.print("No mcp config found, please add your mcp config in ~/.config/yaicli/mcp.json")
        return
    with open(MCP_JSON_PATH, "r") as f:
        mcp_config = json.load(f)
    console.print_json(data=mcp_config)
