"""Behavioral tests for persistent checkpoints and guarded rewind."""

import json
import os
import subprocess
import sys

import pytest

from yaicli.checkpoints import CheckpointError, CheckpointStore
from yaicli.tools import workspace


def snapshot(text="start"):
    return {"title": "Trip", "history": [{"role": "user", "content": text}], "checkpoint_head": -1}


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return CheckpointStore(tmp_path / "sessions" / "checkpoints" / "test", root, "test")


def mutate(store, path, content):
    capture = store.begin_turn(len(store.list_records(store._load()["head"])))
    plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(path)}, root=store.root)
    assert plan.denial is None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    capture.record(plan.build_undo_entry(), True)
    return store.finish_turn(capture, snapshot(content))[0]


def test_cross_process_restore(store):
    path = store.root / "trip.md"
    path.write_text("initial")
    store.ensure_base(snapshot())
    head = mutate(store, path, "changed")
    program = (
        "import json; from pathlib import Path; "
        "from yaicli.checkpoints import CheckpointStore; "
        f"s=CheckpointStore(Path({str(store.directory)!r}),Path({str(store.root)!r}),'test'); "
        "r=s.rewind(0,1,lambda data: None); "
        f"print(json.dumps({{'value':Path({str(path)!r}).read_text(),'dropped':r['dropped_turns']}}))"
    )
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"value": "initial", "dropped": 1}
    assert store._load()["head"] == 0
    assert head == 1


def test_rewind_repeated_path_restores_first_version_and_mode(store):
    path = store.root / "trip.md"
    path.write_text("initial")
    path.chmod(0o640)
    store.ensure_base(snapshot())
    mutate(store, path, "second")
    head = mutate(store, path, "third")
    committed = []
    store.rewind(0, head, committed.append)
    assert path.read_text() == "initial"
    assert path.stat().st_mode & 0o777 == 0o640
    assert committed[0]["history"][0]["content"] == "start"
    lock = store.session_lock()
    assert lock.acquire()
    lock.release()


def test_new_file_is_removed(store):
    store.ensure_base(snapshot())
    path = store.root / "packing.md"
    head = mutate(store, path, "new")
    store.rewind(0, head, lambda data: None)
    assert not path.exists()


def test_external_edit_refuses_entire_rewind(store):
    store.ensure_base(snapshot())
    a, b = store.root / "a", store.root / "b"
    mutate(store, a, "a")
    head = mutate(store, b, "b")
    b.write_text("external")
    with pytest.raises(CheckpointError, match="changed outside"):
        store.rewind(0, head, lambda data: None)
    assert a.read_text() == "a"
    assert b.read_text() == "external"
    assert store._load()["head"] == head


def test_external_edit_between_recorded_writes_refuses(store):
    path = store.root / "trip.md"
    path.write_text("original")
    store.ensure_base(snapshot())
    mutate(store, path, "model")
    path.write_text("human")
    head = mutate(store, path, "model again")
    with pytest.raises(CheckpointError, match="changed outside"):
        store.preview(0, head)


def test_missing_backup_refuses(store):
    path = store.root / "trip.md"
    path.write_text("original")
    store.ensure_base(snapshot())
    head = mutate(store, path, "changed")
    for backup in store.backups_dir.glob("*.bin"):
        backup.unlink()
    with pytest.raises(CheckpointError, match="backup for trip.md is missing"):
        store.preview(0, head)


def test_symbolic_link_parent_is_refused(store):
    store.ensure_base(snapshot())
    path = store.root / "trip.md"
    head = mutate(store, path, "changed")
    path.unlink()
    path.symlink_to(store.root / "other")
    with pytest.raises(CheckpointError):
        store.preview(0, head)


def test_unsupported_tool_is_a_barrier(store):
    store.ensure_base(snapshot())
    capture = store.begin_turn(1)
    capture.barrier = True
    head, _ = store.finish_turn(capture, snapshot("external shell call"))
    with pytest.raises(CheckpointError, match="could not be recorded"):
        store.preview(0, head)


def test_abandoned_turn_prevents_rewind(store):
    store.ensure_base(snapshot())
    mutate(store, store.root / "trip.md", "changed")
    capture = store.begin_turn(2)
    store.abandon_turn(capture)
    with pytest.raises(CheckpointError, match="could not be recorded"):
        store.preview(0, 1)


def test_intermediate_failure_restores_files_and_chat(store, monkeypatch):
    store.ensure_base(snapshot())
    a, b = store.root / "a", store.root / "b"
    mutate(store, a, "a")
    head = mutate(store, b, "b")
    original = store._apply_file_state
    count = 0

    def fail_second(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected disk failure")
        return original(*args)

    monkeypatch.setattr(store, "_apply_file_state", fail_second)
    commits = []
    with pytest.raises(CheckpointError, match="previous workspace and chat were restored"):
        store.rewind(0, head, commits.append)
    assert a.read_text() == "a"
    assert b.read_text() == "b"
    assert commits == []  # Chat persistence was never attempted before the file failure.
    assert not store.has_recovery()


def test_retention_leaves_valid_chain(store):
    store.keep = 2
    store.ensure_base(snapshot())
    path = store.root / "trip.md"
    mutate(store, path, "one")
    head = mutate(store, path, "two")
    records = store.list_records(head)
    assert [r["id"] for r in records] == [1, 2]
    store.rewind(1, head, lambda data: None)
    assert path.read_text() == "one"


def test_snapshot_limit_does_not_write_oversized_snapshot(store):
    store.ensure_base(snapshot())
    capture = store.begin_turn(1)
    head, warning = store.finish_turn(capture, snapshot("x" * (2 * 1024 * 1024 + 1)))
    assert head == -1
    assert "exceeds 2 MiB" in warning
    assert not (store.directory / "1.json").exists()


def test_private_files(store):
    store.ensure_base(snapshot())
    if os.name == "posix":
        assert store.directory.stat().st_mode & 0o777 == 0o700
        assert (store.directory / "0.json").stat().st_mode & 0o777 == 0o600


def test_same_session_lock_refuses_other_process(store):
    store.ensure_base(snapshot())
    lock = store.session_lock()
    assert lock.acquire()
    try:
        program = (
            "from pathlib import Path; from yaicli.checkpoint_lock import SessionLock; "
            f"lock=SessionLock(Path({str(store.lock_path)!r})); "
            "print(lock.acquire())"
        )
        result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True)
        assert result.stdout.strip() == "False"
    finally:
        lock.release()


def test_stale_head_cannot_preview_or_advance(store):
    store.ensure_base(snapshot())
    stale = CheckpointStore(store.directory, store.root, store.session_id, expected_head=0)
    mutate(store, store.root / "trip.md", "new")
    with pytest.raises(CheckpointError, match="Reload the chat"):
        stale.preview(0, 0)
    with pytest.raises(CheckpointError, match="Reload the chat"):
        stale.begin_turn(1)


def test_same_thread_cannot_open_a_second_writer(store):
    store.ensure_base(snapshot())
    capture = store.begin_turn(1)
    try:
        with pytest.raises(CheckpointError, match="busy"):
            store.begin_turn(1)
    finally:
        store.abandon_turn(capture)


def test_mode_only_external_change_is_conflict(store):
    path = store.root / "trip.md"
    store.ensure_base(snapshot())
    head = mutate(store, path, "new")
    path.chmod(0o700)
    with pytest.raises(CheckpointError, match="changed outside"):
        store.preview(0, head)


def test_intermediate_backup_is_checked_even_when_not_final_restore(store):
    path = store.root / "trip.md"
    path.write_text("first")
    store.ensure_base(snapshot())
    mutate(store, path, "second")
    head = mutate(store, path, "third")
    record = store._load()["records"][-1]
    (store.backups_dir / record["files"][0]["before"]["backup"]).unlink()
    with pytest.raises(CheckpointError, match="backup.*missing"):
        store.preview(0, head)


def test_corrupt_snapshot_reference_is_rejected(store):
    store.ensure_base(snapshot())
    data = store._load()
    data["records"][0]["snapshot"] = "../outside.json"
    store._save(data)
    with pytest.raises(CheckpointError, match="corrupt"):
        store.list_records(0)


def test_implicit_parent_directories_are_removed_only_when_empty(store):
    store.ensure_base(snapshot())
    path = store.root / "new" / "nested" / "trip.md"
    capture = store.begin_turn(1)
    plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(path)}, root=store.root)
    capture.prepare(plan.build_undo_entry())
    path.parent.mkdir(parents=True)
    path.write_text("new")
    capture.record(plan.build_undo_entry(), True)
    head, _ = store.finish_turn(capture, snapshot("new"))
    (path.parent / "external").write_text("keep")
    with pytest.raises(CheckpointError, match="changed outside"):
        store.preview(0, head)
    (path.parent / "external").unlink()
    store.rewind(0, head, lambda data: None)
    assert not (store.root / "new").exists()


def test_budget_can_evict_an_oversized_single_snapshot(store):
    store.max_bytes = 1024 * 1024
    store.ensure_base(snapshot())
    capture = store.begin_turn(1)
    head, _ = store.finish_turn(capture, snapshot("x" * (1500 * 1024)))
    assert head == -1
    assert store._owned_bytes() <= store.max_bytes
    assert store._load()["records"] == []


def test_keep_one_means_one_baseline_with_no_backups(store):
    store.keep = 1
    path = store.root / "trip.md"
    path.write_text("old")
    store.ensure_base(snapshot())
    head = mutate(store, path, "new")
    assert len(store.list_records(head)) == 1
    assert store.list_records(head)[0]["files"] == []
    assert list(store.backups_dir.glob("*.bin")) == []


def test_success_and_compensation_leave_no_recovery_backups(store, monkeypatch):
    path = store.root / "trip.md"
    path.write_text("old")
    store.ensure_base(snapshot())
    head = mutate(store, path, "new")
    store.rewind(0, head, lambda data: None)
    assert list(store.backups_dir.glob("*.bin")) == []


def test_failed_chat_commit_compensates_files_and_manifest(store):
    path = store.root / "trip.md"
    path.write_text("old")
    store.ensure_base(snapshot())
    head = mutate(store, path, "new")
    committed = []

    def commit(data):
        committed.append(data)
        if data["checkpoint_head"] == 0:
            raise OSError("chat save failed")

    with pytest.raises(CheckpointError, match="previous workspace and chat were restored"):
        store.rewind(0, head, commit)
    assert path.read_text() == "new"
    assert store._load()["head"] == head
    assert committed[-1]["checkpoint_head"] == head
    assert not store.has_recovery()


def test_manifest_failure_compensates_chat_and_workspace(store, monkeypatch):
    store.ensure_base(snapshot())
    path = store.root / "trip.md"
    head = mutate(store, path, "new")
    save = store._save

    def fail_target(data):
        if data["head"] == 0:
            raise OSError("index save failed")
        save(data)

    monkeypatch.setattr(store, "_save", fail_target)
    committed = []
    with pytest.raises(CheckpointError, match="previous workspace and chat were restored"):
        store.rewind(0, head, committed.append)
    assert path.read_text() == "new"
    assert store._load()["head"] == head
    assert committed[-1]["checkpoint_head"] == head


def test_failed_compensation_preserves_recovery_until_complete_state(store, monkeypatch):
    store.ensure_base(snapshot())
    path = store.root / "trip.md"
    head = mutate(store, path, "new")
    apply = store._apply_file_state

    def fail_restore(path, state, backup):
        if state["exists"]:
            raise OSError("cannot restore source")
        return apply(path, state, backup)

    monkeypatch.setattr(store, "_apply_file_state", fail_restore)

    def bad_commit(data):
        if data["checkpoint_head"] == 0:
            raise OSError("chat failed")

    with pytest.raises(CheckpointError, match="Manual recovery"):
        store.rewind(0, head, bad_commit)
    assert store.has_recovery()
    with pytest.raises(CheckpointError, match="recovery is incomplete"):
        store.reconcile()
    assert not path.exists()  # Startup inspection did not mutate workspace files.
    path.write_text("new")
    path.chmod(0o644)
    store.reconcile()
    assert not store.has_recovery()


def test_prewrite_conflict_does_not_save_chat_or_overwrite_external_file(store, monkeypatch):
    store.ensure_base(snapshot())
    path = store.root / "trip.md"
    head = mutate(store, path, "new")

    def edit_after_preview():
        path.write_text("external")

    committed = []
    with pytest.raises(CheckpointError, match="changed outside"):
        store.rewind(0, head, committed.append, before_apply=edit_after_preview)
    assert path.read_text() == "external"
    assert committed == []
    assert store._load()["head"] == head
    assert not store.has_recovery()


def test_committed_target_journal_is_cleaned_without_workspace_writes(store, monkeypatch):
    store.ensure_base(snapshot())
    path = store.root / "trip.md"
    head = mutate(store, path, "new")
    discard = store._discard_recovery
    monkeypatch.setattr(store, "_discard_recovery", lambda journal: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError, match="crash"):
        store.rewind(0, head, lambda data: None)
    assert store.has_recovery()
    assert not path.exists()
    monkeypatch.setattr(store, "_discard_recovery", discard)
    monkeypatch.setattr(store, "_apply_file_state", lambda *args: pytest.fail("startup must only inspect"))
    store.reconcile()
    assert not store.has_recovery()
    assert store._load()["head"] == 0


def test_saved_chat_ahead_of_failed_turn_manifest_rebaselines_safely(store, monkeypatch):
    from yaicli.checkpoints import _write_json

    store.session_path = store.directory.parent / "saved.json"
    store.ensure_base(snapshot())
    _write_json(store.session_path, store.target_snapshot(0))
    capture = store.begin_turn(1)
    save = store._save
    monkeypatch.setattr(store, "_save", lambda data: (_ for _ in ()).throw(OSError("manifest failed")))
    with pytest.raises(OSError, match="manifest failed"):
        store.finish_turn(capture, snapshot("second"), lambda data: _write_json(store.session_path, data))
    monkeypatch.setattr(store, "_save", save)
    restored = CheckpointStore(
        store.directory, store.root, store.session_id, session_path=store.session_path, expected_head=1
    )
    saved = json.loads(store.session_path.read_text())
    head = restored.ensure_base(saved)
    _write_json(store.session_path, dict(saved, checkpoint_head=head))
    assert len(restored.list_records(head)) == 1
    assert restored.target_snapshot(head)["history"][0]["content"] == "second"
    assert not restored.pending_path.exists()


def test_root_and_internal_session_paths_are_rejected(store, monkeypatch):
    from yaicli import const

    with pytest.raises(CheckpointError, match="protected"):
        store._resolve_file(".")
    monkeypatch.setattr(const, "get_sessions_dir", lambda: store.root / ".yaicli" / "sessions")
    with pytest.raises(CheckpointError, match="protected"):
        store._resolve_file(".yaicli/sessions/other-project/chat.json")


def test_checkpoint_numbers_do_not_recur_after_rewind(store):
    store.ensure_base(snapshot())
    head = mutate(store, store.root / "trip.md", "one")
    store.rewind(0, head, lambda data: None)
    assert mutate(store, store.root / "trip.md", "two") > head


def test_interrupted_json_temporary_files_are_cleaned_before_budget_check(store):
    import tempfile
    from pathlib import Path

    store.max_bytes = 1024 * 1024
    store.ensure_base(snapshot())
    descriptor, name = tempfile.mkstemp(prefix=".manifest.json.", suffix=".tmp", dir=store.directory)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(b"x" * (2 * 1024 * 1024))
    unrelated = store.directory / ".unrelated.tmp"
    unrelated.write_text("leave alone")
    store.ensure_base(snapshot())
    assert not Path(name).exists()
    assert unrelated.read_text() == "leave alone"
    assert store._owned_bytes() <= store.max_bytes


def test_recovery_preserves_temporary_files_until_reconciliation(store):
    store.ensure_base(snapshot())
    temporary = store.directory / ".recovery.json.abc12345.tmp"
    temporary.write_text("possible recovery evidence")
    store.recovery_path.write_text("unresolved")
    lock = store.session_lock()
    assert lock.acquire()
    try:
        store._cleanup_temporary()
    finally:
        lock.release()
    assert temporary.exists()


def test_temporary_cleanup_failure_reports_unverified_budget(store, monkeypatch):
    from pathlib import Path

    store.ensure_base(snapshot())
    temporary = store.directory / ".pending.json.abc12345.tmp"
    temporary.write_text("unfinished")
    unlink = Path.unlink

    def fail_owned(path, *args, **kwargs):
        if path == temporary:
            raise PermissionError("not writable")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_owned)
    with pytest.raises(CheckpointError, match="storage budget cannot be verified"):
        store.ensure_base(snapshot())
    assert temporary.exists()
    lock = store.session_lock()
    assert lock.acquire()  # Cleanup failure also releases the session writer lock.
    lock.release()
