"""Tool approval policy store and argument normalization (v0.19 K06).

This module owns three related concerns used by the confirmation gate:

1. **Approval state** — in-memory session approvals, the persistent
   ``tool_permissions.json`` allowlist (v2 format, backward compatible with the v1
   ``{"always_allow": [...]}`` file) and the per-run ``--yes`` / ``--allowed-tools``
   grants handed over by :func:`configure_run`.
2. **Argument-aware rules** — ``{"tool": ..., "argv_prefix": [...]}`` rules constrain
   shell commands to an argv prefix; ``{"tool": ..., "path_glob": ...}`` rules constrain
   filesystem writes to paths matching an :mod:`fnmatch` pattern.
3. **Faithful argument normalization** — :func:`parse_tool_arguments` parses tool-call
   arguments with ``json_repair`` exactly like ``tools.execute_tool_call`` does, so the
   confirmation prompt, the audit summary and the tool that finally runs all see the
   same decoded object. :func:`summarize_arguments` builds the redacted, truncated
   audit-log summary.

The file is intentionally dependency-light (stdlib + ``json_repair``): it is imported by
the tool gate, the printer and the REPL command handler.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from json_repair import repair_json

from .. import const

# Keys used by the v1 file and by the v2 object form.
_ALLOWLIST_KEY = "always_allow"
_RULES_KEY = "rules"
_VERSION_KEY = "version"

#: Version written by this module; v1 files (no ``version`` key) load unchanged.
CURRENT_PERMISSIONS_VERSION = 2

#: Argument keys that commonly carry a filesystem target, in priority order. A
#: ``path_glob`` rule must match *every* path-like argument of the call (so a move of
#: ``src/a`` to ``/etc/a`` is not covered by a ``src/**`` rule).
_PATH_ARG_KEYS: Tuple[str, ...] = (
    "file_path",
    "file_paths",
    "path",
    "paths",
    "filename",
    "file",
    "dest",
    "destination",
    "target",
    "source",
    "src",
)

_SHELL_OPERATOR_CHARS = ";&|<>"

#: Shell syntax that makes a command compound or expand into another command. An
#: ``argv_prefix`` rule only vouches for one *simple* command, so any of these vetoes
#: rule matching (the call falls back to the normal confirmation path): command
#: separators/pipes/redirects, backticks, ``$(...)``/``${...}`` expansion, process
#: substitution and newlines. Quoted literals containing these characters are
#: rejected too (conservative, always safe: they simply require confirmation).
_SHELL_UNSAFE_SYNTAX_RE = re.compile(r"[;|&<>`]|\$\(|\$\{|<\(|>\(|[\r\n]")


def _workspace_root() -> Path:
    """Resolve the workspace root used to match relative paths (WORKSPACE_ROOT/cwd)."""
    raw = ""
    try:  # Lazy import: approval.py must stay importable without the config singleton.
        from ..config import cfg

        raw = str(cfg.get("WORKSPACE_ROOT") or "").strip()
    except Exception:  # pragma: no cover - config lookups must never break approval
        raw = ""
    if raw:
        try:
            return Path(raw).expanduser().resolve()
        except OSError:  # pragma: no cover - exotic cwd/permission errors
            return Path(raw).expanduser()
    try:
        return Path.cwd()
    except OSError:  # pragma: no cover - deleted cwd
        return Path(os.getcwd())


# ---------------------------------------------------------------------------
# Argument normalization (shared by the gate, the prompt and the audit log)
# ---------------------------------------------------------------------------
def parse_tool_arguments(arguments: Any) -> Optional[Dict[str, Any]]:
    """Parse tool-call arguments into the dict the tool will actually receive.

    This mirrors ``yaicli.tools.execute_tool_call`` exactly: ``json_repair`` with
    ``return_objects=True`` and a ``dict`` result is required. The confirmation prompt
    and the tool gate use this function so what the user sees is what executes
    (duplicate JSON keys resolve to the last value, ``\\u003b`` escapes are decoded,
    ...).

    Returns ``None`` when the arguments are not a JSON object (the execution path then
    reports an in-band error and no tool runs).
    """
    if isinstance(arguments, dict):
        return dict(arguments)
    if not isinstance(arguments, str):
        return None
    try:
        parsed = repair_json(arguments, return_objects=True)
    except Exception:  # pragma: no cover - json_repair is very tolerant, keep defensive
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def canonical_arguments(arguments: Any) -> str:
    """Return the canonical JSON representation of parsed arguments for display."""
    parsed = parse_tool_arguments(arguments) if not isinstance(arguments, dict) else arguments
    if parsed is None:
        text = "" if arguments is None else str(arguments)
        return text
    try:
        return json.dumps(parsed, ensure_ascii=False)
    except (TypeError, ValueError):  # pragma: no cover - parsed JSON is always serializable
        return repr(parsed)


# ---------------------------------------------------------------------------
# Secret redaction for audit summaries
# ---------------------------------------------------------------------------
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|apikey|secret|token|password|passwd|authorization|credential|bearer|private[_-]?key)"
)
_SECRET_VALUE_RES = (
    re.compile(r"(?i)\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_REDACTED = "[redacted]"


def redact_text(text: str) -> str:
    """Redact well-known secret shapes from a string."""
    if not isinstance(text, str):
        text = str(text)
    for pattern in _SECRET_VALUE_RES:
        text = pattern.sub(_REDACTED, text)
    return _CONTROL_CHARS_RE.sub("", text)


def _redact_value(value: Any) -> Any:
    """Recursively redact secret-looking keys/values in parsed JSON."""
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                redacted[key] = _REDACTED
            else:
                redacted[key] = _redact_value(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def summarize_arguments(tool_name: str, arguments: Any, limit: int = 500) -> str:
    """Build the sanitized + truncated ``args_summary`` written to the audit log.

    Shell commands are summarized as the decoded command (that is what matters for an
    audit); other tools as canonical JSON. Secret-looking keys/values are redacted and
    the result is capped to ``limit`` characters.
    """
    parsed = arguments if isinstance(arguments, dict) else parse_tool_arguments(arguments)
    if parsed is None:
        summary = redact_text("" if arguments is None else str(arguments))
    elif isinstance(parsed.get("command"), str):
        summary = redact_text(parsed["command"])
    else:
        try:
            summary = json.dumps(_redact_value(parsed), ensure_ascii=False)
        except (TypeError, ValueError):  # pragma: no cover - parsed JSON is serializable
            summary = redact_text(str(parsed))
    if len(summary) > limit:
        summary = summary[: max(limit - 3, 0)] + "..."
    return summary


# ---------------------------------------------------------------------------
# Path / argv rule matching
# ---------------------------------------------------------------------------
def _path_values(arguments: Dict[str, Any]) -> List[str]:
    """Collect path-like string values from common tool argument keys."""
    values: List[str] = []
    for key in _PATH_ARG_KEYS:
        if key not in arguments:
            continue
        raw = arguments[key]
        if isinstance(raw, str):
            if raw.strip():
                values.append(raw)
        elif isinstance(raw, (list, tuple)):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    values.append(item)
    return values


def _path_candidates(raw: str, workspace: Path) -> List[str]:
    """Return the normalized paths of ``raw`` a path glob may be matched against.

    Only normalized paths are candidates (never the raw ``..``-containing form) so a
    ``path_glob`` rule cannot be bypassed with traversal:

    * a relative path is resolved against the workspace (``strict=False``) and offered
      as its workspace-relative normalized path plus the absolute path;
    * an absolute path inside the workspace is offered the same way;
    * an absolute path outside the workspace is offered only as its normalized
      absolute path, so a relative glob such as ``src/**`` never matches it.

    ``..`` segments that resolve outside the workspace therefore never match a
    workspace-relative glob.
    """
    try:
        expanded = Path(raw).expanduser()
        if expanded.is_absolute():
            absolute = expanded.resolve(strict=False)
        else:
            absolute = (workspace / expanded).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):  # pragma: no cover - defensive
        joined = raw if os.path.isabs(raw) else os.path.join(str(workspace), raw)
        absolute = Path(os.path.normpath(joined)).expanduser()

    absolute_text = str(absolute).replace(os.sep, "/")
    try:
        relative = os.path.relpath(str(absolute), str(workspace))
    except (ValueError, OSError):  # pragma: no cover - different drives on Windows
        relative = ""
    relative_text = os.path.normpath(relative).replace(os.sep, "/") if relative else ""
    if relative_text and relative_text != os.pardir and not relative_text.startswith(os.pardir + "/"):
        return [relative_text, absolute_text]
    # Outside the workspace: only the normalized absolute path can be matched.
    return [absolute_text]


def _path_glob_matches(pattern: str, arguments: Dict[str, Any]) -> bool:
    """True when every path-like argument of the call matches ``pattern``."""
    values = _path_values(arguments)
    if not values:
        return False
    workspace = _workspace_root()
    for raw in values:
        candidates = _path_candidates(raw, workspace)
        if not any(fnmatch.fnmatch(candidate, pattern) for candidate in candidates):
            return False
    return True


def _shell_tokens(command: str) -> Optional[List[str]]:
    """Tokenize a shell command, refusing compound/expanded commands.

    A rule may only auto-approve a single *simple* command. Before tokenizing, the raw
    text is checked for shell control/expansion syntax (``;``, ``|``, ``&``, ``<``,
    ``>``, backticks, ``$(...)``, ``${...}``, process substitution, newlines): if any
    is present the prefix cannot be claimed to cover the whole command, so
    :func:`_argv_prefix_matches` returns False and the user is asked instead.
    """
    if _SHELL_UNSAFE_SYNTAX_RE.search(command):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=_SHELL_OPERATOR_CHARS)
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens:
        return None
    for token in tokens:
        if token and all(char in _SHELL_OPERATOR_CHARS for char in token):
            return None
    return tokens


def _argv_prefix_matches(prefix: Sequence[str], arguments: Dict[str, Any]) -> bool:
    """True when the shell command's argv starts with ``prefix``."""
    if not prefix:
        return False
    command = arguments.get("command")
    if not isinstance(command, str):
        return False
    tokens = _shell_tokens(command)
    if tokens is None:
        return False
    return list(tokens[: len(prefix)]) == list(prefix)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PermissionRule:
    """One persisted ``tool_permissions.json`` v2 rule.

    Exactly one of ``argv_prefix`` / ``path_glob`` is expected. Rules are additive:
    the gate consults every rule whose ``tool`` matches the pending call.
    """

    tool: str
    argv_prefix: Optional[Tuple[str, ...]] = None
    path_glob: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize back to the on-disk v2 object form."""
        data: Dict[str, Any] = {"tool": self.tool}
        if self.argv_prefix is not None:
            data["argv_prefix"] = list(self.argv_prefix)
        if self.path_glob is not None:
            data["path_glob"] = self.path_glob
        return data

    def matches(self, arguments: Dict[str, Any]) -> bool:
        """True when this rule allows a call to ``self.tool`` with ``arguments``."""
        if self.argv_prefix is not None and not _argv_prefix_matches(self.argv_prefix, arguments):
            return False
        if self.path_glob is not None and not _path_glob_matches(self.path_glob, arguments):
            return False
        return self.argv_prefix is not None or self.path_glob is not None

    def describe(self) -> str:
        """Human readable one-line description used by ``/permissions``."""
        parts: List[str] = [self.tool]
        if self.argv_prefix is not None:
            parts.append(f"argv_prefix={list(self.argv_prefix)!r}")
        if self.path_glob is not None:
            parts.append(f"path_glob={self.path_glob!r}")
        return " ".join(parts)


def _parse_rule(raw: Any) -> Optional[PermissionRule]:
    """Parse one v2 rule object; invalid entries are skipped (never fail the load)."""
    if not isinstance(raw, dict):
        return None
    tool = raw.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        return None
    argv_prefix = raw.get("argv_prefix")
    path_glob = raw.get("path_glob")
    if argv_prefix is not None:
        if not isinstance(argv_prefix, (list, tuple)) or not argv_prefix:
            return None
        if not all(isinstance(item, str) and item for item in argv_prefix):
            return None
        argv_tuple: Optional[Tuple[str, ...]] = tuple(str(item) for item in argv_prefix)
    else:
        argv_tuple = None
    if path_glob is not None and (not isinstance(path_glob, str) or not path_glob.strip()):
        return None
    if argv_tuple is None and path_glob is None:
        # A rule must constrain something; a bare {"tool": x} is treated as invalid so
        # it can not silently become a v1-style always-allow.
        return None
    return PermissionRule(tool=tool, argv_prefix=argv_tuple, path_glob=path_glob)


class ToolApprovalManager:
    """Track which tools the user has approved for execution.

    Three scopes:

    - :attr:`session_allow`: in-memory tool names, alive for this process only;
    - :attr:`persistent_allow` + :attr:`persistent_rules`: loaded from and written to
      ``tool_permissions.json`` (v2), surviving restarts;
    - :attr:`run_allow_patterns` / :attr:`auto_allow_read`: the per-run
      ``--allowed-tools`` glob list and ``--yes`` read-only switch (never persisted).

    Tool names are keyed exactly as observed at the confirmation gate; MCP tool names
    keep their ``_mcp__`` prefix so an MCP tool and a built-in function sharing a base
    name are tracked as distinct approvals.
    """

    def __init__(self, permissions_path: Optional[Path] = None):
        self.permissions_path: Path = permissions_path or const.TOOL_PERMISSIONS_PATH
        self.session_allow: Set[str] = set()
        self.persistent_allow: Set[str] = set()
        self.persistent_rules: List[PermissionRule] = []
        #: Format version found on disk (``1`` when the file only had ``always_allow``).
        self.permissions_version: int = CURRENT_PERMISSIONS_VERSION
        #: Per-run grants (K06): ``--allowed-tools`` glob patterns and ``--yes``.
        self.run_allow_patterns: List[str] = []
        self.auto_allow_read: bool = False
        self._load()

    # ------------------- loading / saving -------------------
    def _load(self) -> None:
        """Load the persistent allowlist + rules, tolerating a missing/malformed file."""
        try:
            data = json.loads(self.permissions_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return
        if not isinstance(data, dict):
            return

        names = data.get(_ALLOWLIST_KEY, [])
        if isinstance(names, list):
            self.persistent_allow = {str(name) for name in names if isinstance(name, str) and name}

        raw_version = data.get(_VERSION_KEY)
        if isinstance(raw_version, int):
            self.permissions_version = raw_version
        elif isinstance(raw_version, str) and raw_version.strip().isdigit():
            self.permissions_version = int(raw_version.strip())
        else:
            self.permissions_version = 1

        rules = data.get(_RULES_KEY, [])
        if isinstance(rules, list):
            parsed_rules = [_parse_rule(item) for item in rules]
            self.persistent_rules = [rule for rule in parsed_rules if rule is not None]

    def _save(self, allowlist: Optional[Set[str]] = None, rules: Optional[List[PermissionRule]] = None) -> None:
        """Write the permissions file atomically (temp file + rename) in v2 format.

        A partial write cannot corrupt the existing file: content is written to a temp
        file in the same directory and then atomically moved into place. The file is
        created with mode ``0600`` (best effort) because it records local trust
        decisions.
        """
        names = sorted(self.persistent_allow if allowlist is None else allowlist)
        active_rules = self.persistent_rules if rules is None else rules
        payload = json.dumps(
            {
                _VERSION_KEY: CURRENT_PERMISSIONS_VERSION,
                _ALLOWLIST_KEY: names,
                _RULES_KEY: [rule.to_dict() for rule in active_rules],
            },
            indent=2,
            ensure_ascii=False,
        )
        self.permissions_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.permissions_path.parent), prefix=".tool_permissions_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_path, self.permissions_path)
            try:
                os.chmod(self.permissions_path, 0o600)
            except OSError:  # pragma: no cover - chmod unavailable (Windows/permissions)
                pass
        except Exception:
            # Clean up the temp file on failure; leave the existing file intact.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------- run grants (--yes / --allowed-tools) -------------------
    def configure_run(self, *, yes: bool = False, allowed_tools: Optional[Iterable[str]] = None) -> None:
        """Apply the one-run ``--yes`` / ``--allowed-tools`` policy (never persisted).

        ``--yes`` auto-approves only ``read``-risk tools; ``--allowed-tools`` is a list
        of tool-name glob patterns valid for this process only.
        """
        self.auto_allow_read = bool(yes)
        patterns: List[str] = []
        for pattern in allowed_tools or []:
            text = str(pattern).strip()
            if text:
                patterns.append(text)
        self.run_allow_patterns = patterns

    def is_run_allowed(self, name: str) -> bool:
        """True when ``--allowed-tools`` grants this tool name for the current run."""
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.run_allow_patterns)

    # ------------------- queries -------------------
    def match_source(self, name: str, arguments: Any = None) -> Optional[str]:
        """Explain *why* a call is pre-approved: ``session``/``persist``/``rule``/None.

        ``arguments`` is the repaired argument dict (or the raw JSON string); rules
        need it, the two name-based scopes do not.
        """
        if name in self.session_allow:
            return "session"
        if name in self.persistent_allow:
            return "persist"
        if arguments is not None and self.persistent_rules:
            parsed = arguments if isinstance(arguments, dict) else parse_tool_arguments(arguments)
            if parsed is not None:
                for rule in self.persistent_rules:
                    if rule.tool == name and rule.matches(parsed):
                        return "rule"
        return None

    def is_allowed(self, name: str, arguments: Any = None) -> bool:
        """Return True if the tool is approved for the session or persistently.

        ``arguments`` enables the v2 argument-aware rules (shell argv prefix / path
        glob). Old callers passing only the tool name keep the v1 behaviour.
        """
        return self.match_source(name, arguments) is not None

    # ------------------- approvals -------------------
    def allow_session(self, name: str) -> None:
        """Approve a tool for the remainder of this process."""
        self.session_allow.add(name)

    def allow_persist(self, name: str) -> None:
        """Approve a tool name and persist it across runs.

        The file is written before the in-memory state is updated, so a failed write
        leaves both the file and the in-memory allowlist unchanged. Existing rules are
        preserved.
        """
        if name in self.persistent_allow:
            return
        updated = set(self.persistent_allow)
        updated.add(name)
        self._save(allowlist=updated)
        self.persistent_allow = updated

    # ------------------- revocation (/permissions revoke) -------------------
    def revoke(self, target: str) -> Optional[str]:
        """Revoke one persistent permission by tool name or 1-based rule index.

        - a rule index (as printed by ``/permissions``) removes that rule;
        - a tool name removes the tool from ``always_allow``, removes every rule for
          that tool, and clears the in-memory session approval as well.

        Returns a human readable description of what was revoked, or ``None`` when
        nothing matched. Persistence failures raise :class:`OSError` (the REPL reports
        them) after leaving the in-memory state untouched.
        """
        text = str(target).strip()
        if not text:
            return None
        if text.isdigit():
            return self._revoke_rule_index(int(text))

        removed_parts: List[str] = []
        rules_before = list(self.persistent_rules)
        remaining = [rule for rule in rules_before if rule.tool != text]
        if len(remaining) != len(rules_before):
            removed_parts.append(f"{len(rules_before) - len(remaining)} rule(s) for {text!r}")
        names_before = set(self.persistent_allow)
        if text in names_before:
            remaining_names = names_before - {text}
            removed_parts.append("always_allow entry")
        else:
            remaining_names = names_before

        if removed_parts:
            self._save(allowlist=remaining_names, rules=remaining)
            self.persistent_allow = remaining_names
            self.persistent_rules = remaining
        if text in self.session_allow:
            self.session_allow.discard(text)
            removed_parts.append("session approval")
        return ", ".join(removed_parts) if removed_parts else None

    def _revoke_rule_index(self, index: int) -> Optional[str]:
        """Remove the 1-based ``index`` rule from the persisted rule list."""
        if index < 1 or index > len(self.persistent_rules):
            return None
        rule = self.persistent_rules[index - 1]
        remaining = [item for position, item in enumerate(self.persistent_rules, start=1) if position != index]
        self._save(rules=remaining)
        self.persistent_rules = remaining
        return f"rule #{index} ({rule.describe()})"
