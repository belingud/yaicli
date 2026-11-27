"""Application dependency ownership without changing configuration loading."""

from copy import deepcopy
from io import StringIO
from unittest.mock import MagicMock

import pytest

from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.console import YaiConsole
from yaicli.const import DefaultRoleNames
from yaicli.runtime import SessionContext, bind_config, current_config
from yaicli.schemas import LLMResponse


def test_configuration_binding_restores_nested_and_exceptional_scopes():
    default = {"name": "default"}
    outer = {"name": "outer"}
    assert current_config(default) is default
    with bind_config(outer):
        assert current_config(default) is outer
        with pytest.raises(RuntimeError, match="test failure"):
            with bind_config({}):
                assert current_config(default) == {}
                raise RuntimeError("test failure")
        assert current_config(default) is outer
    assert current_config(default) is default


def test_context_derives_tool_mode_from_the_single_lazy_plan():
    runtime = SessionContext({})
    assert runtime.peek_plan_session() is None
    assert runtime.tool_mode is None
    session = runtime.get_plan_session()
    assert runtime.get_plan_session() is session
    for mode, expected in [("researching", "plan"), ("revising", "plan"), ("executing", "execution"), ("normal", None)]:
        session.mode = mode
        assert runtime.tool_mode == expected
    runtime.set_plan_session(None)
    assert runtime.peek_plan_session() is None
    assert runtime.get_plan_session() is not session


def test_cli_owns_a_deep_snapshot_and_preserves_ready_client_identity(tmp_path):
    source = deepcopy(dict(cfg))
    source.update(CHAT_HISTORY_DIR=str(tmp_path / "a"), MODEL_PRICING={"custom": {"input": 1.0}})
    ready = MagicMock()
    first = CLI(config=source, client=ready)
    second = CLI(config=source, client=MagicMock())
    first.config["MODEL_PRICING"]["custom"]["input"] = 9.0
    first.config["MODEL"] = "changed-model"
    assert source["MODEL_PRICING"]["custom"]["input"] == 1.0
    assert second.config["MODEL_PRICING"]["custom"]["input"] == 1.0
    assert second.config["MODEL"] == source["MODEL"]
    assert first.active_client is ready
    assert first.output.config is first.sessions.config is first.runtime.config
    assert first.planning.runtime is first.runtime
    assert first.planning.config is first.config


def test_default_chat_managers_keep_their_own_directories_after_another_cli(tmp_path):
    source = dict(cfg)
    first = CLI(config={**source, "CHAT_HISTORY_DIR": str(tmp_path / "a")}, client=MagicMock())
    second = CLI(config={**source, "CHAT_HISTORY_DIR": str(tmp_path / "b")}, client=MagicMock())
    first.chat.add_message("user", "first conversation")
    second.chat.add_message("user", "second conversation")
    first.sessions.save_chat("first")
    second.sessions.save_chat("second")
    assert first.chat_manager is not second.chat_manager
    assert first.chat.path.parent == tmp_path / "a"
    assert second.chat.path.parent == tmp_path / "b"
    assert first.chat_manager.chat_dir == first.chat_history_dir == tmp_path / "a"
    assert second.chat_manager.chat_dir == second.chat_history_dir == tmp_path / "b"


def test_model_switch_rebuilds_only_its_client_with_the_same_effective_mapping(monkeypatch):
    source = {**dict(cfg), "MODEL": "initial-model"}
    first = CLI(config=source, client=MagicMock())
    second_client = MagicMock()
    second = CLI(config=source, client=second_client)
    first.console = MagicMock()
    built = []

    def factory(**kwargs):
        built.append(kwargs)
        return MagicMock()

    monkeypatch.setattr("yaicli.cli.LLMClient", factory)
    first.cmd_handler.handle_model("/model changed-model")
    assert first.active_client is None
    _ = first.client
    assert len(built) == 1
    assert built[0]["config"] is first.config
    assert built[0]["runtime"] is first.runtime
    assert built[0]["config"]["MODEL"] == "changed-model"
    assert second.active_client is second_client
    assert second.config["MODEL"] == source["MODEL"] == "initial-model"


def test_coordinator_gets_its_plan_without_the_default_global_getter(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("default plan getter used")

    monkeypatch.setattr("yaicli.planning.service.get_plan_session", forbidden)
    first = CLI(config={**dict(cfg), "PLAN_DIR": str(tmp_path / "plans")}, client=MagicMock())
    second = CLI(config={**dict(cfg), "PLAN_DIR": str(tmp_path / "other-plans")}, client=MagicMock())
    assert first.runtime.peek_plan_session() is None
    session = first._get_plan_session()
    session.enter_researching()
    assert first.plan_session is first.planning.plan_session is first.runtime.peek_plan_session()
    assert first.runtime.tool_mode == "plan"
    assert second.runtime.peek_plan_session() is None
    assert second.runtime.tool_mode is None


@pytest.mark.parametrize("machine", [False, True])
def test_cli_printers_keep_owned_configuration_across_rebuilds(tmp_path, monkeypatch, machine):
    source = deepcopy(dict(cfg))
    source.update(
        SHOW_REASONING=not cfg["SHOW_REASONING"],
        SHOW_THINKING_STATUS=not cfg["SHOW_THINKING_STATUS"],
        CODE_THEME="monokai" if cfg["CODE_THEME"] != "monokai" else "default",
        CHAT_HISTORY_DIR=str(tmp_path / "sessions"),
    )
    monkeypatch.setattr(CLI, "_stdin_is_tty", staticmethod(lambda: not machine))
    monkeypatch.setattr(CLI, "_stdout_is_tty", staticmethod(lambda: not machine))
    cli = CLI(config=source, client=MagicMock())
    output = StringIO()
    cli.console = YaiConsole(file=output, force_terminal=False, width=80)
    cli.printer = cli._make_printer()
    cli.printer.display_stream(iter([LLMResponse(reasoning="owned-thought"), LLMResponse(content="answer")]))
    assert ("owned-thought" in output.getvalue()) is (source["SHOW_REASONING"] and not machine)
    assert cli.printer.code_theme == source["CODE_THEME"]
    assert cli.printer.show_thinking_status is source["SHOW_THINKING_STATUS"]
    assert cli.printer.config is cli.config

    previous = cli.printer
    cli.set_role(DefaultRoleNames.CODER)
    assert cli.printer is not previous
    assert cli.printer.config is cli.config
    assert cli.printer.code_theme == source["CODE_THEME"]
    assert cli.printer.show_reasoning is source["SHOW_REASONING"]
    cli.configure_headless(output_format="stream-json")
    assert cli.printer.machine is True
    assert cli.printer.config is cli.config
    assert cli.printer.show_thinking_status is source["SHOW_THINKING_STATUS"]
