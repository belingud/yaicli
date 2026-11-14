"""Persistent plan storage for plan mode (v0.24 K23).

This is a stdlib-only leaf module: it must not import ``yaicli.*`` (no config
singleton, no rich/typer) so it can be imported lazily from ``plan_mode``/CLI
code without startup cost or import cycles.

Layout::

    <plans root>/<project key>/<YYYYMMDD-HHMMSS>-<slug>.md

``<plans root>`` is ``PLAN_DIR`` when configured, else ``<config-dir>/plans``;
``<project key>`` is ``sha256(resolved cwd)[:16]`` (same scheme as the per-project
session store). Plan files are the user-facing contract:

.. code-block:: markdown

    ---
    id: 20261114-004230-token-estimator
    status: in-progress
    revision: 2
    session_id: 2026-11-14T00:42:30.123456
    created: 2026-11-14T00:42:30+08:00
    updated: 2026-11-14T01:10:05+08:00
    cwd: /Users/vic/Documents/codes/git/yaicli
    project_key: 3f9a1c2d...
    model: gpt-5.2
    base_rev: c51f7a3
    approved_at: 2026-11-14T00:45:00+08:00
    change_summary: 支持 per-provider estimator 覆盖
    ---

    # Plan: <goal>

    ## Goal
    <goal>

    ## Assumptions
    - ...

    ## Steps
    - [ ] **S1** <title>
      - acceptance: <acceptance>
      - detail: <detail>

    ## Risks
    - ...

    ## Not doing
    - ...

The frontmatter deliberately stays ``key: value`` single-line scalars (no YAML
dependency); :meth:`Plan.from_markdown` parses it with regular expressions.
Checkboxes are a *display* of the todo state maintained by the CLI: the writer
regenerates them from plan steps, and the parser ignores the checked state while
stripping a trailing `` (blocked: reason)`` marker from step titles.
"""

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Plans store directories are private: they can contain full project plans.
PLAN_DIR_MODE = 0o700
#: Plan files (Markdown + frontmatter) are private as well.
PLAN_FILE_MODE = 0o600

PLAN_STATUS_DRAFT = "draft"
PLAN_STATUS_IN_PROGRESS = "in-progress"
PLAN_STATUS_DONE = "done"
PLAN_STATUS_ABORTED = "aborted"
PLAN_TERMINAL_STATUSES = (PLAN_STATUS_DONE, PLAN_STATUS_ABORTED)
PLAN_STATUSES = (PLAN_STATUS_DRAFT, PLAN_STATUS_IN_PROGRESS, PLAN_STATUS_DONE, PLAN_STATUS_ABORTED)
PLAN_TODO_STATUSES = ("pending", "in_progress", "completed", "blocked")

#: Git lookup used for ``base_rev`` is best effort and must never hang the CLI.
_GIT_TIMEOUT_SECONDS = 5

_FRONTMATTER_RE = re.compile(r"^\ufeff?\s*---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)
_FRONTMATTER_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):[ \t]*(.*)$")
_PLAN_TITLE_RE = re.compile(r"^#[ \t]+Plan:[ \t]*(.*)$", re.MULTILINE)
_STEP_RE = re.compile(r"^- \[[ xX]\] \*\*(?P<id>[^*]+?)\*\*(?:[ \t]+(?P<title>.*))?$")
_STEP_DETAIL_RE = re.compile(r"^[ \t]+-[ \t]+(?P<kind>acceptance|detail):[ \t]*(?P<value>.*)$")
_BLOCKED_SUFFIX_RE = re.compile(r"\s+\(blocked: [^)]*\)\s*$")

_FRONTMATTER_ORDER = (
    "id",
    "status",
    "revision",
    "session_id",
    "created",
    "updated",
    "cwd",
    "project_key",
    "model",
    "base_rev",
    "approved_at",
)


class PlanStoreError(Exception):
    """Raised when a plan file cannot be read, parsed or written."""


def _single_line(value: Any) -> str:
    """Flatten a value into one trimmed line (plan body fields are single-line)."""
    text = str(value if value is not None else "")
    return re.sub(r"\s*[\r\n]+\s*", " ", text).strip()


def _now_iso() -> str:
    """Current local time as a second-resolution ISO-8601 timestamp."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _coerce_str(value: Any) -> str:
    return str(value) if value is not None else ""


def _coerce_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


@dataclass
class PlanStep:
    """One numbered step of a plan (``S1``..``Sn``)."""

    id: str
    title: str
    detail: str = ""
    acceptance: str = ""

    def to_dict(self) -> Dict[str, str]:
        """JSON-friendly representation used by the headless/session payloads."""
        return {
            "id": self.id,
            "title": self.title,
            "detail": self.detail,
            "acceptance": self.acceptance,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "PlanStep":
        """Rebuild a step from a dict, tolerating missing/None fields."""
        if not isinstance(data, dict):
            data = {}
        return cls(
            id=_coerce_str(data.get("id")),
            title=_coerce_str(data.get("title")),
            detail=_coerce_str(data.get("detail")),
            acceptance=_coerce_str(data.get("acceptance")),
        )


@dataclass
class Plan:
    """A persistent, reviewable implementation plan."""

    id: str
    goal: str
    steps: List[PlanStep]
    assumptions: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    not_doing: List[str] = field(default_factory=list)
    status: str = PLAN_STATUS_DRAFT
    revision: int = 1
    session_id: str = ""
    created: str = ""
    updated: str = ""
    cwd: str = ""
    project_key: str = ""
    model: str = ""
    base_rev: str = ""
    approved_at: str = ""
    change_summary: str = ""
    path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-friendly representation (headless result / session payload)."""
        return {
            "id": self.id,
            "goal": self.goal,
            "assumptions": list(self.assumptions),
            "steps": [step.to_dict() for step in self.steps],
            "risks": list(self.risks),
            "not_doing": list(self.not_doing),
            "status": self.status,
            "revision": self.revision,
            "session_id": self.session_id,
            "created": self.created,
            "updated": self.updated,
            "cwd": self.cwd,
            "project_key": self.project_key,
            "model": self.model,
            "base_rev": self.base_rev,
            "approved_at": self.approved_at,
            "change_summary": self.change_summary,
            "path": str(self.path) if self.path is not None else None,
        }

    def step_ids(self) -> List[str]:
        """Ordered step ids (``["S1", "S2", ...]``)."""
        return [step.id for step in self.steps]

    def to_markdown(self) -> str:
        """Render the plan as Markdown + single-line frontmatter.

        The output is stable and parseable by :meth:`from_markdown`; step
        checkboxes are rendered unchecked because the todo state lives in the
        CLI session (the CLI writes checkboxes back into the file separately).
        """
        lines: List[str] = ["---"]
        for key in _FRONTMATTER_ORDER:
            lines.append(f"{key}: {_single_line(getattr(self, key))}".rstrip())
        if self.change_summary:
            lines.append(f"change_summary: {_single_line(self.change_summary)}")
        lines.extend(["---", "", f"# Plan: {_single_line(self.goal)}", "", "## Goal"])

        goal = str(self.goal or "")
        if goal:
            lines.append(goal)
        lines.extend(["", "## Assumptions"])
        lines.extend(f"- {_single_line(item)}" for item in self.assumptions)
        lines.extend(["", "## Steps"])
        for step in self.steps:
            title = _single_line(step.title)
            lines.append(f"- [ ] **{_single_line(step.id)}** {title}".rstrip())
            if _single_line(step.acceptance):
                lines.append(f"  - acceptance: {_single_line(step.acceptance)}")
            if _single_line(step.detail):
                lines.append(f"  - detail: {_single_line(step.detail)}")
        lines.extend(["", "## Risks"])
        lines.extend(f"- {_single_line(item)}" for item in self.risks)
        lines.extend(["", "## Not doing"])
        lines.extend(f"- {_single_line(item)}" for item in self.not_doing)
        return "\n".join(lines) + "\n"

    @classmethod
    def from_markdown(cls, text: str, path: Optional[Path] = None) -> "Plan":
        """Parse a plan file, raising :class:`PlanStoreError` when it is corrupt."""
        if not isinstance(text, str):
            raise PlanStoreError("plan file content must be a string")
        match = _FRONTMATTER_RE.match(text)
        if match is None:
            raise PlanStoreError("plan file has no frontmatter")
        frontmatter = _parse_frontmatter(match.group(1), path)
        body = text[match.end() :]

        plan_id = _coerce_str(frontmatter.get("id")).strip()
        if not plan_id:
            raise PlanStoreError("plan file has no id")
        status = _coerce_str(frontmatter.get("status")).strip() or PLAN_STATUS_DRAFT
        if status not in PLAN_STATUSES:
            raise PlanStoreError(f"invalid plan status: {status}")
        revision = _parse_revision(frontmatter.get("revision", ""))

        goal = _extract_section(body, "Goal")
        if goal is None or not goal.strip():
            title_match = _PLAN_TITLE_RE.search(body)
            goal = title_match.group(1) if title_match is not None else ""
        goal = goal.strip()
        if not goal:
            raise PlanStoreError("plan file has no goal")

        steps = _parse_steps(_extract_section(body, "Steps") or "")
        if not steps:
            raise PlanStoreError("plan file has no steps")

        return cls(
            id=plan_id,
            goal=goal,
            steps=steps,
            assumptions=_parse_bullets(_extract_section(body, "Assumptions") or ""),
            risks=_parse_bullets(_extract_section(body, "Risks") or ""),
            not_doing=_parse_bullets(_extract_section(body, "Not doing") or ""),
            status=status,
            revision=revision,
            session_id=_coerce_str(frontmatter.get("session_id")),
            created=_coerce_str(frontmatter.get("created")),
            updated=_coerce_str(frontmatter.get("updated")),
            cwd=_coerce_str(frontmatter.get("cwd")),
            project_key=_coerce_str(frontmatter.get("project_key")),
            model=_coerce_str(frontmatter.get("model")),
            base_rev=_coerce_str(frontmatter.get("base_rev")),
            approved_at=_coerce_str(frontmatter.get("approved_at")),
            change_summary=_coerce_str(frontmatter.get("change_summary")),
            path=Path(path) if path is not None else None,
        )

    @classmethod
    def from_dict(cls, data: Any) -> "Plan":
        """Rebuild a plan from a JSON dict (session restore); never raises."""
        if not isinstance(data, dict):
            data = {}
        raw_steps = data.get("steps")
        steps: List[PlanStep] = []
        if isinstance(raw_steps, list):
            steps = [PlanStep.from_dict(item) for item in raw_steps if isinstance(item, dict)]
        status = _coerce_str(data.get("status")) or PLAN_STATUS_DRAFT
        if status not in PLAN_STATUSES:
            status = PLAN_STATUS_DRAFT
        plan_path: Optional[Path] = None
        raw_path = data.get("path")
        if raw_path:
            try:
                plan_path = Path(str(raw_path))
            except (TypeError, ValueError):  # pragma: no cover - exotic path objects
                plan_path = None
        return cls(
            id=_coerce_str(data.get("id")),
            goal=_coerce_str(data.get("goal")),
            steps=steps,
            assumptions=_coerce_str_list(data.get("assumptions")),
            risks=_coerce_str_list(data.get("risks")),
            not_doing=_coerce_str_list(data.get("not_doing")),
            status=status,
            revision=_tolerant_revision(data.get("revision", 1)),
            session_id=_coerce_str(data.get("session_id")),
            created=_coerce_str(data.get("created")),
            updated=_coerce_str(data.get("updated")),
            cwd=_coerce_str(data.get("cwd")),
            project_key=_coerce_str(data.get("project_key")),
            model=_coerce_str(data.get("model")),
            base_rev=_coerce_str(data.get("base_rev")),
            approved_at=_coerce_str(data.get("approved_at")),
            change_summary=_coerce_str(data.get("change_summary")),
            path=plan_path,
        )


def _parse_frontmatter(raw: str, path: Optional[Path]) -> Dict[str, str]:
    """Parse the ``key: value`` frontmatter block (no YAML dependency)."""
    data: Dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _FRONTMATTER_LINE_RE.match(stripped)
        if match is None:
            where = f" in {path}" if path is not None else ""
            raise PlanStoreError(f"invalid frontmatter line{where}: {stripped}")
        data[match.group(1)] = match.group(2).strip()
    return data


def _parse_revision(value: Any) -> int:
    try:
        revision = int(value)
    except (TypeError, ValueError):
        raise PlanStoreError(f"invalid plan revision: {value}") from None
    return max(1, revision)


def _tolerant_revision(value: Any) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _extract_section(body: str, heading: str) -> Optional[str]:
    """Return the text under ``## <heading>`` up to the next ``## `` heading."""
    pattern = re.compile(rf"^##[ \t]+{re.escape(heading)}[ \t]*$", re.MULTILINE)
    match = pattern.search(body)
    if match is None:
        return None
    start = match.end()
    next_match = re.search(r"^##[ \t]+\S", body[start:], re.MULTILINE)
    end = start + next_match.start() if next_match is not None else len(body)
    return body[start:end]


def _parse_bullets(section: str) -> List[str]:
    """Parse ``- item`` bullet lines from a body section."""
    items: List[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        if item:
            items.append(item)
    return items


def _parse_steps(section: str) -> List[PlanStep]:
    """Parse ``- [ ] **S1** title`` blocks (with indented acceptance/detail)."""
    steps: List[PlanStep] = []
    current: Optional[PlanStep] = None
    for line in section.splitlines():
        step_match = _STEP_RE.match(line.strip())
        if step_match is not None:
            step_id = step_match.group("id").strip()
            title = (step_match.group("title") or "").strip()
            title = _BLOCKED_SUFFIX_RE.sub("", title).strip()
            if not step_id or not title:
                raise PlanStoreError("invalid plan step: missing id or title")
            current = PlanStep(id=step_id, title=title)
            steps.append(current)
            continue
        detail_match = _STEP_DETAIL_RE.match(line)
        if detail_match is not None and current is not None:
            setattr(current, detail_match.group("kind"), detail_match.group("value").strip())
    seen: set = set()
    for step in steps:
        if step.id in seen:
            raise PlanStoreError(f"duplicate plan step id: {step.id}")
        seen.add(step.id)
    return steps


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def plans_root(plan_dir: str = "", config_dir: Optional[Path] = None) -> Path:
    """Resolve the plans root: ``PLAN_DIR`` when set, else ``<config-dir>/plans``.

    One of the two arguments must be provided; a bare call is a programming error
    and raises :class:`ValueError` so callers pass an explicit, testable location
    instead of silently falling back to a real home directory.
    """
    configured = str(plan_dir or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if config_dir is not None and str(config_dir).strip():
        return (Path(config_dir) / "plans").expanduser().resolve()
    raise ValueError("plans_root requires plan_dir or config_dir")


def project_key(cwd: Optional[Path] = None) -> str:
    """Stable project key: ``sha256(str(resolved cwd))[:16]``."""
    project_dir = Path(cwd) if cwd is not None else Path.cwd()
    try:
        resolved = project_dir.resolve()
    except OSError:  # pragma: no cover - deleted cwd / permission edge
        resolved = project_dir.absolute()
    return hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]


def project_plan_dir(root: Path, cwd: Optional[Path] = None) -> Path:
    """Per-project plan directory: ``<plans root>/<project key>``."""
    return Path(root) / project_key(cwd)


def slugify_goal(goal: str, max_len: int = 40) -> str:
    """Safe filename slug from a goal; non-ASCII (e.g. Chinese) falls back to ``plan``."""
    text = str(goal or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    slug = slug[:max_len].strip("-")
    return slug or "plan"


def new_plan_path(plan_dir: Path, goal: str, now: Optional[datetime] = None) -> Path:
    """Allocate ``<YYYYMMDD-HHMMSS>-<slug>.md`` (``-2``/``-3`` on collisions)."""
    directory = Path(plan_dir)
    _ensure_dir(directory)
    timestamp = (now if now is not None else datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = f"{timestamp}-{slugify_goal(goal)}"
    candidate = directory / f"{base}.md"
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{base}-{suffix}.md"
        suffix += 1
    return candidate


def git_rev(cwd: Optional[Path] = None) -> str:
    """Short HEAD revision for ``base_rev``; an empty string outside a git repo."""
    directory = Path(cwd) if cwd is not None else Path.cwd()
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(directory),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def shorten_path(path: Path) -> str:
    """Abbreviate a path with ``~`` (best effort; falls back to the raw string)."""
    try:
        raw = str(path)
        home = os.environ.get("HOME", "").strip() or os.environ.get("USERPROFILE", "").strip()
        if home:
            home = home.rstrip("/\\")
            if raw == home:
                return "~"
            for separator in ("/", "\\"):
                if raw.startswith(home + separator):
                    return "~" + raw[len(home) :]
        return raw
    except (OSError, TypeError, ValueError):  # pragma: no cover - defensive
        return str(path)


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def _ensure_dir(path: Path) -> None:
    """Create a plans directory with ``0700`` (best effort on platforms without chmod)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PlanStoreError(f"cannot create plan directory: {path} ({exc})") from exc
    try:
        os.chmod(path, PLAN_DIR_MODE)
    except OSError:
        pass


def _write_atomic(path: Path, text: str) -> None:
    """Write ``text`` atomically (same-directory temp file + ``os.replace``), mode 0600."""
    parent = path.parent
    temp = parent / f".{path.name}.{os.getpid()}.tmp"
    counter = 0
    fd = -1
    while fd < 0:
        try:
            fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, PLAN_FILE_MODE)
        except FileExistsError:
            counter += 1
            temp = parent / f".{path.name}.{os.getpid()}.{counter}.tmp"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp, PLAN_FILE_MODE)
        except OSError:
            pass
        os.replace(temp, path)
        try:
            os.chmod(path, PLAN_FILE_MODE)
        except OSError:
            pass
    finally:
        if fd >= 0:  # pragma: no cover - os.fdopen failure path
            os.close(fd)
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass


def write_plan(plan: Plan, path: Optional[Path] = None) -> Path:
    """Atomically write a plan file (0600), updating ``plan.path``/``plan.updated``."""
    target = path if path is not None else plan.path
    if target is None:
        raise PlanStoreError("plan has no path")
    target = Path(target)
    plan.path = target
    plan.updated = _now_iso()
    _ensure_dir(target.parent)
    try:
        _write_atomic(target, plan.to_markdown())
    except OSError as exc:
        raise PlanStoreError(f"cannot write plan file: {target} ({exc})") from exc
    return target


def read_plan(path: Path) -> Plan:
    """Read + parse one plan file; corrupt or missing files raise :class:`PlanStoreError`."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PlanStoreError(f"cannot read plan file: {file_path} ({exc})") from exc
    return Plan.from_markdown(text, path=file_path)


def _candidate_plan_dirs(root: Path, project_key_value: Optional[str] = None) -> List[Path]:
    if project_key_value:
        return [root / project_key_value]
    if not root.is_dir():
        return []
    try:
        subdirs = sorted(entry for entry in root.iterdir() if entry.is_dir() and not entry.name.startswith("."))
    except OSError:  # pragma: no cover - permission edge
        return []
    return subdirs


def list_plans(root: Path, project_key: Optional[str] = None) -> List[Plan]:
    """All plans for one project (or all projects), newest ``updated`` first.

    Corrupt files are skipped: one hand-edited plan must not break the listing.
    """
    root_path = Path(root)
    plans: List[Plan] = []
    for directory in _candidate_plan_dirs(root_path, project_key):
        if not directory.is_dir():
            continue
        try:
            candidates = sorted(directory.glob("*.md"))
        except OSError:  # pragma: no cover - permission edge
            continue
        for plan_path in candidates:
            if plan_path.name.startswith("."):
                continue
            try:
                plans.append(read_plan(plan_path))
            except PlanStoreError:
                continue
    plans.sort(key=_plan_sort_key, reverse=True)
    return plans


def _plan_sort_key(plan: Plan) -> tuple:
    return (_plan_timestamp(plan), plan.path.name if plan.path is not None else "")


def _plan_timestamp(plan: Plan) -> float:
    for raw in (plan.updated, plan.created):
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw)).timestamp()
        except (TypeError, ValueError):
            continue
    return 0.0


def find_plan(root: Path, plan_id: str, project_key: Optional[str] = None) -> Optional[Plan]:
    """Find a plan by its id (or filename stem); ``None`` when it does not exist."""
    if not plan_id:
        return None
    for plan in list_plans(root, project_key):
        if plan.id == plan_id:
            return plan
        if plan.path is not None and plan.path.stem == plan_id:
            return plan
    return None


def find_latest_unfinished(root: Path, project_key: str, session_id: Optional[str] = None) -> Optional[Plan]:
    """Newest draft/in-progress plan, optionally restricted to one session."""
    candidates = [
        plan for plan in list_plans(root, project_key) if plan.status in (PLAN_STATUS_DRAFT, PLAN_STATUS_IN_PROGRESS)
    ]
    if session_id is not None:
        candidates = [plan for plan in candidates if plan.session_id == session_id]
    return candidates[0] if candidates else None


def prune_plans(root: Path, project_key: str, keep: int, now: Optional[datetime] = None) -> List[Path]:
    """Delete old terminal plans so at most ``keep`` remain per project.

    Draft/in-progress plans are never pruned. ``now`` is accepted so callers share
    a single clock source; pruning itself only depends on each file's ``updated``.
    """
    del now
    try:
        keep_count = max(0, int(keep))
    except (TypeError, ValueError):
        keep_count = 0
    terminal = [plan for plan in list_plans(root, project_key) if plan.status in PLAN_TERMINAL_STATUSES]
    deleted: List[Path] = []
    for plan in reversed(terminal[keep_count:]):
        if plan.path is None:
            continue
        try:
            plan.path.unlink()
        except OSError:
            continue
        deleted.append(plan.path)
    return deleted


def clear_plans(root: Path, project_key: Optional[str] = None, *, done_only: bool = False) -> List[Path]:
    """Delete matching plan files; ``done_only`` keeps drafts/in-progress plans."""
    plans = list_plans(root, project_key)
    if done_only:
        plans = [plan for plan in plans if plan.status in PLAN_TERMINAL_STATUSES]
    deleted: List[Path] = []
    for plan in reversed(plans):
        if plan.path is None:
            continue
        try:
            plan.path.unlink()
        except OSError:
            continue
        deleted.append(plan.path)
    return deleted


def update_plan_status(plan: Plan, status: str) -> Plan:
    """Change a plan's status in memory (the caller decides when to write it)."""
    if status not in PLAN_STATUSES:
        raise PlanStoreError(f"invalid plan status: {status}")
    plan.status = status
    plan.updated = _now_iso()
    return plan
