"""Workspace write confinement, backups and undo (v0.21 K11).

Builtin filesystem tools are **standalone** modules (they may only import stdlib,
pydantic and ``yaicli.function_schema``), so the safety guard lives in the execution
layer: :func:`yaicli.tools.execute_tool_call` calls :func:`prepare_mutation` before it
runs ``fs_write_file`` / ``fs_edit_file`` / ``fs_file_operations``.

Three guarantees:

1. **Confinement** — the resolved target must live inside the effective workspace root.
   The root is ``YAI_WORKSPACE_ROOT`` (exported from ``cfg["WORKSPACE_ROOT"]`` by
   ``execute_tool_call``; empty = process cwd). ``Path.resolve(strict=False)`` is used
   so existing symlinks and ``..`` segments are resolved *before* the check: a symlink
   that points outside the workspace is refused, while a not-yet-existing file inside
   it is allowed.
2. **Protection** — ``.git`` / ``.ssh`` / ``.aws`` / ``.gnupg`` path components and
   ``.env`` / ``.env.*`` / ``*.pem`` / ``*.key`` basenames are refused even inside the
   workspace. ``.yaicli-backups`` is deliberately *not* protected: the guard itself
   writes there (and only there). The persistent plan files root (``PLAN_DIR`` or
   ``<config-dir>/plans``) is refused too: plan files are written by the CLI only
   (v0.24 K23), so the agent cannot edit or delete approved plans.
3. **Revertibility** — before an existing file/directory is overwritten, edited,
   appended to, deleted or moved, it is copied to
   ``<workspace>/.yaicli-backups/<UTC stamp>/<relative path>`` (files ``0600``,
   directories ``0700``). A failed backup refuses the mutation. Successful mutations
   are pushed onto a bounded in-memory undo stack; ``/undo`` restores the last one
   (or deletes paths the agent created).

This module is stdlib-only, never prints and never raises: :func:`prepare_mutation`
returns a :class:`MutationPlan` whose ``denial`` field is the in-band JSON text sent
back to the model. A denial keeps the "call reached the tool" convention of
``execute_tool_call`` (``ok=True``) so the model can read the reason and retry.

Known scope note: substitution of a *directory* that merely contains a protected path
(e.g. deleting ``project/`` which has a ``project/.git`` child) is not expanded; the
workspace root itself is never a mutation target.
"""

import json
import os
import shutil
import stat
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple, Union

#: Environment variable carrying the workspace root (set by ``execute_tool_call``
#: from ``cfg["WORKSPACE_ROOT"]``; the standalone shell tool reads the same key).
WORKSPACE_ENV_KEY = "YAI_WORKSPACE_ROOT"
#: Backup directory created inside the workspace root.
BACKUP_DIR_NAME = ".yaicli-backups"
#: Mutations kept in the in-memory undo stack.
UNDO_LIMIT = 20

#: Builtin tools whose filesystem side effects go through this guard.
MUTATING_TOOL_NAMES = frozenset({"fs_write_file", "fs_edit_file", "fs_file_operations"})

#: Path components that are always protected (case-insensitive; Windows FS).
PROTECTED_DIR_COMPONENTS = frozenset({".git", ".ssh", ".aws", ".gnupg"})

_TRUTHY_STRINGS = frozenset({"1", "true", "yes", "on", "y", "t"})
#: Backup files are private (tool arguments may carry secrets); best effort.
_BACKUP_FILE_MODE = 0o600
_BACKUP_DIR_MODE = 0o700


class BackupError(Exception):
    """A pre-mutation backup could not be created; the mutation must be refused.

    ``raw`` carries the user-visible path that triggered the backup so the denial
    message can name it (never the absolute backup path).
    """

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


@dataclass
class UndoOriginal:
    """One path touched by one mutation.

    ``existed=False`` (and therefore ``backup_path is None``) means the mutation
    created the path, so undo deletes it. Otherwise undo copies ``backup_path``
    back and restores the recorded mode (best effort).
    """

    path: Path
    backup_path: Optional[Path]
    existed: bool
    is_dir: bool = False
    mode: Optional[int] = None
    #: Created directories: remove the whole tree (copy/move) instead of ``rmdir``.
    remove_tree: bool = False


@dataclass
class UndoEntry:
    """One undoable mutation: ``{tool, ts, originals: [(path, backup, existed)]}``."""

    tool: str
    ts: str
    originals: List[UndoOriginal] = field(default_factory=list)


@dataclass
class UndoOutcome:
    """What one ``/undo`` did, with display paths and partial failure messages."""

    tool: str
    ts: str = ""
    restored: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class MutationPlan:
    """Result of :func:`prepare_mutation`: either a denial or prepared backups.

    ``denial`` is the in-band JSON string to return to the model; ``originals``
    describe the undo entry. Backups (when needed) are already on disk when the
    plan is returned, so the caller can execute the tool and push the undo entry
    only if the mutation succeeded.
    """

    tool: str
    root: Path
    originals: List[UndoOriginal] = field(default_factory=list)
    denial: Optional[str] = None

    @property
    def allowed(self) -> bool:
        """True when the mutation may run (no denial was produced)."""
        return self.denial is None

    @property
    def has_originals(self) -> bool:
        """True when there is something for ``/undo`` to restore."""
        return bool(self.originals)

    def build_undo_entry(self) -> UndoEntry:
        """Build the undo entry to push after a successful mutation."""
        return UndoEntry(tool=self.tool, ts=utc_stamp(), originals=list(self.originals))


# ---------------------------------------------------------------------------
# Workspace root, containment and protected paths
# ---------------------------------------------------------------------------
def resolve_workspace_root(root: Union[str, Path, None] = None) -> Path:
    """Return the effective workspace root.

    Explicit ``root`` wins, then ``YAI_WORKSPACE_ROOT``, then the process cwd.
    The result is symlink-resolved (``strict=False``: the root itself may not
    exist yet; mutations then fail closed at backup/write time).
    """
    raw = "" if root is None else str(root).strip()
    if not raw:
        raw = os.environ.get(WORKSPACE_ENV_KEY, "").strip()
    if not raw:
        try:
            return Path.cwd().resolve()
        except OSError:  # pragma: no cover - deleted cwd
            return Path(os.getcwd())
    candidate = Path(raw).expanduser()
    try:
        return candidate.resolve()
    except OSError:  # pragma: no cover - permission/loop errors
        return candidate.absolute()


def resolve_target(raw: Union[str, Path], root: Union[str, Path, None] = None) -> Path:
    """Resolve one tool path exactly like the builtins do.

    Relative paths resolve against the **process cwd** (existing builtin behaviour
    via ``Path(...).resolve()``); ``root`` is accepted for API symmetry and is not
    used to rewrite the path. The resolved path is what the containment check sees.
    """
    expanded = Path(str(raw)).expanduser()
    try:
        return expanded.resolve()
    except OSError:  # pragma: no cover - permission/loop errors
        return expanded.absolute()


def is_inside_workspace(path: Union[str, Path], root: Union[str, Path]) -> bool:
    """True when the (already resolved) ``path`` is inside ``root`` (inclusive)."""
    try:
        Path(path).relative_to(Path(root))
        return True
    except ValueError:
        return False


def _protected_basename(name: str) -> Optional[str]:
    """Return a description when ``name`` is a protected file basename."""
    lowered = name.lower()
    if lowered == ".env" or lowered.startswith(".env."):
        return ".env/.env.* file"
    if lowered.endswith(".pem"):
        return "*.pem file"
    if lowered.endswith(".key"):
        return "*.key file"
    return None


def protected_reason(path: Union[str, Path], root: Union[str, Path, None] = None) -> Optional[str]:
    """Return why ``path`` is protected (``None`` when it may be mutated).

    ``.git``/``.ssh``/``.aws``/``.gnupg`` are checked as path components relative to
    ``root`` (or against the absolute path when no root is given); protected file
    basenames are matched case-insensitively. ``.yaicli-backups`` is not protected.
    """
    resolved = Path(path)
    parts: Tuple[str, ...]
    if root is not None:
        try:
            parts = resolved.relative_to(Path(root)).parts
        except ValueError:
            parts = resolved.parts
    else:
        parts = resolved.parts
    for part in parts:
        if part.lower() in PROTECTED_DIR_COMPONENTS:
            return f"{part} (protected directory)"
    return _protected_basename(resolved.name)


def _denial(reason: str, message: str, raw: str = "", root: Optional[Path] = None) -> str:
    """Build the in-band JSON denial payload returned to the model."""
    payload: Dict[str, Any] = {"success": False, "error": message, "reason": reason}
    if isinstance(raw, str) and raw:
        payload["path"] = raw
    if root is not None:
        payload["workspace_root"] = str(root)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _deny_outside(raw: str, root: Path) -> str:
    return _denial(
        "outside_workspace",
        f"Refusing to modify '{raw}': it resolves outside the workspace root "
        f"'{root}'. Only files inside the workspace may be modified; retry with a "
        f"path inside it.",
        raw,
        root,
    )


def _deny_protected(raw: str, reason: str, root: Path) -> str:
    return _denial(
        "protected_path",
        f"Refusing to modify '{raw}': it is a protected path ({reason}). "
        "Protected paths are .git/.ssh/.aws/.gnupg directories and "
        ".env/.env.*/*.pem/*.key files; choose another file.",
        raw,
        root,
    )


def plans_root(plan_dir: str = "") -> Optional[Path]:
    """Return the persistent plan-files root protected from agent writes.

    Resolution follows the plan feature: an explicit ``PLAN_DIR`` (from the config
    singleton, imported lazily to keep this module a stdlib leaf) wins, otherwise
    ``<config-dir>/plans``. Returns ``None`` when it cannot be resolved; a missing
    config is *not* an error (the guard simply has nothing extra to protect).
    """
    try:
        raw = str(plan_dir or "").strip()
    except Exception:  # pragma: no cover - exotic config values
        raw = ""
    try:
        if raw:
            return Path(raw).expanduser().resolve()
        from ..config import cfg
        from ..const import get_config_dir

        try:
            raw = str(cfg.get("PLAN_DIR") or "").strip()
        except (AttributeError, TypeError):  # pragma: no cover - exotic config mappings
            raw = ""
        if raw:
            return Path(raw).expanduser().resolve()
        return (Path(get_config_dir()).expanduser() / "plans").resolve()
    except Exception:  # pragma: no cover - resolution must never block a write
        return None


def is_inside_plans_root(path: Union[str, Path], root: Union[str, Path, None] = None) -> bool:
    """True when ``path`` (already resolved) is inside the persistent plan root."""
    plans = Path(root) if root is not None else plans_root()
    if plans is None:
        return False
    try:
        return is_inside_workspace(Path(path), plans)
    except Exception:  # pragma: no cover - defensive
        return False


def _deny_plans_root(raw: str, plans: Path, root: Path) -> str:
    """In-band denial for writes under the CLI-managed plan files root."""
    payload: Dict[str, Any] = {
        "success": False,
        "error": "protected_path",
        "reason": "plan files are managed by the CLI",
        "path": raw,
        "plans_root": str(plans),
        "workspace_root": str(root),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _deny_root(raw: str, root: Path) -> str:
    return _denial(
        "workspace_root",
        f"Refusing to modify '{raw}': the workspace root itself ('{root}') cannot be "
        "written, moved or deleted as a whole.",
        raw,
        root,
    )


def _deny_backup_failed(raw: str, exc: BaseException, root: Path) -> str:
    return _denial(
        "backup_failed",
        f"Refusing to modify '{raw}': the pre-change backup could not be created "
        f"({type(exc).__name__}), so the change was not applied. /undo would not be "
        "able to restore the file; free disk space or fix workspace permissions and retry.",
        raw,
        root,
    )


def _check_target(raw: Any, root: Path) -> Tuple[Optional[Path], Optional[str]]:
    """Validate one mutation target.

    Returns ``(resolved_path, denial_json)``. Missing/non-string values are left to
    the builtin (which reports its own in-band argument error), so they yield
    ``(None, None)``.
    """
    if not isinstance(raw, (str, os.PathLike)):
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None
    resolved = resolve_target(text)
    plan_root = plans_root()
    if plan_root is not None and is_inside_plans_root(resolved, plan_root):
        return None, _deny_plans_root(text, plan_root, root)
    if not is_inside_workspace(resolved, root):
        return None, _deny_outside(text, root)
    if resolved == root:
        return None, _deny_root(text, root)
    reason = protected_reason(resolved, root)
    if reason:
        return None, _deny_protected(text, reason, root)
    return resolved, None


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
def utc_stamp() -> str:
    """Return a unique UTC timestamp for one backup generation."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def workspace_backup_root(root: Union[str, Path, None] = None) -> Path:
    """Return ``<workspace>/.yaicli-backups``."""
    return resolve_workspace_root(root) / BACKUP_DIR_NAME


def backup_path_for(path: Union[str, Path], root: Union[str, Path, None] = None, stamp: Optional[str] = None) -> Path:
    """Return the backup destination for ``path`` (no filesystem access)."""
    root_path = resolve_workspace_root(root)
    target = Path(path)
    relative = target.relative_to(root_path)
    return root_path / BACKUP_DIR_NAME / (stamp or utc_stamp()) / relative


def _mkdir_private(directory: Path) -> None:
    """Create ``directory`` (and missing parents) with mode ``0700`` (best effort)."""
    missing: List[Path] = []
    current = directory
    while not current.exists():
        missing.append(current)
        parent = current.parent
        if parent == current:  # pragma: no cover - filesystem root
            break
        current = parent
    for item in reversed(missing):
        item.mkdir(exist_ok=True)
        try:
            os.chmod(item, _BACKUP_DIR_MODE)
        except OSError:  # pragma: no cover - Windows / exotic filesystems
            pass


def _secure_backup_tree(base: Path) -> None:
    """Best-effort tighten a directory backup to dirs ``0700`` / files ``0600``."""
    for current_dir, _dirs, files in os.walk(base):
        try:
            os.chmod(current_dir, _BACKUP_DIR_MODE)
        except OSError:  # pragma: no cover - Windows / exotic filesystems
            pass
        for name in files:
            item = Path(current_dir) / name
            if item.is_symlink():
                continue
            try:
                os.chmod(item, _BACKUP_FILE_MODE)
            except OSError:  # pragma: no cover - Windows / exotic filesystems
                pass


def backup_existing(path: Union[str, Path], root: Union[str, Path, None] = None, stamp: Optional[str] = None) -> Path:
    """Copy an existing file or directory tree into the workspace backup area.

    Returns the backup path. Raises :class:`BackupError` for every failure so the
    caller can refuse the mutation (never silently write without an undo copy).
    Directories are copied recursively with symlinks preserved (not followed).
    """
    root_path = resolve_workspace_root(root)
    target = Path(path)
    raw = str(path)
    if not is_inside_workspace(target, root_path):
        raise BackupError("target is outside the workspace root", raw)
    try:
        destination = backup_path_for(target, root_path, stamp)
    except ValueError as exc:  # pragma: no cover - _check_target already refused these
        raise BackupError("target cannot be made workspace-relative", raw) from exc
    try:
        _mkdir_private(destination.parent)
        if destination.exists() or destination.is_symlink():
            raise BackupError("backup destination already exists", raw)
        if target.is_dir() and not target.is_symlink():
            shutil.copytree(target, destination, symlinks=True)
            _secure_backup_tree(destination)
        else:
            shutil.copy2(target, destination)
            try:
                os.chmod(destination, _BACKUP_FILE_MODE)
            except OSError:  # pragma: no cover - Windows / exotic filesystems
                pass
    except BackupError:
        raise
    except Exception as exc:  # shutil.Error, OSError, ValueError, ...
        raise BackupError(f"backup failed ({type(exc).__name__})", raw) from exc
    return destination


# ---------------------------------------------------------------------------
# Undo stack (process-local, bounded)
# ---------------------------------------------------------------------------
_UNDO_STACK: Deque[UndoEntry] = deque(maxlen=UNDO_LIMIT)
_UNDO_LOCK = threading.Lock()


def push_undo(entry: UndoEntry) -> None:
    """Push one successful mutation onto the bounded undo stack."""
    with _UNDO_LOCK:
        _UNDO_STACK.append(entry)


def undo_depth() -> int:
    """Return how many mutations can still be undone."""
    with _UNDO_LOCK:
        return len(_UNDO_STACK)


def peek_undo() -> Optional[UndoEntry]:
    """Return the most recent undo entry without popping it."""
    with _UNDO_LOCK:
        return _UNDO_STACK[-1] if _UNDO_STACK else None


def reset_undo() -> None:
    """Clear the undo stack (test/CLI-reset helper)."""
    with _UNDO_LOCK:
        _UNDO_STACK.clear()


def _display_path(path: Path) -> str:
    """Render a path for the console: cwd-relative when possible."""
    try:
        return str(path.relative_to(Path.cwd()))
    except (OSError, ValueError):
        return str(path)


def _delete_created(original: UndoOriginal) -> bool:
    """Delete a path the agent created; return whether something was removed."""
    path = original.path
    if path.is_symlink() or path.is_file():
        path.unlink()
        return True
    if not path.exists():
        return False
    if path.is_dir():
        if original.remove_tree:
            shutil.rmtree(path)
        else:
            path.rmdir()
        return True
    path.unlink()
    return True


def _restore_backup(original: UndoOriginal) -> None:
    """Restore one path from its backup, recreating parent directories."""
    backup = original.backup_path
    if backup is None or not backup.exists():
        raise OSError("backup is missing")
    target = original.path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()
    if original.is_dir:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        shutil.copytree(backup, target, symlinks=True)
    else:
        if target.is_dir():
            shutil.rmtree(target)
        shutil.copy2(backup, target)
    if original.mode is not None:
        try:
            os.chmod(target, original.mode)
        except OSError:  # pragma: no cover - Windows / exotic filesystems
            pass


def undo_last() -> Optional[UndoOutcome]:
    """Restore the most recent mutation; ``None`` when the stack is empty.

    Never raises: partial failures are reported in ``UndoOutcome.errors``.
    """
    with _UNDO_LOCK:
        if not _UNDO_STACK:
            return None
        entry = _UNDO_STACK.pop()
    outcome = UndoOutcome(tool=entry.tool, ts=entry.ts)
    for original in entry.originals:
        try:
            if original.existed:
                _restore_backup(original)
                outcome.restored.append(_display_path(original.path))
            elif _delete_created(original):
                outcome.deleted.append(_display_path(original.path))
        except Exception as exc:  # undo must report, never crash the REPL
            outcome.errors.append(f"{_display_path(original.path)}: {exc}")
    return outcome


# ---------------------------------------------------------------------------
# Mutation planning
# ---------------------------------------------------------------------------
def _is_dry_run(value: Any) -> bool:
    """Interpret ``fs_edit_file.dry_run`` (bool or string)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY_STRINGS
    return bool(value) if value is not None else False


def _file_mode(path: Path) -> Optional[int]:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:  # pragma: no cover - permission races
        return None


def _existing_original(path: Path, root: Path, stamp: str) -> UndoOriginal:
    """Back up an existing path (file or directory) and describe it for undo."""
    backup = backup_existing(path, root=root, stamp=stamp)
    return UndoOriginal(
        path=path,
        backup_path=backup,
        existed=True,
        is_dir=path.is_dir() and not path.is_symlink(),
        mode=_file_mode(path),
    )


def _created_original(path: Path, is_dir: bool = False, remove_tree: bool = False) -> UndoOriginal:
    """Describe a path the mutation creates (undo deletes it)."""
    return UndoOriginal(path=path, backup_path=None, existed=False, is_dir=is_dir, remove_tree=remove_tree)


def _actual_destination(source: Optional[Path], destination: Path) -> Path:
    """Mirror the builtins' "destination is a directory => move into it" behaviour."""
    try:
        if destination.is_dir() and source is not None:
            return destination / source.name
    except OSError:  # pragma: no cover - permission races
        pass
    return destination


def _plan_write(plan: MutationPlan, args: Dict[str, Any], stamp: str) -> MutationPlan:
    resolved, denial = _check_target(args.get("file_path"), plan.root)
    if denial is not None:
        plan.denial = denial
        return plan
    if resolved is None:
        return plan
    if resolved.exists() and not resolved.is_dir():
        plan.originals.append(_existing_original(resolved, plan.root, stamp))
    elif not resolved.exists() and not resolved.is_symlink():
        plan.originals.append(_created_original(resolved))
    # An existing directory target is left to the builtin (it fails in-band; no mutation).
    return plan


def _plan_edit(plan: MutationPlan, args: Dict[str, Any], stamp: str) -> MutationPlan:
    if _is_dry_run(args.get("dry_run")):
        return plan  # preview only: no mutation, no backup, no undo entry
    resolved, denial = _check_target(args.get("file_path"), plan.root)
    if denial is not None:
        plan.denial = denial
        return plan
    if resolved is not None and resolved.exists() and not resolved.is_dir():
        plan.originals.append(_existing_original(resolved, plan.root, stamp))
    return plan


def _plan_delete(plan: MutationPlan, args: Dict[str, Any], stamp: str) -> MutationPlan:
    resolved, denial = _check_target(args.get("path"), plan.root)
    if denial is not None:
        plan.denial = denial
        return plan
    if resolved is not None and (resolved.exists() or resolved.is_symlink()):
        plan.originals.append(_existing_original(resolved, plan.root, stamp))
    return plan


def _plan_move(plan: MutationPlan, args: Dict[str, Any], stamp: str) -> MutationPlan:
    destination_raw = args.get("destination")
    if not isinstance(destination_raw, str) or not destination_raw.strip():
        return plan  # the builtin reports the missing destination; no mutation happens
    source, denial = _check_target(args.get("path"), plan.root)
    if denial is not None:
        plan.denial = denial
        return plan
    destination, denial = _check_target(destination_raw, plan.root)
    if denial is not None:
        plan.denial = denial
        return plan
    if source is None or destination is None:
        return plan
    actual = _actual_destination(source, destination)
    if actual != destination:
        reason = protected_reason(actual, plan.root)
        if reason:
            plan.denial = _deny_protected(destination_raw, reason, plan.root)
            return plan
    if source.exists() or source.is_symlink():
        plan.originals.append(_existing_original(source, plan.root, stamp))
    if actual == source:
        return plan  # move onto itself: the builtin fails, nothing to undo
    if actual.exists() or actual.is_symlink():
        plan.originals.append(_existing_original(actual, plan.root, stamp))
    else:
        source_is_dir = source.is_dir() and not source.is_symlink()
        plan.originals.append(_created_original(actual, is_dir=source_is_dir, remove_tree=source_is_dir))
    return plan


def _plan_copy(plan: MutationPlan, args: Dict[str, Any], stamp: str) -> MutationPlan:
    destination_raw = args.get("destination")
    if not isinstance(destination_raw, str) or not destination_raw.strip():
        return plan  # the builtin reports the missing destination; no mutation happens
    source, denial = _check_target(args.get("path"), plan.root)
    if denial is not None:
        plan.denial = denial
        return plan
    destination, denial = _check_target(destination_raw, plan.root)
    if denial is not None:
        plan.denial = denial
        return plan
    if source is None or destination is None or not (source.exists() or source.is_symlink()):
        return plan  # missing source: the builtin fails, nothing is copied
    source_is_dir = source.is_dir() and not source.is_symlink()
    # A file copied into an existing directory lands at its basename; a directory is
    # copied onto the destination itself (copytree(..., dirs_exist_ok=True)).
    actual = _actual_destination(source, destination) if not source_is_dir else destination
    if actual != destination:
        reason = protected_reason(actual, plan.root)
        if reason:
            plan.denial = _deny_protected(destination_raw, reason, plan.root)
            return plan
    if actual == source:
        return plan  # copy onto itself: the builtin fails, nothing to undo
    if actual.exists() or actual.is_symlink():
        plan.originals.append(_existing_original(actual, plan.root, stamp))
    else:
        plan.originals.append(_created_original(actual, is_dir=source_is_dir, remove_tree=source_is_dir))
    return plan


def _plan_create_dir(plan: MutationPlan, args: Dict[str, Any]) -> MutationPlan:
    resolved, denial = _check_target(args.get("path"), plan.root)
    if denial is not None:
        plan.denial = denial
        return plan
    if resolved is not None and not resolved.exists() and not resolved.is_symlink():
        plan.originals.append(_created_original(resolved, is_dir=True))
    return plan


def prepare_mutation(tool_name: str, arguments: Any, root: Union[str, Path, None] = None) -> MutationPlan:
    """Validate and prepare one mutating builtin call.

    Performs the containment/protected checks and creates the pre-mutation backups
    needed by ``/undo``. The caller runs the tool afterwards and pushes
    :meth:`MutationPlan.build_undo_entry` only when the tool reported success.

    Never raises: any guard failure is returned as a fail-closed ``denial``.
    """
    try:
        return _prepare_mutation(tool_name, arguments, root)
    except BackupError as exc:  # a backup must exist before any mutation
        try:
            resolved_root = resolve_workspace_root(root)
        except Exception:  # pragma: no cover - defensive
            resolved_root = Path.cwd()
        return MutationPlan(
            tool=str(tool_name),
            root=resolved_root,
            denial=_deny_backup_failed(exc.raw, exc, resolved_root),
        )
    except Exception as exc:  # fail closed: a broken guard must not allow a write
        try:
            resolved_root = resolve_workspace_root(root)
        except Exception:  # pragma: no cover - defensive
            resolved_root = Path.cwd()
        return MutationPlan(
            tool=str(tool_name),
            root=resolved_root,
            denial=_denial(
                "workspace_guard_error",
                f"Refusing to modify files: the workspace guard failed ({type(exc).__name__}); nothing was changed.",
            ),
        )


def _prepare_mutation(tool_name: str, arguments: Any, root: Union[str, Path, None]) -> MutationPlan:
    root_path = resolve_workspace_root(root)
    plan = MutationPlan(tool=str(tool_name), root=root_path)
    args: Dict[str, Any] = arguments if isinstance(arguments, dict) else {}
    if tool_name == "fs_write_file":
        return _plan_write(plan, args, utc_stamp())
    if tool_name == "fs_edit_file":
        return _plan_edit(plan, args, utc_stamp())
    if tool_name == "fs_file_operations":
        operation = str(args.get("operation") or "").strip().lower()
        if operation == "delete":
            return _plan_delete(plan, args, utc_stamp())
        if operation == "move":
            return _plan_move(plan, args, utc_stamp())
        if operation == "copy":
            return _plan_copy(plan, args, utc_stamp())
        if operation == "create_dir":
            return _plan_create_dir(plan, args)
        return plan  # exists/get_info/unknown ops do not mutate
    return plan


def tool_result_succeeded(result: Any) -> bool:
    """Return whether an fs tool result means "the mutation happened".

    ``fs_*`` tools report expected failures in-band as ``{"success": false, ...}``;
    anything else (a non-JSON or success result) is treated as successful. Used to
    decide whether an undo entry is pushed.
    """
    if not isinstance(result, str):
        return True
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return True
    if isinstance(payload, dict):
        return payload.get("success") is not False
    return True


__all__ = [
    "BACKUP_DIR_NAME",
    "BackupError",
    "MUTATING_TOOL_NAMES",
    "MutationPlan",
    "PROTECTED_DIR_COMPONENTS",
    "UNDO_LIMIT",
    "WORKSPACE_ENV_KEY",
    "UndoEntry",
    "UndoOriginal",
    "UndoOutcome",
    "backup_existing",
    "backup_path_for",
    "is_inside_plans_root",
    "is_inside_workspace",
    "peek_undo",
    "plans_root",
    "prepare_mutation",
    "protected_reason",
    "push_undo",
    "reset_undo",
    "resolve_target",
    "resolve_workspace_root",
    "tool_result_succeeded",
    "undo_depth",
    "undo_last",
    "utc_stamp",
    "workspace_backup_root",
]
