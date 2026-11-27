"""Actual execution scopes must restore managed keys on every exit path."""

import json
import os
from unittest.mock import MagicMock

import pytest

from yaicli.runtime import SessionContext, current_config
from yaicli.schemas import ToolCall
from yaicli.tools import executor, workspace
from yaicli.tools.environment import tool_environment


@pytest.mark.parametrize("fail", [False, True])
def test_nested_environment_restores_absence_values_and_effective_mapping(monkeypatch, fail):
    monkeypatch.setenv("YAI_TOOL_TIMEOUT", "original")
    monkeypatch.delenv("YAI_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("YAI_UNMANAGED_PROBE", "keep")
    outer = {"TOOL_TIMEOUT": 17, "WORKSPACE_ROOT": "/outer", "TOOL_ENV_INHERIT": False}
    with tool_environment(outer):
        assert os.environ["YAI_TOOL_TIMEOUT"] == "17"
        assert os.environ["YAI_TOOL_ENV_INHERIT"] == "false"
        assert current_config(None) is outer
        try:
            with tool_environment({"TOOL_TIMEOUT": "", "WORKSPACE_ROOT": None}):
                assert "YAI_TOOL_TIMEOUT" not in os.environ
                assert "YAI_WORKSPACE_ROOT" not in os.environ
                if fail:
                    raise RuntimeError("probe")
        except RuntimeError:
            pass
        assert os.environ["YAI_TOOL_TIMEOUT"] == "17"
        assert os.environ["YAI_WORKSPACE_ROOT"] == "/outer"
    assert os.environ["YAI_TOOL_TIMEOUT"] == "original"
    assert "YAI_WORKSPACE_ROOT" not in os.environ
    assert os.environ["YAI_UNMANAGED_PROBE"] == "keep"
    assert current_config(None) is None


def test_real_guard_write_and_undo_use_the_same_scoped_workspace(tmp_path, monkeypatch):
    root = tmp_path / "owned"
    root.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    monkeypatch.setenv("YAI_WORKSPACE_ROOT", str(outside))
    config = {"WORKSPACE_ROOT": str(root), "SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False}
    runtime = SessionContext(config)
    path = root / "probe.txt"
    result, ok = executor.execute_tool_call(
        ToolCall(id="write", name="fs_write_file", arguments=json.dumps({"file_path": str(path), "content": "owned"})),
        config=config,
        console=MagicMock(),
        runtime=runtime,
    )
    assert ok and json.loads(result)["success"]
    assert path.read_text() == "owned"
    assert os.environ["YAI_WORKSPACE_ROOT"] == str(outside)
    with tool_environment(config):
        outcome = workspace.undo_last()
    assert outcome is not None and outcome.deleted
    assert not path.exists()
    assert os.environ["YAI_WORKSPACE_ROOT"] == str(outside)


def test_failed_execution_restores_environment_before_the_next_call(monkeypatch):
    monkeypatch.setenv("YAI_TOOL_TIMEOUT", "outside")
    monkeypatch.delenv("YAI_WORKSPACE_ROOT", raising=False)
    seen = []
    tool = MagicMock()

    def execute():
        seen.append((os.environ.get("YAI_TOOL_TIMEOUT"), os.environ.get("YAI_WORKSPACE_ROOT")))
        if len(seen) == 1:
            raise RuntimeError("failed execution")
        return "next call"

    tool.execute.side_effect = execute
    monkeypatch.setattr(executor, "get_function", lambda name: tool)
    first = {"TOOL_TIMEOUT": 3, "WORKSPACE_ROOT": "/first", "SHOW_FUNCTION_OUTPUT": False}
    second = {"TOOL_TIMEOUT": "", "WORKSPACE_ROOT": "", "SHOW_FUNCTION_OUTPUT": False}
    result, ok = executor.execute_tool_call(
        ToolCall(id="fail", name="custom", arguments="{}"), config=first, console=MagicMock()
    )
    assert not ok and "failed execution" in result
    assert os.environ["YAI_TOOL_TIMEOUT"] == "outside"
    assert "YAI_WORKSPACE_ROOT" not in os.environ
    result, ok = executor.execute_tool_call(
        ToolCall(id="next", name="custom", arguments="{}"), config=second, console=MagicMock()
    )
    assert ok and result == "next call"
    assert seen == [("3", "/first"), (None, None)]
    assert os.environ["YAI_TOOL_TIMEOUT"] == "outside"
    assert "YAI_WORKSPACE_ROOT" not in os.environ
