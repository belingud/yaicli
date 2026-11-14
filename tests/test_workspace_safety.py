"""Tests for workspace write confinement, backups and /undo (v0.21 K11)."""

import importlib.util
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yaicli.cmd_handler import CMD_UNDO, CmdHandler
from yaicli.schemas import ToolCall
from yaicli.tools import execute_tool_call, output_history, workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDIN_DIR = REPO_ROOT / "yaicli" / "functions" / "buildin"
_FAKE_CFG = {"SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False}


@pytest.fixture(autouse=True)
def isolate_undo_and_env(monkeypatch):
    """Every test starts with an empty undo stack and no ambient workspace env."""
    workspace.reset_undo()
    output_history.reset()
    monkeypatch.delenv(workspace.WORKSPACE_ENV_KEY, raising=False)
    yield
    workspace.reset_undo()
    # ``_sync_shell_guardrail_env`` writes os.environ directly (not via monkeypatch).
    os.environ.pop(workspace.WORKSPACE_ENV_KEY, None)


def _load_builtin_function(name: str):
    """Load one builtin template as a standalone module (like the runtime loader)."""
    module_name = f"test_workspace_builtin_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name].Function
    spec = importlib.util.spec_from_file_location(module_name, BUILDIN_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.Function


def _run_tool(monkeypatch, tool_name, arguments, workspace_root=None, patch_sync=True):
    """Run the real ``execute_tool_call`` against a real builtin function.

    Returns ``(result_text, ok, console_mock)``. ``workspace_root`` is exported via
    the env key the production path uses; the announce/panel output is silenced.
    """
    if workspace_root is not None:
        monkeypatch.setenv(workspace.WORKSPACE_ENV_KEY, str(workspace_root))
    function = _load_builtin_function(tool_name)
    console = MagicMock()
    patches = [
        patch("yaicli.tools.get_function", return_value=function),
        patch("yaicli.tools.cfg", _FAKE_CFG),
        patch("yaicli.tools.console", console),
    ]
    if patch_sync:
        patches.append(patch("yaicli.tools._sync_shell_guardrail_env"))
    for item in patches:
        item.start()
    try:
        result, ok = execute_tool_call(
            ToolCall(id="call-1", name=tool_name, arguments=json.dumps(arguments)),
            announce=False,
        )
    finally:
        for item in reversed(patches):
            item.stop()
    return result, ok, console


def _write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestWorkspaceRoot:
    def test_explicit_root_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv(workspace.WORKSPACE_ENV_KEY, str(tmp_path / "from-env"))
        explicit = tmp_path / "explicit"
        assert workspace.resolve_workspace_root(explicit) == explicit.resolve()

    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv(workspace.WORKSPACE_ENV_KEY, str(tmp_path))
        assert workspace.resolve_workspace_root() == tmp_path.resolve()

    def test_default_root_is_cwd(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        assert workspace.resolve_workspace_root() == tmp_path.resolve()

    def test_backup_root_layout(self, tmp_path):
        assert workspace.workspace_backup_root(tmp_path) == tmp_path / ".yaicli-backups"

    def test_backup_path_for_uses_relative_path_and_stamp(self, tmp_path):
        target = tmp_path / "src" / "main.py"
        backup = workspace.backup_path_for(target, root=tmp_path, stamp="20260101T000000000000Z")
        assert backup == tmp_path / ".yaicli-backups" / "20260101T000000000000Z" / "src" / "main.py"


class TestContainment:
    def test_inside_paths_are_contained(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        for relative in ("a.txt", "sub/dir/b.txt", "new/deep/file.txt"):
            resolved = workspace.resolve_target(str(root / relative))
            assert workspace.is_inside_workspace(resolved, root.resolve())

    def test_outside_paths_are_refused(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(outside / "x.txt")}, root=root)
        assert plan.allowed is False
        payload = json.loads(plan.denial)
        assert payload["success"] is False
        assert payload["reason"] == "outside_workspace"
        assert "workspace root" in payload["error"]
        assert payload["workspace_root"] == str(root.resolve())

    def test_parent_traversal_is_refused(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(root / ".." / "escape.txt")}, root=root)
        assert plan.allowed is False
        assert json.loads(plan.denial)["reason"] == "outside_workspace"

    def test_relative_path_resolves_against_cwd(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": "relative.txt"})
        assert plan.allowed is True
        assert plan.originals[0].path == (tmp_path / "relative.txt").resolve()

    def test_relative_path_outside_root_is_refused(self, monkeypatch, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        monkeypatch.chdir(tmp_path)  # cwd is outside the workspace root
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": "relative.txt"}, root=root)
        assert plan.allowed is False
        assert json.loads(plan.denial)["reason"] == "outside_workspace"

    def test_workspace_root_itself_is_refused(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        plan = workspace.prepare_mutation("fs_file_operations", {"operation": "delete", "path": str(root)}, root=root)
        assert plan.allowed is False
        assert json.loads(plan.denial)["reason"] == "workspace_root"

    def test_symlink_escape_is_refused(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        try:
            (root / "link").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):  # pragma: no cover - Windows without privileges
            pytest.skip("symlinks not supported")
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(root / "link" / "secret.txt")}, root=root)
        assert plan.allowed is False
        assert json.loads(plan.denial)["reason"] == "outside_workspace"
        assert not (outside / "secret.txt").exists()

    def test_symlink_to_inside_workspace_is_allowed(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        real = root / "real_dir"
        real.mkdir()
        try:
            (root / "link").symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):  # pragma: no cover - Windows without privileges
            pytest.skip("symlinks not supported")
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(root / "link" / "ok.txt")}, root=root)
        assert plan.allowed is True
        assert plan.originals[0].path == (real / "ok.txt").resolve()


class TestProtectedPaths:
    @pytest.mark.parametrize(
        "relative,reason_fragment",
        [
            (".git/config", ".git"),
            (".git/hooks/pre-commit", ".git"),
            (".ssh/id_rsa", ".ssh"),
            (".aws/credentials", ".aws"),
            (".gnupg/private.key", ".gnupg"),
            ("sub/.git/HEAD", ".git"),
            (".env", ".env"),
            (".env.local", ".env"),
            ("sub/.env.production", ".env"),
            ("server.pem", "*.pem"),
            ("certs/chain.pem", "*.pem"),
            ("id.key", "*.key"),
            ("keys/private.KEY", "*.key"),
        ],
    )
    def test_protected_targets_are_refused(self, tmp_path, relative, reason_fragment):
        root = tmp_path / "ws"
        root.mkdir()
        target = root / relative
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(target)}, root=root)
        assert plan.allowed is False
        payload = json.loads(plan.denial)
        assert payload["reason"] == "protected_path"
        assert reason_fragment in payload["error"]
        assert not target.exists()

    @pytest.mark.parametrize(
        "relative",
        ["main.py", ".gitignore", "docs/.envrc", "keys/README.md", "src/.github/workflow.yml", "backups.db"],
    )
    def test_normal_paths_are_not_protected(self, tmp_path, relative):
        root = tmp_path / "ws"
        root.mkdir()
        assert workspace.protected_reason((root / relative).resolve(), root.resolve()) is None

    def test_backup_directory_is_not_protected(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        path = root / ".yaicli-backups" / "stamp" / "file.txt"
        assert workspace.protected_reason(path.resolve(), root.resolve()) is None

    def test_protected_delete_and_move_are_refused(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        secret = _write(root / ".ssh" / "id_rsa", "private")
        plan = workspace.prepare_mutation("fs_file_operations", {"operation": "delete", "path": str(secret)}, root=root)
        assert plan.allowed is False
        assert secret.read_text(encoding="utf-8") == "private"
        plan = workspace.prepare_mutation(
            "fs_file_operations",
            {"operation": "move", "path": str(secret), "destination": str(root / "leak.txt")},
            root=root,
        )
        assert plan.allowed is False
        assert secret.exists() and not (root / "leak.txt").exists()

    def test_protected_destination_is_refused(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "source.txt", "data")
        plan = workspace.prepare_mutation(
            "fs_file_operations",
            {"operation": "copy", "path": str(source), "destination": str(root / ".git" / "source.txt")},
            root=root,
        )
        assert plan.allowed is False
        assert json.loads(plan.denial)["reason"] == "protected_path"
        assert not (root / ".git" / "source.txt").exists()


class TestBackups:
    def test_existing_file_backup_layout_content_and_modes(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "src" / "main.py", "print('hi')")
        backup = workspace.backup_existing(source, root=root, stamp="20260101T000000000000Z")
        assert backup == root / ".yaicli-backups" / "20260101T000000000000Z" / "src" / "main.py"
        assert backup.read_text(encoding="utf-8") == "print('hi')"
        assert _mode(backup) == 0o600
        assert _mode(backup.parent) == 0o700
        assert _mode(root / ".yaicli-backups") == 0o700

    def test_directory_backup_is_recursive_and_private(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        tree = root / "tree"
        _write(tree / "a.txt", "a")
        _write(tree / "sub" / "b.txt", "b")
        backup = workspace.backup_existing(tree, root=root, stamp="stamp")
        assert (backup / "a.txt").read_text(encoding="utf-8") == "a"
        assert (backup / "sub" / "b.txt").read_text(encoding="utf-8") == "b"
        assert _mode(backup) == 0o700
        assert _mode(backup / "a.txt") == 0o600

    def test_backup_failure_refuses_mutation(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        existing = _write(root / "config.txt", "original")
        monkeypatch.setattr(workspace.shutil, "copy2", MagicMock(side_effect=OSError("disk full")))
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(existing), "content": "new"}, root=root)
        assert plan.allowed is False
        payload = json.loads(plan.denial)
        assert payload["reason"] == "backup_failed"
        assert "backup could not be created" in payload["error"]
        # No backup path leaks into the model-visible payload.
        assert ".yaicli-backups" not in payload["error"]
        assert existing.read_text(encoding="utf-8") == "original"

    def test_no_backup_for_new_file(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(root / "new.txt")}, root=root)
        assert plan.allowed is True
        assert plan.originals[0].existed is False
        assert plan.originals[0].backup_path is None
        assert not (root / ".yaicli-backups").exists()

    def test_append_backs_up_pre_append_content(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        target = _write(root / "log.txt", "before")
        plan = workspace.prepare_mutation(
            "fs_write_file", {"file_path": str(target), "content": "after", "append": True}, root=root
        )
        assert plan.originals[0].backup_path.read_text(encoding="utf-8") == "before"

    def test_dry_run_creates_no_backup(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        target = _write(root / "edit.txt", "content")
        plan = workspace.prepare_mutation(
            "fs_edit_file", {"file_path": str(target), "edits": [], "dry_run": True}, root=root
        )
        assert plan.allowed is True
        assert plan.originals == []
        assert not (root / ".yaicli-backups").exists()


class TestUndoStack:
    def _entry(self, ts: str = "t") -> workspace.UndoEntry:
        return workspace.UndoEntry(tool="fs_write_file", ts=ts)

    def test_empty_stack(self):
        assert workspace.undo_depth() == 0
        assert workspace.undo_last() is None
        assert workspace.peek_undo() is None

    def test_push_pop_and_reset(self):
        entry = self._entry("first")
        workspace.push_undo(entry)
        assert workspace.undo_depth() == 1
        assert workspace.peek_undo() is entry
        outcome = workspace.undo_last()
        assert outcome.tool == "fs_write_file"
        assert workspace.undo_depth() == 0

    def test_stack_is_bounded(self):
        for index in range(workspace.UNDO_LIMIT + 7):
            workspace.push_undo(self._entry(str(index)))
        assert workspace.undo_depth() == workspace.UNDO_LIMIT
        assert workspace.peek_undo().ts == str(workspace.UNDO_LIMIT + 6)
        workspace.reset_undo()
        assert workspace.undo_depth() == 0

    def test_restore_file_from_backup(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        target = _write(root / "file.txt", "original")
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(target), "content": "new"}, root=root)
        target.write_text("new", encoding="utf-8")
        workspace.push_undo(plan.build_undo_entry())
        outcome = workspace.undo_last()
        assert target.read_text(encoding="utf-8") == "original"
        assert outcome.errors == []
        assert len(outcome.restored) == 1

    def test_restore_preserves_mode(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        target = _write(root / "script.sh", "#!/bin/sh\n")
        os.chmod(target, 0o750)
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(target), "content": "changed"}, root=root)
        target.write_text("changed", encoding="utf-8")
        workspace.push_undo(plan.build_undo_entry())
        workspace.undo_last()
        assert _mode(target) == 0o750

    def test_restore_recreates_parent_directories(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        target = _write(root / "deep" / "nested" / "file.txt", "keep me")
        plan = workspace.prepare_mutation("fs_file_operations", {"operation": "delete", "path": str(target)}, root=root)
        shutil.rmtree(root / "deep")
        workspace.push_undo(plan.build_undo_entry())
        workspace.undo_last()
        assert target.read_text(encoding="utf-8") == "keep me"

    def test_created_file_is_deleted_on_undo(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        target = root / "created.txt"
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(target), "content": "new"}, root=root)
        target.write_text("new", encoding="utf-8")
        workspace.push_undo(plan.build_undo_entry())
        outcome = workspace.undo_last()
        assert not target.exists()
        assert len(outcome.deleted) == 1

    def test_created_directory_is_removed_on_undo(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        target = root / "newdir"
        plan = workspace.prepare_mutation(
            "fs_file_operations", {"operation": "create_dir", "path": str(target)}, root=root
        )
        target.mkdir()
        workspace.push_undo(plan.build_undo_entry())
        workspace.undo_last()
        assert not target.exists()

    def test_undo_reports_non_empty_created_directory(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        target = root / "newdir"
        plan = workspace.prepare_mutation(
            "fs_file_operations", {"operation": "create_dir", "path": str(target)}, root=root
        )
        target.mkdir()
        _write(target / "later.txt", "user data")
        workspace.push_undo(plan.build_undo_entry())
        outcome = workspace.undo_last()
        assert outcome.errors
        assert target.exists()


class TestMutationPlans:
    def test_invalid_arguments_do_not_raise(self):
        for arguments in (None, "not-a-dict", [], {"file_path": 123}):
            plan = workspace.prepare_mutation("fs_write_file", arguments)
            assert plan.allowed is True
            assert plan.denial is None

    def test_guard_error_fails_closed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(workspace, "_prepare_mutation", MagicMock(side_effect=RuntimeError("boom")))
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(tmp_path / "x")}, root=tmp_path)
        assert plan.allowed is False
        payload = json.loads(plan.denial)
        assert payload["reason"] == "workspace_guard_error"

    def test_non_mutating_operations_have_no_plan(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        for operation in ("exists", "get_info", "unknown-op"):
            plan = workspace.prepare_mutation(
                "fs_file_operations", {"operation": operation, "path": str(root / "x")}, root=root
            )
            assert plan.allowed is True
            assert plan.originals == []

    def test_move_plan_records_source_and_created_destination(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "a.txt", "a")
        plan = workspace.prepare_mutation(
            "fs_file_operations",
            {"operation": "move", "path": str(source), "destination": str(root / "b.txt")},
            root=root,
        )
        assert plan.allowed is True
        assert [(original.existed, original.is_dir) for original in plan.originals] == [(True, False), (False, False)]

    def test_copy_plan_only_records_destination(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "a.txt", "a")
        plan = workspace.prepare_mutation(
            "fs_file_operations",
            {"operation": "copy", "path": str(source), "destination": str(root / "c.txt")},
            root=root,
        )
        assert plan.allowed is True
        assert len(plan.originals) == 1
        assert plan.originals[0].path == (root / "c.txt").resolve()
        assert plan.originals[0].existed is False

    def test_missing_destination_is_left_to_the_tool(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "a.txt", "a")
        plan = workspace.prepare_mutation("fs_file_operations", {"operation": "move", "path": str(source)}, root=root)
        assert plan.allowed is True
        assert plan.originals == []

    def test_tool_result_succeeded(self):
        assert workspace.tool_result_succeeded('{"success": true}') is True
        assert workspace.tool_result_succeeded('{"success": false}') is False
        assert workspace.tool_result_succeeded("plain text result") is True
        assert workspace.tool_result_succeeded(None) is True


class TestExecuteToolCallGuard:
    def test_write_outside_workspace_is_denied_in_band(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        target = outside / "escape.txt"
        result, ok, console = _run_tool(
            monkeypatch,
            "fs_write_file",
            {"file_path": str(target), "content": "pwned"},
            workspace_root=root,
        )
        assert ok is True  # the call reached the guard: in-band denial, not an exception
        payload = json.loads(result)
        assert payload["success"] is False
        assert payload["reason"] == "outside_workspace"
        assert not target.exists()
        assert console.print.call_count == 0  # the guard never prints

    def test_write_inside_workspace_succeeds_and_is_undoable(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        target = root / "hello.txt"
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_write_file",
            {"file_path": str(target), "content": "hello"},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert target.read_text(encoding="utf-8") == "hello"
        assert workspace.undo_depth() == 1
        workspace.undo_last()
        assert not target.exists()

    def test_default_workspace_is_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, ok, _ = _run_tool(
            monkeypatch, "fs_write_file", {"file_path": "rel.txt", "content": "x"}, patch_sync=False
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert (tmp_path / "rel.txt").exists()
        assert (tmp_path / ".yaicli-backups").exists() is False  # new file: no backup
        workspace.undo_last()
        assert not (tmp_path / "rel.txt").exists()

    def test_cfg_workspace_root_is_exported_to_the_guard(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = {**_FAKE_CFG, "WORKSPACE_ROOT": str(tmp_path)}
        console = MagicMock()
        with (
            patch("yaicli.tools.get_function", return_value=_load_builtin_function("fs_write_file")),
            patch("yaicli.tools.cfg", cfg),
            patch("yaicli.tools.console", console),
        ):
            result, ok = execute_tool_call(
                ToolCall(
                    id="c", name="fs_write_file", arguments=json.dumps({"file_path": "via-cfg.txt", "content": "x"})
                ),
                announce=False,
            )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert workspace.resolve_workspace_root() == tmp_path.resolve()
        assert (tmp_path / "via-cfg.txt").exists()

    def test_denied_protected_permission_keeps_file_untouched(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        git_config = _write(root / ".git" / "config", "[core]\n")
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_write_file",
            {"file_path": str(git_config), "content": "evil"},
            workspace_root=root,
        )
        assert ok is True
        payload = json.loads(result)
        assert payload["reason"] == "protected_path"
        assert git_config.read_text(encoding="utf-8") == "[core]\n"
        assert workspace.undo_depth() == 0

    def test_backup_failure_denies_and_does_not_run_the_tool(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        existing = _write(root / "config.txt", "original")
        monkeypatch.setattr(workspace.shutil, "copy2", MagicMock(side_effect=OSError("disk full")))
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_write_file",
            {"file_path": str(existing), "content": "new"},
            workspace_root=root,
        )
        assert ok is True
        payload = json.loads(result)
        assert payload["reason"] == "backup_failed"
        assert existing.read_text(encoding="utf-8") == "original"
        assert workspace.undo_depth() == 0

    def test_overwrite_append_and_undo(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        target = _write(root / "notes.txt", "start")
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_write_file",
            {"file_path": str(target), "content": "-more", "append": True},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert target.read_text(encoding="utf-8") == "start-more"
        workspace.undo_last()
        assert target.read_text(encoding="utf-8") == "start"

    def test_edit_and_undo(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        target = _write(root / "edit.txt", "hello world")
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_edit_file",
            {"file_path": str(target), "edits": [{"type": "replace", "old": "world", "new": "there"}]},
            workspace_root=root,
        )
        assert ok is True
        payload = json.loads(result)
        assert payload["success"] is True
        assert target.read_text(encoding="utf-8") == "hello there"
        workspace.undo_last()
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_edit_dry_run_has_no_undo_entry(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        target = _write(root / "edit.txt", "hello")
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_edit_file",
            {
                "file_path": str(target),
                "edits": [{"type": "replace", "old": "hello", "new": "bye"}],
                "dry_run": True,
            },
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert target.read_text(encoding="utf-8") == "hello"
        assert workspace.undo_depth() == 0
        assert not (root / ".yaicli-backups").exists()

    def test_edit_outside_workspace_is_denied(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        target = _write(outside / "file.txt", "content")
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_edit_file",
            {"file_path": str(target), "edits": [{"type": "append", "content": "x"}]},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["reason"] == "outside_workspace"
        assert target.read_text(encoding="utf-8") == "content"

    def test_file_operations_delete_and_undo(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        target = _write(root / "delete-me.txt", "bye")
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_file_operations",
            {"operation": "delete", "path": str(target)},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert not target.exists()
        workspace.undo_last()
        assert target.read_text(encoding="utf-8") == "bye"

    def test_file_operations_move_and_undo(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "a.txt", "content")
        destination = root / "b.txt"
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_file_operations",
            {"operation": "move", "path": str(source), "destination": str(destination)},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert not source.exists() and destination.exists()
        workspace.undo_last()
        assert source.read_text(encoding="utf-8") == "content"
        assert not destination.exists()

    def test_move_overwriting_existing_destination_undo_restores_both(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "source.txt", "source content")
        destination = _write(root / "target.txt", "target content")
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_file_operations",
            {"operation": "move", "path": str(source), "destination": str(destination)},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert destination.read_text(encoding="utf-8") == "source content"
        workspace.undo_last()
        assert source.read_text(encoding="utf-8") == "source content"
        assert destination.read_text(encoding="utf-8") == "target content"

    def test_move_into_existing_directory_records_the_child(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "a.txt", "content")
        target_dir = root / "archive"
        target_dir.mkdir()
        plan = workspace.prepare_mutation(
            "fs_file_operations",
            {"operation": "move", "path": str(source), "destination": str(target_dir)},
            root=root,
        )
        assert plan.allowed is True
        paths = [original.path for original in plan.originals]
        assert (target_dir / "a.txt").resolve() in paths

    def test_file_operations_delete_directory_and_undo(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        tree = root / "tree"
        _write(tree / "sub" / "keep.txt", "keep")
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_file_operations",
            {"operation": "delete", "path": str(tree)},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert not tree.exists()
        workspace.undo_last()
        assert (tree / "sub" / "keep.txt").read_text(encoding="utf-8") == "keep"

    def test_file_operations_copy_directory_and_undo(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        source = root / "srcdir"
        _write(source / "file.txt", "data")
        destination = root / "copydir"
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_file_operations",
            {"operation": "copy", "path": str(source), "destination": str(destination)},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert (destination / "file.txt").read_text(encoding="utf-8") == "data"
        workspace.undo_last()
        assert source.exists()
        assert not destination.exists()

    def test_file_operations_copy_and_undo(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "a.txt", "content")
        destination = root / "copy.txt"
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_file_operations",
            {"operation": "copy", "path": str(source), "destination": str(destination)},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert destination.read_text(encoding="utf-8") == "content"
        workspace.undo_last()
        assert source.exists()
        assert not destination.exists()

    def test_file_operations_create_dir_and_undo(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        target = root / "newdir"
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_file_operations",
            {"operation": "create_dir", "path": str(target)},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["success"] is True
        assert target.is_dir()
        workspace.undo_last()
        assert not target.exists()

    def test_file_operations_move_outside_is_denied(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "a.txt", "content")
        outside = tmp_path / "outside"
        outside.mkdir()
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_file_operations",
            {"operation": "move", "path": str(source), "destination": str(outside / "a.txt")},
            workspace_root=root,
        )
        assert ok is True
        payload = json.loads(result)
        assert payload["reason"] == "outside_workspace"
        assert source.read_text(encoding="utf-8") == "content"
        assert not (outside / "a.txt").exists()
        assert workspace.undo_depth() == 0

    def test_file_operations_copy_to_protected_is_denied(self, tmp_path, monkeypatch):
        root = tmp_path / "ws"
        root.mkdir()
        source = _write(root / "a.txt", "content")
        result, ok, _ = _run_tool(
            monkeypatch,
            "fs_file_operations",
            {"operation": "copy", "path": str(source), "destination": str(root / ".gnupg" / "a.txt")},
            workspace_root=root,
        )
        assert ok is True
        assert json.loads(result)["reason"] == "protected_path"
        assert not (root / ".gnupg" / "a.txt").exists()


class TestUndoCommand:
    def _handler(self):
        cli = MagicMock()
        cli.console = MagicMock()
        return CmdHandler(cli), cli

    def _pushed_created_file(self, root: Path) -> Path:
        target = root / "created-by-agent.txt"
        plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(target), "content": "x"}, root=root)
        target.write_text("x", encoding="utf-8")
        workspace.push_undo(plan.build_undo_entry())
        return target

    def test_undo_command_is_registered(self):
        handler, _ = self._handler()
        assert CMD_UNDO in handler.commands
        assert handler.commands[CMD_UNDO] == handler.handle_undo

    def test_undo_command_deletes_created_file(self, tmp_path):
        handler, cli = self._handler()
        target = self._pushed_created_file(tmp_path)
        assert handler.handle_command(CMD_UNDO) is True
        assert not target.exists()
        printed = " ".join(str(call.args[0]) for call in cli.console.print.call_args_list)
        assert "Undid the last file change" in printed
        assert "deleted" in printed

    def test_undo_command_restores_file(self, tmp_path):
        handler, cli = self._handler()
        target = _write(tmp_path / "restore.txt", "before")
        plan = workspace.prepare_mutation(
            "fs_write_file", {"file_path": str(target), "content": "after"}, root=tmp_path
        )
        target.write_text("after", encoding="utf-8")
        workspace.push_undo(plan.build_undo_entry())
        assert handler.handle_command(CMD_UNDO) is True
        assert target.read_text(encoding="utf-8") == "before"
        printed = " ".join(str(call.args[0]) for call in cli.console.print.call_args_list)
        assert "restored" in printed

    def test_undo_command_empty_stack_message(self):
        handler, cli = self._handler()
        assert handler.handle_command(CMD_UNDO) is True
        printed = " ".join(str(call.args[0]) for call in cli.console.print.call_args_list)
        assert "Nothing to undo" in printed

    def test_undo_command_handles_handle_undo_directly(self, tmp_path):
        handler, _ = self._handler()
        target = self._pushed_created_file(tmp_path)
        assert handler.handle_undo() is True
        assert not target.exists()

    def test_undo_is_listed_in_help(self):
        from yaicli.cli import CLI

        console = MagicMock()
        cli = CLI.__new__(CLI)
        cli.console = console
        CLI.print_help(cli)
        printed = " ".join(str(call.args[0]) for call in console.print.call_args_list)
        assert CMD_UNDO in printed


class TestPlansRootProtection:
    """Persistent plan files are written by the CLI only (v0.24 K23)."""

    def test_agent_write_under_plans_root_is_refused(self, tmp_path, monkeypatch):
        from yaicli.config import cfg

        plans = tmp_path / "plans"
        monkeypatch.setitem(cfg, "PLAN_DIR", str(plans))
        workspace_root = tmp_path / "ws"
        workspace_root.mkdir()
        target = plans / "project-key" / "20261114-004230-plan.md"

        plan = workspace.prepare_mutation(
            "fs_write_file",
            {"file_path": str(target), "content": "tampered", "mode": "write"},
            root=workspace_root,
        )

        assert plan.denial is not None
        payload = json.loads(plan.denial)
        assert payload["error"] == "protected_path"
        assert payload["reason"] == "plan files are managed by the CLI"
        assert not target.exists()

    def test_plans_root_inside_the_workspace_is_refused_too(self, tmp_path, monkeypatch):
        from yaicli.config import cfg

        workspace_root = tmp_path / "ws"
        plans = workspace_root / "plans"
        monkeypatch.setitem(cfg, "PLAN_DIR", str(plans))
        target = plans / "project-key" / "plan.md"

        plan = workspace.prepare_mutation(
            "fs_write_file",
            {"file_path": str(target), "content": "tampered", "mode": "write"},
            root=workspace_root,
        )

        assert plan.denial is not None
        assert json.loads(plan.denial)["error"] == "protected_path"

    def test_agent_write_outside_the_plans_root_still_works(self, tmp_path, monkeypatch):
        from yaicli.config import cfg

        monkeypatch.setitem(cfg, "PLAN_DIR", str(tmp_path / "plans"))
        workspace_root = tmp_path / "ws"
        workspace_root.mkdir()
        target = workspace_root / "notes.txt"

        plan = workspace.prepare_mutation(
            "fs_write_file",
            {"file_path": str(target), "content": "ok", "mode": "write"},
            root=workspace_root,
        )

        assert plan.allowed
        assert plan.denial is None
