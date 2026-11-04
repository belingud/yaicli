"""Tool risk classification for the permission / approval gates (v0.19 K03/K06).

This module is intentionally **stdlib-only** and imports nothing from ``yaicli``: the builtin
function loader, the tool approval gate and the tests can import it without pulling in the rest
of the package.

Public contract (stable — consumed by the approval layer):

* ``RiskLevel``: a ``StrEnum`` with ``read`` / ``write`` / ``network`` / ``exec``.
* ``BUILTIN_TOOL_RISK``: mapping of the 12 builtin function names to a ``RiskLevel``.
* ``get_tool_risk(name) -> RiskLevel``: MCP tools (``_mcp__`` prefix) and unknown tools are
  ``RiskLevel.exec``.
* ``ShellRisk``: dataclass ``(level: RiskLevel, dangerous: bool, reasons: list[str])``.
* ``classify_shell_command(command) -> ShellRisk``: tokenises with :mod:`shlex` and analyses the
  argv/flag structure. There is deliberately **no substring blacklist**, so ``git add`` is no
  longer a false positive while ``rm -r -f`` is caught. ``dangerous`` is *advisory*: the caller
  decides whether to confirm, deny or allow — this module never blocks execution itself.
* ``is_dangerous_shell(command) -> tuple[bool, list[str]]``: convenience wrapper.

Only ``dangerous`` / ``reasons`` are security relevant; ``level`` is the coarse class used to pick
a policy (auto-allow ``read`` tools, confirm the rest).
"""

from __future__ import annotations

import enum
import os
import re
import shlex
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

try:  # Python 3.11+
    from enum import StrEnum as _StrEnumBase
except ImportError:  # pragma: no cover - Python 3.10 fallback

    class _StrEnumBase(str, enum.Enum):  # type: ignore[no-redef]
        """Minimal ``StrEnum`` backport for Python 3.10."""

        def __str__(self) -> str:
            return str(self.value)


class RiskLevel(_StrEnumBase):
    """Coarse risk class of a tool or shell command."""

    read = "read"
    write = "write"
    network = "network"
    exec = "exec"


#: Risk class of every bundled builtin function (``yaicli/functions/buildin/``).
BUILTIN_TOOL_RISK: Dict[str, RiskLevel] = {
    # read
    "fs_read_file": RiskLevel.read,
    "fs_list_directory": RiskLevel.read,
    "fs_search_files": RiskLevel.read,
    "fs_get_filesystem_info": RiskLevel.read,
    "fs_read_image": RiskLevel.read,
    # write
    "fs_write_file": RiskLevel.write,
    "fs_edit_file": RiskLevel.write,
    "fs_file_operations": RiskLevel.write,
    # network
    "fetch_webpage": RiskLevel.network,
    "web_search": RiskLevel.network,
    "get_weather": RiskLevel.network,
    # exec
    "execute_shell_command": RiskLevel.exec,
}

_MCP_TOOL_PREFIX = "_mcp__"

_LEVEL_ORDER: Tuple[RiskLevel, ...] = (
    RiskLevel.read,
    RiskLevel.network,
    RiskLevel.write,
    RiskLevel.exec,
)
_LEVEL_RANK = {level: rank for rank, level in enumerate(_LEVEL_ORDER)}


def _max_level(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    """Return the more severe of two risk levels."""
    return left if _LEVEL_RANK[left] >= _LEVEL_RANK[right] else right


def get_tool_risk(name: str) -> RiskLevel:
    """Return the risk level of a tool name.

    MCP tools (``_mcp__`` prefix) and unknown/custom tools are arbitrary code from the caller's
    point of view, so they are classified as ``RiskLevel.exec``.
    """
    if not name:
        return RiskLevel.exec
    if name.startswith(_MCP_TOOL_PREFIX):
        return RiskLevel.exec
    return BUILTIN_TOOL_RISK.get(name, RiskLevel.exec)


@dataclass
class ShellRisk:
    """Classification result for a shell command.

    Attributes:
        level: coarse risk class; ``exec`` for ``dangerous`` commands.
        dangerous: whether the command matches a destructive pattern. Advisory only: callers may
            still execute it after an explicit confirmation.
        reasons: human readable reasons, empty when the command is not dangerous.
    """

    level: RiskLevel
    dangerous: bool
    reasons: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Shell token / argv analysis helpers
# ---------------------------------------------------------------------------

_OPERATOR_CHARS = ";&|<>"
_COMMAND_SEPARATORS = frozenset({"|", "|&", "||", "&&", ";", "&"})
_WRITE_REDIRECT_OPS = frozenset({">", ">>", "&>", "&>>", ">|"})

# Wrappers that run another command: the dangerous command is the *inner* one, so the wrapper
# and its own arguments are stripped before argv analysis (``sudo rm -rf /`` is an ``rm``).
_WRAPPER_NAMES = frozenset(
    "sudo doas env command builtin exec nohup nice ionice time timeout watch strace ltrace xargs busybox caffeinate".split()
)
_WRAPPER_VALUE_FLAGS: Dict[str, FrozenSet[str]] = {
    name: frozenset(flags.split(" "))
    for name, flags in {
        "sudo": "-u --user -g --group -p --prompt -C --close-from -h --host -r --role -t --type",
        "doas": "-u",
        "env": "-u --unset -C --chdir -S --split-string",
        "nice": "-n --adjustment",
        "ionice": "-c --class -n --classdata -p --pid",
        "watch": "-n --interval",
        "timeout": "-s --signal -k --kill-after",
        "strace": "-e --trace -o --output -p --attach -s --string-limit",
        "xargs": "-n --max-args -I --replace -d --delimiter -L --max-lines -P --max-procs "
        "-s --max-chars -E --eof -a --arg-file",
    }.items()
}
_DURATION_RE = re.compile(r"\d+(?:\.\d+)?[smhd]?")
_ENV_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")

# Commands that can stream remote content into a shell interpreter.
_DOWNLOAD_VERBS = frozenset({"curl", "wget", "wget2", "fetch", "http", "https", "httpie", "aria2c"})
_SHELL_VERB_RE = re.compile(
    r"^(?:sh|bash|zsh|dash|ksh|mksh|ash|fish|csh|tcsh|"
    r"python\d*(?:\.\d+)?|py|perl|ruby|node(?:js)?|php\d*|lua\d*(?:\.\d+)?|"
    r"rscript|osascript|powershell|pwsh|cmd)$"
)

_READ_VERBS = frozenset(
    "ls cat head tail wc grep egrep fgrep rg ag file stat pwd whoami id date uname hostname df du ps top htop "
    "free uptime which whereis type tree diff cmp sort uniq cut tr jq yq nl od xxd hexdump strings md5sum "
    "sha1sum sha256sum shasum basename dirname realpath readlink echo printf printenv find sed awk gawk true "
    "false test [ getent locale cal history less more bat cd pushd popd sleep wait clear dir".split()
)
_WRITE_VERBS = frozenset(
    "touch mkdir rmdir rm mv cp ln chmod chown chgrp truncate tee dd install unlink shred patch tar unzip zip "
    "gzip gunzip bzip2 xz mkfifo mknod mount umount useradd userdel groupadd passwd chattr setfacl crontab at "
    "kill pkill killall fdisk parted mkswap swapon swapoff sysctl modprobe insmod rmmod iptables nft ufw "
    "firewall-cmd wipefs sgdisk gdisk partprobe losetup dd_rescue".split()
)
_NETWORK_VERBS = frozenset(
    "curl wget wget2 ssh scp sftp rsync nc netcat ncat telnet ping ping6 dig host nslookup traceroute tracert "
    "ftp aria2c socat nmap masscan iperf iperf3 whois".split()
)

_GIT_READ_SUBCOMMANDS = frozenset(
    "status log diff show rev-parse ls-files ls-tree ls-remote blame describe grep shortlog whatchanged "
    "version help".split()
)
_GIT_WRITE_SUBCOMMANDS = frozenset(
    "add commit reset checkout switch restore rm mv clean merge rebase apply am stash init cherry-pick revert "
    "tag branch notes worktree".split()
)
_GIT_NETWORK_SUBCOMMANDS = frozenset("clone fetch pull push remote submodule".split())


def _level_map(risk: RiskLevel, words: str) -> Dict[str, RiskLevel]:
    return dict.fromkeys(words.split(), risk)


_PACKAGE_SUBCOMMAND_RISK: Dict[str, Dict[str, RiskLevel]] = {
    "pip": {
        **_level_map(RiskLevel.read, "list show freeze check"),
        **_level_map(RiskLevel.write, "install uninstall"),
        **_level_map(RiskLevel.network, "download"),
    },
    "pip3": {
        **_level_map(RiskLevel.read, "list show freeze"),
        **_level_map(RiskLevel.write, "install uninstall"),
        **_level_map(RiskLevel.network, "download"),
    },
    "uv": {**_level_map(RiskLevel.write, "pip add remove sync lock"), **_level_map(RiskLevel.exec, "run tool")},
    "npm": {
        **_level_map(RiskLevel.read, "ls list view outdated"),
        **_level_map(RiskLevel.write, "install i add remove uninstall"),
        **_level_map(RiskLevel.exec, "run"),
    },
    "yarn": {**_level_map(RiskLevel.read, "list info"), **_level_map(RiskLevel.write, "add install remove")},
    "pnpm": {**_level_map(RiskLevel.read, "list"), **_level_map(RiskLevel.write, "add install remove")},
    "docker": _level_map(RiskLevel.read, "ps images logs inspect version info"),
    "podman": _level_map(RiskLevel.read, "ps images logs inspect version"),
    "systemctl": _level_map(RiskLevel.read, "status show is-active is-enabled list-units list-unit-files"),
    "brew": {
        **_level_map(RiskLevel.read, "list info search"),
        **_level_map(RiskLevel.write, "install uninstall upgrade"),
        **_level_map(RiskLevel.network, "update"),
    },
}

_MKFS_RE = re.compile(r"^mkfs(?:\.[A-Za-z0-9._-]+)?$")
_SHUTDOWN_VERBS = frozenset({"shutdown", "reboot", "poweroff", "halt"})
_FIND_DESTRUCTIVE_EXECS = frozenset({"rm", "rmdir", "shred", "unlink", "dd", "mv", "chmod", "chown", "truncate"})
_SYSTEMCTL_DANGEROUS_SUBCOMMANDS = frozenset({"poweroff", "reboot", "halt", "shutdown", "suspend", "hibernate"})
_SYSTEM_DIRS = frozenset(
    {"/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32", "/proc", "/sbin", "/sys", "/usr"}
)
_SAFE_DEVICE_NAMES = frozenset(
    {"null", "zero", "full", "random", "urandom", "stdout", "stderr", "stdin", "tty", "ptmx"}
)

# A shell function that pipes itself into itself in the background and calls itself. This cannot
# be expressed as argv, so it is the one structural pattern detected on the raw text.
_FORK_BOMB_PATTERNS = (
    re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
    re.compile(r"([A-Za-z_][\w.-]*)\s*\(\s*\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}\s*;\s*\1"),
)


def _verb(token: str) -> str:
    """Normalise a command token to its bare verb (``/usr/bin/rm`` -> ``rm``)."""
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".com"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def _is_shell_verb(verb: str) -> bool:
    return bool(_SHELL_VERB_RE.match(verb))


def _is_operator(token: str) -> bool:
    return bool(token) and all(char in _OPERATOR_CHARS for char in token)


def _is_env_assignment(token: str) -> bool:
    return bool(_ENV_ASSIGNMENT_RE.fullmatch(token))


def _tokenize(command: str) -> Optional[List[str]]:
    """Tokenise with shlex, keeping shell operators as standalone tokens.

    Returns ``None`` when the command cannot be quoted/parsed safely.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_OPERATOR_CHARS)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return None


def _skip_prelude(argv: List[str]) -> List[str]:
    """Strip privilege/launcher/timeout wrappers so the real command is argv[0]."""
    index = 0
    total = len(argv)
    while index < total:
        token = argv[index]
        name = _verb(token)
        if name in _WRAPPER_NAMES:
            index += 1
            value_flags = _WRAPPER_VALUE_FLAGS.get(name, frozenset())
            while index < total:
                inner = argv[index]
                if name == "env" and _is_env_assignment(inner):
                    index += 1
                    continue
                if inner.startswith("-") and inner != "-":
                    index += 1
                    if inner in value_flags:
                        index += 1
                    continue
                if name == "timeout" and _DURATION_RE.fullmatch(inner):
                    index += 1
                    continue
                break
            continue
        if _is_env_assignment(token):
            index += 1
            continue
        return argv[index:]
    return []


def _short_flag_chars(args: List[str]) -> str:
    """Return the characters of combined short flags (``-rf`` -> ``rf``), case preserved."""
    chars = []
    for arg in args:
        if arg.startswith("-") and not arg.startswith("--") and arg != "-":
            chars.extend(arg[1:])
    return "".join(chars)


def _has_recursive_flag(args: List[str]) -> bool:
    if "--recursive" in args:
        return True
    return any(arg.startswith("-") and not arg.startswith("--") and "R" in arg[1:] for arg in args)


def _subcommand_lookup(table: Dict[str, RiskLevel], args: List[str]) -> RiskLevel:
    if not args:
        return RiskLevel.exec
    return table.get(args[0].lower(), RiskLevel.exec)


def _is_safe_device_path(path: str) -> bool:
    """True for harmless pseudo devices such as ``/dev/null`` or ``/dev/stdout``."""
    normalized = os.path.normpath(path.replace("\\", "/")).lower()
    if not normalized.startswith("/dev/"):
        return False
    name = normalized[len("/dev/") :]
    return name in _SAFE_DEVICE_NAMES or name.startswith(("fd/", "pts/", "shm/"))


def _is_device_path(path: str) -> bool:
    """True for a raw device path (``/dev/sda``, ``/dev/nvme0n1``, ...)."""
    normalized = os.path.normpath(path.replace("\\", "/")).lower()
    return normalized.startswith("/dev/") and not _is_safe_device_path(normalized)


def _is_system_path(path: str) -> bool:
    """True for a path inside a system directory (``/etc``, ``/usr/bin``, ``C:\\Windows``, ...)."""
    if not path or path.startswith("~"):
        return False
    normalized = path.replace("\\", "/").strip()
    if re.match(r"^[A-Za-z]:/", normalized):
        return normalized.lower().startswith(("c:/windows", "c:/program files", "c:/programdata"))
    if not normalized.startswith("/"):
        return False
    if _is_safe_device_path(normalized):
        return False
    norm = os.path.normpath(normalized)
    if norm == "/":
        return True
    first = "/" + norm.lstrip("/").split("/", 1)[0]
    return first in _SYSTEM_DIRS


def _plain_operands(args: List[str]) -> List[str]:
    """Arguments that look like operands (not flags / option values)."""
    return [arg for arg in args if not arg.startswith("-") or arg == "-"]


def _destination(args: List[str]) -> str:
    """Best-effort destination operand of ``cp``/``mv``/``install``/``ln``."""
    for index, arg in enumerate(args):
        if arg in {"-t", "--target-directory"} and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("--target-directory="):
            return arg.split("=", 1)[1]
    operands = _plain_operands(args)
    return operands[-1] if operands else ""


def _parse_command(tokens: List[str]) -> Tuple[List[List[str]], List[str], List[Tuple[str, str]]]:
    """Split tokens into simple commands, the separators between them and redirects."""
    segments: List[List[str]] = []
    separators: List[str] = []
    redirects: List[Tuple[str, str]] = []
    current: List[str] = []
    index = 0
    total = len(tokens)
    while index < total:
        token = tokens[index]
        if _is_operator(token):
            if token in _COMMAND_SEPARATORS:
                segments.append(current)
                current = []
                separators.append(token)
                index += 1
                continue
            redirect_op = token
            target = ""
            index += 1
            if index < total and not _is_operator(tokens[index]):
                target = tokens[index]
                index += 1
            redirects.append((redirect_op, target))
            continue
        current.append(token)
        index += 1
    segments.append(current)
    if len(separators) >= len(segments):
        separators = separators[: max(len(segments) - 1, 0)]
    return segments, separators, redirects


def _classify_segment(argv: List[str]) -> RiskLevel:
    """Classify one simple command (already split on ``;``/``&&``/``|``/...)."""
    effective = _skip_prelude(argv)
    if not effective:
        return RiskLevel.read
    verb = _verb(effective[0])
    args = effective[1:]

    if verb == "git":
        subcommand = args[0].lower() if args else ""
        if subcommand in _GIT_READ_SUBCOMMANDS:
            return RiskLevel.read
        if subcommand in _GIT_NETWORK_SUBCOMMANDS:
            return RiskLevel.network
        if subcommand in _GIT_WRITE_SUBCOMMANDS:
            return RiskLevel.write
        return RiskLevel.exec
    if verb in _PACKAGE_SUBCOMMAND_RISK:
        return _subcommand_lookup(_PACKAGE_SUBCOMMAND_RISK[verb], args)
    if verb == "sed":
        for arg in args:
            if (
                arg == "--in-place"
                or arg.startswith("--in-place=")
                or (arg.startswith("-") and not arg.startswith("--") and "i" in arg[1:])
            ):
                return RiskLevel.write
        return RiskLevel.read
    if verb == "find" and any(arg in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for arg in args):
        return RiskLevel.exec
    if _is_shell_verb(verb):
        return RiskLevel.exec
    if verb in _WRITE_VERBS:
        return RiskLevel.write
    if verb in _NETWORK_VERBS:
        return RiskLevel.network
    if verb in _READ_VERBS:
        return RiskLevel.read
    return RiskLevel.exec


def _segment_danger_reasons(argv: List[str], depth: int = 1) -> List[str]:
    """Return destructive patterns found in one simple command."""
    reasons: List[str] = []
    effective = _skip_prelude(argv)
    if not effective:
        return reasons
    verb = _verb(effective[0])
    args = effective[1:]

    if _MKFS_RE.match(verb):
        reasons.append(f"{verb} formats a filesystem")
    if verb in _SHUTDOWN_VERBS:
        reasons.append(f"{verb} stops or reboots the machine")
    if verb == "init" and any(arg in {"0", "6"} for arg in args):
        reasons.append("init switches the machine runlevel (shutdown/reboot)")
    if verb in {"systemctl", "service"} and args:
        subcommand = args[0].lower()
        if subcommand in _SYSTEMCTL_DANGEROUS_SUBCOMMANDS:
            reasons.append(f"{verb} {subcommand} stops or reboots the machine")

    if verb == "rm":
        short_flags = _short_flag_chars(args)
        recursive = "r" in short_flags or "R" in short_flags or "--recursive" in args
        force = "f" in short_flags or "--force" in args
        if recursive or force:
            parts = []
            if recursive:
                parts.append("recursive")
            if force:
                parts.append("force")
            reasons.append("rm with " + "/".join(parts) + " delete")

    if verb == "dd":
        for arg in args:
            if arg.startswith("of=") and _is_device_path(arg[3:]):
                reasons.append(f"dd writes to the raw device {arg[3:]}")

    if verb in {"chmod", "chown", "chgrp"} and _has_recursive_flag(args):
        if any(_is_system_path(operand) for operand in _plain_operands(args)):
            reasons.append(f"recursive {verb} on a system path")

    if verb == "find":
        for index, arg in enumerate(args):
            if arg == "-delete":
                reasons.append("find -delete removes the matching files")
            elif arg in {"-exec", "-execdir", "-ok", "-okdir"} and index + 1 < len(args):
                exec_verb = _verb(args[index + 1])
                if exec_verb in _FIND_DESTRUCTIVE_EXECS:
                    reasons.append(f"find {arg} {exec_verb} runs a destructive command")

    if verb == "git" and args and args[0].lower() == "clean":
        clean_args = args[1:]
        if "f" in _short_flag_chars(clean_args) or any(arg.startswith("--force") for arg in clean_args):
            reasons.append("git clean removes untracked files")

    if verb == "truncate":
        for operand in _plain_operands(args):
            if _is_device_path(operand):
                reasons.append(f"truncate writes to the raw device {operand}")

    if verb in {"mv", "cp", "install", "ln"}:
        destination = _destination(args)
        if destination and _is_device_path(destination):
            reasons.append(f"{verb} writes to the raw device {destination}")
        elif destination and _is_system_path(destination):
            reasons.append(f"{verb} writes into the system directory {destination}")

    if depth > 0 and _is_shell_verb(verb):
        for index, arg in enumerate(args):
            script: Optional[str] = None
            if arg == "-c" and index + 1 < len(args):
                script = args[index + 1]
            elif arg.startswith("-c") and len(arg) > 2 and not arg.startswith("--"):
                script = arg[2:]
            if not script:
                continue
            if _DOWNLOAD_IN_SHELL_RE.search(script):
                reasons.append("downloads and executes a command through a shell -c script")
            reasons.extend(f"shell -c: {reason}" for reason in _script_danger_reasons(script, depth - 1))

    return reasons


_DOWNLOAD_IN_SHELL_RE = re.compile(r"(?:\$\(|`)\s*(?:curl|wget|fetch)\b")
# ``$(...)`` and backtick command substitutions execute a nested command; its text is analysed
# like a top level command so a destructive command cannot hide behind ``echo $(...)``.
_SUBSTITUTION_PATTERNS = (
    re.compile(r"\$\(([^()]*)\)"),
    re.compile(r"`([^`]*)`"),
    # process substitution: ``diff <(rm -rf /)``
    re.compile(r"[<>]\(([^()]*)\)"),
)


def _substitution_analysis(command: str, depth: int = 1) -> Tuple[RiskLevel, List[str]]:
    """Classify the nested commands inside ``$(...)``/backtick substitutions."""
    level = RiskLevel.read
    reasons: List[str] = []
    if depth <= 0:
        return level, reasons
    for pattern in _SUBSTITUTION_PATTERNS:
        for match in pattern.finditer(command):
            inner = match.group(1).strip()
            if not inner:
                continue
            tokens = _tokenize(inner)
            if tokens is None:
                level = RiskLevel.exec
                reasons.append("command substitution could not be parsed safely")
                continue
            segments, separators, redirects = _parse_command(tokens)
            for argv in segments:
                level = _max_level(level, _classify_segment(argv))
                reasons.extend(f"command substitution: {reason}" for reason in _segment_danger_reasons(argv))
            level = _max_level(level, _redirect_level(redirects))
            reasons.extend(f"command substitution: {reason}" for reason in _redirect_danger_reasons(redirects))
            reasons.extend(f"command substitution: {reason}" for reason in _pipe_danger_reasons(segments, separators))
            nested_level, nested_reasons = _substitution_analysis(inner, depth - 1)
            level = _max_level(level, nested_level)
            reasons.extend(nested_reasons)
    return level, reasons


def _script_danger_reasons(script: str, depth: int) -> List[str]:
    """Analyse the command string passed to ``sh -c`` (one level deep)."""
    tokens = _tokenize(script)
    if tokens is None:
        return ["unparseable shell -c script"]
    segments, separators, redirects = _parse_command(tokens)
    reasons: List[str] = []
    for argv in segments:
        reasons.extend(_segment_danger_reasons(argv, depth=depth))
    reasons.extend(_redirect_danger_reasons(redirects))
    reasons.extend(_pipe_danger_reasons(segments, separators))
    return reasons


def _redirect_danger_reasons(redirects: List[Tuple[str, str]]) -> List[str]:
    reasons: List[str] = []
    for redirect_op, target in redirects:
        if not target:
            continue
        is_write = redirect_op in _WRITE_REDIRECT_OPS or (redirect_op == ">&" and not target.isdigit())
        if not is_write:
            continue
        if _is_device_path(target):
            reasons.append(f"redirects output to the raw device {target}")
        elif _is_system_path(target):
            reasons.append(f"redirects output into the system path {target}")
    return reasons


def _redirect_level(redirects: List[Tuple[str, str]]) -> RiskLevel:
    for redirect_op, target in redirects:
        if not target or not (redirect_op in _WRITE_REDIRECT_OPS or (redirect_op == ">&" and not target.isdigit())):
            continue
        if _is_safe_device_path(target):
            continue
        return RiskLevel.write
    return RiskLevel.read


def _pipe_danger_reasons(segments: List[List[str]], separators: List[str]) -> List[str]:
    reasons: List[str] = []
    for index, separator in enumerate(separators):
        if separator not in {"|", "|&"} or index + 1 >= len(segments):
            continue
        left = _skip_prelude(segments[index])
        right = _skip_prelude(segments[index + 1])
        left_verb = _verb(left[0]) if left else ""
        right_verb = _verb(right[0]) if right else ""
        if left_verb in _DOWNLOAD_VERBS and _is_shell_verb(right_verb):
            reasons.append(f"{left_verb} output piped into {right_verb}")
    return reasons


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    unique = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def classify_shell_command(command: str) -> ShellRisk:
    """Classify a shell command without running it.

    The command is tokenised with :mod:`shlex` and every simple command in the pipeline/chain is
    analysed through its argv and flags (combined short flags included). ``dangerous`` is
    advisory and must not be treated as a block — callers decide the policy.
    """
    text = "" if command is None else str(command)
    stripped = text.strip()
    if not stripped:
        return ShellRisk(level=RiskLevel.read, dangerous=False, reasons=[])
    for pattern in _FORK_BOMB_PATTERNS:
        if pattern.search(stripped):
            return ShellRisk(
                level=RiskLevel.exec,
                dangerous=True,
                reasons=["fork bomb (recursively spawns processes until the machine hangs)"],
            )
    tokens = _tokenize(stripped)
    if tokens is None:
        return ShellRisk(
            level=RiskLevel.exec,
            dangerous=False,
            reasons=["could not parse the command safely; treated as exec"],
        )
    segments, separators, redirects = _parse_command(tokens)
    level = RiskLevel.read
    for argv in segments:
        level = _max_level(level, _classify_segment(argv))
    level = _max_level(level, _redirect_level(redirects))
    substitution_level, substitution_reasons = _substitution_analysis(stripped)
    level = _max_level(level, substitution_level)
    reasons: List[str] = []
    for argv in segments:
        reasons.extend(_segment_danger_reasons(argv))
    reasons.extend(_redirect_danger_reasons(redirects))
    reasons.extend(_pipe_danger_reasons(segments, separators))
    reasons.extend(substitution_reasons)
    reasons = _dedupe(reasons)
    if reasons:
        # A destructive command is never auto-allowable, regardless of the matched verb family.
        level = RiskLevel.exec
    return ShellRisk(level=level, dangerous=bool(reasons), reasons=reasons)


def is_dangerous_shell(command: str) -> Tuple[bool, List[str]]:
    """Return ``(dangerous, reasons)`` for a shell command; convenience wrapper."""
    risk = classify_shell_command(command)
    return risk.dangerous, list(risk.reasons)
