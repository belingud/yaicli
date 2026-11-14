"""Provider-level regression: plan-mode instructions must survive message conversion.

The K23 plan-mode fix moved the plan rules from a *second* system message into the
first one. Anthropic only sends one system prompt (its ``messages`` list allows
``user``/``assistant`` roles only) and Gemini only reads ``messages[0]`` as
``system_instruction``, so those providers used to silently lose the plan rules —
the request then behaved like normal chat and could answer with the implementation
(e.g. print HTML) instead of planning. These tests pin the message shape at the
provider conversion boundary.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from yaicli import plan_mode, tools
from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.llms.provider import Provider
from yaicli.llms.providers.anthropic_provider import AnthropicProvider

#: Stable phrases the model must receive in plan mode.
PLAN_MARKERS = ("YOU ARE NOW IN PLAN MODE", "submit_plan")


@pytest.fixture(autouse=True)
def reset_plan_state():
    """Reset the process-global plan session / tool mode around every test."""
    plan_mode.reset_plan_session()
    tools.set_plan_tool_mode(None)
    yield
    plan_mode.reset_plan_session()
    tools.set_plan_tool_mode(None)


@pytest.fixture
def plan_cli(tmp_path, monkeypatch):
    """A real CLI with a mocked LLM client and its plans root inside tmp_path."""
    monkeypatch.setitem(cfg, "PLAN_DIR", str(tmp_path / "plans"))
    manager = MagicMock()
    manager.chat_dir = tmp_path / "sessions"
    cli = CLI(verbose=False, client=MagicMock(), chat_manager=manager)
    cli.console = MagicMock()
    cli.interactive = True
    cli.machine_output = False
    monkeypatch.setattr(CLI, "_get_project_context", lambda self: "")
    return cli


def _plan_messages(cli):
    """Enter plan mode and build the request messages for one turn."""
    session = cli._get_plan_session()
    session.enter_researching()
    return cli._build_messages("build a weather page")


def _assert_plan_markers(text: str) -> None:
    for marker in PLAN_MARKERS:
        assert marker in text, f"missing plan-mode marker {marker!r} in provider payload"


def test_plan_prompt_is_the_only_system_message(plan_cli):
    """A second system message would be dropped by some providers; there must be one."""
    messages = _plan_messages(plan_cli)
    system_messages = [message for message in messages if message.role == "system"]
    assert len(system_messages) == 1
    _assert_plan_markers(system_messages[0].content or "")


def test_anthropic_payload_keeps_plan_prompt_in_system_param(plan_cli):
    """Anthropic sends one system string and keeps only user/assistant in messages."""
    messages = _plan_messages(plan_cli)
    system_prompt, system_index = AnthropicProvider._extract_system_prompt(None, messages)
    assert system_index == 0
    _assert_plan_markers(system_prompt or "")

    converted = AnthropicProvider._convert_messages(None, messages)
    converted.pop(system_index)
    assert {message["role"] for message in converted} <= {"user", "assistant"}


def test_gemini_system_instruction_keeps_plan_prompt(plan_cli):
    """Gemini only reads messages[0] as system_instruction and skips system messages."""
    pytest.importorskip("google.genai")
    from yaicli.llms.providers.gemini_provider import GeminiProvider

    messages = _plan_messages(plan_cli)
    # GeminiProvider.completion() does: chat_config.system_instruction = messages[0].content
    _assert_plan_markers(messages[0].content or "")

    fake_self = SimpleNamespace(_map_role=lambda role: "model" if role == "assistant" else role)
    converted = GeminiProvider._convert_messages(fake_self, messages)
    assert all(content.role != "system" for content in converted)


def test_openai_style_payload_keeps_plan_prompt(plan_cli):
    """OpenAI-compatible providers pass the first system message through unchanged."""
    messages = _plan_messages(plan_cli)
    converted = Provider._convert_messages(None, messages)  # type: ignore[arg-type]
    assert converted[0]["role"] == "system"
    _assert_plan_markers(converted[0]["content"])
    assert converted[-1]["role"] == "user"


def test_normal_mode_payload_has_no_plan_prompt(plan_cli):
    """The normal path stays byte-identical: no plan rules without a plan session."""
    messages = plan_cli._build_messages("hello")
    converted = Provider._convert_messages(None, messages)  # type: ignore[arg-type]
    assert "PLAN MODE" not in converted[0]["content"]
    assert "submit_plan" not in converted[0]["content"]
