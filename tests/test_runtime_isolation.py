"""Independent contracts for application-owned configuration and plan state.

The two legacy-surface tests also run against an archived stage-two tree. Tests
never reset plan state between the A -> B -> A operations being checked.
"""

import inspect
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from yaicli import cli as cli_module
from yaicli.chat import FileChatManager
from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall

MANAGED_ENV = ("YAI_WORKSPACE_ROOT", "YAI_TOOL_TIMEOUT", "YAI_TOOL_ENV_INHERIT", "YAI_TOOL_OUTPUT_MAX_CHARS")


def _config(tmp_path, name, **overrides):
    result = deepcopy(dict(cfg))
    result.update(
        MODEL=f"runtime-{name}",
        MODEL_CONTEXT_WINDOWS={f"runtime-{name}": 128000},
        MODEL_PRICING={f"runtime-{name}": {"input": 1.0, "output": 2.0}},
        CHAT_HISTORY_DIR=str(tmp_path / name / "sessions"),
        WORKSPACE_ROOT=str(tmp_path / name),
        PLAN_DIR=str(tmp_path / name / "plans"),
        OS_NAME="test-os",
        SHELL_NAME="test-shell",
        ENABLE_MCP=False,
        ENABLE_PROJECT_CONTEXT=False,
        SHOW_USAGE=False,
        SHOW_FUNCTION_OUTPUT=False,
        SHOW_MCP_OUTPUT=False,
        RETRY_ENABLED=False,
        TOOL_AUDIT=False,
        TOOL_CONFIRM=False,
        TOOL_POLICY="standard",
        ENABLED_TOOLS="",
    )
    result.update(overrides)
    return result


def test_model_prompt_keeps_its_application_configuration(tmp_path, monkeypatch):
    """An existing CLI surface must not switch models when B is constructed."""
    source_a = _config(tmp_path, "a")
    source_b = _config(tmp_path, "b")
    monkeypatch.setattr(cli_module, "cfg", source_a)
    first = CLI(client=MagicMock(), chat_manager=FileChatManager(tmp_path / "a-sessions"))
    monkeypatch.setattr(cli_module, "cfg", source_b)
    second = CLI(client=MagicMock(), chat_manager=FileChatManager(tmp_path / "b-sessions"))

    assert first._prompt_model_name() == "runtime-a"
    assert second._prompt_model_name() == "runtime-b"
    assert first._prompt_model_name() == "runtime-a"


def test_default_manager_saves_to_its_original_application_directory(tmp_path, monkeypatch):
    """Saving A after constructing B must still write into A's real store."""
    for key, value in _config(tmp_path, "a").items():
        monkeypatch.setitem(cfg, key, value)
    first = CLI(client=MagicMock())
    for key, value in _config(tmp_path, "b").items():
        monkeypatch.setitem(cfg, key, value)
    second = CLI(client=MagicMock())
    first.chat.history = [ChatMessage(role="user", content="from A")]
    second.chat.history = [ChatMessage(role="user", content="from B")]
    first.sessions.save_chat_inner("A saved after B")
    second.sessions.save_chat_inner("B")

    a_files = list((tmp_path / "a" / "sessions").glob("*.json"))
    b_files = list((tmp_path / "b" / "sessions").glob("*.json"))
    assert len(a_files) == len(b_files) == 1
    assert json.loads(a_files[0].read_text())["history"] == [{"role": "user", "content": "from A"}]
    assert json.loads(b_files[0].read_text())["history"] == [{"role": "user", "content": "from B"}]


def _exercise_plan_ownership(root):
    """Run in a fresh interpreter, without conftest or global reset fixtures."""
    from yaicli import tools
    from yaicli.llms.provider import ProviderFactory
    from yaicli.llms.providers.anthropic_provider import AnthropicProvider
    from yaicli.llms.providers.openai_provider import OpenAIProvider
    from yaicli.planning import service
    from yaicli.tools import executor, schemas
    from yaicli.tools.session_tools import SubmitPlanFunction

    def forbidden(*args, **kwargs):
        raise AssertionError("explicit application path read a default plan/tool mode")

    first = CLI(config=_config(root, "a", ENABLED_TOOLS="fs_read_file,submit_plan,todo_write"), client=MagicMock())
    second = CLI(config=_config(root, "b", ENABLED_TOOLS="web_search,submit_plan,todo_write"), client=MagicMock())
    assert first.runtime.peek_plan_session() is second.runtime.peek_plan_session() is None
    with ExitStack() as stack:
        stack.enter_context(patch.object(service, "get_plan_session", forbidden))
        stack.enter_context(patch.object(schemas, "get_plan_tool_mode", forbidden))
        if hasattr(executor, "get_plan_tool_mode"):
            stack.enter_context(patch.object(executor, "get_plan_tool_mode", forbidden))
        stack.enter_context(patch.object(OpenAIProvider, "CLIENT_CLS", MagicMock()))
        stack.enter_context(patch.object(AnthropicProvider, "CLIENT_CLS", MagicMock()))
        stack.enter_context(patch("yaicli.llms.providers.gemini_provider.genai.Client", MagicMock()))
        first._toggle_plan_mode()
        assert first.plan_session.mode == "researching"
        assert second.runtime.peek_plan_session() is None
        providers = {
            name: [
                ProviderFactory.create_provider(name, config=app.config, runtime=app.runtime) for app in (first, second)
            ]
            for name in ("openai", "anthropic", "gemini")
        }

        def names(index, family):
            provider = providers[family][index]
            if family == "openai":
                return {item["function"]["name"] for item in provider.get_tools()}
            if family == "anthropic":
                provider.client.messages.create.return_value = SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="text", text="done")],
                    usage=None,
                    stop_reason="end_turn",
                )
                list(provider.completion([ChatMessage(role="user", content="test")]))
                return {item["name"] for item in provider.client.messages.create.call_args.kwargs.get("tools", [])}
            return {func.__name__ for func in provider.gen_gemini_functions()}

        for family in providers:
            offered_a = names(0, family)
            offered_b = names(1, family)
            assert "submit_plan" in offered_a
            assert "todo_write" not in offered_a
            assert "fs_write_file" not in offered_a
            assert "submit_plan" not in offered_b
            assert "todo_write" not in offered_b
            assert "fs_write_file" in offered_b if family == "gemini" else offered_b == {"web_search"}
            assert names(0, family) == offered_a

        # Capture A's callback, generate B's different declarations, then call A.
        callback_a = next(
            func for func in providers["gemini"][0].gen_gemini_functions() if func.__name__ == "submit_plan"
        )
        assert inspect.signature(callback_a) == inspect.signature(SubmitPlanFunction.execute)
        assert not ({"runtime", "session", "config"} & set(inspect.signature(callback_a).parameters))
        second._toggle_plan_mode()
        names(1, "gemini")
        payload = {"goal": "A only", "steps": [{"title": "Read A", "acceptance": "A read"}]}
        result_a = json.loads(callback_a(**payload))
        assert result_a["success"] is True, result_a
        assert first.plan_session.mode == "reviewing"
        assert first.plan_session.draft_plan.goal == "A only"
        assert second.plan_session.mode == "researching"
        assert second.plan_session.draft_plan is None
        plan_a_path = first.plan_session.draft_plan.path
        assert plan_a_path.is_file()
        assert plan_a_path.is_relative_to(root / "a" / "plans")

        service.approve_new_plan(first.plan_session)
        for family in providers:
            assert "todo_write" in names(0, family)
            assert "submit_plan" in names(1, family)
            assert "todo_write" in names(0, family)
        todo_a = first.plan_session.todos[0]
        result, ok = tools.execute_tool_call(
            ToolCall(
                id="todo-a",
                name="todo_write",
                arguments=json.dumps({"items": [{"id": todo_a.id, "content": todo_a.content, "status": "completed"}]}),
            ),
            announce=False,
            runtime=first.runtime,
        )
        assert ok and json.loads(result)["success"], result
        assert first.plan_session.todos[0].status == "completed"
        assert second.plan_session.todos == []
        assert second.plan_session.mode == "researching"
        assert not list((root / "b" / "plans").rglob("*.md"))


def test_fresh_process_alternates_real_plan_schemas_callbacks_and_tools(tmp_path):
    """No test fixture may repair global state between the A/B/A operations."""
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path / "home"),
        "YAI_CONFIG_DIR": str(tmp_path / "config"),
        "YAI_API_KEY": "fake-runtime-test-key",
        "YAI_PROVIDER": "openai",
        "YAI_MODEL": "runtime-test",
        "NO_COLOR": "1",
    }
    script = "import runpy,sys; from pathlib import Path; ns=runpy.run_path(sys.argv[1]); ns['_exercise_plan_ownership'](Path(sys.argv[2]))"
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).resolve()), str(tmp_path)],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_owns_one_deep_configuration_snapshot_and_rebuilds_its_client(tmp_path, monkeypatch):
    from yaicli.llms.provider import ProviderFactory

    source = _config(tmp_path, "a")
    first = CLI(config=source)
    second = CLI(config=source)
    source["MODEL_PRICING"]["runtime-a"]["input"] = 999
    first.config["MODEL_PRICING"]["runtime-a"]["output"] = 77
    assert first.config["MODEL_PRICING"]["runtime-a"]["input"] == 1
    assert second.config["MODEL_PRICING"]["runtime-a"] == {"input": 1.0, "output": 2.0}
    assert first.runtime.config is first.config
    assert first.sessions.config is first.config
    assert first.output.config is first.config
    built = []

    def create_provider(name, **kwargs):
        provider = MagicMock()
        provider.config = kwargs["config"]
        provider.runtime = kwargs.get("runtime")
        provider.model_limits.return_value = None
        built.append(provider)
        return provider

    monkeypatch.setattr(ProviderFactory, "create_provider", create_provider)
    old_client = first.client
    first.cmd_handler.handle_model("/model changed-A")
    rebuilt = first.client
    assert rebuilt is not old_client
    assert rebuilt.config is first.config
    assert rebuilt.runtime is first.runtime
    assert first.config["MODEL"] == "changed-A"
    assert second.config["MODEL"] == "runtime-a"
    assert built[-1].config["MODEL"] == "changed-A"


def test_actual_tool_rounds_use_owned_selection_permissions_and_output_caps(tmp_path, monkeypatch):
    from yaicli.llms.client import LLMClient
    from yaicli.llms.provider import Provider, ProviderFactory
    from yaicli.runtime import SessionContext

    path = tmp_path / "note.txt"
    path.write_text("abcdefghijklmnopqrstuvwxyz" * 200)

    class ScriptedProvider(Provider):
        def __init__(self, name, arguments):
            self.name, self.arguments = name, arguments

        def completion(self, messages, stream=False, tool_policy=None):
            if messages[-1].role == "user":
                yield LLMResponse(
                    tool_call=ToolCall(id="owned-call", name=self.name, arguments=json.dumps(self.arguments))
                )
            else:
                yield LLMResponse(content="done")

        def detect_tool_role(self):
            return "tool"

    def run(config, name, arguments):
        provider = ScriptedProvider(name, arguments)
        provider.config = config
        monkeypatch.setattr(ProviderFactory, "create_provider", lambda *args, **kwargs: provider)
        runtime = SessionContext(config)
        client = LLMClient("openai", config=config, runtime=runtime, interactive=False)
        messages = [ChatMessage(role="user", content="do it")]
        list(client.completion_with_tools(messages, stream=False))
        return next(message.content for message in messages if message.role == "tool")

    small = _config(
        tmp_path, "a", WORKSPACE_ROOT=str(tmp_path), ENABLED_TOOLS="fs_read_file", TOOL_OUTPUT_MAX_CHARS=300
    )
    large = _config(tmp_path, "b", WORKSPACE_ROOT=str(tmp_path), ENABLED_TOOLS="fs_read_file", TOOL_OUTPUT_MAX_CHARS=0)
    first = run(small, "fs_read_file", {"file_paths": [str(path)]})
    other = run(large, "fs_read_file", {"file_paths": [str(path)]})
    again = run(small, "fs_read_file", {"file_paths": [str(path)]})
    assert len(first) <= 300 and len(again) <= 300
    assert json.loads(other)["content"] == path.read_text()
    assert len(other) > 5000
    disabled = run(small, "fs_write_file", {"file_path": str(path), "content": "bad"})
    assert json.loads(disabled)["error"] == "tool_disabled"
    readonly = _config(tmp_path, "readonly", WORKSPACE_ROOT=str(tmp_path), TOOL_POLICY="readonly")
    denied = run(readonly, "fs_write_file", {"file_path": str(path), "content": "bad"})
    assert json.loads(denied)["error"] == "tool_denied"
    assert path.read_text() == "abcdefghijklmnopqrstuvwxyz" * 200


@pytest.fixture
def undo_state():
    from yaicli.tools import workspace

    workspace.reset_undo()
    yield
    workspace.reset_undo()


def test_tool_environment_restores_after_real_mutation_denial_and_exception(tmp_path, monkeypatch, undo_state):
    from yaicli import tools
    from yaicli.runtime import SessionContext
    from yaicli.tools import executor

    roots = [tmp_path / name for name in ("a", "b")]
    for root in roots:
        root.mkdir()
    for index, key in enumerate(MANAGED_ENV):
        monkeypatch.setenv(key, f"original-{index}")
    monkeypatch.setenv("UNMANAGED_RUNTIME_TEST", "keep-this")
    before = {key: os.environ.get(key) for key in MANAGED_ENV}
    contexts = [
        SessionContext(_config(tmp_path, name, TOOL_TIMEOUT=timeout)) for name, timeout in (("a", 3), ("b", 11))
    ]
    for runtime, root, content in (
        (contexts[0], roots[0], "A"),
        (contexts[1], roots[1], "B"),
        (contexts[0], roots[0], "A2"),
    ):
        call = ToolCall(
            id=content,
            name="fs_write_file",
            arguments=json.dumps({"file_path": str(root / "note.txt"), "content": content}),
        )
        result, ok = tools.execute_tool_call(call, announce=False, runtime=runtime)
        assert ok and json.loads(result)["success"], result
        assert {key: os.environ.get(key) for key in MANAGED_ENV} == before
    assert (roots[0] / "note.txt").read_bytes() == b"A2"
    assert (roots[1] / "note.txt").read_bytes() == b"B"
    first = CLI(config=contexts[0].config, client=MagicMock())
    assert first.cmd_handler.handle_undo() is True
    assert (roots[0] / "note.txt").read_bytes() == b"A"
    assert (roots[1] / "note.txt").read_bytes() == b"B"
    assert {key: os.environ.get(key) for key in MANAGED_ENV} == before
    denied, ok = tools.execute_tool_call(
        ToolCall(
            id="outside",
            name="fs_write_file",
            arguments=json.dumps({"file_path": str(roots[1] / "intrusion.txt"), "content": "bad"}),
        ),
        announce=False,
        runtime=contexts[0],
    )
    assert ok and json.loads(denied)["success"] is False
    assert not (roots[1] / "intrusion.txt").exists()
    assert {key: os.environ.get(key) for key in MANAGED_ENV} == before
    monkeypatch.chdir(tmp_path)
    default_runtime = SessionContext(
        _config(
            tmp_path, "default", WORKSPACE_ROOT="", TOOL_TIMEOUT=None, TOOL_ENV_INHERIT="", TOOL_OUTPUT_MAX_CHARS=""
        )
    )
    default_result, ok = tools.execute_tool_call(
        ToolCall(
            id="defaults",
            name="fs_write_file",
            arguments=json.dumps({"file_path": "default.txt", "content": "default-root"}),
        ),
        announce=False,
        runtime=default_runtime,
    )
    assert ok and json.loads(default_result)["success"], default_result
    assert (tmp_path / "default.txt").read_bytes() == b"default-root"
    assert {key: os.environ.get(key) for key in MANAGED_ENV} == before
    observed = []

    def broken(**kwargs):
        observed.append({key: os.environ.get(key) for key in MANAGED_ENV})
        raise RuntimeError("deliberate standalone failure")

    tool = SimpleNamespace(execute=broken, source="user")
    with patch.object(executor, "get_function", return_value=tool):
        result, ok = tools.execute_tool_call(
            ToolCall(id="broken", name="user_probe", arguments="{}"), announce=False, runtime=contexts[0]
        )
    assert not ok and "deliberate standalone failure" in result
    assert observed[0]["YAI_WORKSPACE_ROOT"] == str(roots[0])
    assert observed[0]["YAI_TOOL_TIMEOUT"] == "3"
    assert {key: os.environ.get(key) for key in MANAGED_ENV} == before
    assert os.environ["UNMANAGED_RUNTIME_TEST"] == "keep-this"


def test_empty_environment_values_and_nested_binding_restore_on_failure(tmp_path, monkeypatch):
    from yaicli.runtime import bind_config, current_config
    from yaicli.tools.environment import tool_environment

    for key in MANAGED_ENV:
        monkeypatch.setenv(key, "old-value")
    before = {key: os.environ[key] for key in MANAGED_ENV}
    first = _config(tmp_path, "a")
    empty = {"WORKSPACE_ROOT": "", "TOOL_TIMEOUT": None, "TOOL_ENV_INHERIT": "", "TOOL_OUTPUT_MAX_CHARS": ""}
    with bind_config(first):
        assert current_config({}) is first
        with pytest.raises(RuntimeError, match="deliberate"):
            with tool_environment(empty):
                assert current_config(first) is empty
                assert all(key not in os.environ for key in MANAGED_ENV)
                raise RuntimeError("deliberate")
        assert current_config({}) is first
    assert {key: os.environ[key] for key in MANAGED_ENV} == before
    with bind_config({}):
        assert current_config(first) == {}


def test_save_and_actual_tool_spills_use_the_owning_redaction_configuration(tmp_path):
    from yaicli import tools

    # Deliberately synthetic credential-shaped text; no user credentials are read.
    secret = "sk-" + "A" * 48
    path = tmp_path / "input.txt"
    path.write_text(secret + "\n" + "x" * 3000)
    first = CLI(
        config=_config(
            tmp_path, "a", REDACT_SECRETS=True, TOOL_OUTPUT_MAX_CHARS=300, TOOL_OUTPUT_DIR=str(tmp_path / "a-spills")
        ),
        client=MagicMock(),
    )
    second = CLI(
        config=_config(
            tmp_path, "b", REDACT_SECRETS=False, TOOL_OUTPUT_MAX_CHARS=300, TOOL_OUTPUT_DIR=str(tmp_path / "b-spills")
        ),
        client=MagicMock(),
    )
    for app in (first, second, first):
        app.chat.history = [ChatMessage(role="user", content=secret)]
        app.sessions.save_chat_inner("secret-shaped fixture")
        result, ok = tools.execute_tool_call(
            ToolCall(id="spill", name="fs_read_file", arguments=json.dumps({"file_paths": [str(path)]})),
            announce=False,
            runtime=app.runtime,
        )
        assert ok and len(result) <= 300
        assert app.chat.history[0].content == secret
    a_saved = json.loads(first.chat.path.read_text())
    b_saved = json.loads(second.chat.path.read_text())
    assert a_saved["history"][0]["content"] == "[redacted]"
    assert b_saved["history"][0]["content"] == secret
    a_spills = list((tmp_path / "a-spills").glob("*.txt"))
    b_spills = list((tmp_path / "b-spills").glob("*.txt"))
    assert len(a_spills) == 2 and len(b_spills) == 1
    assert all(secret not in item.read_text() and "[redacted]" in item.read_text() for item in a_spills)
    assert secret in b_spills[0].read_text()


def test_delayed_gemini_builtin_and_mcp_callbacks_keep_their_configuration(tmp_path, monkeypatch):
    from yaicli import tools
    from yaicli.llms.provider import ProviderFactory
    from yaicli.llms.providers import gemini_provider
    from yaicli.runtime import current_config
    from yaicli.tools import mcp, schemas

    first = CLI(
        config=_config(tmp_path, "a", ENABLE_MCP=True, MCP_MAX_TOOLS=1, MCP_TIMEOUT=3, ENABLED_TOOLS="fs_read_file"),
        client=MagicMock(),
    )
    second = CLI(config=_config(tmp_path, "b", ENABLE_MCP=True, MCP_MAX_TOOLS=2, MCP_TIMEOUT=11), client=MagicMock())
    for app in (first, second):
        Path(app.config["WORKSPACE_ROOT"]).mkdir()
        (Path(app.config["WORKSPACE_ROOT"]) / "probe.txt").write_text(app.config["MODEL"])
    before = {key: os.environ.get(key) for key in MANAGED_ENV}

    class Transport:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def call_tool(self, name, arguments):
            return json.dumps({"tool": name, "timeout": current_config({})["MCP_TIMEOUT"], **arguments})

    # Only replace the remote transport. Cached lists, cap evaluation, converters,
    # callable generation, MCP.execute and the async invocation remain real.
    client = object.__new__(mcp.MCPClient)
    client._client = Transport()
    client._tools = [
        SimpleNamespace(
            name=name,
            description="runtime probe",
            inputSchema={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        )
        for name in ("beta", "alpha")
    ]
    client._tools_map = None
    manager = mcp.MCPManager(tmp_path / "unused-mcp.json")
    manager._client = client
    monkeypatch.setattr(mcp, "get_mcp_manager", lambda: manager)
    monkeypatch.setattr(schemas, "get_mcp_manager", lambda: manager)
    monkeypatch.setattr(gemini_provider, "get_mcp_manager", lambda: manager)
    monkeypatch.setattr(gemini_provider.genai, "Client", MagicMock())
    providers = [
        ProviderFactory.create_provider("gemini", config=app.config, runtime=app.runtime) for app in (first, second)
    ]
    a_functions = providers[0].gen_gemini_functions()
    b_functions = providers[1].gen_gemini_functions()
    a_mcp = [func for func in a_functions if func.__name__.startswith("_mcp__")]
    b_mcp = [func for func in b_functions if func.__name__.startswith("_mcp__")]
    assert [func.__name__ for func in a_mcp] == ["_mcp__alpha"]
    assert [func.__name__ for func in b_mcp] == ["_mcp__alpha", "_mcp__beta"]
    assert len(client._tools) == 2
    first.config["MCP_MAX_TOOLS"] = 2
    assert [func.__name__ for func in providers[0].gen_gemini_functions() if func.__name__.startswith("_mcp__")] == [
        "_mcp__alpha",
        "_mcp__beta",
    ]
    assert "fs_write_file" in {func.__name__ for func in a_functions}  # Preserve Gemini's selection difference.
    assert tools.get_openai_mcp_tools(runtime=first.runtime) == []  # OpenAI still applies ENABLED_TOOLS.
    assert [item["function"]["name"] for item in tools.get_openai_mcp_tools(runtime=second.runtime)] == [
        "_mcp__alpha",
        "_mcp__beta",
    ]
    observed_timeouts = []

    async def wait_for(awaitable, timeout):
        observed_timeouts.append(timeout)
        return await awaitable

    monkeypatch.setattr(mcp.asyncio, "wait_for", wait_for)
    assert inspect.signature(a_mcp[0]).parameters.keys() == {"value"}
    assert json.loads(a_mcp[0](value="A")) == {"tool": "alpha", "timeout": 3, "value": "A"}
    assert json.loads(b_mcp[0](value="B")) == {"tool": "alpha", "timeout": 11, "value": "B"}
    first.config["MCP_TIMEOUT"] = 5
    assert json.loads(a_mcp[0](value="A2"))["timeout"] == 5
    assert observed_timeouts == [3, 11, 5]
    for funcs, app in ((a_functions, first), (b_functions, second), (a_functions, first)):
        callback = next(func for func in funcs if func.__name__ == "fs_read_file")
        result = json.loads(callback(file_paths=[str(Path(app.config["WORKSPACE_ROOT"]) / "probe.txt")]))
        assert result["content"] == app.config["MODEL"]
        assert {key: os.environ.get(key) for key in MANAGED_ENV} == before
