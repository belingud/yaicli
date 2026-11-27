"""REPL-facing checkpoint commands, cancellation and persistent turn lifecycle."""

import io
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from yaicli.chat import Chat, FileChatManager
from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.const import CHAT_MODE
from yaicli.schemas import ChatMessage
from yaicli.tools import workspace


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YAI_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setitem(cfg, "CHECKPOINT_ENABLED", True)
    monkeypatch.setitem(cfg, "CHECKPOINT_KEEP", 20)
    monkeypatch.setitem(cfg, "CHECKPOINT_MAX_MB", 50)
    monkeypatch.setitem(cfg, "TOOL_POLICY", "standard")
    monkeypatch.setitem(cfg, "TOOL_AUDIT", False)
    manager = FileChatManager(chat_dir=tmp_path / "sessions")
    instance = CLI(chat_manager=manager, role_manager=MagicMock(), client=MagicMock())
    instance.interactive = True
    instance.machine_output = False
    instance.current_mode = CHAT_MODE
    instance.is_temp_session = False
    instance.chat = Chat(title="Trip", history=[ChatMessage(role="user", content="start")])
    instance.console = Console(file=io.StringIO(), color_system=None, width=200)
    instance.chat.save(instance.chat_history_dir) if instance.chat_history_dir.exists() else manager.save_chat(
        instance.chat
    )
    instance._checkpoint_reset(only_if_new=True)
    return instance


def record_turn(cli, filename="trip.md", text="changed"):
    store = cli._checkpoint_store()
    path = store.root / filename
    capture = store.begin_turn(len(store.list_records(cli.chat.checkpoint_head)))
    plan = workspace.prepare_mutation("fs_write_file", {"file_path": str(path)}, root=store.root)
    path.write_text(text)
    capture.record(plan.build_undo_entry(), True)
    cli.chat.history.append(ChatMessage(role="assistant", content=text))
    cli.chat.checkpoint_head, _ = store.finish_turn(capture, cli.chat.to_dict())
    cli.chat.save(cli.chat_history_dir)
    return path


def output(cli):
    return cli.console.file.getvalue()


def test_list_rewind_and_clear_newer_points(cli, monkeypatch):
    path = record_turn(cli)
    monkeypatch.setattr(cli.console, "input", lambda prompt: "y")
    cli.cmd_handler.handle_command("/checkpoints")
    assert "#1" in output(cli)
    assert "current" in output(cli)
    cli.cmd_handler.handle_command("/rewind 0")
    assert not path.exists()
    assert cli.chat.checkpoint_head == 0
    assert [m.content for m in cli.chat.history] == ["start"]
    assert "Rewound to #0" in output(cli)


@pytest.mark.parametrize("answer", ["", "n", "anything"])
def test_cancellation_has_no_side_effect(cli, monkeypatch, answer):
    path = record_turn(cli)
    before = cli.chat.path.read_bytes()
    monkeypatch.setattr(cli.console, "input", lambda prompt: answer)
    cli.cmd_handler.handle_command("/fork 0 Weekend draft")
    assert path.read_text() == "changed"
    assert cli.chat.path.read_bytes() == before
    assert len(cli.chat_manager.list_chats()) == 1
    assert "Cancelled." in output(cli)


@pytest.mark.parametrize("exc", [KeyboardInterrupt, EOFError])
def test_confirmation_interrupt_is_cancel(cli, monkeypatch, exc):
    path = record_turn(cli)

    def abort(prompt):
        raise exc()

    monkeypatch.setattr(cli.console, "input", abort)
    cli.cmd_handler.handle_command("/rewind")
    assert path.exists()
    assert "Cancelled." in output(cli)


def test_fork_preserves_current_chat_and_title_case(cli, monkeypatch):
    path = record_turn(cli)
    monkeypatch.setattr(cli.console, "input", lambda prompt: "y")
    cli.cmd_handler.handle_command("/fork 0 Weekend draft")
    assert not path.exists()
    fork = cli.chat_manager.load_chat_by_title("Weekend draft")
    assert [m.content for m in fork.history] == ["start", "changed"]
    assert not fork.checkpoint_session_id
    assert not fork.plan
    assert cli.chat.title == "Trip"
    assert cli.chat.checkpoint_head == 0


def test_fork_title_collision_preserves_both_sessions(cli, monkeypatch, capsys):
    path = record_turn(cli)
    cli.chat_manager.save_chat(Chat(title="Weekend draft", history=[ChatMessage(role="user", content="keep me")]))
    monkeypatch.setattr(cli.console, "input", lambda prompt: pytest.fail("must refuse before confirmation"))
    cli.cmd_handler.handle_command("/fork 0 Weekend draft")
    assert path.exists()
    assert cli.chat_manager.load_chat_by_title("Weekend draft").history[0].content == "keep me"
    assert "already exists" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["/rewind 0", "/fork 0 Weekend"])
def test_readonly_refusal(cli, monkeypatch, capsys, command):
    path = record_turn(cli)
    monkeypatch.setitem(cfg, "TOOL_POLICY", "readonly")
    monkeypatch.setattr(cli.console, "input", lambda prompt: pytest.fail("must not confirm"))
    cli.cmd_handler.handle_command(command)
    assert path.exists()
    assert "readonly" in capsys.readouterr().err


def test_non_tty_does_not_modify(cli, capsys):
    path = record_turn(cli)
    cli.interactive = False
    cli.cmd_handler.handle_command("/rewind 0")
    assert path.exists()
    assert "interactive terminal" in capsys.readouterr().err


def test_plain_turn_roundtrip_via_saved_chat(cli, monkeypatch):
    monkeypatch.setattr(
        CLI,
        "_handle_llm_response",
        lambda self, text, images=None: (
            "reply",
            list(self.chat.history)
            + [ChatMessage(role="user", content=text), ChatMessage(role="assistant", content="reply")],
        ),
    )
    monkeypatch.setattr(CLI, "_client_usage_snapshot", lambda self: None)
    monkeypatch.setattr(CLI, "_update_context_percent", lambda self: None)
    cli._process_user_input("where next?")
    loaded = Chat(path=cli.chat.path)
    assert loaded.load()
    assert loaded.checkpoint_head == 1
    assert loaded.checkpoint_session_id == cli.chat.checkpoint_session_id
    assert loaded.history[-1].content == "reply"
    assert len(cli._checkpoint_store().list_records(loaded.checkpoint_head)) == 2


def test_machine_turn_does_not_create_store(cli, monkeypatch):
    cli.machine_output = True
    cli.chat.checkpoint_session_id = ""
    cli.chat.checkpoint_head = -1
    monkeypatch.setattr(CLI, "_process_user_input_inner", lambda self, text, images=None: True)
    assert cli._process_user_input("hi")
    assert cli.chat.checkpoint_session_id == ""


def test_clear_starts_a_new_baseline(cli):
    record_turn(cli)
    cli.cmd_handler.handle_command("/clear")
    assert cli.chat.history == []
    assert len(cli._checkpoint_store().list_records(cli.chat.checkpoint_head)) == 1


def test_commands_registered_for_help_and_completion(cli):
    from yaicli.cmd_handler import command_completions

    offered = dict(command_completions())
    for name in ("/checkpoints", "/rewind", "/fork"):
        assert name in cli.cmd_handler.commands
        assert name in offered


def test_renaming_retains_identity_and_history(cli, monkeypatch):
    path = record_turn(cli)
    original = cli.chat.path
    identity = cli.chat.checkpoint_session_id
    cli._save_chat("New trip")
    assert cli.chat.checkpoint_session_id == identity
    assert not original.exists()
    assert cli._checkpoint_store()._load()["session_path"] == str(cli.chat.path.resolve())
    monkeypatch.setattr(cli.console, "input", lambda prompt: "y")
    cli.cmd_handler.handle_command("/rewind 0")
    assert not path.exists()


def test_copied_session_gets_new_identity(cli):
    import shutil

    record_turn(cli)
    identity = cli.chat.checkpoint_session_id
    copied = cli.chat.path.with_name("20260101-000000-title-Copy.json")
    shutil.copyfile(cli.chat.path, copied)
    cli.chat = Chat(path=copied)
    assert cli.chat.load()
    cli._checkpoint_reset(only_if_new=True)
    assert cli.chat.checkpoint_session_id != identity
    assert len(cli._checkpoint_store().list_records(cli.chat.checkpoint_head)) == 1


def test_stale_session_cannot_overwrite_newer_chat_on_save(cli):
    stale = Chat(path=cli.chat.path)
    stale.load()
    record_turn(cli)
    expected = cli.chat.path.read_bytes()
    cli.chat = stale
    cli._save_chat()
    assert cli.chat.path.read_bytes() == expected


def test_file_tool_exception_cuts_earlier_history(cli, monkeypatch):
    import yaicli.tools as tools
    from yaicli.schemas import ToolCall

    store = cli._checkpoint_store()
    capture = store.begin_turn(1)
    path = store.root / "trip.md"

    class BrokenTool:
        source = "builtin"

        @staticmethod
        def execute(**kwargs):
            path.write_text("partial")
            raise OSError("tool failed after writing")

    monkeypatch.setattr(tools, "get_function", lambda name: BrokenTool())
    with capture.activate():
        _, succeeded = tools.execute_tool_call(
            ToolCall(id="t", name="fs_write_file", arguments='{"file_path":"trip.md"}')
        )
    assert not succeeded
    assert capture.barrier
    store.abandon_turn(capture)


def test_custom_override_of_builtin_is_barrier(cli, monkeypatch):
    import yaicli.tools as tools
    from yaicli.schemas import ToolCall

    store = cli._checkpoint_store()
    capture = store.begin_turn(1)

    class UserTool:
        source = "user"

        @staticmethod
        def execute(**kwargs):
            return '{"success": true}'

    monkeypatch.setattr(tools, "get_function", lambda name: UserTool())
    with capture.activate():
        tools.execute_tool_call(ToolCall(id="t", name="fs_write_file", arguments='{"file_path":"trip.md"}'))
    assert capture.barrier
    store.abandon_turn(capture)


def test_external_shell_and_plan_changes_rebuild_baseline(cli, monkeypatch):
    record_turn(cli)
    monkeypatch.setattr("yaicli.cmd_handler.subprocess.call", lambda *args, **kwargs: 0)
    cli.cmd_handler.handle_shell_command("true")
    assert len(cli._checkpoint_store().list_records(cli.chat.checkpoint_head)) == 1
    record_turn(cli)
    cli._persist_chat_plan({"revision": 2})
    assert len(cli._checkpoint_store().list_records(cli.chat.checkpoint_head)) == 1


def test_delete_removes_owned_store_and_preserves_recovery(cli, capsys):
    store = cli._checkpoint_store()
    cli.chat_manager.delete_chat(cli.chat.path)
    assert not store.directory.exists()


def test_delete_preserves_recovery_and_reports_location(cli, capsys):
    store = cli._checkpoint_store()
    store.recovery_path.write_text('{"interrupted": true}')
    cli.chat_manager.delete_chat(cli.chat.path)
    assert store.recovery_path.exists()
    assert "Recovery record retained" in capsys.readouterr().err


def test_disabled_detachment_still_cleans_store_on_deletion(cli, monkeypatch):
    store = cli._checkpoint_store()
    monkeypatch.setitem(cfg, "CHECKPOINT_ENABLED", False)
    cli._save_chat()
    assert cli.chat.checkpoint_head == -1
    cli.chat_manager.delete_chat(cli.chat.path)
    assert not store.directory.exists()


def test_fork_failure_reports_the_preserved_archive(cli, monkeypatch, capsys):
    from yaicli.checkpoints import CheckpointStore

    record_turn(cli)
    monkeypatch.setattr(cli.console, "input", lambda prompt: "y")
    monkeypatch.setattr(CheckpointStore, "_apply_file_state", lambda *args: (_ for _ in ()).throw(OSError("failed")))
    cli.cmd_handler.handle_command("/fork 0 Saved attempt")
    assert cli.chat_manager.load_chat_by_title("Saved attempt").history[-1].content == "changed"
    assert 'Chat saved as "Saved attempt".' in output(cli)
    assert "Rewind failed" in capsys.readouterr().err


def test_oversized_baseline_still_processes_user_input(cli, monkeypatch):
    from yaicli.checkpoints import CheckpointStore

    cli.chat.history = [ChatMessage(role="user", content="x" * (CheckpointStore.SNAPSHOT_MAX + 1))]
    cli._checkpoint_reset()
    invoked = []
    monkeypatch.setattr(CLI, "_process_user_input_inner", lambda self, text, images=None: invoked.append(text) or True)
    cli._process_user_input("continue")
    assert invoked == ["continue"]
