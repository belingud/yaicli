"""Explicit editor integration for an existing plan or hidden draft."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Tuple

from . import store as plan_store
from .model import PlanSession
from .store import _atomic_write_text

if TYPE_CHECKING:
    from .store import Plan


def write_plan_editor_draft(session: PlanSession, plan: "Plan") -> Path:
    """Write a hidden draft file (``.<id>.editor.md``, 0600) for the ``[e]`` action."""
    directory = session.plan_dir
    if directory is None:
        plan_path = getattr(plan, "path", None)
        directory = Path(plan_path).parent if plan_path is not None else Path.cwd()
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover - caller surfaces the write error
        pass
    path = directory / f".{getattr(plan, 'id', 'plan')}.editor.md"
    _atomic_write_text(path, plan.to_markdown())
    return path


def edit_plan_file(path: Path) -> Tuple[bool, str]:
    """Open ``path`` in ``$EDITOR`` (fallback ``vi``) and re-validate the plan file.

    Returns ``(True, "")`` when the edited file parses, else ``(False, error)``
    with the user-visible reason (never raises).
    """
    path = Path(path)
    editor = os.environ.get("EDITOR", "").strip() or "vi"
    try:
        argv = shlex.split(editor)
    except ValueError:  # pragma: no cover - malformed EDITOR value
        argv = [editor]
    if not argv:
        argv = ["vi"]
    try:
        completed = subprocess.run(argv + [str(path)], check=False)
    except (OSError, ValueError):
        return False, "cannot open editor; plan unchanged"
    except Exception:  # pragma: no cover - defensive
        return False, "cannot open editor; plan unchanged"
    if int(getattr(completed, "returncode", 0) or 0) != 0:
        return False, "cannot open editor; plan unchanged"
    try:
        plan_store.read_plan(path)
    except plan_store.PlanStoreError as exc:
        return False, f"invalid plan file: {path}: {exc}"
    except (OSError, ValueError) as exc:
        return False, f"invalid plan file: {path}: {exc}"
    return True, ""
