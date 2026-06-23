import json
import os
import tempfile
from pathlib import Path
from typing import Optional, Set

from ..const import TOOL_PERMISSIONS_PATH

# Key in the permissions JSON file holding the persistent allowlist
_ALLOWLIST_KEY = "always_allow"


class ToolApprovalManager:
    """Track which tools the user has approved for execution.

    Two scopes:
    - ``session_allow``: in-memory, lives for the current process only.
    - ``persistent_allow``: loaded from and written to a JSON file, survives restarts.

    Tool names are keyed exactly as observed at the confirmation gate; MCP tool
    names keep their ``_mcp__`` prefix so an MCP tool and a built-in function
    sharing a base name are tracked as distinct approvals.
    """

    def __init__(self, permissions_path: Optional[Path] = None):
        self.permissions_path: Path = permissions_path or TOOL_PERMISSIONS_PATH
        self.session_allow: Set[str] = set()
        self.persistent_allow: Set[str] = self._load()

    def _load(self) -> Set[str]:
        """Load the persistent allowlist, tolerating a missing or malformed file."""
        try:
            data = json.loads(self.permissions_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return set()
        if not isinstance(data, dict):
            return set()
        names = data.get(_ALLOWLIST_KEY, [])
        if not isinstance(names, list):
            return set()
        return {str(n) for n in names}

    def is_allowed(self, name: str) -> bool:
        """Return True if the tool is approved for the session or persistently."""
        return name in self.session_allow or name in self.persistent_allow

    def allow_session(self, name: str) -> None:
        """Approve a tool for the remainder of this process."""
        self.session_allow.add(name)

    def allow_persist(self, name: str) -> None:
        """Approve a tool and persist it across runs.

        The file is written before the in-memory set is updated, so a failed write
        leaves both the file and the in-memory allowlist unchanged.
        """
        updated = set(self.persistent_allow)
        updated.add(name)
        self._save(updated)
        self.persistent_allow = updated

    def _save(self, allowlist: Set[str]) -> None:
        """Write the persistent allowlist atomically (temp file + rename).

        A partial write cannot corrupt the existing file: content is written to a
        temp file in the same directory and then atomically moved into place.
        """
        self.permissions_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({_ALLOWLIST_KEY: sorted(allowlist)}, indent=2, ensure_ascii=False)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.permissions_path.parent), prefix=".tool_permissions_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_path, self.permissions_path)
        except Exception:
            # Clean up the temp file on failure; leave the existing file intact.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
