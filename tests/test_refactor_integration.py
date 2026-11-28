"""Behavior contracts across the real CLI, client, dispatcher and checkpoint IO.

Only model responses and terminal input are scripted. The blocked-write wrapper
retains the loaded builtin implementation so capture and guard ordering stay real.
"""

import json
import threading
from dataclasses import asdict

import pytest
from typer.testing import CliRunner

from yaicli import cli as cli_module
from yaicli import console as console_module
from yaicli import tools
from yaicli.chat import Chat, FileChatManager
from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.console import get_console
from yaicli.const import CHAT_MODE
from yaicli.entry import app
from yaicli.llms.provider import Provider, ProviderFactory
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall
from yaicli.tools import output_history, workspace
from yaicli.tools.function import get_function
from yaicli.usage import Usage


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YAI_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(tools, "console", tools.console)
    monkeypatch.setattr(console_module, "_error_console", console_module._error_console)
    for name, value in {
        "PROVIDER": "openai",
        "MODEL": "refactor-contract-test",
        "MODEL_CONTEXT_WINDOWS": {"refactor-contract-test": 128000},
        "ENABLE_FUNCTIONS": True,
        "ENABLE_MCP": False,
        "ENABLE_PROJECT_CONTEXT": False,
        "ENABLED_TOOLS": "",
        "STREAM": True,
        "RETRY_ENABLED": False,
        "SHOW_USAGE": False,
        "SHOW_FUNCTION_OUTPUT": True,
        "TOOL_POLICY": "standard",
        "TOOL_CONFIRM": True,
        "TOOL_AUDIT": False,
        "WORKSPACE_ROOT": str(tmp_path),
        "CHECKPOINT_ENABLED": True,
        "CHECKPOINT_KEEP": 20,
        "CHECKPOINT_MAX_MB": 50,
    }.items():
        monkeypatch.setitem(cfg, name, value)
    # The real dispatcher updates the standalone-tool environment. Restore those
    # managed keys and the process-global undo stack between these test runtimes.
    for name in (
        "YAI_WORKSPACE_ROOT",
        "YAI_TOOL_TIMEOUT",
        "YAI_TOOL_ENV_INHERIT",
        "YAI_TOOL_OUTPUT_MAX_CHARS",
    ):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setenv("YAI_WORKSPACE_ROOT", str(tmp_path))
    workspace.reset_undo()
    output_history.reset()
    yield tmp_path
    workspace.reset_undo()
    output_history.reset()


@pytest.mark.parametrize("policy", ["standard", "readonly"])
def test_real_tool_rounds_keep_ndjson_order_payloads_and_diagnostics(runtime, monkeypatch, policy):
    path = runtime / "note.txt"
    path.write_text("original\n", encoding="utf-8")
    monkeypatch.setitem(cfg, "TOOL_POLICY", policy)
    requests = []
    write_args = {"file_path": str(path), "content": "updated\n"}
    read_args = {"file_paths": [str(path)]}

    class ScriptedProvider(Provider):
        def __init__(self, config, **kwargs):
            self.config = config
            self.console = get_console()

        def completion(self, messages, stream=False, tool_policy=None):
            requests.append([asdict(message) for message in messages])
            self.console.print("provider diagnostic", markup=False)
            if messages[-1].role == "user":
                yield LLMResponse(
                    tool_calls=[
                        ToolCall(id="write-1", name="fs_write_file", arguments=json.dumps(write_args)),
                        ToolCall(id="read-1", name="fs_read_file", arguments=json.dumps(read_args)),
                    ],
                    finish_reason="tool_calls",
                    usage=Usage(10, 3, 13),
                )
            else:
                yield LLMResponse(content="done", finish_reason="stop", usage=Usage(10, 3, 13))

        def detect_tool_role(self):
            return "tool"

    monkeypatch.setattr(ProviderFactory, "create_provider", lambda name, **kwargs: ScriptedProvider(**kwargs))
    result = CliRunner().invoke(
        app,
        ["-p", "--output-format", "stream-json", "--allowed-tools", "fs_write_file,fs_read_file", "update and read"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert [event["type"] for event in events] == [
        "turn_start",
        "turn_start",
        "tool_call",
        "tool_call",
        "tool_result",
        "tool_result",
        "text_delta",
        "usage",
        "done",
    ]
    # RefreshLive starts the next completion round before its tool events are
    # forwarded. Preserve this existing framing as well as tool event ordering.
    assert events[:2] == [{"type": "turn_start", "turn": 0}, {"type": "turn_start", "turn": 1}]
    assert events[2:4] == [
        {"type": "tool_call", "name": "fs_write_file", "arguments": write_args},
        {"type": "tool_call", "name": "fs_read_file", "arguments": read_args},
    ]
    assert [event["name"] for event in events[4:6]] == ["fs_write_file", "fs_read_file"]
    expected = "updated\n" if policy == "standard" else "original\n"
    assert path.read_bytes() == expected.encode()
    written = json.loads(events[4]["result"])
    if policy == "standard":
        assert written["success"] is True
        assert result.stderr.count("@Function call: fs_write_file") == 1
    else:
        assert written["error"] == "tool_denied"
        assert "readonly" in written["reason"]
        assert "@Function call: fs_write_file" not in result.stderr
        assert "was denied" in result.stderr
    assert json.loads(events[5]["result"])["content"] == expected
    assert events[6] == {"type": "text_delta", "delta": "done"}
    assert events[7]["prompt_tokens"] == 20
    assert events[7]["completion_tokens"] == 6
    assert events[7]["total_tokens"] == 26
    assert events[7]["requests"] == 2
    assert events[-1]["exit_code"] == 0
    assert result.stderr.count("provider diagnostic") == 2
    assert result.stderr.count("@Function call: fs_read_file") == 1
    assert len(requests) == 2
    results = [message for message in requests[-1] if message["role"] == "tool"]
    assert [(message["tool_call_id"], message["name"]) for message in results] == [
        ("write-1", "fs_write_file"),
        ("read-1", "fs_read_file"),
    ]
    assert [message["content"] for message in results] == [event["result"] for event in events[4:6]]


@pytest.mark.parametrize("block_after_write", [False, True], ids=["before-write", "after-write"])
def test_cancelled_real_tool_keeps_checkpoint_locked_until_worker_finishes(
    runtime, monkeypatch, capsys, block_after_write
):
    path = runtime / "late.txt"
    reached = threading.Event()
    release = threading.Event()
    requests = []
    write_tool = get_function("fs_write_file")
    original_execute = write_tool.execute

    def blocked_write(**arguments):
        result = original_execute(**arguments) if block_after_write else None
        reached.set()
        if not release.wait(5):
            raise AssertionError("test did not release the blocked builtin")
        return result if block_after_write else original_execute(**arguments)

    monkeypatch.setattr(write_tool, "execute", blocked_write)

    class ScriptedProvider(Provider):
        def __init__(self, config, **kwargs):
            self.config = config

        def completion(self, messages, stream=False, tool_policy=None):
            prompt = next(message.content for message in reversed(messages) if message.role == "user")
            requests.append(prompt)
            if prompt == "blocked write" and messages[-1].role == "user":
                yield LLMResponse(
                    tool_call=ToolCall(
                        id="late-write",
                        name="fs_write_file",
                        arguments=json.dumps({"file_path": str(path), "content": "late bytes\n"}),
                    ),
                    finish_reason="tool_calls",
                )
            else:
                yield LLMResponse(content="reply: " + prompt, finish_reason="stop")

        def detect_tool_role(self):
            return "tool"

    monkeypatch.setattr(ProviderFactory, "create_provider", lambda name, **kwargs: ScriptedProvider(**kwargs))
    monkeypatch.setattr(CLI, "_stdin_is_tty", staticmethod(lambda: True))
    monkeypatch.setattr(CLI, "_stdout_is_tty", staticmethod(lambda: True))
    manager = FileChatManager(chat_dir=runtime / "sessions")
    cli = CLI(chat_manager=manager)
    cli.configure_headless(allowed_tools=["fs_write_file"])
    cli.client.approval.configure_run(yes=False, allowed_tools=["fs_write_file"])
    cli.current_mode = CHAT_MODE
    cli.is_temp_session = False
    cli.chat = Chat(title="Cancelled write", history=[ChatMessage(role="assistant", content="Ready.")])
    manager.save_chat(cli.chat)
    cli._checkpoint_reset(only_if_new=True)
    store = cli._checkpoint_store()
    snapshots = {}

    class ScriptedWatcher:
        interrupted = False

        def take_viewer_request(self):
            if reached.is_set() and not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt
            return False

        def stop(self):
            return ""

    watcher = ScriptedWatcher()
    monkeypatch.setattr(CLI, "_start_generation_watcher", lambda self: watcher)
    monkeypatch.setattr(cli.console, "input", lambda *args, **kwargs: pytest.fail("rewind must not confirm"))

    class ScriptedPromptSession:
        index = 0

        def __init__(self, **kwargs):
            pass

        def prompt(self, *args, **kwargs):
            index = self.index
            self.index += 1
            if index == 0:
                return "baseline"
            if index == 1:
                snapshots["chat"] = cli.chat.path.read_bytes()
                snapshots["history"] = list(cli.chat.history)
                snapshots["manifest"] = store.manifest_path.read_bytes()
                return "blocked write"
            if index == 2:
                bridge = cli._checkpoint_worker
                capture = cli._checkpoint_capture
                snapshots.update(bridge=bridge, capture=capture)
                assert bridge is not None and bridge.alive
                assert capture.barrier and not capture.finished and not capture.completed
                assert store.pending_path.exists()
                assert store.session_lock().acquire() is False
                assert store.manifest_path.read_bytes() == snapshots["manifest"]
                assert cli.chat.path.read_bytes() == snapshots["chat"]
                assert cli.chat.history == snapshots["history"]
                assert path.exists() is block_after_write
                return "/rewind 0"
            if index == 3:
                assert "Workspace is busy. Try again when its file operations finish." in capsys.readouterr().err
                release.set()
                assert snapshots["bridge"].close(timeout=3) is False
                assert path.read_bytes() == b"late bytes\n"
                assert snapshots["capture"].barrier
                assert store.pending_path.exists()
                assert store.session_lock().acquire() is False
                assert cli.chat.path.read_bytes() == snapshots["chat"]
                assert cli.chat.history == snapshots["history"]
                return "/rewind 0"
            if index == 4:
                assert (
                    "Earlier checkpoints are unavailable: a tool change could not be recorded."
                    in capsys.readouterr().err
                )
                assert cli._checkpoint_worker is None and cli._checkpoint_capture is None
                assert snapshots["capture"].finished
                assert store.pending_path.exists()
                lock = store.session_lock()
                assert lock.acquire()
                lock.release()
                return "after cancellation"
            raise EOFError

    monkeypatch.setattr(cli_module, "_prompt_session_class", lambda: ScriptedPromptSession)
    try:
        cli._run_repl()
    finally:
        release.set()
        bridge = snapshots.get("bridge") or cli._checkpoint_worker
        if bridge is not None:
            bridge.close(timeout=3)
        capture = snapshots.get("capture") or cli._checkpoint_capture
        if capture is not None:
            capture.store.abandon_turn(capture)
    assert watcher.interrupted
    assert "after cancellation" in requests
    assert path.read_bytes() == b"late bytes\n"
    assert not store.pending_path.exists()
    saved = json.loads(cli.chat.path.read_text(encoding="utf-8"))
    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert [message["content"] for message in saved["history"] if message["role"] == "user"] == [
        "baseline",
        "after cancellation",
    ]
    loaded = Chat(path=cli.chat.path)
    assert loaded.load()
    assert loaded.history == cli.chat.history
    assert manifest["head"] == saved["checkpoint_head"]
    assert all(record["id"] > 1 for record in manifest["records"])
    assert len(manifest["records"]) == 2
    assert manifest["records"][0]["turn"] == 0
    assert all(record["files"] == [] for record in manifest["records"])
