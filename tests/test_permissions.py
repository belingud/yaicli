"""Tests for the v0.19 K06 permissions MVP.

Covers the acceptance matrix from the roadmap:

* risk classes for builtin/MCP tools (``yaicli.tools.risk``);
* ``tool_permissions.json`` v2 rules (shell ``argv_prefix`` / write ``path_glob``) and
  backward compatibility with the v1 ``{"always_allow": [...]}`` file;
* the client gate: dangerous shell double-confirmation, ``--yes`` read-only auto-allow,
  ``--allowed-tools`` per-run globs, structured ``tool_denied`` results and the
  ``tool_denied`` flag for ``--fail-on-tool-denied``;
* the JSONL audit log (fields, redaction, mode, best-effort behaviour);
* faithful confirmation previews and preview/execution argument equality (duplicate
  JSON keys, ``\\u003b`` escapes);
* the ``/permissions`` / ``/permissions revoke <tool-or-index>`` REPL command and the
  ``entry.py`` run-policy plumbing.
"""

import contextlib
import json
import os
import re
import stat
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rich.console import Console

import yaicli.const as const_module
from yaicli.cli import CLI
from yaicli.cmd_handler import CMD_PERMISSIONS, CmdHandler
from yaicli.config import cfg
from yaicli.entry import _apply_run_tool_policy
from yaicli.llms.client import LLMClient
from yaicli.llms.provider import ProviderFactory
from yaicli.printer import Printer
from yaicli.schemas import (
    ChatMessage,
    ConfirmToolCall,
    LLMResponse,
    ToolCall,
    ToolConfirmDecision,
    ToolPolicy,
)
from yaicli.tools import execute_tool_call
from yaicli.tools.approval import (
    PermissionRule,
    ToolApprovalManager,
    canonical_arguments,
    parse_tool_arguments,
    summarize_arguments,
)
from yaicli.tools.risk import BUILTIN_TOOL_RISK, RiskLevel, classify_shell_command, get_tool_risk

MCP_PREFIX = "_mcp__"


# ---------------------------------------------------------------------------
# Helpers
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


def make_client(scripted, approval, *, interactive=True, tool_confirm=True, audit=True):
    config = {
        "ENABLE_FUNCTIONS": True,
        "ENABLE_MCP": True,
        "MAX_TOOL_CALL_DEPTH": 8,
        "TOOL_CONFIRM": tool_confirm,
        "TOOL_AUDIT": audit,
    }
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


def script_tools(*tool_calls):
    """Script: one turn with ``tool_calls``, then a final content turn."""
    return [
        [LLMResponse(tool_call=tc, finish_reason="tool_calls") for tc in tool_calls],
        [LLMResponse(content="done", finish_reason="stop")],
    ]


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


def write_permissions(tmp_path, data, name="tool_permissions.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A temp cwd used as the workspace root for relative path rule matching."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    monkeypatch.chdir(workspace_dir)
    monkeypatch.setitem(cfg, "WORKSPACE_ROOT", "")
    return workspace_dir


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    """Point the audit log at a tmp file (never the real config dir)."""
    path = tmp_path / "tool_audit.jsonl"
    monkeypatch.setattr(const_module, "TOOL_AUDIT_PATH", path)
    return path


def render_confirm_preview(tool_call) -> str:
    """Render ``_confirm_tool_call`` to a plain-text buffer and return the panel text."""
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=200, color_system=None)
    printer = Printer(console=console)
    printer.console = console
    with patch("yaicli.printer.Prompt.ask", return_value="n"):
        decision = printer._confirm_tool_call(tool_call)
    assert decision is ToolConfirmDecision.DENY
    return buffer.getvalue()


class RecordingTool:
    """Stand-in tool that records the exact kwargs it receives from execute_tool_call."""

    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return "executed"


def execute_and_capture(name, raw_arguments):
    """Run the real ``execute_tool_call`` with a recording tool; return captured kwargs."""
    tool = RecordingTool()
    fake_cfg = {"SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False}
    with (
        patch("yaicli.tools.get_function", return_value=tool),
        patch("yaicli.tools.cfg", fake_cfg),
        patch("yaicli.tools._sync_shell_guardrail_env"),
    ):
        result, ok = execute_tool_call(ToolCall(id="c1", name=name, arguments=raw_arguments), announce=False)
    assert ok is True, result
    assert len(tool.calls) == 1
    return tool.calls[0]


# ---------------------------------------------------------------------------
# 1. Risk classes
# ---------------------------------------------------------------------------
class TestRiskClasses:
    def test_builtin_risk_mapping(self):
        read_tools = [
            "fs_read_file",
            "fs_list_directory",
            "fs_search_files",
            "fs_get_filesystem_info",
            "fs_read_image",
        ]
        write_tools = ["fs_write_file", "fs_edit_file", "fs_file_operations"]
        network_tools = ["fetch_webpage", "web_search", "get_weather"]
        for name in read_tools:
            assert BUILTIN_TOOL_RISK[name] is RiskLevel.read
        for name in write_tools:
            assert BUILTIN_TOOL_RISK[name] is RiskLevel.write
        for name in network_tools:
            assert BUILTIN_TOOL_RISK[name] is RiskLevel.network
        assert BUILTIN_TOOL_RISK["execute_shell_command"] is RiskLevel.exec

    def test_mcp_and_unknown_tools_are_exec(self):
        assert get_tool_risk(f"{MCP_PREFIX}clock") is RiskLevel.exec
        assert get_tool_risk("some_custom_tool") is RiskLevel.exec
        assert get_tool_risk("") is RiskLevel.exec

    def test_function_class_exposes_risk(self):
        from yaicli.tools.function import get_function

        assert get_function("fs_read_file").risk is RiskLevel.read
        assert get_function("execute_shell_command").risk is RiskLevel.exec

    def test_dangerous_shell_classification_is_advisory(self):
        dangerous = classify_shell_command("rm -rf build")
        assert dangerous.dangerous is True
        assert dangerous.level is RiskLevel.exec
        safe = classify_shell_command("git status --short")
        assert safe.dangerous is False


# ---------------------------------------------------------------------------
# 2. tool_permissions.json v2 rules (and v1 backward compatibility)
# ---------------------------------------------------------------------------
class TestPermissionRules:
    def test_v2_file_loads_allowlist_and_rules(self, tmp_path):
        write_permissions(
            tmp_path,
            {
                "version": 2,
                "always_allow": ["fs_read_file"],
                "rules": [
                    {"tool": "execute_shell_command", "argv_prefix": ["git", "status"]},
                    {"tool": "fs_write_file", "path_glob": "src/**"},
                ],
            },
        )
        manager = make_manager(tmp_path)
        assert manager.permissions_version == 2
        assert manager.persistent_allow == {"fs_read_file"}
        assert len(manager.persistent_rules) == 2
        assert manager.is_allowed("fs_read_file") is True
        assert manager.match_source("fs_read_file") == "persist"

    def test_v1_file_is_backward_compatible(self, tmp_path):
        write_permissions(tmp_path, {"always_allow": ["execute_shell_command"]})
        manager = make_manager(tmp_path)
        assert manager.permissions_version == 1
        assert manager.persistent_rules == []
        # Name-only semantics still work for v1 files.
        assert manager.is_allowed("execute_shell_command") is True
        assert manager.is_allowed("execute_shell_command", {"command": "anything"}) is True

    def test_persist_upgrades_v1_file_to_v2_and_keeps_rules(self, tmp_path):
        path = write_permissions(tmp_path, {"always_allow": ["fs_read_file"]})
        manager = make_manager(tmp_path)
        manager.allow_persist("execute_shell_command")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 2
        assert data["always_allow"] == ["execute_shell_command", "fs_read_file"]
        assert data["rules"] == []

        # Rules already on disk are preserved when a new name is persisted.
        write_permissions(
            tmp_path,
            {
                "version": 2,
                "always_allow": [],
                "rules": [{"tool": "fs_write_file", "path_glob": "src/**"}],
            },
            name="with_rules.json",
        )
        manager2 = ToolApprovalManager(permissions_path=tmp_path / "with_rules.json")
        manager2.allow_persist("fs_read_file")
        data2 = json.loads((tmp_path / "with_rules.json").read_text(encoding="utf-8"))
        assert data2["rules"] == [{"tool": "fs_write_file", "path_glob": "src/**"}]

    def test_invalid_rules_are_skipped_not_fatal(self, tmp_path):
        write_permissions(
            tmp_path,
            {
                "version": 2,
                "always_allow": ["fs_read_file"],
                "rules": [
                    "not-an-object",
                    {"tool": ""},
                    {"tool": "execute_shell_command", "argv_prefix": []},
                    {"tool": "execute_shell_command", "argv_prefix": "git"},
                    {"tool": "fs_write_file"},  # constrains nothing -> ignored
                    {"tool": "execute_shell_command", "argv_prefix": ["git", "status"]},
                ],
            },
        )
        manager = make_manager(tmp_path)
        assert manager.persistent_allow == {"fs_read_file"}
        assert len(manager.persistent_rules) == 1
        assert manager.persistent_rules[0].argv_prefix == ("git", "status")

    @pytest.mark.parametrize(
        "command",
        [
            "git status $(touch /tmp/x)",
            "git status `touch /tmp/x`",
            "git status; rm -rf build",
            "git status | cat",
            "git status && rm -rf build",
            "git status || true",
            "git status > out.txt",
            "git status < in.txt",
            "git status & rm -rf build",
            "git status\nrm -rf build",
            "git status ${HOME}",
            "git status <(rm -rf build)",
            "git status >(cat)",
        ],
    )
    def test_argv_prefix_rejects_shell_control_and_expansion(self, tmp_path, command):
        """D5: substitution/chaining syntax must never be auto-approved by a rule."""
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="execute_shell_command", argv_prefix=("git", "status"))]
        arguments = {"command": command}
        assert manager.match_source("execute_shell_command", arguments) is None
        assert manager.is_allowed("execute_shell_command", arguments) is False

    def test_argv_prefix_still_matches_plain_arguments(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="execute_shell_command", argv_prefix=("git", "status"))]
        for command in ("git status -s", "git status --short --branch", "  git status   -s  "):
            assert manager.match_source("execute_shell_command", {"command": command}) == "rule"

    def test_argv_prefix_matches_and_rejects(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [
            PermissionRule(tool="execute_shell_command", argv_prefix=("git", "status")),
        ]
        shell = "execute_shell_command"
        assert manager.is_allowed(shell, {"command": "git status --short"}) is True
        assert manager.match_source(shell, {"command": "git status"}) == "rule"
        assert manager.is_allowed(shell, {"command": "git log --oneline"}) is False
        assert manager.is_allowed(shell, {"command": "rm -rf build"}) is False
        # The prefix only covers a single simple command: compound commands are not
        # auto-approved (they need a fresh confirmation).
        assert manager.is_allowed(shell, {"command": "git status && rm -rf build"}) is False
        assert manager.is_allowed(shell, {"command": "git status; rm -rf build"}) is False
        assert manager.is_allowed(shell, {"command": "git status > out.txt"}) is False
        # Unparseable / non-string commands never match.
        assert manager.is_allowed(shell, {"command": "git 'status"}) is False
        assert manager.is_allowed(shell, {}) is False

    def test_path_glob_matches_relative_and_absolute(self, tmp_path, workspace):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="fs_write_file", path_glob="src/**")]
        assert manager.is_allowed("fs_write_file", {"file_path": "src/main.py"}) is True
        assert manager.is_allowed("fs_write_file", {"file_path": str(workspace / "src" / "deep" / "x.py")}) is True
        assert manager.is_allowed("fs_write_file", {"file_path": "other/main.py"}) is False
        assert manager.is_allowed("fs_write_file", {"file_path": "../outside.py"}) is False
        assert manager.is_allowed("fs_write_file", {"content": "no path"}) is False

    def test_path_glob_requires_every_path_argument_to_match(self, tmp_path, workspace):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="fs_file_operations", path_glob="src/**")]
        move_within = {"operation": "move", "path": "src/a", "destination": "src/b"}
        assert manager.is_allowed("fs_file_operations", move_within) is True
        move_outside = {"operation": "move", "path": "src/a", "destination": "/etc/passwd"}
        assert manager.is_allowed("fs_file_operations", move_outside) is False

    def test_path_glob_rejects_dotdot_traversal(self, tmp_path, workspace):
        """D4: ``..`` segments must not let a relative glob match another directory."""
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="fs_write_file", path_glob="var/probe-g2/allowed/*")]
        arguments = {"file_path": "var/probe-g2/allowed/../../victim.txt"}
        # The traversal target really does resolve outside the allowed directory ...
        assert (workspace / "var" / "probe-g2" / "allowed" / ".." / ".." / "victim.txt").resolve() == (
            workspace / "var" / "victim.txt"
        ).resolve()
        # ... so the rule must not claim it.
        assert manager.match_source("fs_write_file", arguments) is None
        assert manager.is_allowed("fs_write_file", arguments) is False
        # A traversal that stays inside the workspace but leaves the glob root is refused
        # as well (raw text is never a match candidate, only normalized paths).
        assert manager.match_source("fs_write_file", {"file_path": "var/probe-g2/allowed/../allowed2/x.txt"}) is None
        # Normalized "." segments inside the glob root still match.
        assert manager.match_source("fs_write_file", {"file_path": "var/probe-g2/./allowed/ok.txt"}) == "rule"

    def test_path_glob_absolute_escape_not_matched_by_relative_glob(self, tmp_path, workspace):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="fs_write_file", path_glob="src/**")]
        # Absolute path inside the workspace is matched via its normalized relative form.
        assert manager.match_source("fs_write_file", {"file_path": str(workspace / "src" / "app.py")}) == "rule"
        # An absolute path outside the workspace has no workspace-relative form.
        outside = (tmp_path / "victim.txt").resolve()
        assert manager.match_source("fs_write_file", {"file_path": str(outside)}) is None
        assert manager.is_allowed("fs_write_file", {"file_path": str(outside)}) is False

    @pytest.mark.skipif(os.name != "posix", reason="symlinks are POSIX-only here")
    def test_path_glob_rejects_symlink_escape(self, tmp_path, workspace):
        allowed = workspace / "var" / "probe-g2" / "allowed"
        allowed.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "victim.txt").write_text("x", encoding="utf-8")
        (allowed / "link").symlink_to(outside, target_is_directory=True)
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="fs_write_file", path_glob="var/probe-g2/allowed/*")]
        # The symlink resolves outside the workspace, so no relative candidate matches.
        assert manager.match_source("fs_write_file", {"file_path": "var/probe-g2/allowed/link/victim.txt"}) is None
        # A plain file inside the same directory still matches.
        assert manager.match_source("fs_write_file", {"file_path": "var/probe-g2/allowed/ok.txt"}) == "rule"

    def test_rules_are_per_tool(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="execute_shell_command", argv_prefix=("git",))]
        assert manager.is_allowed("fs_write_file", {"file_path": "git/status"}) is False

    def test_raw_json_string_arguments_are_parsed_for_rules(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="execute_shell_command", argv_prefix=("pytest",))]
        assert manager.is_allowed("execute_shell_command", '{"command": "pytest -q"}') is True

    def test_session_allow_keeps_name_only_semantics(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.allow_session("execute_shell_command")
        assert manager.match_source("execute_shell_command") == "session"
        # Session approvals are not argument-aware (v1 semantics): the gate still runs
        # the danger classification before executing.
        assert manager.is_allowed("execute_shell_command", {"command": "rm -rf /"}) is True

    def test_persisted_file_mode_is_0600(self, tmp_path):
        if os.name != "posix":  # pragma: no cover - Windows has no POSIX mode bits
            pytest.skip("POSIX file modes only")
        path = tmp_path / "tool_permissions.json"
        manager = ToolApprovalManager(permissions_path=path)
        manager.allow_persist("fs_read_file")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


# ---------------------------------------------------------------------------
# 3. Client gate behaviour
# ---------------------------------------------------------------------------
class TestClientGate:
    def test_yes_allows_read_and_denies_write_exec(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.configure_run(yes=True)
        read = ToolCall(id="c1", name="fs_read_file", arguments='{"file_paths": ["a.txt"]}')
        write = ToolCall(id="c2", name="fs_write_file", arguments='{"file_path": "a.txt", "content": "x"}')
        shell = ToolCall(id="c3", name="execute_shell_command", arguments='{"command": "ls -la"}')
        client = make_client(script_tools(read, write, shell), manager, interactive=False)

        messages, confirms, execute_mock = run_turn(client)

        assert confirms == 0  # never prompts without a TTY
        execute_mock.assert_called_once()  # only the read tool ran
        assert client.tool_denied is True
        results = {message.name: message.content for message in tool_messages(messages)}
        assert results["fs_read_file"] == "ok"
        for name in ("fs_write_file", "execute_shell_command"):
            payload = json.loads(results[name])
            assert payload["error"] == "tool_denied"
            assert payload["reason"]

    def test_allowed_tools_patterns_are_per_run(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.configure_run(allowed_tools=["fs_*"])
        write = ToolCall(id="c1", name="fs_write_file", arguments='{"file_path": "a.txt", "content": "x"}')
        network = ToolCall(id="c2", name="web_search", arguments='{"query": "x"}')
        client = make_client(script_tools(write, network), manager, interactive=False)

        messages, confirms, execute_mock = run_turn(client)

        assert confirms == 0
        execute_mock.assert_called_once()
        results = {message.name: message.content for message in tool_messages(messages)}
        assert results["fs_write_file"] == "ok"
        assert json.loads(results["web_search"])["error"] == "tool_denied"
        # --allowed-tools is not persisted.
        assert manager.persistent_allow == set()
        assert ToolApprovalManager(permissions_path=manager.permissions_path).persistent_allow == set()

    def test_allowed_tools_enables_safe_shell_but_not_dangerous(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.configure_run(allowed_tools=["execute_shell_command"])
        safe = ToolCall(id="c1", name="execute_shell_command", arguments='{"command": "ls -la"}')
        client = make_client(script_tools(safe), manager, interactive=False)
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_called_once()
        assert client.tool_denied is False

        # A dangerous command is refused even though the tool name is allowed.
        dangerous = ToolCall(id="c2", name="execute_shell_command", arguments='{"command": "rm -rf build"}')
        manager2 = make_manager(tmp_path, "tool_permissions_2.json")
        manager2.configure_run(allowed_tools=["execute_shell_command"])
        client2 = make_client(script_tools(dangerous), manager2, interactive=False)
        messages2, confirms2, execute_mock2 = run_turn(client2)
        assert confirms2 == 0
        execute_mock2.assert_not_called()
        assert client2.tool_denied is True
        payload = json.loads(tool_messages(messages2)[0].content)
        assert payload["error"] == "tool_denied"
        assert "danger" in payload["reason"].lower()

    def test_approved_shell_tool_still_blocks_dangerous(self, tmp_path):
        """Acceptance: approving execute_shell_command does not approve ``rm -rf``."""
        manager = make_manager(tmp_path)
        manager.allow_session("execute_shell_command")
        dangerous = ToolCall(id="c1", name="execute_shell_command", arguments='{"command": "rm -rf build"}')
        client = make_client(script_tools(dangerous), manager, interactive=False)
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_not_called()
        assert client.tool_denied is True
        assert json.loads(tool_messages(messages)[0].content)["error"] == "tool_denied"

    def test_dangerous_shell_prompts_even_when_tool_is_allowed(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.allow_persist("execute_shell_command")
        dangerous = ToolCall(id="c1", name="execute_shell_command", arguments='{"command": "rm -rf build"}')
        client = make_client(script_tools(dangerous), manager, interactive=True)
        messages, confirms, execute_mock = run_turn(client, [ToolConfirmDecision.ONCE])
        assert confirms == 1  # an explicit confirmation was still required
        execute_mock.assert_called_once()
        assert client.tool_denied is False

    def test_dangerous_shell_denied_when_user_denies(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.allow_persist("execute_shell_command")
        dangerous = ToolCall(id="c1", name="execute_shell_command", arguments='{"command": "rm -rf build"}')
        client = make_client(script_tools(dangerous), manager, interactive=True)
        messages, confirms, execute_mock = run_turn(client, [ToolConfirmDecision.DENY])
        assert confirms == 1
        execute_mock.assert_not_called()
        payload = json.loads(tool_messages(messages)[0].content)
        assert payload["error"] == "tool_denied"
        assert "declined" in payload["reason"].lower()

    def test_dangerous_shell_denied_when_confirm_disabled(self, tmp_path):
        manager = make_manager(tmp_path)
        dangerous = ToolCall(id="c1", name="execute_shell_command", arguments='{"command": "rm -rf build"}')
        client = make_client(script_tools(dangerous), manager, interactive=True, tool_confirm=False)
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_not_called()
        assert client.tool_denied is True
        assert json.loads(tool_messages(messages)[0].content)["error"] == "tool_denied"

    def test_dangerous_detection_uses_decoded_arguments(self, tmp_path):
        """``\\u003b`` is decoded before danger classification (prompt/exec equality)."""
        manager = make_manager(tmp_path)
        manager.allow_persist("execute_shell_command")
        # ``\u003b`` is ``;`` — decoded the command is ``echo harmless; rm -rf build``.
        hidden = ToolCall(
            id="c1",
            name="execute_shell_command",
            arguments='{"command": "echo harmless\\u003b rm -rf build"}',
        )
        client = make_client(script_tools(hidden), manager, interactive=False)
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_not_called()
        assert client.tool_denied is True
        payload = json.loads(tool_messages(messages)[0].content)
        assert payload["error"] == "tool_denied"
        assert "rm" in payload["reason"].lower()

    def test_rule_allows_matching_call_without_prompt(self, tmp_path, workspace):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="execute_shell_command", argv_prefix=("git", "status"))]
        allowed = ToolCall(id="c1", name="execute_shell_command", arguments='{"command": "git status --short"}')
        client = make_client(script_tools(allowed), manager, interactive=True)
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_called_once()
        assert client.tool_denied is False

    def test_rule_denies_non_matching_command_then_prompts(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.persistent_rules = [PermissionRule(tool="execute_shell_command", argv_prefix=("git", "status"))]
        non_matching = ToolCall(id="c1", name="execute_shell_command", arguments='{"command": "git push"}')
        client = make_client(script_tools(non_matching), manager, interactive=True)
        messages, confirms, execute_mock = run_turn(client, [ToolConfirmDecision.ONCE])
        assert confirms == 1
        execute_mock.assert_called_once()

    def test_non_interactive_denies_unapproved(self, tmp_path):
        manager = make_manager(tmp_path)
        weather = ToolCall(id="c1", name="get_weather", arguments='{"city": "Paris"}')
        client = make_client(script_tools(weather), manager, interactive=False)
        messages, confirms, execute_mock = run_turn(client)
        assert confirms == 0
        execute_mock.assert_not_called()
        assert client.tool_denied is True
        payload = json.loads(tool_messages(messages)[0].content)
        assert payload["error"] == "tool_denied"
        assert "--allowed-tools" in payload["reason"]

    def test_deny_result_is_structured_json_and_sets_flag(self, tmp_path):
        manager = make_manager(tmp_path)
        write = ToolCall(id="c1", name="fs_write_file", arguments='{"file_path": "a.txt", "content": "x"}')
        client = make_client(script_tools(write), manager, interactive=True)
        messages, confirms, execute_mock = run_turn(client, [ToolConfirmDecision.DENY])
        execute_mock.assert_not_called()
        content = tool_messages(messages)[0].content
        payload = json.loads(content)
        assert payload["error"] == "tool_denied"
        assert "declined" in payload["reason"].lower()
        assert client.tool_denied is True
        # The old prose contract is gone: the model gets JSON it can reason about.
        assert not content.startswith("The user")

    def test_mcp_deny_result_keeps_gate_name_and_deprefixed_result_name(self, tmp_path):
        manager = make_manager(tmp_path)
        mcp = ToolCall(id="c1", name=f"{MCP_PREFIX}clock", arguments="{}")
        client = make_client(script_tools(mcp), manager, interactive=False)
        messages, _, execute_mock = run_turn(client)
        execute_mock.assert_not_called()
        assert tool_messages(messages)[0].name == "clock"
        assert json.loads(tool_messages(messages)[0].content)["error"] == "tool_denied"


# ---------------------------------------------------------------------------
# 4. Audit log
# ---------------------------------------------------------------------------
class TestAuditLog:
    def test_decisions_are_appended_as_jsonl(self, tmp_path, audit_log):
        manager = make_manager(tmp_path)
        manager.configure_run(yes=True)
        read = ToolCall(id="c1", name="fs_read_file", arguments='{"file_paths": ["a.txt"]}')
        write = ToolCall(id="c2", name="fs_write_file", arguments='{"file_path": "a.txt", "content": "x"}')
        client = make_client(script_tools(read, write), manager, interactive=False)
        run_turn(client)

        lines = audit_log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        records = [json.loads(line) for line in lines]
        assert [record["tool"] for record in records] == ["fs_read_file", "fs_write_file"]
        assert [record["decision"] for record in records] == ["allowed", "denied"]
        assert records[0]["risk"] == "read"
        assert records[1]["risk"] == "write"
        assert records[0]["source"] == "yes"
        assert records[1]["source"] == "non_interactive"
        for record in records:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["ts"])
            assert isinstance(record["args_summary"], str) and record["args_summary"]
            assert isinstance(record["duration_ms"], int) and record["duration_ms"] >= 0
        # Denials carry a reason; allowed calls do not.
        assert "reason" in records[1]
        assert "reason" not in records[0]
        if os.name == "posix":
            assert stat.S_IMODE(audit_log.stat().st_mode) == 0o600

    def test_error_decision_is_recorded(self, tmp_path, audit_log):
        manager = make_manager(tmp_path)
        weather = ToolCall(id="c1", name="get_weather", arguments='{"city": "Paris"}')
        manager.allow_persist("get_weather")
        client = make_client(script_tools(weather), manager, interactive=False)
        run_turn(client, execute_result=("tool exploded", False))
        record = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[0])
        assert record["decision"] == "error"
        assert record["source"] == "persist"

    def test_no_audit_file_when_disabled(self, tmp_path, audit_log):
        manager = make_manager(tmp_path)
        manager.allow_persist("get_weather")
        weather = ToolCall(id="c1", name="get_weather", arguments='{"city": "Paris"}')
        client = make_client(script_tools(weather), manager, interactive=False, audit=False)
        run_turn(client)
        assert not audit_log.exists()

    def test_unwritable_audit_log_does_not_break_the_tool_call(self, tmp_path, monkeypatch):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(const_module, "TOOL_AUDIT_PATH", blocker / "tool_audit.jsonl")
        manager = make_manager(tmp_path)
        manager.allow_persist("get_weather")
        weather = ToolCall(id="c1", name="get_weather", arguments='{"city": "Paris"}')
        client = make_client(script_tools(weather), manager, interactive=False)
        _, _, execute_mock = run_turn(client)
        execute_mock.assert_called_once()

    def test_args_summary_redacts_secrets_and_truncates(self):
        summary = summarize_arguments("execute_shell_command", {"command": "echo sk-abcdef1234567890AKIA"})
        assert "sk-abcdef1234567890AKIA" not in summary
        assert "[redacted]" in summary

        long_summary = summarize_arguments("get_weather", {"city": "x" * 2000})
        assert len(long_summary) <= 500
        assert long_summary.endswith("...")

        secret_args = {"api_key": "sk-super-secret-value-123"}
        redacted = summarize_arguments("get_weather", secret_args)
        assert "api_key" in redacted
        assert "sk-super-secret-value-123" not in redacted


# ---------------------------------------------------------------------------
# 5. Faithful confirmation preview / preview == execution arguments
# ---------------------------------------------------------------------------
class TestConfirmationPreview:
    def test_generic_preview_shows_canonical_arguments(self):
        preview = render_confirm_preview(
            ToolCall(id="c1", name="get_weather", arguments='{"city": "Paris", "city": "London"}')
        )
        # json_repair keeps the last duplicate key; the prompt must show that value.
        assert '"city": "London"' in preview
        assert "Paris" not in preview
        assert "risk: network" in preview

    def test_shell_preview_decodes_escapes_and_shows_danger(self):
        preview = render_confirm_preview(
            ToolCall(
                id="c1",
                name="execute_shell_command",
                arguments='{"command": "echo harmless\\u003b rm -rf build"}',
            )
        )
        assert "echo harmless; rm -rf build" in preview
        assert "dangerous: yes" in preview
        assert "recursive/force delete" in preview

    def test_shell_preview_safe_command(self):
        preview = render_confirm_preview(
            ToolCall(
                id="c1",
                name="execute_shell_command",
                arguments='{"command": "git status", "timeout": 30, "cwd": "/tmp"}',
            )
        )
        assert "command: git status" in preview
        assert "timeout: 30s" in preview
        assert "cwd: /tmp" in preview
        assert "dangerous: no" in preview

    def test_fs_write_preview_target_and_mode(self, tmp_path):
        target = tmp_path / "notes.txt"
        create_preview = render_confirm_preview(
            ToolCall(
                id="c1",
                name="fs_write_file",
                arguments=json.dumps({"file_path": str(target), "content": "hello\nworld\n"}),
            )
        )
        assert "mode: create new file" in create_preview
        assert "| hello" in create_preview
        assert "| world" in create_preview

        target.write_text("old", encoding="utf-8")
        overwrite_preview = render_confirm_preview(
            ToolCall(id="c2", name="fs_write_file", arguments=json.dumps({"file_path": str(target), "content": "new"}))
        )
        assert "mode: overwrite existing file" in overwrite_preview
        assert "| new" in overwrite_preview

    def test_fs_edit_preview_shows_unified_diff(self, tmp_path):
        target = tmp_path / "app.py"
        target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        preview = render_confirm_preview(
            ToolCall(
                id="c1",
                name="fs_edit_file",
                arguments=json.dumps(
                    {"file_path": str(target), "edits": [{"type": "replace", "old": "beta", "new": "BETA"}]}
                ),
            )
        )
        assert "diff (head)" in preview
        assert "-beta" in preview
        assert "+BETA" in preview
        assert "alpha" in preview

    def test_fs_edit_preview_falls_back_to_snippets(self, tmp_path):
        preview = render_confirm_preview(
            ToolCall(
                id="c1",
                name="fs_edit_file",
                arguments=json.dumps(
                    {
                        "file_path": str(tmp_path / "missing.py"),
                        "edits": [{"type": "append", "content": "tail"}],
                    }
                ),
            )
        )
        assert "diff (per edit)" in preview
        assert "append" in preview
        assert "+tail" in preview

    def test_preview_strips_control_characters(self):
        preview = render_confirm_preview(ToolCall(id="c1", name="get_weather", arguments='{"city": "\\u001b[31mred"}'))
        assert "\x1b" not in preview

    def test_preview_arguments_equal_executed_arguments_duplicate_keys(self):
        raw = '{"city": "Paris", "city": "London"}'
        executed = execute_and_capture("get_weather", raw)
        assert executed == parse_tool_arguments(raw) == {"city": "London"}
        preview = render_confirm_preview(ToolCall(id="c1", name="get_weather", arguments=raw))
        assert f"get_weather({canonical_arguments(raw)})" in preview

    def test_preview_arguments_equal_executed_arguments_unicode_escape(self):
        raw = '{"command": "echo harmless\\u003b rm -rf build"}'
        executed = execute_and_capture("execute_shell_command", raw)
        assert executed["command"] == "echo harmless; rm -rf build"
        preview = render_confirm_preview(ToolCall(id="c1", name="execute_shell_command", arguments=raw))
        assert executed["command"] in preview
        assert "dangerous: yes" in preview


# ---------------------------------------------------------------------------
# 6. /permissions REPL command
# ---------------------------------------------------------------------------
class CmdConsole:
    """CLI-shaped object exposing a real console to CmdHandler."""

    def __init__(self, manager):
        self.buffer = StringIO()
        self.console = Console(file=self.buffer, force_terminal=False, width=160, color_system=None)
        self.client = SimpleNamespace(approval=manager)
        self.chat = SimpleNamespace(history=[], title="test")
        self.verbose = False

    def output(self) -> str:
        return self.buffer.getvalue()


def make_cmd_handler(manager):
    fake_cli = CmdConsole(manager)
    return CmdHandler(fake_cli), fake_cli


class TestPermissionsCommand:
    def _seeded_manager(self, tmp_path):
        write_permissions(
            tmp_path,
            {
                "version": 2,
                "always_allow": ["fs_read_file", "get_weather"],
                "rules": [
                    {"tool": "execute_shell_command", "argv_prefix": ["git", "status"]},
                    {"tool": "fs_write_file", "path_glob": "src/**"},
                ],
            },
        )
        manager = make_manager(tmp_path)
        manager.allow_session("web_search")
        return manager

    def test_list_shows_session_persisted_and_rules(self, tmp_path):
        manager = self._seeded_manager(tmp_path)
        handler, cli = make_cmd_handler(manager)
        assert handler.handle_command(CMD_PERMISSIONS) is True
        output = cli.output()
        assert "Session approvals" in output
        assert "web_search" in output
        assert "Persistent always_allow" in output
        assert "fs_read_file" in output
        assert "1. execute_shell_command argv_prefix=['git', 'status']" in output
        assert "2. fs_write_file path_glob='src/**'" in output
        assert "/permissions revoke <tool-or-index>" in output

    def test_revoke_by_rule_index(self, tmp_path):
        manager = self._seeded_manager(tmp_path)
        handler, cli = make_cmd_handler(manager)
        assert handler.handle_command("/permissions revoke 1") is True
        assert "Revoked rule #1" in cli.output()
        assert len(manager.persistent_rules) == 1
        assert manager.persistent_rules[0].tool == "fs_write_file"
        # Persisted on disk too.
        reloaded = make_manager(tmp_path)
        assert len(reloaded.persistent_rules) == 1

    def test_revoke_by_tool_name_removes_allowlist_and_rules(self, tmp_path):
        manager = self._seeded_manager(tmp_path)
        manager.persistent_rules.append(PermissionRule(tool="get_weather", argv_prefix=("get",)))
        manager.allow_session("get_weather")
        handler, cli = make_cmd_handler(manager)
        assert handler.handle_command("/permissions revoke get_weather") is True
        assert "Revoked" in cli.output()
        assert "get_weather" not in manager.persistent_allow
        assert all(rule.tool != "get_weather" for rule in manager.persistent_rules)
        assert "get_weather" not in manager.session_allow

    def test_remove_is_accepted_as_alias(self, tmp_path):
        manager = self._seeded_manager(tmp_path)
        handler, cli = make_cmd_handler(manager)
        handler.handle_command("/permissions remove fs_read_file")
        assert "fs_read_file" not in manager.persistent_allow
        assert "Revoked" in cli.output()

    def test_unknown_target_is_reported(self, tmp_path):
        manager = self._seeded_manager(tmp_path)
        handler, cli = make_cmd_handler(manager)
        handler.handle_command("/permissions revoke 99")
        output = cli.output()
        assert "No permission matched '99'" in output
        assert "Persistent rules: 2" in output  # lists state again

    def test_oserror_is_reported_without_crashing(self, tmp_path, monkeypatch):
        manager = self._seeded_manager(tmp_path)

        def boom(target):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(manager, "revoke", boom)
        handler, cli = make_cmd_handler(manager)
        assert handler.handle_command("/permissions revoke fs_read_file") is True
        assert "Could not update the permission file" in cli.output()

    def test_unknown_subcommand_prints_usage(self, tmp_path):
        manager = self._seeded_manager(tmp_path)
        handler, cli = make_cmd_handler(manager)
        handler.handle_command("/permissions bogus")
        output = cli.output()
        assert "Unknown sub-command: bogus" in output
        assert "revoke <tool-or-index>" in output


# ---------------------------------------------------------------------------
# 7. entry.py run-policy plumbing
# ---------------------------------------------------------------------------
class TestEntryRunPolicy:
    def test_apply_run_tool_policy_configures_manager(self, tmp_path):
        manager = make_manager(tmp_path)
        cli = SimpleNamespace(client=SimpleNamespace(approval=manager))
        _apply_run_tool_policy(cli, yes=True, allowed_tools=["fs_*", "execute_shell_command"])
        assert manager.auto_allow_read is True
        assert manager.run_allow_patterns == ["fs_*", "execute_shell_command"]
        assert manager.is_run_allowed("fs_read_file") is True
        assert manager.is_run_allowed("web_search") is False

    def test_apply_run_tool_policy_tolerates_missing_client(self):
        # Mocked/legacy CLI objects must not break the entrypoint.
        _apply_run_tool_policy(SimpleNamespace(), yes=True, allowed_tools=["fs_*"])
        _apply_run_tool_policy(SimpleNamespace(client=None), yes=False, allowed_tools=[])


# ---------------------------------------------------------------------------
# 8. CLI mirroring: deny -> CLI.tool_denied -> --fail-on-tool-denied exit 3
# ---------------------------------------------------------------------------
class TestCliMirror:
    def test_cli_mirrors_client_tool_denied_and_exit_code_3(self):
        class FakeClient:
            tool_denied = True

            def completion_with_tools(self, messages, stream=False, tool_policy=None):
                yield LLMResponse(content="I could not run that.")

        cli = CLI(client=FakeClient())
        cli.configure_headless(print_mode=True, output_format="json", fail_on_tool_denied=True)
        stdout = StringIO()
        with contextlib.redirect_stdout(stdout):
            cli.run(chat=False, user_input="do it")

        payload = json.loads(stdout.getvalue())
        # The client sets the flag on any denial; the CLI mirrors it and the exit
        # mapping turns it into code 3 (entry.py raises typer.Exit(exit_code)).
        assert cli.tool_denied is True
        assert payload["exit_code"] == 3
        assert payload["error"]["kind"] == "tool"

    def test_cli_ignores_denial_without_flag(self):
        class FakeClient:
            tool_denied = True

            def completion_with_tools(self, messages, stream=False, tool_policy=None):
                yield LLMResponse(content="I could not run that.")

        cli = CLI(client=FakeClient())
        cli.configure_headless(print_mode=True, output_format="json", fail_on_tool_denied=False)
        stdout = StringIO()
        with contextlib.redirect_stdout(stdout):
            cli.run(chat=False, user_input="do it")

        payload = json.loads(stdout.getvalue())
        assert cli.tool_denied is True
        assert payload["exit_code"] == 0
