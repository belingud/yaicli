import json

import pytest

from yaicli.tools.approval import ToolApprovalManager


def make_manager(tmp_path) -> ToolApprovalManager:
    return ToolApprovalManager(permissions_path=tmp_path / "tool_permissions.json")


def test_missing_file_is_empty(tmp_path):
    mgr = make_manager(tmp_path)
    assert mgr.persistent_allow == set()
    assert mgr.is_allowed("anything") is False


def test_malformed_file_treated_as_empty(tmp_path):
    path = tmp_path / "tool_permissions.json"
    path.write_text("not json{", encoding="utf-8")
    mgr = ToolApprovalManager(permissions_path=path)
    assert mgr.persistent_allow == set()
    assert mgr.is_allowed("anything") is False


def test_session_allow_is_not_persisted(tmp_path):
    path = tmp_path / "tool_permissions.json"
    mgr = ToolApprovalManager(permissions_path=path)
    mgr.allow_session("get_weather")
    assert mgr.is_allowed("get_weather") is True
    # Session approval never touches the file
    assert not path.exists()


def test_persist_writes_and_reloads(tmp_path):
    path = tmp_path / "tool_permissions.json"
    mgr = ToolApprovalManager(permissions_path=path)
    mgr.allow_persist("get_weather")

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "get_weather" in data["always_allow"]

    # A fresh manager loaded from the same file honors the approval
    reloaded = ToolApprovalManager(permissions_path=path)
    assert reloaded.is_allowed("get_weather") is True


def test_mcp_and_function_names_are_distinct(tmp_path):
    mgr = make_manager(tmp_path)
    mgr.allow_session("_mcp__read")
    assert mgr.is_allowed("_mcp__read") is True
    # A built-in function sharing the base name is a different approval
    assert mgr.is_allowed("read") is False


def test_atomic_write_failure_keeps_prior_file(tmp_path, monkeypatch):
    path = tmp_path / "tool_permissions.json"
    mgr = ToolApprovalManager(permissions_path=path)
    mgr.allow_persist("first")  # file now contains "first"

    def boom(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        mgr.allow_persist("second")

    # Prior file is intact and uncorrupted
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["always_allow"] == ["first"]
    # In-memory allowlist unchanged on failure
    assert "second" not in mgr.persistent_allow
    # No leftover temp files
    assert list(tmp_path.glob(".tool_permissions_*")) == []
