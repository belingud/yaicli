"""Execute a shell command with bounded runtime, filtered environment and capped output.

This is a standalone builtin function template: it is copied to
``~/.config/yaicli/functions/`` and executed as its own module, so it may only import the
standard library, ``pydantic`` and ``yaicli.function_schema``.

Guardrails (v0.19 K03):

* ``timeout`` (default 120s, clamped to 1..600) kills the whole process group with SIGKILL;
  a timed-out command reports the conventional exit code 124.
* ``cwd`` is resolved inside the workspace root (``YAI_WORKSPACE_ROOT`` when present, else the
  current directory); anything outside it is rejected in-band.
* The child process only receives an allowlisted environment (no ``YAI_API_KEY`` or other
  ``*KEY*``/``*TOKEN*``/``*SECRET*`` variables). ``YAI_TOOL_ENV_INHERIT=true`` restores the old
  full-environment behavior.
* Output is read from a temporary file (never a pipe, so large output cannot deadlock) and
  truncated to a head/tail window (default 32000 chars, ``YAI_TOOL_OUTPUT_MAX_CHARS`` override).
* ``YAI_TOOL_TIMEOUT`` overrides the default timeout when the model leaves it at 120s.
"""

import os
import re
import signal
import subprocess
import tempfile
from typing import Dict, Optional, Tuple

from pydantic import Field

from yaicli.function_schema import OpenAISchema

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600
MIN_TIMEOUT = 1
DEFAULT_OUTPUT_MAX_CHARS = 32000

ENV_TOOL_TIMEOUT = "YAI_TOOL_TIMEOUT"
ENV_TOOL_ENV_INHERIT = "YAI_TOOL_ENV_INHERIT"
ENV_TOOL_OUTPUT_MAX_CHARS = "YAI_TOOL_OUTPUT_MAX_CHARS"
ENV_WORKSPACE_ROOT = "YAI_WORKSPACE_ROOT"

# Only these variables are passed to the child by default. Windows names are matched
# case-insensitively (``Path`` vs ``PATH``).
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
_TIMEOUT_MESSAGE = "command timed out after {seconds}s and was killed"
_KILL_REAP_SECONDS = 5


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean-ish environment variable."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _workspace_root() -> str:
    """Return the directory shell commands may run in."""
    raw = os.environ.get(ENV_WORKSPACE_ROOT, "").strip()
    if raw:
        root = os.path.abspath(os.path.expanduser(raw))
        if os.path.isdir(root):
            return os.path.realpath(root)
    return os.path.realpath(os.getcwd())


def _resolve_cwd(cwd: Optional[str], root: str) -> Tuple[str, Optional[str]]:
    """Resolve and validate the requested working directory against the workspace root.

    Returns ``(resolved_path, error_message)``; exactly one of them is meaningful.
    """
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
    """Build the environment for the child process."""
    if _env_flag(ENV_TOOL_ENV_INHERIT, False):
        return dict(os.environ)
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _ALLOWED_ENV_KEYS and not _SENSITIVE_ENV_RE.search(key)
    }


def _resolve_timeout(timeout: Optional[int]) -> int:
    """Clamp the timeout to ``MIN_TIMEOUT..MAX_TIMEOUT``.

    ``YAI_TOOL_TIMEOUT`` is the configured default. It also replaces the model-facing default
    (120s) because an omitted argument and an explicit 120 are indistinguishable at this point.
    """
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
    """Kill the child shell and every process it spawned.

    Commands run with ``start_new_session=True`` so the shell is a process-group leader;
    ``os.killpg`` reaches the shell's children too. Windows has no ``os.killpg`` (and ignores
    ``start_new_session``), so fall back to ``process.kill()`` there.
    """
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
    """Decode captured bytes, normalising newlines like the old ``text=True`` capture did."""
    text = data.decode("utf-8", errors="replace")
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _read_output(stream, max_chars: int) -> str:
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


class Function(OpenAISchema):
    """
    Execute a shell command and return the output (result).

    Commands run inside the workspace root with a timeout (the whole process group is killed
    when it expires), a filtered environment without API keys, and a cap on the returned
    output size.
    """

    shell_command: str = Field(
        ...,
        json_schema_extra={
            "example": "ls -la",
        },
        description="Shell command to execute.",
    )
    timeout: int = Field(
        default=DEFAULT_TIMEOUT,
        description="Maximum execution time in seconds (1-600). The process group is killed when it expires.",
    )
    cwd: Optional[str] = Field(
        default=None,
        description=(
            "Working directory for the command, absolute or relative to the workspace root. "
            "It must stay inside the workspace root; defaults to the workspace root."
        ),
    )

    class Config:
        title = "execute_shell_command"

    @classmethod
    def execute(cls, shell_command: str, timeout: int = DEFAULT_TIMEOUT, cwd: Optional[str] = None) -> str:
        """
        Execute a shell command and return the output (result).

        Args:
            shell_command (str): shell command to execute.
            timeout (int): maximum execution time in seconds, clamped to 1-600.
            cwd (Optional[str]): working directory inside the workspace root.

        Returns:
            str: exit code and output string.
        """
        if not isinstance(shell_command, str) or not shell_command.strip():
            return "Error: shell_command must be a non-empty string."
        effective_timeout = _resolve_timeout(timeout)
        root = _workspace_root()
        resolved_cwd, cwd_error = _resolve_cwd(cwd, root)
        if cwd_error:
            return cwd_error
        max_chars = _output_max_chars()
        with tempfile.TemporaryFile() as output_file:
            try:
                process = subprocess.Popen(
                    shell_command,
                    shell=True,
                    stdout=output_file,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    cwd=resolved_cwd,
                    env=_filtered_env(),
                    start_new_session=True,
                )
            except OSError as exc:
                return f"Error: failed to start shell command: {exc}"
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
                notice = _TIMEOUT_MESSAGE.format(seconds=effective_timeout)
                if output and not output.endswith("\n"):
                    output += "\n"
                output += notice
            return f"Exit code: {exit_code}, Output:\n{output}"
