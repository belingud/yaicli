"""Tests for the v0.21 K10 session-wide ``TOOL_POLICY`` permission modes.

Covers ``readonly``/``standard``/``trusted`` enforcement in the LLM tool gate:

* config wiring (``DEFAULT_CONFIG_MAP``/``DEFAULT_CONFIG_INI``/``YAI_TOOL_POLICY``);
* normalization: default ``standard``, case/whitespace handling, invalid values fall
  back to ``standard`` with exactly one stderr warning (never per tool call);
* ``readonly`` auto-allows ``read``/``network`` and hard-denies ``write``/``exec`` —
  persisted rules, session approvals, ``--yes``, ``--allowed-tools`` and
  ``TOOL_CONFIRM=false`` cannot override the deny;
* ``trusted`` auto-allows every non-dangerous tool without prompts;
* ``standard`` keeps the exact v0.19 behaviour;
* danger-classified shell commands keep their precedence in every mode (interactive
  confirm, ``TOOL_CONFIRM=false`` deny, non-interactive deny);
* structured ``tool_denied`` results, ``tool_denied`` flags, stderr diagnostics and
  the new ``policy`` field in the JSONL audit log.
"""

import json
import re
from unittest.mock import MagicMock, patch

import pytest

import yaicli.config
import yaicli.const as const_module
from yaicli.config import Config
from yaicli.llms.client import LLMClient
from yaicli.llms.provider import ProviderFactory
from yaicli.schemas import (
    ChatMessage,
    ConfirmToolCall,
    LLMResponse,
    ToolCall,
    ToolConfirmDecision,
    ToolPolicy,
)
from yaicli.tools.approval import PermissionRule, ToolApprovalManager

#: Sentinel: build a client config that omits ``TOOL_POLICY`` entirely.
_OMIT = object()

MCP_PREFIX = "_mcp__"


# ---------------------------------------------------------------------------
# Helpers / fixtures (mirror tests/test_permissions.py conventions)
# ---------------------------------------------------------------------------
class FakeProvider:
    """Minimal provider replaying scripted LLMResponse batches, one per completion()."""

    def __init__(self, scripted):
        self._scripted = scripted
        self.calls = 0

    def resolve_tool_policy(self, tool_policy):
        return tool_policy or ToolPolicy(enable_functions=True, enable_mcp=True)

    def completion(self, messages, stream=False, tool_policy=None):
        batch = self._scripted[self.calls]
        self.calls += 1
        yield from batch

    def detect_tool_role(self):
        return "tool"


def make_client(
    scripted,
    approval,
    *,
    interactive=True,
    tool_confirm=True,
    audit=False,
    policy="standard",
    config=None,
):
    """Build a gate-only LLMClient (provider creation is mocked)."""
    if config is None:
        config = {
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": True,
            "MAX_TOOL_CALL_DEPTH": 8,
            "TOOL_CONFIRM": tool_confirm,
            "TOOL_AUDIT": audit,
        }
        if policy is not _OMIT:
            config["TOOL_POLICY"] = policy
    fake = FakeProvider(scripted)
    with patch.object(ProviderFactory, "create_provider", return_value=fake):
        client = LLMClient(provider_name="openai", config=config, approval=approval, interactive=interactive)
    client.provider = fake
    return client


def drive(gen, decisions):
    """Pump a completion_with_tools generator, answering ConfirmToolCall from a queue."""
    decisions = list(decisions)
    items = []
    send_value = None
    confirms = 0
    while True:
        try:
            item = gen.send(send_value) if send_value is not None else next(gen)
        except StopIteration:
            break
        send_value = None
        items.append(item)
        if isinstance(item, ConfirmToolCall):
            confirms += 1
            send_value = decisions.pop(0)
    return items, confirms


def script_tools(*tool_calls, repeats=1):
    """Script: ``repeats`` turns, each one tool batch followed by a final content turn."""
    script = []
    for _ in range(repeats):
        script.append([LLMResponse(tool_call=tc, finish_reason="tool_calls") for tc in tool_calls])
        script.append([LLMResponse(content="done", finish_reason="stop")])
    return script


def run_turn(client, decisions=(), *, execute_result=("ok", True)):
    """Drive one client turn; the real tool execution is mocked.

    Returns ``(messages, confirms, execute_mock)`` so tests can assert what executed.
    """
    messages = [ChatMessage(role="user", content="go")]
    patcher = patch("yaicli.llms.client.execute_tool_call", return_value=execute_result)
    execute_mock = patcher.start()
    try:
        gen = client.completion_with_tools(messages, tool_policy=ToolPolicy(True, True))
        _, confirms = drive(gen, list(decisions))
    finally:
        patcher.stop()
    return messages, confirms, execute_mock


def tool_messages(messages):
    return [message for message in messages if getattr(message, "role", None) == "tool"]


def make_manager(tmp_path, name="tool_permissions.json"):
    return ToolApprovalManager(permissions_path=tmp_path / name)


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    """Point the audit log at a tmp file (never the real config dir)."""
    path = tmp_path / "tool_audit.jsonl"
    monkeypatch.setattr(const_module, "TOOL_AUDIT_PATH", path)
    return path


def read_call():
    return ToolCall(id="c-read", name="fs_read_file", arguments='{"file_paths": ["a.txt"]}')


def network_call():
    return ToolCall(id="c-net", name="web_search", arguments='{"query": "x"}')


def write_call():
    return ToolCall(id="c-write", name="fs_write_file", arguments='{"file_path": "a.txt", "content": "x"}')


def edit_call():
    return ToolCall(id="c-edit", name="fs_edit_file", arguments='{"file_path": "a.txt", "edits": []}')


def shell_call(command="ls -la"):
    return ToolCall(id="c-shell", name="execute_shell_command", arguments=json.dumps({"command": command}))


def dangerous_shell_call():
    return ToolCall(
        id="c-danger", name="execute_shell_command", arguments='{"command": "rm -rf build"}'
    )


def mcp_call():
    return ToolCall(id="c-mcp", name=f"{MCP_PREFIX}clock", arguments="{}")


def denied_payload(messages, tool_call_id):
    """Return the structured JSON payload of the matching denied tool result."""
    for message in tool_messages(messages):
        if message.tool_call_id == tool_call_id:
            return json.loads(message.content)
    raise AssertionError(f"no tool result for {tool_call_id}")


# ---------------------------------------------------------------------------
# 1. Config wiring: TOOL_POLICY default / env / template
# ---------------------------------------------------------------------------
class TestToolPolicyConfig:
    def test_config_map_and_template_entry(self):
        entry = const_module.DEFAULT_CONFIG_MAP["TOOL_POLICY"]
        assert entry["value"] == "standard"
        assert entry["env_key"] == "YAI_TOOL_POLICY"
        assert entry["type"] is str
        assert const_module.DEFAULT_TOOL_POLICY == "standard"
        assert const_module.TOOL_POLICY_MODES == ("readonly", "standard", "trusted")
        assert "TOOL_POLICY=standard" in const_module.DEFAULT_CONFIG_INI

    def test_default_is_standard_from_layered_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("YAI_TOOL_POLICY", raising=False)
        monkeypatch.setattr(yaicli.config, "CONFIG_PATH", tmp_path / "missing.ini")
        config = Config(MagicMock())
        assert config["TOOL_POLICY"] == "standard"
        assert isinstance(config["TOOL_POLICY"], str)

    def test_env_override_is_loaded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yaicli.config, "CONFIG_PATH", tmp_path / "missing.ini")
        monkeypatch.setenv("YAI_TOOL_POLICY", "trusted")
        assert Config(MagicMock())["TOOL_POLICY"] == "trusted"
        # The config layer keeps the raw string; the gate normalizes case/whitespace.
        monkeypatch.setenv("YAI_TOOL_POLICY", " ReadOnly ")
        assert Config(MagicMock())["TOOL_POLICY"] == " ReadOnly "

    def test_env_value_flows_into_the_gate(self, tmp_path, monkeypatch):
        """YAI_TOOL_POLICY -> Config -> client -> readonly enforcement (end to end)."""
        monkeypatch.setattr(yaicli.config, "CONFIG_PATH", tmp_path / "missing.ini")
        monkeypatch.setenv("YAI_TOOL_POLICY", "readonly")
        config = Config(MagicMock())
        config["TOOL_AUDIT"] = False  # never touch the real audit log in tests
        manager = make_manager(tmp_path)
        client = make_client(script_tools(read_call(), write_call()), manager, interactive=False, config=config)
        messages, confirms, execute_mock = run_turn(client)

        assert client.tool_policy_mode == "readonly"
        assert confirms == 0
        execute_mock.assert_called_once()  # read tool ran
        payload = denied_payload(messages, "c-write")
        assert payload["error"] == "tool_denied"
        assert "TOOL_POLICY=readonly" in payload["reason"]


# ---------------------------------------------------------------------------
# 2. Mode normalization / invalid fallback
# ---------------------------------------------------------------------------
class TestToolPolicyNormalization:
    def test_default_standard_keeps_prompting(self, tmp_path, capsys):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(write_call()), manager, interactive=True, policy=_OMIT)
        _, confirms, execute_mock = run_turn(client, [ToolConfirmDecision.DENY])
        assert client.tool_policy_mode == "standard"
        assert confirms == 1  # standard still asks
        execute_mock.assert_not_called()
        assert "Invalid TOOL_POLICY" not in capsys.readouterr().err

    def test_invalid_value_falls_back_to_standard_with_one_warning(self, tmp_path, capsys):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(write_call()), manager, interactive=True, policy="yolo")
        _, confirms, _ = run_turn(client, [ToolConfirmDecision.DENY])

        assert client.tool_policy_mode == "standard"
        assert confirms == 1  # standard flow, not trusted/readonly
        err = capsys.readouterr().err
        assert err.count("Invalid TOOL_POLICY") == 1
        assert "readonly, standard, trusted" in err

    def test_invalid_value_warns_once_per_client_not_per_call(self, tmp_path, capsys):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(write_call(), repeats=2), manager, interactive=True, policy="bogus")
        run_turn(client, [ToolConfirmDecision.DENY])
        assert capsys.readouterr().err.count("Invalid TOOL_POLICY") == 1
        # A later turn on the same client must not warn again.
        run_turn(client, [ToolConfirmDecision.DENY])
        assert capsys.readouterr().err.count("Invalid TOOL_POLICY") == 0
        assert client.tool_policy_mode == "standard"

    def test_empty_value_is_treated_as_unset_without_warning(self, tmp_path, capsys):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(write_call()), manager, interactive=True, policy="")
        _, confirms, _ = run_turn(client, [ToolConfirmDecision.DENY])
        assert client.tool_policy_mode == "standard"
        assert confirms == 1
        assert "Invalid TOOL_POLICY" not in capsys.readouterr().err

    def test_case_and_whitespace_are_normalized(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(write_call()), manager, interactive=False, policy="  ReAdOnLy  ")
        messages, _, execute_mock = run_turn(client)
        assert client.tool_policy_mode == "readonly"
        execute_mock.assert_not_called()
        assert "TOOL_POLICY=readonly" in denied_payload(messages, "c-write")["reason"]

    def test_uppercase_trusted_is_normalized(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(write_call()), manager, interactive=False, policy="TRUSTED")
        _, confirms, execute_mock = run_turn(client)
        assert client.tool_policy_mode == "trusted"
        assert confirms == 0
        execute_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 3. readonly mode
# ---------------------------------------------------------------------------
class TestReadonlyMode:
    def test_readonly_allows_read_and_network_non_interactive(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(
            script_tools(read_call(), network_call()), manager, interactive=False, policy="readonly"
        )
        _, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        assert execute_mock.call_count == 2
        assert client.tool_denied is False

    def test_readonly_allows_read_and_network_interactively_without_prompt(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(read_call(), network_call()), manager, interactive=True, policy="readonly")
        _, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        assert execute_mock.call_count == 2

    @pytest.mark.parametrize("interactive", [False, True])
    def test_readonly_denies_write_and_exec_with_structured_result(self, tmp_path, capsys, interactive):
        manager = make_manager(tmp_path)
        client = make_client(
            script_tools(write_call(), edit_call(), shell_call(), mcp_call()),
            manager,
            interactive=interactive,
            policy="readonly",
        )
        messages, confirms, execute_mock = run_turn(client)

        assert confirms == 0  # readonly never prompts for write/exec, even on a TTY
        execute_mock.assert_not_called()
        assert client.tool_denied is True
        for call_id in ("c-write", "c-edit", "c-shell", "c-mcp"):
            payload = denied_payload(messages, call_id)
            assert payload["error"] == "tool_denied"
            assert "TOOL_POLICY=readonly" in payload["reason"]
        # One stderr diagnostic per denial, naming TOOL_POLICY and the fix.
        err = capsys.readouterr().err
        assert err.count("was denied") == 4
        assert "TOOL_POLICY=readonly" in err
        assert "TOOL_POLICY=standard" in err

    def test_readonly_cannot_be_overridden_by_approvals_or_flags(self, tmp_path):
        """Persisted rules, session approvals, --yes, --allowed-tools, TOOL_CONFIRM=false lose."""
        manager = make_manager(tmp_path)
        manager.allow_session("fs_write_file")
        manager.allow_session("execute_shell_command")
        manager.persistent_rules = [PermissionRule(tool="fs_write_file", path_glob="**")]
        manager.configure_run(yes=True, allowed_tools=["fs_*", "execute_shell_command"])
        # Prove the override attempts would authorize these calls under standard mode.
        write_arguments = {"file_path": "a.txt", "content": "x"}
        assert manager.match_source("fs_write_file", write_arguments) == "session"
        assert manager.is_run_allowed("fs_write_file") is True
        assert manager.auto_allow_read is True

        client = make_client(
            script_tools(read_call(), write_call(), shell_call()),
            manager,
            interactive=True,
            tool_confirm=False,  # would normally execute non-dangerous calls silently
            policy="readonly",
        )
        messages, confirms, execute_mock = run_turn(client)

        assert confirms == 0
        execute_mock.assert_called_once()  # only the read call ran
        assert client.tool_denied is True
        assert "TOOL_POLICY=readonly" in denied_payload(messages, "c-write")["reason"]
        assert "TOOL_POLICY=readonly" in denied_payload(messages, "c-shell")["reason"]

    def test_readonly_dangerous_shell_non_interactive_denied(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(dangerous_shell_call()), manager, interactive=False, policy="readonly")
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_not_called()
        reason = denied_payload(messages, "c-danger")["reason"]
        assert "Dangerous shell command" in reason  # danger reason, not the readonly one

    def test_readonly_dangerous_shell_interactive_prompts(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(dangerous_shell_call()), manager, interactive=True, policy="readonly")
        messages, confirms, execute_mock = run_turn(client, [ToolConfirmDecision.DENY])
        assert confirms == 1  # danger precedence over the readonly deny
        execute_mock.assert_not_called()
        assert "declined" in denied_payload(messages, "c-danger")["reason"].lower()

    def test_readonly_confirmed_dangerous_shell_executes(self, tmp_path):
        """PRD precedence: danger branch wins first; an explicit interactive confirm runs."""
        manager = make_manager(tmp_path)
        client = make_client(script_tools(dangerous_shell_call()), manager, interactive=True, policy="readonly")
        _, confirms, execute_mock = run_turn(client, [ToolConfirmDecision.ONCE])
        assert confirms == 1
        execute_mock.assert_called_once()
        assert client.tool_denied is False


# ---------------------------------------------------------------------------
# 4. trusted mode
# ---------------------------------------------------------------------------
class TestTrustedMode:
    def test_trusted_auto_allows_all_non_dangerous_tools(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(
            script_tools(read_call(), network_call(), write_call(), shell_call()),
            manager,
            interactive=True,
            policy="trusted",
        )
        _, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        assert execute_mock.call_count == 4
        assert client.tool_denied is False

    def test_trusted_auto_allows_non_interactively(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(write_call(), shell_call()), manager, interactive=False, policy="trusted")
        _, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        assert execute_mock.call_count == 2

    def test_trusted_dangerous_shell_non_interactive_denied(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(dangerous_shell_call()), manager, interactive=False, policy="trusted")
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_not_called()
        assert client.tool_denied is True
        assert "Dangerous shell command" in denied_payload(messages, "c-danger")["reason"]

    def test_trusted_dangerous_shell_interactive_prompts(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(dangerous_shell_call()), manager, interactive=True, policy="trusted")
        messages, confirms, execute_mock = run_turn(client, [ToolConfirmDecision.DENY])
        assert confirms == 1
        execute_mock.assert_not_called()
        assert "declined" in denied_payload(messages, "c-danger")["reason"].lower()

    def test_trusted_confirm_disabled_still_denies_dangerous_shell(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(
            script_tools(dangerous_shell_call()),
            manager,
            interactive=True,
            tool_confirm=False,
            policy="trusted",
        )
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_not_called()
        assert denied_payload(messages, "c-danger")["error"] == "tool_denied"


# ---------------------------------------------------------------------------
# 5. standard mode regression (v0.19 behaviour unchanged)
# ---------------------------------------------------------------------------
class TestStandardMode:
    def test_standard_non_interactive_denies_unapproved_write(self, tmp_path, capsys):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(write_call()), manager, interactive=False, policy="standard")
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_not_called()
        payload = denied_payload(messages, "c-write")
        assert payload["error"] == "tool_denied"
        assert "--allowed-tools" in payload["reason"]
        assert "TOOL_POLICY" not in payload["reason"]  # standard deny text is unchanged
        capsys.readouterr()

    def test_standard_interactive_prompts_unapproved_tool(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(script_tools(write_call()), manager, interactive=True, policy="standard")
        _, confirms, execute_mock = run_turn(client, [ToolConfirmDecision.ONCE])
        assert confirms == 1
        execute_mock.assert_called_once()

    def test_standard_rule_allows_without_prompt(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="fs_write_file", path_glob="a.txt")]
        client = make_client(script_tools(write_call()), manager, interactive=True, policy="standard")
        _, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_called_once()

    def test_standard_confirm_disabled_allows_non_dangerous(self, tmp_path):
        manager = make_manager(tmp_path)
        client = make_client(
            script_tools(write_call()), manager, interactive=True, tool_confirm=False, policy="standard"
        )
        _, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_called_once()

    def test_standard_dangerous_shell_unchanged(self, tmp_path):
        manager = make_manager(tmp_path)
        # Non-interactive: hard deny.
        client = make_client(script_tools(dangerous_shell_call()), manager, interactive=False, policy="standard")
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_not_called()
        assert "Dangerous shell command" in denied_payload(messages, "c-danger")["reason"]
        # Interactive: explicit confirmation.
        client2 = make_client(script_tools(dangerous_shell_call()), manager, interactive=True, policy="standard")
        _, confirms2, _ = run_turn(client2, [ToolConfirmDecision.ONCE])
        assert confirms2 == 1


# ---------------------------------------------------------------------------
# 6. Audit log: new ``policy`` field on allowed/denied/error decisions
# ---------------------------------------------------------------------------
class TestAuditPolicyField:
    @staticmethod
    def records(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_readonly_audit_records_policy_on_allowed_and_denied(self, tmp_path, audit_log):
        manager = make_manager(tmp_path)
        client = make_client(
            script_tools(read_call(), write_call()), manager, interactive=False, audit=True, policy="readonly"
        )
        run_turn(client)

        records = self.records(audit_log)
        assert len(records) == 2
        assert [record["policy"] for record in records] == ["readonly", "readonly"]
        assert [record["decision"] for record in records] == ["allowed", "denied"]
        for record in records:
            # K06 fields are unchanged; only ``policy`` is new.
            for key in ("ts", "tool", "risk", "decision", "source", "args_summary", "duration_ms"):
                assert key in record
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["ts"])
        assert records[0]["source"] == "policy"

    def test_trusted_audit_records_policy_on_error(self, tmp_path, audit_log):
        manager = make_manager(tmp_path)
        client = make_client(
            script_tools(write_call()), manager, interactive=False, audit=True, policy="trusted"
        )
        run_turn(client, execute_result=("boom", False))

        record = self.records(audit_log)[0]
        assert record["policy"] == "trusted"
        assert record["decision"] == "error"
        assert record["source"] == "policy"

    def test_standard_audit_records_policy(self, tmp_path, audit_log):
        manager = make_manager(tmp_path)
        client = make_client(
            script_tools(write_call()), manager, interactive=False, audit=True, policy="standard"
        )
        run_turn(client)
        record = self.records(audit_log)[0]
        assert record["policy"] == "standard"
        assert record["decision"] == "denied"

    def test_dangerous_deny_audit_records_policy(self, tmp_path, audit_log):
        manager = make_manager(tmp_path)
        client = make_client(
            script_tools(dangerous_shell_call()), manager, interactive=False, audit=True, policy="trusted"
        )
        run_turn(client)
        record = self.records(audit_log)[0]
        assert record["policy"] == "trusted"
        assert record["decision"] == "denied"
        assert "reason" in record
