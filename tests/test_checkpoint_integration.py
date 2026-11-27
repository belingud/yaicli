"""Checkpoint acceptance through fresh CLI processes and the real guarded tool loop."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIP_FIRST = "Coast trip\nDay 1: beach\n"
TRIP_SECOND = "Coast trip\nDay 1: beach\nDay 2: hills\n"
PACKING = "boots\nwater\n"

# Only the provider and terminal input are replaced. Entry, REPL, LLMClient,
# ThreadedStream, tool dispatch/guards, chat saves and checkpoint IO stay real.
CLI_PROCESS = textwrap.dedent(
    r"""
    import importlib.abc
    import io
    import json
    import os
    import sys
    import threading
    from dataclasses import asdict
    from pathlib import Path

    payload = json.load(sys.stdin)
    sys.path.insert(0, payload["repo"])
    report = {"requests": [], "import_attempts": [], "workspace_env_at_start": os.environ.get("YAI_WORKSPACE_ROOT")}

    class CheckpointImportGuard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "yaicli.checkpoints":
                report["import_attempts"].append(fullname)
                if payload["forbid_checkpoints"]:
                    raise AssertionError("This CLI path must not import checkpoints")

    sys.meta_path.insert(0, CheckpointImportGuard())

    class TerminalInput(io.StringIO):
        def isatty(self):
            return payload["tty"]

    sys.stdin = TerminalInput("\n".join(payload["answers"]) + "\n")
    sys.stdout.isatty = lambda: payload["tty"]

    if not payload["meta"]:
        import yaicli.cli as cli_module
        from yaicli.llms.provider import Provider, ProviderFactory
        from yaicli.schemas import LLMResponse, ToolCall
        from yaicli.usage import Usage

        class ScriptedProvider(Provider):
            def __init__(self, config, **kwargs):
                self.config = config

            def completion(self, messages, stream=False, tool_policy=None):
                report["requests"].append({
                    "messages": [asdict(message) for message in messages],
                    "thread": threading.current_thread().name,
                    "stream": stream,
                })
                prompt = next(message.content for message in reversed(messages) if message.role == "user")
                writes = {
                    "write the itinerary": [("trip.md", "Coast trip\nDay 1: beach\n")],
                    "pack for the weekend": [
                        ("trip.md", "Coast trip\nDay 1: beach\nDay 2: hills\n"),
                        ("packing.md", "boots\nwater\n"),
                    ],
                    "rebuild original": [("original.bin", "rebuilt from scratch\n")],
                }
                operations = {
                    "copy original": {"operation": "copy", "path": "original.bin", "destination": "copied.bin"},
                    "move copy": {"operation": "move", "path": "copied.bin", "destination": "moved.bin"},
                    "delete original": {"operation": "delete", "path": "original.bin"},
                }
                if messages[-1].role == "user" and prompt in writes:
                    calls = [
                        ToolCall(
                            id=f"{prompt}-{index}",
                            name="fs_write_file",
                            arguments=json.dumps({"file_path": name, "content": content}),
                        )
                        for index, (name, content) in enumerate(writes[prompt])
                    ]
                    yield LLMResponse(tool_calls=calls, finish_reason="tool_calls", usage=Usage(10, 3, 13))
                elif messages[-1].role == "user" and prompt in operations:
                    call = ToolCall(id=prompt, name="fs_file_operations", arguments=json.dumps(operations[prompt]))
                    yield LLMResponse(tool_call=call, finish_reason="tool_calls", usage=Usage(10, 3, 13))
                else:
                    yield LLMResponse(content="answer: " + prompt + "\n", finish_reason="stop", usage=Usage(10, 3, 13))

            def detect_tool_role(self):
                return "tool"

        ProviderFactory.create_provider = staticmethod(lambda name, **kwargs: ScriptedProvider(**kwargs))
        instances = []
        original_init = cli_module.CLI.__init__

        def observe_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            instances.append(self)

        cli_module.CLI.__init__ = observe_init

        class ScriptedPromptSession:
            def __init__(self, **kwargs):
                self.inputs = iter(payload["inputs"])

            def prompt(self, *args, **kwargs):
                try:
                    return next(self.inputs)
                except StopIteration:
                    raise EOFError

        cli_module._prompt_session_class = lambda: ScriptedPromptSession

        class GenerationWatcher:
            def take_viewer_request(self):
                return False

            def stop(self):
                return ""

        # Starting a key watcher requires a physical terminal; its presence is
        # the existing seam that selects the real stream worker in the CLI.
        cli_module.CLI._start_generation_watcher = lambda self: (
            GenerationWatcher() if payload["worker"] and self.interactive else None
        )

    from yaicli._faststart import main

    sys.argv = ["ai", *payload["args"]]
    exit_code = 0
    try:
        main(payload["args"])
    except SystemExit as exc:
        exit_code = exc.code or 0
    finally:
        report["checkpoint_imported"] = "yaicli.checkpoints" in sys.modules
        if not payload["meta"] and instances:
            cli = instances[-1]
            report["chat"] = cli.chat.to_dict()
            report["chat_path"] = str(cli.chat.path) if cli.chat.path else None
            report["sessions"] = [
                {"idx": chat.idx, "title": chat.title} for chat in cli.chat_manager.list_chats()
            ]
            report["had_error"] = cli.had_error
        Path(payload["report"]).write_text(json.dumps(report), encoding="utf-8")
    raise SystemExit(exit_code)
    """
)


def run_cli(
    root,
    args,
    *,
    inputs=(),
    answers=(),
    tty=True,
    worker=False,
    forbid_checkpoints=False,
    enabled=True,
    workspace_from_config=False,
    cwd=None,
):
    """Use a fresh interpreter with no inherited config, secrets or real HOME."""
    home = root / "home"
    project = root / "project"
    home.mkdir(exist_ok=True)
    project.mkdir(exist_ok=True)
    report_path = root / "process-report.json"
    payload = {
        "repo": str(REPO_ROOT),
        "report": str(report_path),
        "args": args,
        "inputs": list(inputs),
        "answers": list(answers),
        "tty": tty,
        "worker": worker,
        "meta": args[0] in ("--help", "--version"),
        "forbid_checkpoints": forbid_checkpoints,
    }
    env = {
        "PATH": os.defpath,
        "HOME": str(home),
        "YAI_CONFIG_DIR": str(home / "config"),
        "YAI_CHAT_HISTORY_DIR": str(home / "sessions"),
        "YAI_WORKSPACE_ROOT": str(project),
        "YAI_PROVIDER": "openai",
        "YAI_MODEL": "checkpoint-test",
        "YAI_MODEL_CONTEXT_WINDOWS": '{"checkpoint-test": 128000}',
        "YAI_ENABLE_FUNCTIONS": "true",
        "YAI_ENABLE_MCP": "false",
        "YAI_ENABLE_PROJECT_CONTEXT": "false",
        "YAI_CHECKPOINT_ENABLED": str(enabled).lower(),
        "YAI_STREAM": str(worker).lower(),
        "YAI_SHOW_USAGE": "false",
        "YAI_RETRY_ENABLED": "false",
        "YAI_OS_NAME": "test-os",
        "YAI_SHELL_NAME": "test-shell",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "COLUMNS": "200",
    }
    if workspace_from_config:
        env.pop("YAI_WORKSPACE_ROOT")
        config_dir = home / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "config.ini").write_text(f"[core]\nWORKSPACE_ROOT={project}\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", CLI_PROCESS],
        input=json.dumps(payload),
        cwd=cwd or project,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert not report.get("had_error"), result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    return result, report


def saved_chats(root):
    return {
        data["title"]: (path, data)
        for path in (root / "home" / "sessions").glob("*.json")
        for data in [json.loads(path.read_text(encoding="utf-8"))]
    }


def manifest(root, session_id):
    paths = list((root / "home" / "sessions" / "checkpoints").glob(f"*/{session_id}/manifest.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


@pytest.mark.parametrize("worker", [False, True], ids=["sync", "stream-worker"])
def test_config_only_workspace_root_survives_first_write_resume_and_rewind(tmp_path, worker):
    project = tmp_path / "project"
    cwd = project / "nested"
    cwd.mkdir(parents=True)
    options = {"workspace_from_config": True, "cwd": cwd, "worker": worker}

    result, created = run_cli(
        tmp_path,
        ["--chat", "Config root", "--allowed-tools", "fs_write_file"],
        inputs=["write the itinerary", "/checkpoints", "pack for the weekend", "/checkpoints"],
        **options,
    )

    assert created["workspace_env_at_start"] is None
    assert result.stderr == 'No saved session titled "Config root" for this project; starting a new session.\n'
    assert "No checkpoints for this session." not in result.stdout
    assert "#1" in result.stdout and "#2" in result.stdout
    current_rows = [
        line.split()[0] for line in result.stdout.splitlines() if line.startswith("#") and line.endswith("current")
    ]
    assert current_rows == ["#1", "#2"]
    source_path, source = saved_chats(tmp_path)["Config root"]
    session_id = source["checkpoint_session_id"]
    before = manifest(tmp_path, session_id)
    assert created["chat_path"] == str(source_path)
    assert created["chat"]["checkpoint_session_id"] == before["session_id"] == session_id
    assert created["chat"]["checkpoint_head"] == source["checkpoint_head"] == before["head"] == 2
    assert before["root"] == str(project.resolve())
    assert before["session_path"] == str(source_path.resolve())
    assert [record["id"] for record in before["records"]] == [0, 1, 2]
    assert [[item["path"] for item in record["files"]] for record in before["records"]] == [
        [],
        ["nested/trip.md"],
        ["nested/trip.md", "nested/packing.md"],
    ]
    tool_messages = [message for message in source["history"] if message["role"] == "tool"]
    assert len(tool_messages) == 3
    assert all(json.loads(message["content"])["success"] for message in tool_messages)
    assert all((request["thread"] != "MainThread") is worker for request in created["requests"])
    assert (cwd / "trip.md").read_bytes() == TRIP_SECOND.encode()
    assert (cwd / "packing.md").read_bytes() == PACKING.encode()

    result, resumed = run_cli(tmp_path, ["--resume"], inputs=["/checkpoints"], **options)

    assert resumed["workspace_env_at_start"] is None
    assert result.stderr == ""
    assert "#2" in result.stdout and "current" in result.stdout
    assert resumed["chat_path"] == str(source_path)
    assert resumed["chat"]["checkpoint_session_id"] == session_id
    assert resumed["chat"]["checkpoint_head"] == 2
    assert resumed["chat"]["history"] == source["history"]
    assert manifest(tmp_path, session_id) == before

    result, rewound = run_cli(tmp_path, ["--resume"], inputs=["/rewind 1"], answers=["y"], **options)

    assert rewound["workspace_env_at_start"] is None
    assert result.stderr == ""
    assert "Restore: nested/trip.md" in result.stdout
    assert "Remove:  nested/packing.md" in result.stdout
    assert "Rewound to #1." in result.stdout
    saved_path, saved = saved_chats(tmp_path)["Config root"]
    after = manifest(tmp_path, session_id)
    assert saved_path == source_path
    assert rewound["chat_path"] == str(source_path)
    assert saved["checkpoint_session_id"] == rewound["chat"]["checkpoint_session_id"] == session_id
    assert saved["checkpoint_head"] == rewound["chat"]["checkpoint_head"] == after["head"] == 1
    assert saved["history"] == rewound["chat"]["history"]
    assert [message["content"] for message in saved["history"] if message["role"] == "user"] == ["write the itinerary"]
    assert after["root"] == before["root"]
    assert after["session_path"] == before["session_path"]
    assert [record["id"] for record in after["records"]] == [0, 1]
    assert after["next"] > 2
    assert (cwd / "trip.md").read_bytes() == TRIP_FIRST.encode()
    assert not (cwd / "packing.md").exists()


@pytest.mark.parametrize(("restore_entry", "worker", "command"), [("resume", False, "rewind"), ("load", True, "fork")])
def test_real_turns_survive_restart_and_restore_chat_manifest_and_files(tmp_path, restore_entry, worker, command):
    result, created = run_cli(
        tmp_path,
        ["--chat", "Trip", "--allowed-tools", "fs_write_file"],
        inputs=["where next?", "write the itinerary", "pack for the weekend"],
        worker=worker,
    )
    assert result.stderr == 'No saved session titled "Trip" for this project; starting a new session.\n'
    source_path, source = saved_chats(tmp_path)["Trip"]
    source_id = source["checkpoint_session_id"]
    before = manifest(tmp_path, source_id)
    assert source["checkpoint_head"] == before["head"] == 3
    assert [record["id"] for record in before["records"]] == [0, 1, 2, 3]
    assert [len(record["files"]) for record in before["records"]] == [0, 0, 1, 2]
    assert (tmp_path / "project" / "trip.md").read_bytes() == TRIP_SECOND.encode()
    assert (tmp_path / "project" / "packing.md").read_bytes() == PACKING.encode()
    tool_messages = [message for message in source["history"] if message["role"] == "tool"]
    assert len(tool_messages) == 3
    assert all(json.loads(message["content"])["success"] for message in tool_messages)
    assert all(request["stream"] is worker for request in created["requests"])
    assert all((request["thread"] != "MainThread") is worker for request in created["requests"])

    # Request messages carry conversation/tool data, never storage bookkeeping.
    requests = json.dumps(created["requests"])
    for private in (source_id, "checkpoint_head", "checkpoint_session_id", "manifest.json", "checkpoints/"):
        assert private not in requests

    args = ["--resume"] if restore_entry == "resume" else ["--chat"]
    inputs = [] if restore_entry == "resume" else ["/load 1"]
    inputs += ["continue", "/checkpoints", f"/{command} 2 Weekend draft" if command == "fork" else "/rewind 2"]
    inputs += ["/rewind 3"]
    result, restored = run_cli(tmp_path, args, inputs=inputs, answers=["y"], worker=worker)

    assert "#4" in result.stdout and "current" in result.stdout
    assert "Restore: trip.md" in result.stdout
    assert "Remove:  packing.md" in result.stdout
    assert "Rewound to #2." in result.stdout
    assert result.stderr == "Checkpoint #3 is unavailable.\n"
    assert restored["requests"][0]["messages"][-1]["content"] == "continue"
    assert [message["content"] for message in restored["requests"][0]["messages"] if message["role"] == "user"] == [
        "where next?",
        "write the itinerary",
        "pack for the weekend",
        "continue",
    ]
    current_path, current = saved_chats(tmp_path)["Trip"]
    after = manifest(tmp_path, source_id)
    assert current_path == source_path
    assert current["checkpoint_session_id"] == source_id
    assert current["checkpoint_head"] == after["head"] == restored["chat"]["checkpoint_head"] == 2
    assert [record["id"] for record in after["records"]] == [0, 1, 2]
    assert after["next"] > 4
    checkpoint_dir = next((tmp_path / "home" / "sessions" / "checkpoints").glob(f"*/{source_id}"))
    target_snapshot = json.loads((checkpoint_dir / after["records"][-1]["snapshot"]).read_text(encoding="utf-8"))
    assert target_snapshot["history"] == current["history"] == restored["chat"]["history"]
    assert target_snapshot["checkpoint_head"] == 2
    assert target_snapshot["checkpoint_session_id"] == source_id
    assert [message["content"] for message in current["history"] if message["role"] == "user"] == [
        "where next?",
        "write the itinerary",
    ]
    assert (tmp_path / "project" / "trip.md").read_bytes() == TRIP_FIRST.encode()
    assert not (tmp_path / "project" / "packing.md").exists()

    if command == "fork":
        _, archive = saved_chats(tmp_path)["Weekend draft"]
        assert not archive.get("checkpoint_session_id")
        assert not archive.get("plan")
        assert [message["content"] for message in archive["history"] if message["role"] == "user"] == [
            "where next?",
            "write the itinerary",
            "pack for the weekend",
            "continue",
        ]
        archive_index = next(item["idx"] for item in restored["sessions"] if item["title"] == "Weekend draft")
        result, loaded = run_cli(tmp_path, ["--chat"], inputs=[f"/load {archive_index}", "archive followup"])
        assert "Loaded chat: Weekend draft" in result.stdout
        assert loaded["chat"]["checkpoint_session_id"] != source_id
        archive_manifest = manifest(tmp_path, loaded["chat"]["checkpoint_session_id"])
        assert archive_manifest["head"] == loaded["chat"]["checkpoint_head"] == 1
        assert loaded["chat"]["history"][:-2] == archive["history"]
        assert loaded["chat"]["history"][-2]["content"] == "archive followup"
        assert (tmp_path / "project" / "trip.md").read_bytes() == TRIP_FIRST.encode()
        assert not (tmp_path / "project" / "packing.md").exists()


def test_copy_move_delete_and_recreate_rewind_across_processes(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    original = project / "original.bin"
    original_bytes = b"\x00original\r\n\xff\x80\n"
    original.write_bytes(original_bytes)
    original.chmod(0o751)
    original_mode = original.stat().st_mode & 0o777
    prompts = ["file baseline", "copy original", "move copy", "delete original", "rebuild original"]

    _, created = run_cli(
        tmp_path,
        ["--chat", "Files", "--allowed-tools", "fs_file_operations,fs_write_file"],
        inputs=prompts,
        worker=True,
    )
    _, source = saved_chats(tmp_path)["Files"]
    session_id = source["checkpoint_session_id"]
    before = manifest(tmp_path, session_id)
    assert before["head"] == source["checkpoint_head"] == 5
    assert [len(record["files"]) for record in before["records"]] == [0, 0, 1, 2, 1, 1]
    calls = [call for message in source["history"] for call in message.get("tool_calls", [])]
    assert [call["name"] for call in calls] == ["fs_file_operations"] * 3 + ["fs_write_file"]
    assert [json.loads(call["arguments"])["operation"] for call in calls[:3]] == ["copy", "move", "delete"]
    results = [json.loads(message["content"]) for message in source["history"] if message["role"] == "tool"]
    assert len(results) == 4 and all(result["success"] for result in results)
    assert all(request["thread"] != "MainThread" for request in created["requests"])
    assert original.read_bytes() == b"rebuilt from scratch\n"
    assert not (project / "copied.bin").exists()
    assert (project / "moved.bin").read_bytes() == original_bytes

    result, restored = run_cli(tmp_path, ["--resume"], inputs=["/checkpoints", "/rewind 1"], answers=["y"])

    assert result.stderr == ""
    assert "Rewound to #1." in result.stdout
    assert original.read_bytes() == original_bytes
    assert original.stat().st_mode & 0o777 == original_mode
    assert not (project / "copied.bin").exists()
    assert not (project / "moved.bin").exists()
    _, saved = saved_chats(tmp_path)["Files"]
    after = manifest(tmp_path, session_id)
    assert saved["history"] == restored["chat"]["history"]
    assert [message["content"] for message in saved["history"] if message["role"] == "user"] == ["file baseline"]
    assert saved["checkpoint_session_id"] == session_id
    assert saved["checkpoint_head"] == after["head"] == 1
    assert [record["id"] for record in after["records"]] == [0, 1]
    assert after["next"] > 5


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_meta_entry_does_not_import_checkpoints_or_create_store(tmp_path, flag):
    result, report = run_cli(tmp_path, [flag], tty=False, forbid_checkpoints=True)
    assert "Usage:" in result.stdout if flag == "--help" else result.stdout.startswith("yaicli ")
    assert not report["import_attempts"]
    assert not report["checkpoint_imported"]
    assert list((tmp_path / "home").iterdir()) == []


def test_unsaved_interactive_turn_does_not_import_checkpoints_or_create_store(tmp_path):
    _, report = run_cli(tmp_path, ["--chat"], inputs=["temporary chat"], worker=True, forbid_checkpoints=True)
    assert report["chat"]["history"][-1]["content"] == "answer: temporary chat\n"
    assert not report["import_attempts"]
    assert not report["checkpoint_imported"]
    assert not (tmp_path / "home" / "sessions").exists()


@pytest.mark.parametrize(
    ("args", "enabled"),
    [(["--chat", "Trip", "--quiet"], True), (["--chat", "Trip"], False)],
    ids=["quiet", "disabled"],
)
def test_ineligible_persistent_turn_saves_chat_without_importing_checkpoints(tmp_path, args, enabled):
    _, report = run_cli(
        tmp_path,
        args,
        inputs=["private chat"],
        enabled=enabled,
        forbid_checkpoints=True,
    )
    _, saved = saved_chats(tmp_path)["Trip"]
    assert saved["history"][-1]["content"] == "answer: private chat\n"
    assert not saved.get("checkpoint_session_id")
    assert not report["import_attempts"]
    assert not report["checkpoint_imported"]
    assert not (tmp_path / "home" / "sessions" / "checkpoints").exists()


@pytest.mark.parametrize("output_format", ["text", "json", "stream-json"])
def test_headless_keeps_exact_output_without_importing_checkpoints(tmp_path, output_format):
    args = ["-p", "/rewind 2", "--output-format", output_format]
    result, report = run_cli(tmp_path, args, tty=False, forbid_checkpoints=True)
    without_checkpoints, _ = run_cli(tmp_path, args, tty=False, forbid_checkpoints=True, enabled=False)
    assert result.stdout == without_checkpoints.stdout
    assert result.stderr == without_checkpoints.stderr == ""
    assert report["requests"][0]["messages"][-1]["content"] == "/rewind 2"
    assert not report["import_attempts"]
    assert not report["checkpoint_imported"]
    assert not (tmp_path / "home" / "sessions").exists()
    if output_format == "text":
        assert result.stdout == "answer: /rewind 2\n"
    elif output_format == "json":
        data = json.loads(result.stdout)
        assert set(data) == {
            "content",
            "tool_calls",
            "usage",
            "finish_reason",
            "model",
            "provider",
            "error",
            "exit_code",
        }
        assert data["content"] == "answer: /rewind 2\n"
        assert data["tool_calls"] == []
        assert data["exit_code"] == 0 and data["error"] is None
        assert result.stdout.count("\n") == 1
    else:
        events = [json.loads(line) for line in result.stdout.splitlines()]
        assert [event["type"] for event in events] == ["turn_start", "text_delta", "usage", "done"]
        assert events[1]["delta"] == "answer: /rewind 2\n"
        assert events[-1]["exit_code"] == 0
