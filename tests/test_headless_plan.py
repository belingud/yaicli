"""v0.24 K23 headless ``--plan`` contract: JSON payload, events, exit codes.

Runs the real Typer app with a mocked ``LLMClient`` and ``PLAN_DIR`` redirected to
``tmp_path``; nothing touches the network or the developer's config directory.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from yaicli import plan_mode
from yaicli.config import cfg
from yaicli.entry import app
from yaicli.schemas import LLMResponse

runner = CliRunner()

#: The frozen v0.19 JSON key set; ``--plan`` runs add exactly three more keys.
BASE_JSON_KEYS = {
    "content",
    "tool_calls",
    "usage",
    "finish_reason",
    "model",
    "provider",
    "error",
    "exit_code",
}
PLAN_JSON_KEYS = {"plan", "plan_path", "revision"}
PLAN_STEPS = [
    {"title": "Locate the write path", "acceptance": "files identified"},
    {"title": "Add the dry-run short circuit", "acceptance": "no file is written"},
]


@pytest.fixture(autouse=True)
def reset_global_plan_session(tmp_path, monkeypatch):
    """Isolate plan state and the plans root; reset the global session."""
    from yaicli import tools

    monkeypatch.setitem(cfg, "PLAN_DIR", str(tmp_path / "plans"))
    plan_mode.reset_plan_session()
    tools.set_plan_tool_mode(None)
    yield
    plan_mode.reset_plan_session()
    tools.set_plan_tool_mode(None)


def make_client(*, submit=True, chunks=None):
    """A mocked LLM client that optionally submits a plan on the first request."""
    client = MagicMock()
    submitted = {}

    def completion(messages, **kwargs):
        if submit:
            submitted["result"] = plan_mode.handle_submit_plan({"goal": "Headless plan", "steps": PLAN_STEPS})
        return iter(chunks if chunks is not None else [LLMResponse(content="done")])

    client.completion_with_tools = MagicMock(side_effect=completion)
    client.submitted = submitted
    return client


def invoke_with_client(client, args):
    """Invoke the Typer app with the real CLI but the mocked LLM client."""
    with patch("yaicli.cli.LLMClient", return_value=client):
        return runner.invoke(app, args)


class TestHeadlessPlanJson:
    """``-p --plan --output-format json``: plan + plan_path + revision, exit 0."""

    def test_submitted_plan_json(self):
        client = make_client()
        result = invoke_with_client(client, ["-p", "--plan", "--output-format", "json", "plan the task"])

        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert set(payload) == BASE_JSON_KEYS | PLAN_JSON_KEYS
        assert payload["exit_code"] == 0
        assert payload["error"] is None
        assert payload["plan"]["goal"] == "Headless plan"
        assert payload["plan"]["status"] == "draft"
        assert payload["plan"]["revision"] == 1
        assert [step["title"] for step in payload["plan"]["steps"]] == [step["title"] for step in PLAN_STEPS]
        assert payload["revision"] == 1
        assert payload["plan_path"] == payload["plan"]["path"]
        assert Path(payload["plan_path"]).is_file()
        assert client.submitted["result"].get("success") is True

    def test_json_is_a_single_document(self):
        client = make_client()
        result = invoke_with_client(client, ["-p", "--plan", "--output-format", "json", "plan"])

        assert result.exit_code == 0
        assert result.stdout.count("\n") == 1
        assert "Assistant:" not in result.stdout

    def test_not_submitted_exits_one_with_error_kind(self):
        client = make_client(submit=False)
        result = invoke_with_client(client, ["-p", "--plan", "--output-format", "json", "plan"])

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert set(payload) == BASE_JSON_KEYS | PLAN_JSON_KEYS
        assert payload["plan"] is None
        assert payload["plan_path"] is None
        assert payload["revision"] is None
        assert payload["error"]["kind"] == "plan_not_submitted"
        assert payload["exit_code"] == 1
        assert "plan mode ended: model did not submit a plan" in result.stderr

    def test_normal_json_without_plan_keeps_exact_key_set(self):
        client = make_client(submit=False)
        result = invoke_with_client(client, ["-p", "--output-format", "json", "hi"])

        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert set(payload) == BASE_JSON_KEYS
        assert "plan" not in payload


class TestHeadlessPlanStreamJson:
    """stream-json gains plan_start/plan_ready events without changing the rest."""

    def test_plan_events_and_done(self):
        client = make_client()
        result = invoke_with_client(client, ["-p", "--plan", "--output-format", "stream-json", "plan"])

        assert result.exit_code == 0, result.stderr
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        types = [event["type"] for event in events]
        assert types[0] == "plan_start"
        assert "plan_ready" in types
        assert types[-1] == "done"
        ready = next(event for event in events if event["type"] == "plan_ready")
        assert ready["steps"] == len(PLAN_STEPS)
        assert ready["revision"] == 1
        assert ready["path"].endswith(".md")
        done = events[-1]
        assert done["exit_code"] == 0
        assert done["error"] is None

    def test_not_submitted_stream_ends_with_error_and_exit_one(self):
        client = make_client(submit=False)
        result = invoke_with_client(client, ["-p", "--plan", "--output-format", "stream-json", "plan"])

        assert result.exit_code == 1
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        assert events[-1]["type"] == "done"
        assert events[-1]["exit_code"] == 1
        assert events[-1]["error"]["kind"] == "plan_not_submitted"
        assert "plan_start" in [event["type"] for event in events]


class TestHeadlessPlanText:
    """Plain ``-p --plan`` prints the plan body (never executes it)."""

    def test_plan_markdown_reaches_stdout(self):
        client = make_client()
        result = invoke_with_client(client, ["-p", "--plan", "plan the task"])

        assert result.exit_code == 0, result.stderr
        assert "## Steps" in result.stdout
        assert "Locate the write path" in result.stdout

    def test_not_submitted_text_exits_one(self):
        client = make_client(submit=False)
        result = invoke_with_client(client, ["-p", "--plan", "plan the task"])

        assert result.exit_code == 1
        assert "## Steps" not in result.stdout
        assert "plan mode ended: model did not submit a plan" in result.stderr


class TestHeadlessPlanFlagValidation:
    """--plan conflicts and the PLAN_ENABLED switch are usage errors (exit 2)."""

    @pytest.mark.parametrize("flag", ["--shell", "--code"])
    def test_shell_or_code_conflict(self, flag):
        result = runner.invoke(app, ["--plan", flag, "do it"])

        assert result.exit_code == 2
        assert "Error: --plan cannot be combined with --shell/--code." in result.stderr

    def test_disabled_plan_mode_is_usage_error(self, monkeypatch):
        monkeypatch.setitem(cfg, "PLAN_ENABLED", False)

        result = runner.invoke(app, ["-p", "--plan", "plan the task"])

        assert result.exit_code == 2
        assert "Error: --plan requires PLAN_ENABLED=true." in result.stderr

    def test_plan_forces_one_shot_and_warns_about_chat(self):
        client = make_client()
        result = invoke_with_client(client, ["--plan", "--chat", "plan the task"])

        assert result.exit_code == 0, result.stderr
        assert "Warning: --chat is ignored with --plan; running one-shot." in result.stderr
        assert "## Steps" in result.stdout

    def test_plan_forces_one_shot_and_warns_about_resume(self):
        client = make_client()
        result = invoke_with_client(client, ["--plan", "--resume", "plan the task"])

        assert result.exit_code == 0, result.stderr
        assert "Warning: --resume is ignored with --plan; running one-shot." in result.stderr
        assert "## Steps" in result.stdout
