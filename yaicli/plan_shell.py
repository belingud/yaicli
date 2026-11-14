"""Read-only shell allowlist for plan mode (v0.24 K23).

Plan mode must stay write-free, but read-only exploration needs a shell. Instead
of asking the user to trust an LLM-classified command, plan mode exposes a small,
**fixed** allowlist of read-only commands executed as direct argv (never
``shell=True``). Anything else is rejected with a reason the model can read.

Validation is deliberately conservative:

* shell metacharacters (``; & | > < `` backquote, ``$(``, parentheses, newlines)
  are rejected before parsing — no pipes, redirects or command substitution;
* only :data:`PLAN_SHELL_ALLOWLIST` commands may run, plus ``git`` with a
  read-only subcommand (:data:`GIT_READONLY_SUBCOMMANDS`; ``git branch`` also
  requires ``--list``/``-l`);
* dangerous arguments (``find -delete``, ``find -exec``, ``rg --pre``,
  ``tree -o``, ``git -c``/``--exec-path``/...) are rejected for those commands.

This is a "best effort read-only front door", not a kernel-level security
boundary: ``cat`` can still read any readable path and ``find``/``grep`` can
walk large trees, hence the process-group timeout and the output cap below.
"""

import os
import re
import shlex
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

PLAN_SHELL_ALLOWLIST = ("ls", "pwd", "cat", "head", "tail", "wc", "grep", "rg", "find", "file", "stat", "tree", "which")
GIT_READONLY_SUBCOMMANDS = ("status", "diff", "log", "show", "ls-files", "blame", "rev-parse", "describe", "branch")
SHELL_METACHARS = (";", "&", "|", ">", "<", "`", "$(", ")", "\n", "\r")
DANGEROUS_ARGS: Dict[str, Tuple[str, ...]] = {
    "find": ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"),
    "rg": ("--pre", "--pre-glob", "--search-zip"),
    "tree": ("-o", "--output"),
    "file": ("-C", "--compile"),
    "git": ("-c", "--exec-path", "--config", "--upload-pack", "--work-tree"),
}
DEFAULT_TIMEOUT = 120
DEFAULT_OUTPUT_MAX_CHARS = 32000
MIN_TIMEOUT = 1
MAX_TIMEOUT = 600

ENV_TOOL_TIMEOUT = "YAI_TOOL_TIMEOUT"
ENV_TOOL_OUTPUT_MAX_CHARS = "YAI_TOOL_OUTPUT_MAX_CHARS"
ENV_WORKSPACE_ROOT = "YAI_WORKSPACE_ROOT"

DEFAULT_HINT = "use fs_read_file / fs_search_files / leave plan mode with Shift+Tab"
_METACHAR_REASON = "shell metacharacters are not allowed in plan mode (use `git status` or fs_read_file)"
_TIMEOUT_MESSAGE = "Error: command timed out after {seconds}s and was killed"

#: Only these variables are passed to the child process (same allowlist as the
#: ``execute_shell_command`` tool). Windows names are matched case-insensitively.
_ALLOWED_ENV_KEYS = frozenset(
    {
        # POSIX
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TERM",
        "TMPDIR",
        "SHELL",
        "USER",
        # Windows equivalents
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "USERNAME",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "COMPUTERNAME",
        "PSMODULEPATH",
    }
)
# Defence in depth: even if a future allowlist entry looks sensitive, never leak it.
_SENSITIVE_ENV_RE = re.compile(r"YAI_|KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|AUTH", re.IGNORECASE)
_KILL_REAP_SECONDS = 5


@dataclass(frozen=True)
class PlanShellVerdict:
    """Result of :func:`validate_plan_shell_command`."""

    allowed: bool
    argv: Tuple[str, ...] = ()
    reason: str = ""
    hint: str = DEFAULT_HINT


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _dangerous_flag(argument: str, flags: Sequence[str]) -> Optional[str]:
    """Return the offending argument when it matches one of ``flags``.

    Both the plain argument and the part before ``=`` are compared so
    ``--pre=/path/to/cmd`` is caught, and a leading prefix match also catches
    attached values (``-fprint0``, ``-execdir``) as well as the basename of a
    path-like argument.
    """
    normalized = argument.strip()
    if not normalized:
        return None
    flag_part = normalized.split("=", 1)[0]
    basename = normalized.replace("\\", "/").rsplit("/", 1)[-1]
    for flag in flags:
        if normalized == flag or flag_part == flag or normalized.startswith(flag) or basename == flag:
            return normalized
    return None


def _validate_git_argv(argv: Sequence[str]) -> PlanShellVerdict:
    """Validate ``git`` read-only subcommands (no global options, branch needs --list)."""
    if len(argv) < 2:
        return PlanShellVerdict(allowed=False, argv=tuple(argv), reason="`git` requires a read-only subcommand")
    subcommand = str(argv[1])
    if subcommand.startswith("-"):
        return PlanShellVerdict(
            allowed=False,
            argv=tuple(argv),
            reason=f"`git {subcommand}` global options are not allowed in plan mode",
        )
    if subcommand not in GIT_READONLY_SUBCOMMANDS:
        return PlanShellVerdict(
            allowed=False,
            argv=tuple(argv),
            reason=f"`git {subcommand}` is not a read-only git subcommand",
        )
    if subcommand == "branch" and not any(str(arg) in ("--list", "-l") for arg in argv[2:]):
        return PlanShellVerdict(
            allowed=False,
            argv=tuple(argv),
            reason="`git branch` without --list is not allowed in plan mode",
        )
    return PlanShellVerdict(allowed=True, argv=tuple(argv))


def _validate_argv(argv: Sequence[str]) -> PlanShellVerdict:
    """Allowlist / dangerous-argument validation for an already-split argv."""
    if not argv:
        return PlanShellVerdict(allowed=False, reason="empty command")
    command_name = str(argv[0])
    if command_name not in PLAN_SHELL_ALLOWLIST and command_name != "git":
        return PlanShellVerdict(
            allowed=False,
            argv=tuple(argv),
            reason=f"`{command_name}` is not in the plan-mode read-only allowlist",
        )
    dangerous_flags = DANGEROUS_ARGS.get(command_name, ())
    for argument in argv[1:]:
        offending = _dangerous_flag(str(argument), dangerous_flags)
        if offending is not None:
            return PlanShellVerdict(
                allowed=False,
                argv=tuple(argv),
                reason=f"`{offending}` is not allowed in plan mode",
            )
    if command_name == "git":
        return _validate_git_argv(argv)
    return PlanShellVerdict(allowed=True, argv=tuple(argv))


def validate_plan_shell_command(command: str) -> PlanShellVerdict:
    """Validate one plan-mode shell command string.

    Rejects empty input, shell metacharacters (no pipes/redirects/substitution),
    unparsable quoting, non-allowlisted commands and dangerous flags; an allowed
    verdict carries the argv to execute with :func:`run_plan_shell`.
    """
    if not isinstance(command, str) or not command.strip():
        return PlanShellVerdict(allowed=False, reason="empty command")
    # Parentheses are rejected unconditionally (a conservative rule that also
    # covers ``$(...)``/regex parentheses); the rest come from SHELL_METACHARS.
    if "(" in command or any(marker in command for marker in SHELL_METACHARS):
        return PlanShellVerdict(allowed=False, reason=_METACHAR_REASON)
    try:
        argv: List[str] = shlex.split(command)
    except ValueError as exc:
        return PlanShellVerdict(allowed=False, reason=f"cannot parse command: {exc}")
    return _validate_argv(argv)


def _workspace_root() -> str:
    """Return the directory shell commands may run in ('' env = current cwd)."""
    raw = os.environ.get(ENV_WORKSPACE_ROOT, "").strip()
    if raw:
        root = os.path.abspath(os.path.expanduser(raw))
        if os.path.isdir(root):
            return os.path.realpath(root)
    return os.path.realpath(os.getcwd())


def _resolve_cwd(cwd: Optional[str], root: str) -> Tuple[str, Optional[str]]:
    """Resolve a requested cwd against the workspace root; outside = in-band error."""
    if cwd is None or not str(cwd).strip():
        return root, None
    raw = os.path.expanduser(str(cwd).strip())
    if os.path.isabs(raw):
        target = os.path.realpath(raw)
    else:
        target = os.path.realpath(os.path.join(root, raw))
    try:
        common = os.path.commonpath([root, target])
    except ValueError:  # different drives on Windows
        common = ""
    if os.path.normcase(common) != os.path.normcase(root):
        return "", f"Error: cwd '{cwd}' is outside the workspace root '{root}'."
    if not os.path.isdir(target):
        return "", f"Error: cwd '{cwd}' does not exist or is not a directory."
    return target, None


def _filtered_env() -> Dict[str, str]:
    """Build the child environment: allowlisted keys only, no YAI_*/secrets."""
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _ALLOWED_ENV_KEYS and not _SENSITIVE_ENV_RE.search(key)
    }


def _resolve_timeout(timeout: Optional[int]) -> int:
    """Clamp the timeout to ``1..600``; ``YAI_TOOL_TIMEOUT`` supplies the default."""
    configured = _env_int(ENV_TOOL_TIMEOUT, DEFAULT_TIMEOUT)
    if timeout is None:
        requested = configured
    else:
        try:
            requested = int(timeout)
        except (TypeError, ValueError):
            requested = configured
        if requested == DEFAULT_TIMEOUT and configured != DEFAULT_TIMEOUT:
            requested = configured
    return max(MIN_TIMEOUT, min(requested, MAX_TIMEOUT))


def _output_max_chars() -> int:
    """Return the output cap in characters; ``0`` disables truncation."""
    return max(0, _env_int(ENV_TOOL_OUTPUT_MAX_CHARS, DEFAULT_OUTPUT_MAX_CHARS))


def _kill_process_group(process: "subprocess.Popen[bytes]") -> None:
    """Kill the child and every process it spawned (best effort)."""
    killpg = getattr(os, "killpg", None)
    getpgid = getattr(os, "getpgid", None)
    if killpg is not None and getpgid is not None:
        try:
            killpg(getpgid(process.pid), getattr(signal, "SIGKILL", signal.SIGTERM))
            return
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def _reap_process(process: "subprocess.Popen[bytes]") -> None:
    """Best-effort wait for an already killed process."""
    try:
        process.wait(timeout=_KILL_REAP_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _decode_output(data: bytes) -> str:
    """Decode captured bytes, normalising newlines like the shell tool."""
    text = data.decode("utf-8", errors="replace")
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _read_output(stream: Any, max_chars: int) -> str:
    """Read captured output from the temporary file, truncating to a head/tail window."""
    try:
        stream.flush()
        size = stream.seek(0, os.SEEK_END)
        stream.seek(0)
        if max_chars <= 0 or size <= max_chars:
            return _decode_output(stream.read())
        head_bytes = stream.read(max_chars)
        stream.seek(max(0, size - max_chars))
        tail_bytes = stream.read()
    except OSError:
        return ""
    marker = f"\n\n... [output truncated: {size} bytes total, showing head and tail] ...\n\n"
    budget = max(max_chars - len(marker), 2)
    head_chars = budget // 2
    tail_chars = budget - head_chars
    head = _decode_output(head_bytes)[:head_chars]
    tail = _decode_output(tail_bytes)[-tail_chars:]
    return f"{head}{marker}{tail}"


def run_plan_shell(argv: Sequence[str], *, cwd: Optional[str] = None, timeout: Optional[int] = None) -> str:
    """Execute an already-validated read-only argv and return the tool-result string.

    Runs :data:`argv` directly (``shell=False``) inside the workspace root, in its
    own process group (the whole group is SIGKILLed on timeout, case 124), with a
    filtered environment and a capped output capture. The result format mirrors
    the shell tool: ``Exit code: N, Output:\\n<text>``. Re-validates the argv as a
    defence in depth, so calling it without :func:`validate_plan_shell_command`
    can never execute a non-allowlisted command.
    """
    args = [str(arg) for arg in argv]
    verdict = _validate_argv(args)
    if not verdict.allowed:
        return f"Error: plan shell denied: {verdict.reason}"
    effective_timeout = _resolve_timeout(timeout)
    root = _workspace_root()
    resolved_cwd, cwd_error = _resolve_cwd(cwd, root)
    if cwd_error:
        return cwd_error
    max_chars = _output_max_chars()
    with tempfile.TemporaryFile() as output_file:
        try:
            process = subprocess.Popen(
                args,
                shell=False,
                stdout=output_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=resolved_cwd,
                env=_filtered_env(),
                start_new_session=True,
            )
        except OSError as exc:
            return f"Error: failed to start command: {exc}"
        timed_out = False
        try:
            exit_code = process.wait(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_group(process)
            _reap_process(process)
            exit_code = 124
        except KeyboardInterrupt:
            # Kill the child before letting the user's Ctrl-C unwind the agent loop.
            _kill_process_group(process)
            _reap_process(process)
            raise
        output = _read_output(output_file, max_chars)
        if timed_out:
            return _TIMEOUT_MESSAGE.format(seconds=effective_timeout)
        return f"Exit code: {exit_code}, Output:\n{output}"


__all__ = [
    "PLAN_SHELL_ALLOWLIST",
    "GIT_READONLY_SUBCOMMANDS",
    "SHELL_METACHARS",
    "DANGEROUS_ARGS",
    "DEFAULT_TIMEOUT",
    "DEFAULT_OUTPUT_MAX_CHARS",
    "PlanShellVerdict",
    "validate_plan_shell_command",
    "run_plan_shell",
]
