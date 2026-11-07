"""Auto-load project instruction files into the system prompt (v0.21 K12).

The agent reads ``.yaicli.md`` / ``AGENTS.md`` / ``CLAUDE.md`` from the current working
directory upward to the nearest git root and appends them to the system prompt. The
feature is intentionally conservative:

* **Bounded**: the collected block is capped by ``PROJECT_CONTEXT_MAX_CHARS`` (default
  20000, ``0`` = no cap). When the cap cuts content, exactly one warning naming the
  files and the chars involved is printed to stderr (raising the limit is easy).
* **Cheap when absent**: no files means an empty result, so the request payload is
  byte-identical to the pre-K12 behaviour (no extra system message).
* **No reads when disabled**: ``ENABLE_PROJECT_CONTEXT=false`` returns before any
  filesystem access.
* **Never fatal**: an unreadable file is skipped with one warning; ``OSError`` never
  aborts a turn.

Discovery contract:

* walk from the current directory up to the git root (a directory containing a
  ``.git`` directory or the ``.git`` file of a worktree), inclusive; never above it.
  Without a git root the walk stops at the filesystem root;
* directories are emitted from the outermost (git root) to the innermost (cwd), so the
  most specific instructions appear last in the prompt;
* within one directory the order is ``.yaicli.md``, then ``AGENTS.md``, then
  ``CLAUDE.md``; files that resolve to the same real path (e.g. ``AGENTS.md`` symlinked
  to ``CLAUDE.md``) are loaded only once.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .config import cfg
from .console import get_error_console
from .const import DEFAULT_PROJECT_CONTEXT_MAX_CHARS

#: Instruction-file names checked in every directory, in priority order.
PROJECT_CONTEXT_FILENAMES = (".yaicli.md", "AGENTS.md", "CLAUDE.md")

#: Marks a git repository root (a directory, or a file for git worktrees).
GIT_MARKER = ".git"

#: Safety bound for pathological directory trees (Path.parents terminates anyway).
MAX_ANCESTOR_DEPTH = 128

#: Heading added before the file blocks; the cap includes it.
PROJECT_CONTEXT_HEADER = "## Project context (auto-loaded instruction files)\n"

error_console = get_error_console()


@dataclass
class ProjectContextFile:
    """One instruction file that contributed to the system prompt."""

    path: Path
    original_chars: int
    kept_chars: int

    @property
    def truncated(self) -> bool:
        """True when the size cap cut part of this file."""
        return self.kept_chars < self.original_chars


@dataclass
class ProjectContextResult:
    """Bounded project-context block collected for the system prompt."""

    text: str = ""
    files: List[ProjectContextFile] = field(default_factory=list)
    omitted: List[Path] = field(default_factory=list)
    queried_chars: int = 0
    limit: int = 0
    truncated: bool = False

    @property
    def has_content(self) -> bool:
        """True when there is something to add to the system prompt."""
        return bool(self.text)

    @property
    def paths(self) -> List[Path]:
        """Paths of the files that contributed to the prompt."""
        return [item.path for item in self.files]


def _warn(message: str) -> None:
    """Write one diagnostic line to stderr (warnings never pollute scripted stdout)."""
    try:
        error_console.print(message, markup=False, soft_wrap=True)
    except Exception:  # pragma: no cover - the stderr console is always available
        pass


def _resolve_start(start: Optional[Path] = None) -> Optional[Path]:
    """Return an absolute start directory, or ``None`` if the cwd is unavailable."""
    try:
        path = Path.cwd() if start is None else Path(start)
    except OSError:  # pragma: no cover - deleted cwd
        return None
    try:
        return path.expanduser().absolute()
    except (RuntimeError, OSError):  # pragma: no cover - exotic path resolution
        return path


def find_git_root(start: Optional[Path] = None) -> Optional[Path]:
    """Return the nearest ancestor of ``start`` that contains a ``.git`` marker.

    Both a ``.git`` directory and the ``.git`` file used by git worktrees count. The
    filesystem root is never considered a git root unless it really contains ``.git``.
    """
    directory = _resolve_start(start)
    for _ in range(MAX_ANCESTOR_DEPTH):
        if directory is None:
            return None
        try:
            if (directory / GIT_MARKER).exists():
                return directory
        except OSError:  # pragma: no cover - unreadable ancestor
            pass
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent
    return None  # pragma: no cover - defensive depth guard


def _ordered_directories(cwd: Path, git_root: Optional[Path]) -> List[Path]:
    """Return ``cwd`` ancestors from the outermost (git root) down to ``cwd``."""
    chain = [cwd]
    current = cwd
    while True:
        if git_root is not None and current == git_root:
            break
        parent = current.parent
        if parent == current:
            break
        chain.append(parent)
        current = parent
    return list(reversed(chain))


def iter_project_context_files(start: Optional[Path] = None) -> List[Path]:
    """Return the ordered, de-duplicated instruction files for ``start`` (no reads)."""
    cwd = _resolve_start(start)
    if cwd is None:  # pragma: no cover - deleted cwd
        return []
    try:
        git_root = find_git_root(cwd)
    except OSError:  # pragma: no cover - find_git_root is already tolerant
        git_root = None

    files: List[Path] = []
    seen: set[str] = set()
    for directory in _ordered_directories(cwd, git_root):
        for filename in PROJECT_CONTEXT_FILENAMES:
            candidate = directory / filename
            try:
                if not candidate.is_file():
                    continue
                real_path = str(candidate.resolve())
            except (OSError, RuntimeError):  # pragma: no cover - broken symlink etc.
                continue
            if real_path in seen:
                continue
            seen.add(real_path)
            files.append(candidate)
    return files


def _format_file_block(path: Path, content: str) -> str:
    return f"\n### {path.name} ({path})\n\n{content}\n"


def _format_truncation_warning(result: ProjectContextResult) -> str:
    details: List[str] = []
    for item in result.files:
        if item.truncated:
            details.append(f"{item.path} ({item.kept_chars} of {item.original_chars} chars kept)")
        else:
            details.append(f"{item.path} ({item.original_chars} chars)")
    details.extend(f"{path} (skipped)" for path in result.omitted)
    described = ", ".join(details) if details else "none"
    return (
        f"WARNING: Project context was truncated to PROJECT_CONTEXT_MAX_CHARS={result.limit}: "
        f"{len(result.text)} chars kept from {len(result.files)} file(s) ({described}). "
        f"Raise PROJECT_CONTEXT_MAX_CHARS (env YAI_PROJECT_CONTEXT_MAX_CHARS) "
        f"or set ENABLE_PROJECT_CONTEXT=false to disable."
    )


def collect_project_context(start: Optional[Path] = None, limit: Optional[int] = None) -> ProjectContextResult:
    """Read and bound the project instruction files for ``start`` (default: cwd).

    Args:
        start: Directory to start discovery from (tests pass an explicit path).
        limit: Maximum characters of the resulting block, including the heading.
            ``None`` or a non-positive value means unbounded.

    Returns:
        A :class:`ProjectContextResult`; ``text`` is ``""`` when nothing was found or
        the whole content had to be dropped by the cap.
    """
    cap = int(limit) if limit is not None and int(limit) > 0 else 0
    result = ProjectContextResult(limit=cap)

    for path in iter_project_context_files(start):
        header = _format_file_block(path, "")
        # Content + blocks are appended after the heading; stop before reading files
        # that cannot fit anymore (the cap is a hard bound on the emitted text).
        remaining = cap - (len(PROJECT_CONTEXT_HEADER) + len(result.text)) if cap else None
        if remaining is not None and remaining <= len(header):
            result.omitted.append(path)
            result.truncated = True
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            _warn(f"WARNING: Could not read project context file {path}: {exc}")
            continue
        original = len(content)
        result.queried_chars += original
        if remaining is not None:
            available = remaining - len(header)
            if original > available:
                content = content[:available]
                result.truncated = True
        result.files.append(ProjectContextFile(path=path, original_chars=original, kept_chars=len(content)))
        result.text += _format_file_block(path, content)

    if not result.files:
        result.text = ""
    elif result.text:
        result.text = PROJECT_CONTEXT_HEADER + result.text

    if result.truncated:
        _warn(_format_truncation_warning(result))
    return result


def _config_enabled() -> bool:
    """Read ``ENABLE_PROJECT_CONTEXT`` (default enabled) from the global config."""
    value = cfg.get("ENABLE_PROJECT_CONTEXT", True)
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off", "n")
    return bool(value)


def _config_limit() -> int:
    """Read ``PROJECT_CONTEXT_MAX_CHARS`` (default 20000) from the global config."""
    try:
        return max(int(cfg.get("PROJECT_CONTEXT_MAX_CHARS", DEFAULT_PROJECT_CONTEXT_MAX_CHARS)), 0)
    except (TypeError, ValueError):
        return DEFAULT_PROJECT_CONTEXT_MAX_CHARS


def load_project_context() -> ProjectContextResult:
    """Collect the project context for the current working directory.

    This is the CLI entry point: it honours ``ENABLE_PROJECT_CONTEXT`` (false means no
    filesystem reads at all) and ``PROJECT_CONTEXT_MAX_CHARS``.
    """
    if not _config_enabled():
        return ProjectContextResult()
    limit = _config_limit()
    try:
        return collect_project_context(limit=limit)
    except OSError:  # pragma: no cover - individual reads are already tolerated
        return ProjectContextResult(limit=limit)
