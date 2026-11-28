"""Behavior contracts for the application boundary extraction.

Expected payloads and saved messages are fixed independently of the extracted
services. The CLI cases also run against the stage-one implementation.
"""

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from yaicli.chat import Chat, FileChatManager
from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.entry import app
from yaicli.schemas import ChatMessage, LLMResponse
from yaicli.usage import Usage, UsageTracker


@pytest.fixture
def application_config(tmp_path, monkeypatch):
    """Keep application contracts independent of user files and cwd discovery."""
    workspace = tmp_path / "workspace"
    invocation = workspace / "nested"
    invocation.mkdir(parents=True)
    monkeypatch.chdir(invocation)
    for key, value in {
        "MODEL": "contract-model",
        "PROVIDER": "contract-provider",
        "MODEL_PRICING": {"contract-model": {"input": 1.0, "output": 2.0}},
        "WORKSPACE_ROOT": str(workspace),
        "CHAT_HISTORY_DIR": str(tmp_path / "saved-conversations"),
        "PLAN_DIR": str(tmp_path / "plans"),
        "CHECKPOINT_ENABLED": False,
        "ENABLE_PROJECT_CONTEXT": False,
        "ENABLE_FUNCTIONS": False,
        "ENABLE_MCP": False,
        "SHOW_USAGE": False,
    }.items():
        monkeypatch.setitem(cfg, key, value)
    return cfg


def _usage_payload():
    return {
        "prompt_tokens": 100,
        "completion_tokens": 25,
        "total_tokens": 125,
        "cached_tokens": 7,
        "reasoning_tokens": 3,
        "estimated": False,
        "requests": 1,
        "cost_usd": pytest.approx(0.00015),
        "models": {
            "contract-model": {
                "prompt_tokens": 100,
                "completion_tokens": 25,
                "total_tokens": 125,
                "estimated": False,
                "cost_usd": pytest.approx(0.00015),
            }
        },
        "tools": {"count": 1, "duration_ms": 4.25, "result_chars": 17},
    }


class ReportingClient:
    """A provider boundary with a real tracker and deterministic completion."""

    last_depth_limit_reached = False
    tool_denied = False
    output_truncated = False
    last_finish_reason = "stop"

    def __init__(self, config):
        self.tracker = UsageTracker(config)
        self.tracker.record(Usage(100, 25, 125, cached_tokens=7, reasoning_tokens=3), "contract-model")
        self.tracker.record_tool(4.25, 17)

    def usage_snapshot(self):
        return self.tracker.snapshot()

    def completion_with_tools(self, messages, **kwargs):
        yield LLMResponse(content="Answer 中文", finish_reason="stop")


@pytest.mark.parametrize("output_format", ["json", "stream-json"])
def test_real_cli_output_keeps_usage_finish_reason_and_channels(application_config, output_format):
    client = ReportingClient(application_config)
    with patch("yaicli.cli.LLMClient", return_value=client):
        result = CliRunner().invoke(app, ["-p", "--output-format", output_format, "Question"])

    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    if output_format == "json":
        assert json.loads(result.stdout) == {
            "content": "Answer 中文",
            "tool_calls": [],
            "usage": _usage_payload(),
            "finish_reason": "stop",
            "model": "contract-model",
            "provider": "contract-provider",
            "error": None,
            "exit_code": 0,
        }
        assert result.stdout.count("\n") == 1
    else:
        events = [json.loads(line) for line in result.stdout.splitlines()]
        assert [event["type"] for event in events] == ["turn_start", "text_delta", "usage", "done"]
        assert events[1] == {"type": "text_delta", "delta": "Answer 中文"}
        assert events[2] == {"type": "usage", **_usage_payload(), "finish_reason": "stop"}
        assert events[3] == {"type": "done", "exit_code": 0, "error": None}


def test_result_construction_is_lazy_and_leaves_conversation_untouched(application_config, tmp_path, monkeypatch):
    manager = FileChatManager(chat_dir=tmp_path / "chats")
    cli = CLI(chat_manager=manager, print_mode=True, output_format="json")
    original = Chat(title="Untouched", history=[ChatMessage(role="user", content="Keep me")])
    cli.chat = original
    cli.last_content = "Result only"

    def unexpected_client(_self):
        pytest.fail("Serializing a result must not construct an LLM client")

    monkeypatch.setattr(CLI, "_create_client", unexpected_client)
    payload = cli._build_result()

    assert payload == {
        "content": "Result only",
        "tool_calls": [],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
            "estimated": False,
            "requests": 0,
            "cost_usd": None,
            "models": {},
            "tools": {"count": 0, "duration_ms": 0.0, "result_chars": 0},
        },
        "finish_reason": None,
        "model": "contract-model",
        "provider": "contract-provider",
        "error": None,
        "exit_code": 0,
    }
    assert cli.chat is original
    assert cli.chat.history == [ChatMessage(role="user", content="Keep me")]
    assert not manager.chat_dir.exists()


def test_load_then_save_keeps_recorded_metadata_tool_pairs_and_actual_store(application_config, tmp_path):
    directory = tmp_path / "separate-store"
    directory.mkdir()
    history = [
        {"role": "user", "content": "Read the notes"},
        {
            "role": "assistant",
            "content": "",
            "reasoning": "Check the existing notes first",
            "tool_calls": [{"id": "legacy-call", "name": "fs_read_file", "arguments": '{"file_paths":["notes.txt"]}'}],
        },
        {"role": "tool", "content": "Notes 中文", "name": "fs_read_file", "tool_call_id": "legacy-call"},
        {"role": "assistant", "content": "The notes are ready"},
    ]
    path = directory / "20240101-120000-title-Kept Title.json"
    path.write_text(
        json.dumps(
            {
                "title": "Kept Title",
                "date": "2024-01-01T12:00:00",
                "model": "recorded-model",
                "provider": "recorded-provider",
                "role": "recorded-role",
                "cwd": "/recorded/workspace",
                "history": history,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manager = FileChatManager(chat_dir=directory)
    cli = CLI(chat_manager=manager, print_mode=True)
    cli._last_turn_snapshot = {"user_input": "A different conversation"}

    assert cli.cmd_handler.handle_command("/load 1") is True
    assert cli.is_temp_session is False
    assert cli._last_turn_snapshot is None
    assert cli.chat.to_dict()["history"] == history
    assert cli.chat_history_dir == directory

    assert cli.cmd_handler.handle_command("/save") is True
    saved = json.loads(cli.chat.path.read_text(encoding="utf-8"))
    assert cli.chat.path.parent == directory
    assert saved["history"] == history
    assert (saved["model"], saved["provider"], saved["role"], saved["cwd"]) == (
        "recorded-model",
        "recorded-provider",
        "recorded-role",
        "/recorded/workspace",
    )
    assert saved["created_at"] == "2024-01-01T12:00:00"
    assert not Path(application_config["CHAT_HISTORY_DIR"]).exists()


@pytest.fixture
def no_cli_construction(monkeypatch):
    """Application services must work without constructing an orchestrator."""

    def unexpected_cli(*args, **kwargs):
        pytest.fail("An application service must not construct CLI")

    monkeypatch.setattr(CLI, "__init__", unexpected_cli)


def _real_services(config, directory, *, interactive=False, history_changed=None, client=None):
    from yaicli.application.output import MachineOutput
    from yaicli.application.session import SessionController
    from yaicli.application.state import RunState
    from yaicli.const import CHAT_MODE

    state = RunState(
        interactive=interactive,
        machine_output=not interactive,
        output_format="text" if interactive else "json",
        current_mode=CHAT_MODE,
        role_name="DEFAULT",
        init_role="DEFAULT",
    )
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=160)
    sessions = SessionController(
        config, FileChatManager(chat_dir=directory), state, console, history_changed=history_changed
    )
    output = MachineOutput(config, state, live_client=lambda: client)
    return sessions, state, output, console, buffer


def test_session_service_load_replaces_retry_snapshot_and_saves_real_chat(
    application_config, tmp_path, no_cli_construction
):
    changed = []
    sessions, state, _, _, buffer = _real_services(
        application_config, tmp_path / "direct-sessions", history_changed=lambda: changed.append(sessions.chat.title)
    )
    saved = Chat(title="Saved original", history=[ChatMessage(role="user", content="Stored question")])
    saved.update_metadata(model="stored-model", provider="stored-provider", role="stored-role", cwd="/stored/root")
    sessions.chat_manager.save_chat(saved)
    sessions.chat.add_message("user", "Another conversation")
    sessions.remember_turn_for_retry("Unrelated retry")
    sessions.chat.add_message("assistant", "Partial response")
    assert sessions.retry_snapshot["history"] == [ChatMessage(role="user", content="Another conversation")]

    assert sessions.load_chat_by_index("1") is True

    assert sessions.retry_snapshot is None
    assert changed == ["Saved original"]
    assert sessions.chat.history == [ChatMessage(role="user", content="Stored question")]
    assert sessions.is_temp_session is False
    sessions.chat.add_message("assistant", "Preserved response")
    sessions.save_chat()
    reloaded = sessions.chat_manager.load_chat_by_title("Saved original")
    assert [message.content for message in reloaded.history] == ["Stored question", "Preserved response"]
    assert (reloaded.model, reloaded.provider, reloaded.role, reloaded.cwd) == (
        "stored-model",
        "stored-provider",
        "stored-role",
        "/stored/root",
    )
    assert state.role_name == "DEFAULT"
    assert "Loaded chat: Saved original" in buffer.getvalue()
    assert "Chat saved as: Saved original" in buffer.getvalue()


def test_session_service_checkpoint_identity_survives_reopen_with_configured_root(
    application_config, tmp_path, no_cli_construction
):
    configuration = dict(application_config, CHECKPOINT_ENABLED=True)
    directory = tmp_path / "real-saved-store"
    sessions, _, _, _, _ = _real_services(configuration, directory, interactive=True)
    sessions.chat = Chat(title="Checkpoint identity", history=[ChatMessage(role="user", content="A recorded turn")])

    sessions.save_chat()

    identity = sessions.chat.checkpoint_session_id
    head = sessions.chat.checkpoint_head
    store = sessions.checkpoint_store()
    assert len(identity) == 32
    assert head >= 0
    assert store.root == Path(configuration["WORKSPACE_ROOT"]).resolve()
    assert store.root != Path.cwd()
    assert store.directory.is_relative_to(directory.resolve() / "checkpoints")
    assert store.target_snapshot(head)["history"] == [{"role": "user", "content": "A recorded turn"}]
    manifest = store.manifest_path.read_bytes()

    reopened, _, _, _, _ = _real_services(configuration, directory, interactive=True)
    reopened.start_chat_by_title("Checkpoint identity")
    reopened_store = reopened.checkpoint_store()

    assert reopened.chat.checkpoint_session_id == identity
    assert reopened.chat.checkpoint_head == head
    assert reopened_store.root == store.root
    assert reopened_store.directory == store.directory
    assert reopened_store.manifest_path.read_bytes() == manifest
    assert reopened.chat.path.parent == directory


@pytest.mark.parametrize("status", ["draft", "in-progress"])
def test_plan_coordinator_restores_existing_markdown_and_todos_without_running_turns(
    application_config, tmp_path, no_cli_construction, status
):
    from yaicli.planning.coordinator import PlanCoordinator, PlanTurns

    sessions, state, output, console, buffer = _real_services(application_config, tmp_path / "plan-session-store")
    session_id = "2024-01-01T12:00:00"
    path = Path(application_config["PLAN_DIR"]) / "legacy-plan.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "id: legacy-plan\n"
        f"status: {status}\n"
        "revision: 2\n"
        f"session_id: {session_id}\n"
        "base_rev: recorded-revision\n"
        "---\n\n"
        "# Plan: Keep existing work\n\n"
        "## Goal\nKeep existing work\n\n"
        "## Steps\n"
        "- [ ] **S1** First step\n"
        "  - acceptance: First result remains available\n"
        "- [ ] **S2** Second step\n"
        "  - acceptance: Second result remains available\n",
        encoding="utf-8",
    )
    original_markdown = path.read_bytes()
    todos = [
        {"id": "S1", "content": "First step", "status": "completed"},
        {"id": "S2", "content": "Second step", "status": "in_progress"},
    ]
    pointer = {
        "id": "legacy-plan",
        "path": str(path),
        "status": status,
        "revision": 2,
        "session_id": session_id,
        "base_rev": "recorded-revision",
        "updated": "2024-01-02T12:00:00",
    }
    if status == "in-progress":
        pointer["todos"] = todos
    saved = Chat(
        title="Existing plan session",
        date=session_id,
        history=[ChatMessage(role="user", content="Previous discussion")],
        plan=pointer,
    )
    sessions.chat_manager.save_chat(saved)
    sessions.start_chat_by_title("Existing plan session")

    def unexpected_turn(*args, **kwargs):
        pytest.fail("Restoring a plan must not execute a turn, change role, or open a panel")

    synced = []
    turns = PlanTurns(
        process=unexpected_turn,
        once=unexpected_turn,
        set_role=unexpected_turn,
        sync_client=lambda: synced.append(True),
    )
    coordinator = PlanCoordinator(application_config, sessions, state, output, console, unexpected_turn, turns)

    coordinator.restore_plan_from_session()

    plan_session = coordinator.get_plan_session()
    restored = plan_session.draft_plan if status == "draft" else plan_session.active_plan
    assert restored is not None
    assert (restored.id, restored.path, restored.status, restored.revision) == ("legacy-plan", path, status, 2)
    assert restored.goal == "Keep existing work"
    assert [step.id for step in restored.steps] == ["S1", "S2"]
    assert plan_session.mode == "normal"
    assert plan_session.is_plan_mode is False
    expected_todos = [{**todo, "reason": ""} for todo in todos] if status == "in-progress" else []
    assert [todo.to_dict() for todo in plan_session.todos] == expected_todos
    assert path.read_bytes() == original_markdown
    assert synced
    persisted = json.loads(sessions.chat.path.read_text(encoding="utf-8"))["plan"]
    assert (persisted["id"], persisted["path"], persisted["status"], persisted["revision"]) == (
        "legacy-plan",
        str(path),
        status,
        2,
    )
    expected_command = "/plan review" if status == "draft" else "/plan resume"
    assert expected_command in buffer.getvalue()


@pytest.mark.parametrize(
    "flags,expected_exit,expected_error",
    [
        ({}, 0, None),
        ({"interrupted": True, "tool_denied": True}, 130, {"kind": "tool", "message": "a tool call was denied"}),
        ({"tool_denied": True}, 3, {"kind": "tool", "message": "a tool call was denied"}),
        ({"depth_limit_reached": True}, 1, {"kind": "depth_limit", "message": "tool-call depth limit reached"}),
    ],
)
def test_machine_output_finalizes_real_usage_and_exit_mapping_without_cli(
    application_config, tmp_path, no_cli_construction, capsys, flags, expected_exit, expected_error
):
    _, state, output, _, _ = _real_services(
        application_config, tmp_path / "unused-sessions", client=ReportingClient(application_config)
    )
    state.fail_on_tool_denied = True
    output.result.last_content = "Final answer"
    for key, value in flags.items():
        setattr(output.result, key, value)

    assert output.finalize_headless() == expected_exit

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["content"] == "Final answer"
    assert payload["usage"] == _usage_payload()
    assert payload["finish_reason"] == "stop"
    assert payload["error"] == expected_error
    assert payload["exit_code"] == expected_exit
