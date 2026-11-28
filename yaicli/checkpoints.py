"""Persistent, per-session checkpoints for guarded workspace file mutations."""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from .checkpoint_lock import SessionLock


class CheckpointError(Exception):
    """An operation cannot be completed without risking session or workspace data."""


def display_text(value: Any) -> str:
    """Show paths literally while making terminal control characters visible."""
    return "".join(f"\\x{ord(char):02x}" if ord(char) < 32 or 127 <= ord(char) < 160 else char for char in str(value))


_ACTIVE_CAPTURE: contextvars.ContextVar[Optional["TurnCapture"]] = contextvars.ContextVar(
    "yaicli_checkpoint_capture", default=None
)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _private_dir(path: Path) -> None:
    if path.is_symlink():
        raise CheckpointError("Checkpoint storage contains a symbolic link.")
    if not path.exists():
        _private_dir(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    _private_dir(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


class TurnCapture:
    """Thread-context mutation journal for one user turn."""

    def __init__(self, store: "CheckpointStore", lock: SessionLock, turn: int):
        self.store = store
        self.lock = lock
        self.turn = turn
        self.files: List[Dict[str, Any]] = []
        self.barrier = False
        self.finished = False
        self.completed = False

    def prepare(self, entry: Any, raw_paths: Optional[List[str]] = None) -> None:
        """Remember implicit parents and symlinks before a guarded call starts."""
        self.parents: List[Path] = []
        for raw in raw_paths or []:
            path = Path(raw).expanduser().absolute()
            for candidate in (path, *path.parents):
                if candidate == self.store.root:
                    break
                if candidate.is_symlink():
                    self.barrier = True
        for original in getattr(entry, "originals", []):
            parent = Path(original.path).parent
            while parent != self.store.root and self.store.root in parent.parents and not parent.exists():
                if parent not in self.parents:
                    self.parents.append(parent)
                parent = parent.parent

    @contextmanager
    def activate(self) -> Iterator["TurnCapture"]:
        token = _ACTIVE_CAPTURE.set(self)
        try:
            yield self
        finally:
            _ACTIVE_CAPTURE.reset(token)

    def record(self, entry: Any, success: bool) -> None:
        if self.finished:
            return
        originals = getattr(entry, "originals", [])
        for original in originals:
            path = Path(original.path)
            if path.is_symlink() or getattr(original, "is_dir", False):
                if success or original.existed or path.exists() != original.existed:
                    self.barrier = True
                continue
            try:
                relative = path.resolve(strict=False).relative_to(self.store.root).as_posix()
            except (OSError, ValueError):
                self.barrier = True
                continue
            before_exists = bool(original.existed)
            backup = Path(original.backup_path) if original.backup_path is not None else None
            if before_exists:
                if backup is None or not backup.is_file() or backup.is_symlink():
                    self.barrier = True
                    continue
                before_hash = _hash_file(backup)
            else:
                before_hash = None
            after_exists = path.is_file() and not path.is_symlink()
            after_hash = _hash_file(path) if after_exists else None
            after_mode = stat.S_IMODE(path.stat().st_mode) if after_exists else None
            if (
                before_exists == after_exists
                and before_hash == after_hash
                and (not before_exists or original.mode == after_mode)
            ):
                continue
            if not success:
                self.barrier = True
                continue
            backup_rel = None
            if before_exists:
                backup_name = f"{uuid.uuid4().hex}.bin"
                backup_path = self.store.backups_dir / backup_name
                _private_dir(backup_path.parent)
                if path.exists() and os.path.samefile(path, backup):
                    self.barrier = True
                    continue
                try:
                    os.link(backup, backup_path)
                except OSError:
                    shutil.copyfile(backup, backup_path)
                try:
                    os.chmod(backup_path, 0o600)
                except OSError:
                    pass
                backup_rel = backup_name
            self.files.append(
                {
                    "path": relative,
                    "before": {
                        "exists": before_exists,
                        "sha256": before_hash,
                        "backup": backup_rel,
                        "mode": original.mode,
                    },
                    "after": {
                        "exists": after_exists,
                        "sha256": after_hash,
                        "mode": after_mode,
                    },
                }
            )
        for parent in sorted(getattr(self, "parents", []), key=lambda item: len(item.parts), reverse=True):
            if parent.is_dir() and not parent.is_symlink():
                if not success:
                    self.barrier = True
                    continue
                self.files.append(
                    {
                        "path": parent.relative_to(self.store.root).as_posix(),
                        "before": {"exists": False, "sha256": None, "mode": None},
                        "after": {"exists": True, "kind": "directory", "sha256": None, "mode": None},
                    }
                )
        self.parents = []


class CheckpointStore:
    """A bounded checkpoint chain stored beside a saved session store."""

    VERSION = 1
    SNAPSHOT_MAX = 2 * 1024 * 1024

    def __init__(
        self,
        directory: Path,
        root: Path,
        session_id: str,
        keep: int = 20,
        max_mb: int = 50,
        session_path: Optional[Path] = None,
        expected_head: Optional[int] = None,
    ):
        self.directory = directory.absolute()
        self.root = root.resolve()
        self.session_id = session_id
        self.keep = max(1, int(keep))
        self.max_bytes = max(1, int(max_mb)) * 1024 * 1024
        self.manifest_path = directory / "manifest.json"
        self.lock_path = directory / "session.lock"
        self.backups_dir = directory / "backups"
        self.recovery_path = directory / "recovery.json"
        self.pending_path = directory / "pending.json"
        self.session_path = session_path.absolute() if session_path is not None else None
        self.expected_head = expected_head
        self.warning: Optional[str] = None

    def belongs_to_path(self) -> bool:
        self._check_storage()
        if not self.manifest_path.exists() or self.session_path is None:
            return True
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return data.get("session_path", str(self.session_path)) == str(self.session_path)
        except (OSError, ValueError, AttributeError):
            return True

    def session_lock(self) -> SessionLock:
        return SessionLock(self.lock_path)

    def _load(self) -> Dict[str, Any]:
        try:
            self._check_storage()
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty()
        except (OSError, ValueError) as exc:
            raise CheckpointError("Checkpoint data is corrupt.") from exc
        if (
            not isinstance(data, dict)
            or data.get("version") != self.VERSION
            or data.get("session_id") != self.session_id
            or data.get("root") != str(self.root)
            or not isinstance(data.get("records"), list)
            or (self.session_path is not None and data.get("session_path") != str(self.session_path))
        ):
            raise CheckpointError("Checkpoint data does not match this session or workspace.")
        try:
            ids = [record["id"] for record in data["records"]]
            if (
                any(type(value) is not int or value < 0 for value in ids)
                or ids != sorted(set(ids))
                or type(data["head"]) is not int
                or type(data["next"]) is not int
                or data["next"] <= data["head"]
                or (ids and data["head"] != ids[-1])
                or (not ids and data["head"] != -1)
            ):
                raise ValueError("invalid checkpoint chain")
            for index, record in enumerate(data["records"]):
                if (
                    record["snapshot"] != f"{record['id']}.json"
                    or not isinstance(record["files"], list)
                    or type(record["turn"]) is not int
                    or not isinstance(record["ts"], str)
                    or record.get("parent") != (ids[index - 1] if index else None)
                ):
                    raise ValueError("invalid checkpoint record")
                for mutation in record["files"]:
                    if not isinstance(mutation["path"], str):
                        raise ValueError("invalid checkpoint path")
                    for state in (mutation["before"], mutation["after"]):
                        if type(state["exists"]) is not bool or state.get("kind", "file") not in ("file", "directory"):
                            raise ValueError("invalid checkpoint state")
                        backup = state.get("backup")
                        if backup and (not isinstance(backup, str) or Path(backup).name != backup):
                            raise ValueError("invalid backup reference")
        except (KeyError, TypeError, ValueError) as exc:
            raise CheckpointError("Checkpoint data is corrupt.") from exc
        return data

    def _empty(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "session_id": self.session_id,
            "root": str(self.root),
            "session_path": str(self.session_path) if self.session_path is not None else None,
            "head": -1,
            "next": 0,
            "records": [],
        }

    def _check_storage(self) -> None:
        for path in (self.directory, self.backups_dir, self.manifest_path, self.pending_path, self.recovery_path):
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
                # System aliases such as /var -> /private/var are normalized by callers.
                raise CheckpointError("Checkpoint storage contains a symbolic link.")

    def _fresh(self, data: Dict[str, Any], head: Optional[int] = None) -> None:
        expected = self.expected_head if head is None else head
        if expected is not None and data["head"] != expected:
            raise CheckpointError("Checkpoint data does not match the current session. Reload the chat.")
        if self.session_path is not None and expected is not None and expected >= 0:
            try:
                saved = json.loads(self.session_path.read_text(encoding="utf-8"))
                if saved.get("checkpoint_session_id") != self.session_id or saved.get("checkpoint_head") != expected:
                    raise ValueError("session version changed")
            except (OSError, ValueError, AttributeError) as exc:
                raise CheckpointError("Checkpoint data does not match the current session. Reload the chat.") from exc

    def _pending_fresh(self, data: Dict[str, Any]) -> None:
        """A crashed turn may have saved its chat before replacing the index."""
        if self.session_path is None or self.expected_head is None:
            return
        saved = json.loads(self.session_path.read_text(encoding="utf-8"))
        pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
        if (
            saved.get("checkpoint_session_id") != self.session_id
            or saved.get("checkpoint_head") != self.expected_head
            or pending.get("head") not in (data["head"], data["head"] - 1)
            or self.expected_head not in (data["head"], data["next"], data["next"] - 1)
        ):
            raise CheckpointError("Checkpoint data does not match the current session. Reload the chat.")

    def has_recovery(self) -> bool:
        return self.recovery_path.exists()

    def ensure_base(self, snapshot: Dict[str, Any]) -> int:
        lock = self.session_lock()
        if not lock.acquire():
            raise CheckpointError("Workspace is busy. Try again when its file operations finish.")
        try:
            data = self._load()
            self._reconcile(data)
            self._cleanup_temporary()
            if self.pending_path.exists():
                self._pending_fresh(data)
            else:
                self._fresh(data)
            if data["head"] >= 0 and data["records"] and not self.pending_path.exists():
                return int(data["head"])
            from .tools.workspace import mutation_lock

            with mutation_lock(self.root):
                return self._base(data, snapshot)
        finally:
            lock.release()

    def _base(self, data: Dict[str, Any], snapshot: Dict[str, Any]) -> int:
        removed = data["records"]
        record_id = max(0, data["next"])
        snapshot = dict(snapshot, checkpoint_session_id=self.session_id, checkpoint_head=record_id)
        if len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) > self.SNAPSHOT_MAX:
            self.warning = "Checkpoint skipped: chat snapshot exceeds 2 MiB."
            data.update(records=[], head=-1, next=record_id + 1)
            self._save(data)
            self._remove_unreferenced(removed, [])
            self.pending_path.unlink(missing_ok=True)
            self.expected_head = -1
            return -1
        _private_dir(self.backups_dir)
        self._write_snapshot(record_id, snapshot)
        data.update(head=record_id, next=record_id + 1, records=[self._record(record_id, 0, [], None)])
        self._save(data)
        self._remove_unreferenced(removed, data["records"])
        self.pending_path.unlink(missing_ok=True)
        self.expected_head = record_id
        self._prune(data)
        return data["head"]

    def _record(self, record_id: int, turn: int, files: List[Dict[str, Any]], parent: Optional[int]) -> Dict[str, Any]:
        return {
            "id": record_id,
            "turn": turn,
            "ts": self._now(),
            "snapshot": f"{record_id}.json",
            "files": files,
            "barrier": False,
            "parent": parent,
        }

    def begin_turn(self, turn: int) -> TurnCapture:
        lock = self.session_lock()
        if not lock.acquire():
            raise CheckpointError("Session is busy. Try again when its file operations finish.")
        try:
            data = self._load()
            self._fresh(data)
            self._reconcile(data)
            self._cleanup_temporary()
            if self.has_recovery():
                raise CheckpointError("Checkpoint recovery is incomplete. Resolve the reported paths before rewinding.")
            if self.pending_path.exists():
                raise CheckpointError("Earlier checkpoints are unavailable: a tool change could not be recorded.")
            _write_json(self.pending_path, {"turn": turn, "head": data["head"]})
            return TurnCapture(self, lock, turn)
        except Exception:
            lock.release()
            raise

    def finish_turn(
        self,
        capture: TurnCapture,
        snapshot: Dict[str, Any],
        commit_chat: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> tuple[int, Optional[str]]:
        if capture.finished:
            raise CheckpointError("Checkpoint turn was already finalized.")
        try:
            data = self._load()
            self._fresh(data)
            if data["head"] < 0:
                data["records"] = []
            record_id = int(data["next"])
            snapshot = dict(snapshot, checkpoint_session_id=self.session_id, checkpoint_head=record_id)
            snapshot_size = len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
            warning = None
            if snapshot_size > self.SNAPSHOT_MAX:
                self._remove_record_files_list(data["records"])
                data.update({"records": [], "head": -1, "next": record_id + 1})
                self._save(data)
                if commit_chat is not None:
                    commit_chat(dict(snapshot, checkpoint_head=-1))
                self._remove_unreferenced([], [])
                self.pending_path.unlink(missing_ok=True)
                capture.finished = True
                return -1, "Checkpoint skipped: chat snapshot exceeds 2 MiB."
            self._write_snapshot(record_id, snapshot)
            records = data["records"]
            removed = []
            if capture.barrier:
                removed, records = records, []
                data["barrier_floor"] = record_id
                warning = "Earlier checkpoints are unavailable: a tool change could not be recorded."
            records.append(
                self._record(
                    record_id,
                    capture.turn,
                    [] if capture.barrier else capture.files,
                    records[-1]["id"] if records else None,
                )
            )
            data["head"] = record_id
            data["next"] = record_id + 1
            data["records"] = records
            if commit_chat is not None:
                commit_chat(snapshot)
            self._save(data)
            self.expected_head = record_id
            self._remove_unreferenced(removed, records)
            self._prune(data)
            if data["head"] != record_id and commit_chat is not None:
                commit_chat(dict(snapshot, checkpoint_head=data["head"]))
            self.expected_head = data["head"]
            self.pending_path.unlink(missing_ok=True)
            capture.finished = True
            return data["head"], warning
        finally:
            capture.lock.release()

    def abandon_turn(self, capture: TurnCapture) -> None:
        if not capture.finished:
            capture.finished = True
            capture.lock.release()

    def reset(self, snapshot: Dict[str, Any]) -> int:
        lock = self.session_lock()
        if not lock.acquire():
            raise CheckpointError("Session is busy. Try again when its file operations finish.")
        try:
            data = self._load()
            self._fresh(data)
            self._reconcile(data)
            from .tools.workspace import mutation_lock

            with mutation_lock(self.root):
                return self._base(data, snapshot)
        finally:
            lock.release()

    def list_records(self, head: int) -> List[Dict[str, Any]]:
        data = self._load()
        self._fresh(data, head)
        return data["records"]

    def target_snapshot(self, record_id: int) -> Dict[str, Any]:
        data = self._load()
        for record in data["records"]:
            if int(record["id"]) == int(record_id):
                try:
                    path = self.directory / record["snapshot"]
                    if path.is_symlink() or path.stat().st_size > self.SNAPSHOT_MAX:
                        raise ValueError("invalid snapshot")
                    snapshot = json.loads(path.read_text(encoding="utf-8"))
                    if (
                        not isinstance(snapshot, dict)
                        or snapshot.get("checkpoint_session_id") != self.session_id
                        or snapshot.get("checkpoint_head") != record_id
                        or not isinstance(snapshot.get("history"), list)
                    ):
                        raise ValueError("snapshot binding changed")
                    return snapshot
                except (OSError, ValueError) as exc:
                    raise CheckpointError(f"Checkpoint #{record_id} is unavailable.") from exc
        raise CheckpointError(f"Checkpoint #{record_id} is unavailable.")

    def preview(self, target: int, head: int) -> Dict[str, Any]:
        if self.has_recovery():
            raise CheckpointError("Checkpoint recovery is incomplete. Resolve the reported paths before rewinding.")
        if self.pending_path.exists():
            raise CheckpointError("Earlier checkpoints are unavailable: a tool change could not be recorded.")
        data = self._load()
        self._fresh(data, head)
        records = [record for record in data["records"] if int(record["id"]) <= int(head)]
        ids = [int(record["id"]) for record in records]
        if target not in ids:
            if target < data.get("barrier_floor", -1):
                raise CheckpointError("Earlier checkpoints are unavailable: a tool change could not be recorded.")
            raise CheckpointError(f"Checkpoint #{target} is unavailable.")
        target_index = ids.index(target)
        head_index = ids.index(int(head)) if int(head) in ids else -1
        if head_index < 0:
            raise CheckpointError("Checkpoint data does not match the current session.")
        if target_index == head_index:
            raise CheckpointError(f"Already at checkpoint #{target}.")
        crossed = records[target_index + 1 : head_index + 1]
        if any(record.get("barrier") for record in crossed):
            raise CheckpointError("Earlier checkpoints are unavailable: a tool change could not be recorded.")
        grouped: Dict[str, Dict[str, Any]] = {}
        for record in crossed:
            for mutation in record.get("files", []):
                rel = str(mutation.get("path") or "")
                if rel not in grouped:
                    grouped[rel] = {"path": rel, "before": mutation["before"], "after": mutation["after"]}
                else:
                    previous = grouped[rel]["after"]
                    if not self._same_state(previous, mutation["before"]):
                        raise CheckpointError(f"Cannot rewind: {rel} changed outside the recorded history.")
                    grouped[rel]["after"] = mutation["after"]
                self._backup(mutation["before"], rel)
        plan = []
        for rel, change in grouped.items():
            path = self._resolve_file(rel)
            before, after = change["before"], change["after"]
            if not self._same_state(self._file_state(path), after):
                raise CheckpointError(f"Cannot rewind: {rel} changed outside the recorded history.")
            backup = self._backup(before, rel)
            if not path.parent.is_dir() or not os.access(path.parent, os.W_OK | os.X_OK):
                raise CheckpointError(f"Cannot rewind: {rel} is not writable.")
            if after.get("kind") == "directory":
                allowed = {self.root / name for name in grouped}
                if any(child not in allowed for child in path.iterdir()):
                    raise CheckpointError(f"Cannot rewind: {rel} changed outside the recorded history.")
            if self._same_state(before, after):
                continue
            plan.append({"path": rel, "absolute": path, "before": before, "after": after, "backup": backup})
        plan.sort(key=lambda item: (item["after"].get("kind") == "directory", -len(Path(item["path"]).parts)))
        snapshot = self.target_snapshot(target)
        current_snapshot = self.target_snapshot(head)
        if snapshot.get("plan", {}) != current_snapshot.get("plan", {}):
            raise CheckpointError("Earlier checkpoints are unavailable: a tool change could not be recorded.")
        if self.session_path is not None:
            saved = json.loads(self.session_path.read_text(encoding="utf-8"))
            if saved.get("plan", {}) != current_snapshot.get("plan", {}):
                raise CheckpointError("Earlier checkpoints are unavailable: a tool change could not be recorded.")
        return {
            "plan": plan,
            "snapshot": snapshot,
            "dropped_turns": len(crossed),
            "restore": [item["path"] for item in plan if item["before"]["exists"]],
            "remove": [item["path"] for item in plan if not item["before"]["exists"]],
        }

    @staticmethod
    def _same_state(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        if left.get("exists") != right.get("exists"):
            return False
        if not left.get("exists"):
            return True
        if left.get("kind", "file") != right.get("kind", "file"):
            return False
        return left.get("kind") == "directory" or (
            left.get("sha256") == right.get("sha256") and left.get("mode") == right.get("mode")
        )

    @staticmethod
    def _file_state(path: Path) -> Dict[str, Any]:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return {"exists": False, "sha256": None, "mode": None}
        if stat.S_ISREG(info.st_mode):
            return {"exists": True, "sha256": _hash_file(path), "mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISDIR(info.st_mode):
            return {"exists": True, "kind": "directory", "sha256": None, "mode": None}
        raise CheckpointError(f"Cannot rewind: {path.name} changed outside the recorded history.")

    def _backup(self, state: Dict[str, Any], relative: str) -> Optional[Path]:
        if not state.get("exists") or state.get("kind") == "directory":
            return None
        name = state.get("backup")
        if not isinstance(name, str) or Path(name).name != name:
            raise CheckpointError(f"Cannot rewind: backup for {relative} is missing.")
        path = self.backups_dir / name
        if not path.is_file() or path.is_symlink() or _hash_file(path) != state.get("sha256"):
            raise CheckpointError(f"Cannot rewind: backup for {relative} is missing.")
        target = self._resolve_file(relative)
        if target.is_file() and os.path.samefile(path, target):
            raise CheckpointError(f"Cannot rewind: backup for {relative} is missing.")
        return path

    def rewind(
        self,
        target: int,
        head: int,
        commit_chat: Callable[[Dict[str, Any]], None],
        source_snapshot: Optional[Dict[str, Any]] = None,
        before_apply: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        from .tools.workspace import mutation_lock

        lock = self.session_lock()
        if not lock.acquire():
            raise CheckpointError("Workspace is busy. Try again when its file operations finish.")
        staged: List[Dict[str, Any]] = []
        applied: List[Dict[str, Any]] = []
        committed = False
        chat_attempted = False
        manifest_attempted = False
        try:
            with mutation_lock(self.root):
                self._reconcile(self._load())
                result = self.preview(target, head)
                source_data = self._load()
                for item in result["plan"]:
                    path = item["absolute"]
                    self._check_current(item)
                    current = self._file_state(path)
                    if current["exists"] and current.get("kind") != "directory":
                        name = f"recovery-{uuid.uuid4().hex}.bin"
                        staged_path = self.backups_dir / name
                        shutil.copyfile(path, staged_path)
                        os.chmod(staged_path, 0o600)
                        current.update({"backup": name, "sha256": _hash_file(staged_path)})
                    staged.append({"path": item["path"], "state": current, "target": item["before"]})
                source = source_snapshot or self.target_snapshot(head)
                journal = {
                    "version": self.VERSION,
                    "session_id": self.session_id,
                    "root": str(self.root),
                    "source": head,
                    "target": target,
                    "files": staged,
                    "chat": source,
                    "target_chat": result["snapshot"],
                    "manifest": source_data,
                }
                _write_json(self.recovery_path, journal)
                if self._owned_bytes() > self.max_bytes:
                    self._discard_recovery(journal)
                    raise CheckpointError("Cannot rewind: checkpoint storage budget is insufficient for recovery.")
                if before_apply is not None:
                    try:
                        before_apply()
                    except Exception:
                        self._discard_recovery(journal)
                        raise
                try:
                    for item in result["plan"]:
                        self._check_current(item)
                        applied.append(item)
                        self._apply_file_state(item["absolute"], item["before"], item["backup"])
                    chat_attempted = True
                    commit_chat(result["snapshot"])
                    data = dict(source_data)
                    data["head"] = target
                    target_index = next(i for i, rec in enumerate(data["records"]) if int(rec["id"]) == target)
                    removed = data["records"][target_index + 1 :]
                    data["records"] = data["records"][: target_index + 1]
                    manifest_attempted = True
                    self._save(data)
                    self.expected_head = target
                    committed = True
                except Exception as exc:
                    if not applied and not chat_attempted:
                        self._discard_recovery(journal)
                        raise
                    failed = []
                    originals = {item["path"]: item for item in staged}
                    for item in reversed(applied):
                        try:
                            actual = self._file_state(self._resolve_file(item["path"]))
                            if self._same_state(actual, originals[item["path"]]["state"]):
                                continue
                            if not self._same_state(actual, item["before"]):
                                raise CheckpointError("path changed during rewind")
                            self._restore_recovery(originals[item["path"]])
                        except Exception:
                            failed.append(item["path"])
                    if chat_attempted:
                        try:
                            commit_chat(source)
                        except Exception:
                            failed.append("chat")
                    if manifest_attempted:
                        try:
                            self._save(source_data)
                        except Exception:
                            failed.append("checkpoint index")
                    self.expected_head = head
                    if failed:
                        raise CheckpointError(
                            f"Rewind failed. Manual recovery is required for {', '.join(failed)}. Recovery record: {self.recovery_path}"
                        ) from exc
                    self._discard_recovery(journal)
                    raise CheckpointError("Rewind failed. The previous workspace and chat were restored.") from exc
                self._discard_recovery(journal)
                self._remove_unreferenced(removed, data["records"])
                return result
        finally:
            # Preflight/staging errors have not changed the workspace. A committed
            # journal remains available if housekeeping fails after the commit.
            if not self.has_recovery() and not committed:
                for item in staged:
                    name = item["state"].get("backup")
                    if name:
                        (self.backups_dir / name).unlink(missing_ok=True)
            lock.release()

    def reconcile(self) -> None:
        """Inspect a crash journal without writing any workspace path."""
        if not self.has_recovery():
            return
        from .tools.workspace import mutation_lock

        lock = self.session_lock()
        if not lock.acquire():
            raise CheckpointError("Workspace is busy. Try again when its file operations finish.")
        try:
            with mutation_lock(self.root):
                self._reconcile(self._load())
        finally:
            lock.release()

    def _reconcile(self, data: Dict[str, Any]) -> None:
        if not self.has_recovery():
            return
        message = "Checkpoint recovery is incomplete. Resolve the reported paths before rewinding."
        try:
            journal = json.loads(self.recovery_path.read_text(encoding="utf-8"))
            if (
                journal["version"] != self.VERSION
                or journal["session_id"] != self.session_id
                or journal["root"] != str(self.root)
            ):
                raise ValueError("invalid recovery binding")
            saved = json.loads(self.session_path.read_text(encoding="utf-8")) if self.session_path else None
            fields = ("history", "plan", "checkpoint_session_id", "checkpoint_head")
            source = data["head"] == journal["source"] and (
                saved is None or all(saved.get(key) == journal["chat"].get(key) for key in fields)
            )
            target = data["head"] == journal["target"] and (
                saved is None or all(saved.get(key) == journal["target_chat"].get(key) for key in fields)
            )
            for item in journal["files"]:
                actual = self._file_state(self._resolve_file(item["path"]))
                source = source and self._same_state(actual, item["state"])
                target = target and self._same_state(actual, item["target"])
            if source or target:
                self._discard_recovery(journal)
                self._remove_unreferenced([], data["records"])
                return
        except (OSError, ValueError, TypeError, KeyError, AttributeError, CheckpointError):
            pass
        raise CheckpointError(f"{message} Recovery record: {self.recovery_path}")

    def _discard_recovery(self, journal: Dict[str, Any]) -> None:
        self.recovery_path.unlink(missing_ok=True)
        for item in journal["files"]:
            name = item["state"].get("backup")
            if isinstance(name, str) and Path(name).name == name and name.startswith("recovery-"):
                (self.backups_dir / name).unlink(missing_ok=True)

    def _apply_file_state(self, path: Path, state: Dict[str, Any], backup: Optional[Path]) -> None:
        if state["exists"]:
            if state.get("kind") == "directory":
                path.mkdir(exist_ok=True)
                return
            if backup is None:
                raise CheckpointError("Checkpoint backup is missing.")
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            os.close(fd)
            temp = Path(temp_name)
            try:
                shutil.copyfile(backup, temp)
                os.chmod(temp, int(state["mode"]) if state.get("mode") is not None else 0o600)
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
        elif path.exists():
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()

    def _restore_recovery(self, item: Dict[str, Any]) -> None:
        path = self._resolve_file(item["path"])
        state = item["state"]
        backup = self.backups_dir / state["backup"] if state.get("backup") else None
        self._apply_file_state(path, state, backup)

    def _resolve_file(self, relative: str) -> Path:
        from .const import get_sessions_dir
        from .tools.workspace import (
            BACKUP_DIR_NAME,
            is_inside_plans_root,
            protected_reason,
        )

        path = self.root / relative
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise CheckpointError("Checkpoint path is invalid.")
        if path == self.root:
            raise CheckpointError("Checkpoint path is protected.")
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise CheckpointError("Checkpoint path is outside the workspace.") from exc
        if protected_reason(path, self.root) or BACKUP_DIR_NAME in Path(relative).parts or is_inside_plans_root(path):
            raise CheckpointError("Checkpoint path is protected.")
        if path == self.directory or self.directory in path.parents:
            raise CheckpointError("Checkpoint path is protected.")
        storage_root = (
            self.session_path.parent
            if self.session_path is not None
            else next(
                (parent.parent for parent in self.directory.parents if parent.name == "checkpoints"), self.directory
            )
        )
        if path == storage_root or storage_root in path.parents:
            raise CheckpointError("Checkpoint path is protected.")
        sessions_root = get_sessions_dir().resolve()
        if path == sessions_root or sessions_root in path.parents:
            raise CheckpointError("Checkpoint path is protected.")
        for parent in (path, *path.parents):
            if parent == self.root:
                break
            if parent.is_symlink():
                raise CheckpointError("Checkpoint path contains a symbolic link.")
            if parent != path and parent.exists() and not parent.is_dir():
                raise CheckpointError("Checkpoint parent is not a directory.")
        return path

    def _check_current(self, item: Dict[str, Any]) -> None:
        path = self._resolve_file(item["path"])
        state = item["after"]
        if not self._same_state(self._file_state(path), state):
            raise CheckpointError(f"Cannot rewind: {item['path']} changed outside the recorded history.")

    def _write_snapshot(self, record_id: int, snapshot: Dict[str, Any]) -> None:
        _write_json(self.directory / f"{record_id}.json", snapshot)

    def _save(self, data: Dict[str, Any]) -> None:
        _write_json(self.manifest_path, data)

    def _prune(self, data: Dict[str, Any]) -> None:
        self._cleanup_temporary()
        records = data["records"]
        removed = []
        while len(records) > self.keep:
            removed.append(records.pop(0))
            if records:
                records[0]["files"] = []
                records[0]["barrier"] = False
                records[0]["parent"] = None
        while records and self._retained_bytes(data) > self.max_bytes:
            removed.append(records.pop(0))
            if records:
                records[0]["files"] = []
                records[0]["barrier"] = False
                records[0]["parent"] = None
        if not records:
            data["head"] = -1
        self._save(data)
        self.expected_head = data["head"]
        self._remove_unreferenced(removed, records)

    def _cleanup_temporary(self) -> None:
        """Remove interrupted JSON writes only while the caller owns the session lock."""
        if self.has_recovery():
            return
        pattern = re.compile(r"\.(?:manifest|pending|recovery|[0-9]+)\.json\.[a-z0-9_]{8}\.tmp")
        try:
            for path in self.directory.glob(".*.tmp"):
                if pattern.fullmatch(path.name):
                    path.unlink()
        except OSError as exc:
            raise CheckpointError(
                "Checkpoint temporary files could not be cleaned; storage budget cannot be verified."
            ) from exc

    def _retained_bytes(self, data: Dict[str, Any]) -> int:
        paths = set()
        for record in data["records"]:
            paths.add(self.directory / record["snapshot"])
            for mutation in record["files"]:
                name = mutation["before"].get("backup")
                if name:
                    paths.add(self.backups_dir / name)
        return len(json.dumps(data, ensure_ascii=False).encode("utf-8")) + sum(path.stat().st_size for path in paths)

    def _owned_bytes(self) -> int:
        return sum(
            path.stat().st_size
            for path in self.directory.rglob("*")
            if path.is_file() and not path.is_symlink() and path != self.lock_path
        )

    def _remove_unreferenced(self, removed: List[Dict[str, Any]], retained: List[Dict[str, Any]]) -> None:
        self._remove_record_files_list(removed)
        referenced = {record.get("snapshot") for record in retained}
        for path in self.directory.glob("*.json"):
            if path.name not in referenced and path not in (self.manifest_path, self.recovery_path, self.pending_path):
                path.unlink(missing_ok=True)
        backups = {mutation["before"].get("backup") for record in retained for mutation in record["files"]}
        if not self.has_recovery():
            for path in self.backups_dir.glob("*.bin"):
                if path.name not in backups:
                    path.unlink(missing_ok=True)

    def _remove_record_files(self, record: Dict[str, Any]) -> None:
        self._remove_record_files_list([record])

    def _remove_record_files_list(self, records: List[Dict[str, Any]]) -> None:
        for record in records:
            (self.directory / str(record.get("snapshot", ""))).unlink(missing_ok=True)
            self._remove_mutation_backups(record)

    def _remove_mutation_backups(self, record: Dict[str, Any]) -> None:
        for mutation in record.get("files", []):
            backup = mutation.get("before", {}).get("backup")
            if backup and Path(str(backup)).name == backup:
                (self.backups_dir / str(backup)).unlink(missing_ok=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


def current_capture() -> Optional[TurnCapture]:
    return _ACTIVE_CAPTURE.get()


def record_mutation(entry: Any, success: bool) -> None:
    capture = current_capture()
    if capture is not None:
        try:
            capture.record(entry, success)
        except (OSError, ValueError, CheckpointError):
            capture.barrier = True


def checkpoint_audit(
    event: str, session_id: str, target: int, result: str, restored: int = 0, removed: int = 0
) -> None:
    """Append bounded checkpoint metadata using the existing private audit log."""
    from . import const
    from .config import cfg
    from .redaction import redact_text
    from .runtime import current_config

    if not current_config(cfg).get("TOOL_AUDIT", False):
        return
    try:
        payload = {
            "ts": CheckpointStore._now(),
            "event": f"checkpoint.{event}",
            "session": redact_text(session_id),
            "target": target,
            "result": result,
            "restored": restored,
            "removed": removed,
        }
        path = Path(const.TOOL_AUDIT_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


__all__ = ["CheckpointError", "CheckpointStore", "TurnCapture", "current_capture", "record_mutation"]
