"""Tests for the plan-mode read-only shell layer (v0.24 K23).

Validation is pure; execution tests patch ``subprocess.Popen`` so no real child
process ever runs (except the tiny fake-process bookkeeping in this file).
"""

import os
import subprocess

import pytest

from yaicli import plan_shell
from yaicli.plan_shell import (
    DANGEROUS_ARGS,
    DEFAULT_HINT,
    DEFAULT_OUTPUT_MAX_CHARS,
    DEFAULT_TIMEOUT,
    GIT_READONLY_SUBCOMMANDS,
    PLAN_SHELL_ALLOWLIST,
    SHELL_METACHARS,
    PlanShellVerdict,
    run_plan_shell,
    validate_plan_shell_command,
)

METACHAR_REASON = "shell metacharacters are not allowed in plan mode (use `git status` or fs_read_file)"


class FakeProcess:
    """Minimal ``subprocess.Popen`` stand-in used by the execution tests."""

    def __init__(self, exit_code: int = 0, wait_error=None):
        self.pid = 987654321  # practically never a live pid: killpg falls back to kill()
        self.exit_code = exit_code
        self.wait_error = wait_error
        self.killed = False
        self.wait_timeouts = []

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        if self.wait_error is not None:
            raise self.wait_error
        return self.exit_code

    def kill(self):
        self.killed = True


def install_fake_popen(monkeypatch, *, output: bytes = b"", exit_code: int = 0, wait_error=None):
    """Patch ``plan_shell``'s Popen; returns (calls, fake process)."""
    calls = []
    process = FakeProcess(exit_code=exit_code, wait_error=wait_error)

    def fake_popen(args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        stdout = kwargs.get("stdout")
        if stdout is not None and output:
            stdout.write(output)
            stdout.flush()
        return process

    monkeypatch.setattr(plan_shell.subprocess, "Popen", fake_popen)
    return calls, process


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Isolated workspace root + a clean default shell environment."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "sub").mkdir()
    (root / "nested").mkdir()
    monkeypatch.setenv("YAI_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("YAI_TOOL_OUTPUT_MAX_CHARS", raising=False)
    monkeypatch.delenv("YAI_TOOL_TIMEOUT", raising=False)
    monkeypatch.delenv("YAI_TOOL_ENV_INHERIT", raising=False)
    return root


class TestConstants:
    def test_frozen_contract_constants(self):
        assert PLAN_SHELL_ALLOWLIST == (
            "ls",
            "pwd",
            "cat",
            "head",
            "tail",
            "wc",
            "grep",
            "rg",
            "find",
            "file",
            "stat",
            "tree",
            "which",
        )
        assert GIT_READONLY_SUBCOMMANDS == (
            "status",
            "diff",
            "log",
            "show",
            "ls-files",
            "blame",
            "rev-parse",
            "describe",
            "branch",
        )
        assert SHELL_METACHARS == (";", "&", "|", ">", "<", "`", "$(", ")", "\n", "\r")
        assert DANGEROUS_ARGS["find"] == (
            "-delete",
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-fprint",
            "-fprint0",
            "-fprintf",
            "-fls",
        )
        assert DANGEROUS_ARGS["rg"] == ("--pre", "--pre-glob", "--search-zip")
        assert DANGEROUS_ARGS["tree"] == ("-o", "--output")
        assert DANGEROUS_ARGS["file"] == ("-C", "--compile")
        assert DANGEROUS_ARGS["git"] == ("-c", "--exec-path", "--config", "--upload-pack", "--work-tree")
        assert DEFAULT_TIMEOUT == 120
        assert DEFAULT_OUTPUT_MAX_CHARS == 32000
        assert DEFAULT_HINT == "use fs_read_file / fs_search_files / leave plan mode with Shift+Tab"


class TestValidation:
    @pytest.mark.parametrize(
        ("command", "expected_argv"),
        [
            ("ls", ("ls",)),
            ("ls -la", ("ls", "-la")),
            ("pwd", ("pwd",)),
            ('cat "my file.txt"', ("cat", "my file.txt")),
            ("head -n 5 README.md", ("head", "-n", "5", "README.md")),
            ("tail -20 log.txt", ("tail", "-20", "log.txt")),
            ("wc -l tests/test_plan_store.py", ("wc", "-l", "tests/test_plan_store.py")),
            ("grep -rn submit_plan yaicli", ("grep", "-rn", "submit_plan", "yaicli")),
            ('rg -n "submit_plan" yaicli', ("rg", "-n", "submit_plan", "yaicli")),
            ("find . -name '*.py'", ("find", ".", "-name", "*.py")),
            ("file README.md", ("file", "README.md")),
            ("stat yaicli/const.py", ("stat", "yaicli/const.py")),
            ("tree -L 2 docs", ("tree", "-L", "2", "docs")),
            ("which python", ("which", "python")),
            ("git status", ("git", "status")),
            ("git diff --stat", ("git", "diff", "--stat")),
            ("git log --oneline -5", ("git", "log", "--oneline", "-5")),
            ("git show HEAD:yaicli/chat.py", ("git", "show", "HEAD:yaicli/chat.py")),
            ("git ls-files", ("git", "ls-files")),
            ("git blame README.md", ("git", "blame", "README.md")),
            ("git rev-parse --short HEAD", ("git", "rev-parse", "--short", "HEAD")),
            ("git describe --tags", ("git", "describe", "--tags")),
            ("git branch --list", ("git", "branch", "--list")),
            ("git branch -l", ("git", "branch", "-l")),
        ],
    )
    def test_allows_read_only_commands(self, command, expected_argv):
        verdict = validate_plan_shell_command(command)
        assert verdict == PlanShellVerdict(allowed=True, argv=expected_argv)

    @pytest.mark.parametrize(
        "command",
        [
            "git status | head -5",
            "ls; rm -rf /",
            "cat x > y",
            "cat x < y",
            "echo `date`",
            "echo $(date)",
            "find . -name '*.py' (x)",
            "ls && pwd",
            "ls || true",
            "cat file\nrm -rf build",
            "ls &",
        ],
    )
    def test_rejects_shell_metacharacters(self, command):
        verdict = validate_plan_shell_command(command)
        assert verdict.allowed is False
        assert verdict.reason == METACHAR_REASON
        assert verdict.hint == DEFAULT_HINT
        assert verdict.argv == ()

    @pytest.mark.parametrize("command", ["", "   ", "\t", None, 123])
    def test_rejects_empty_or_non_string(self, command):
        verdict = validate_plan_shell_command(command)
        assert verdict.allowed is False
        assert verdict.reason == "empty command"

    def test_rejects_unparsable_quoting(self):
        verdict = validate_plan_shell_command("cat 'unterminated")
        assert verdict.allowed is False
        assert verdict.reason.startswith("cannot parse command:")

    @pytest.mark.parametrize(
        ("command", "command_name"),
        [
            ("rm -rf build/", "rm"),
            ("python script.py", "python"),
            ("curl https://example.com", "curl"),
            ("make test", "make"),
            ("mv a b", "mv"),
            ("/bin/ls .", "/bin/ls"),
        ],
    )
    def test_rejects_non_allowlisted_commands(self, command, command_name):
        verdict = validate_plan_shell_command(command)
        assert verdict.allowed is False
        assert verdict.reason == f"`{command_name}` is not in the plan-mode read-only allowlist"
        assert verdict.hint == DEFAULT_HINT

    @pytest.mark.parametrize(
        ("command", "reported"),
        [
            ("find . -delete", "`-delete` is not allowed in plan mode"),
            ("find . -exec rm", "`-exec` is not allowed in plan mode"),
            ("find . -execdir rm", "`-execdir` is not allowed in plan mode"),
            ("find . -fprint0 out", "`-fprint0` is not allowed in plan mode"),
            ("find . -fls out", "`-fls` is not allowed in plan mode"),
            ("rg --pre ./script pattern", "`--pre` is not allowed in plan mode"),
            ("rg --pre=./script pattern", "`--pre=./script` is not allowed in plan mode"),
            ("rg --search-zip pattern", "`--search-zip` is not allowed in plan mode"),
            ("tree -o out.txt", "`-o` is not allowed in plan mode"),
            ("tree --output out.txt", "`--output` is not allowed in plan mode"),
            ("file -C", "`-C` is not allowed in plan mode"),
            ("git -c core.quotepath=false status", "`-c` is not allowed in plan mode"),
            ("git status --work-tree=/tmp", "`--work-tree=/tmp` is not allowed in plan mode"),
            ("git --exec-path status", "`--exec-path` is not allowed in plan mode"),
        ],
    )
    def test_rejects_dangerous_arguments(self, command, reported):
        verdict = validate_plan_shell_command(command)
        assert verdict.allowed is False
        assert verdict.reason == reported

    @pytest.mark.parametrize(
        ("command", "reason"),
        [
            ("git", "`git` requires a read-only subcommand"),
            ("git -C /tmp status", "`git -C` global options are not allowed in plan mode"),
            ("git push origin main", "`git push` is not a read-only git subcommand"),
            ("git checkout main", "`git checkout` is not a read-only git subcommand"),
            ("git branch", "`git branch` without --list is not allowed in plan mode"),
            ("git branch -a", "`git branch` without --list is not allowed in plan mode"),
        ],
    )
    def test_rejects_unsafe_git_usage(self, command, reason):
        verdict = validate_plan_shell_command(command)
        assert verdict.allowed is False
        assert verdict.reason == reason

    def test_git_branch_with_pattern_is_allowed(self):
        verdict = validate_plan_shell_command("git branch --list feature")
        assert verdict.allowed is True
        assert verdict.argv == ("git", "branch", "--list", "feature")


class TestRunPlanShell:
    def test_executes_argv_directly_in_the_workspace(self, workspace, monkeypatch):
        calls, _ = install_fake_popen(monkeypatch, output=b"hello\n", exit_code=0)

        result = run_plan_shell(["ls", "-la"])

        assert result == "Exit code: 0, Output:\nhello\n"
        assert len(calls) == 1
        assert calls[0]["args"] == ["ls", "-la"]
        kwargs = calls[0]["kwargs"]
        assert kwargs["shell"] is False
        assert kwargs["cwd"] == os.path.realpath(str(workspace))
        assert kwargs["start_new_session"] is True
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["stdout"].write is not None  # temporary file, not a pipe

    def test_non_zero_exit_code_is_reported(self, workspace, monkeypatch):
        install_fake_popen(monkeypatch, output=b"oops\n", exit_code=2)
        assert run_plan_shell(["cat", "missing"]) == "Exit code: 2, Output:\noops\n"

    def test_default_timeout_comes_from_the_shell_guardrail_config(self, workspace, monkeypatch):
        monkeypatch.setenv("YAI_TOOL_TIMEOUT", "7")
        _, process = install_fake_popen(monkeypatch)
        run_plan_shell(["ls"])
        assert process.wait_timeouts == [7]

    @pytest.mark.parametrize(("requested", "effective"), [(3, 3), (0, 1), (99999, 600)])
    def test_explicit_timeout_is_clamped(self, workspace, monkeypatch, requested, effective):
        _, process = install_fake_popen(monkeypatch)
        run_plan_shell(["ls"], timeout=requested)
        assert process.wait_timeouts == [effective]

    def test_timeout_kills_the_process_group(self, workspace, monkeypatch):
        monkeypatch.setenv("YAI_TOOL_TIMEOUT", "1")
        _, process = install_fake_popen(monkeypatch, wait_error=subprocess.TimeoutExpired("ls", 1))

        result = run_plan_shell(["ls"])

        assert result == "Error: command timed out after 1s and was killed"
        assert process.killed is True

    def test_output_is_capped(self, workspace, monkeypatch):
        monkeypatch.setenv("YAI_TOOL_OUTPUT_MAX_CHARS", "20")
        install_fake_popen(monkeypatch, output=b"A" * 500)

        result = run_plan_shell(["cat", "big.txt"])

        assert "A" * 500 not in result
        assert "output truncated: 500 bytes total, showing head and tail" in result

    def test_environment_is_filtered(self, workspace, monkeypatch):
        monkeypatch.setenv("YAI_API_KEY", "secret-yai")
        monkeypatch.setenv("SOME_SECRET_TOKEN", "secret-token")
        monkeypatch.setenv("YAI_TOOL_ENV_INHERIT", "true")  # plan mode never inherits
        monkeypatch.setenv("PATH", "/usr/bin")
        calls, _ = install_fake_popen(monkeypatch)

        run_plan_shell(["pwd"])

        child_env = calls[0]["kwargs"]["env"]
        assert "YAI_API_KEY" not in child_env
        assert "SOME_SECRET_TOKEN" not in child_env
        assert child_env["PATH"] == "/usr/bin"

    def test_relative_cwd_inside_workspace(self, workspace, monkeypatch):
        calls, _ = install_fake_popen(monkeypatch)
        run_plan_shell(["ls"], cwd="sub")
        expected = os.path.realpath(os.path.join(str(workspace), "sub"))
        assert calls[0]["kwargs"]["cwd"] == expected

    def test_cwd_outside_workspace_is_rejected_in_band(self, workspace, monkeypatch):
        calls, _ = install_fake_popen(monkeypatch)
        result = run_plan_shell(["ls"], cwd="..")
        assert result.startswith("Error: cwd '..' is outside the workspace root")
        assert calls == []

    def test_missing_cwd_is_rejected_in_band(self, workspace, monkeypatch):
        calls, _ = install_fake_popen(monkeypatch)
        result = run_plan_shell(["ls"], cwd="missing-dir")
        assert result == "Error: cwd 'missing-dir' does not exist or is not a directory."
        assert calls == []

    def test_start_failure_returns_in_band_error(self, workspace, monkeypatch):
        def failing_popen(*args, **kwargs):
            raise OSError("exec failed")

        monkeypatch.setattr(plan_shell.subprocess, "Popen", failing_popen)
        assert run_plan_shell(["ls"]) == "Error: failed to start command: exec failed"

    def test_invalid_argv_is_denied_before_execution(self, workspace, monkeypatch):
        calls, _ = install_fake_popen(monkeypatch)
        result = run_plan_shell(["rm", "-rf", "/"])
        assert result == "Error: plan shell denied: `rm` is not in the plan-mode read-only allowlist"
        assert calls == []

    def test_keyboard_interrupt_kills_the_child_and_propagates(self, workspace, monkeypatch):
        _, process = install_fake_popen(monkeypatch, wait_error=KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            run_plan_shell(["ls"])
        assert process.killed is True
