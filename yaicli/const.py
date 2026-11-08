try:
    from enum import StrEnum  # type: ignore
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatible with python below 3.11"""


import hashlib
import os
import sys
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Literal, Optional, Union

from rich.console import JustifyMethod

BOOL_STR = Literal["true", "false", "yes", "no", "y", "n", "1", "0", "on", "off"]


class JustifyEnum(StrEnum):  # type: ignore
    DEFAULT = "default"
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    FULL = "full"


CMD_CLEAR = "/clear"
CMD_EXIT = "/exit"
CMD_HISTORY = "/his"
CMD_MODE = "/mode"
CMD_SAVE_CHAT = "/save"
CMD_LOAD_CHAT = "/load"
CMD_LIST_CHATS = "/list"
CMD_DELETE_CHAT = "/del"
CMD_CONTEXT = ("/context", "/ctx")
CMD_ADD = "/add"
CMD_HELP = ("/help", "?")

EXEC_MODE = "exec"
CHAT_MODE = "chat"
TEMP_MODE = "temp"


def get_home_dir() -> Path:
    """Resolve the user's home directory without relying on ``expanduser('~')``.

    ``expanduser('~')`` returns the root directory when an empty ``HOME`` is set
    (``HOME=""`` resolves to ``/.config/...``), which made a container/CI run
    write outside its sandbox. Resolve HOME explicitly and fall back to a temp
    directory when neither HOME nor USERPROFILE is usable.
    """
    home = os.environ.get("HOME", "").strip() or os.environ.get("USERPROFILE", "").strip()
    if not home:
        return Path(gettempdir()) / "yaicli-home"
    try:
        return Path(home).expanduser()
    except (RuntimeError, OSError):
        return Path(gettempdir()) / "yaicli-home"


def get_config_dir() -> Path:
    """Resolve the config directory.

    Priority: ``YAI_CONFIG_DIR`` > ``XDG_CONFIG_HOME/yaicli`` >
    ``%APPDATA%/yaicli`` (Windows) > ``~/.config/yaicli``.
    """
    env_dir = os.environ.get("YAI_CONFIG_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_config:
        return Path(xdg_config).expanduser() / "yaicli"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return Path(appdata) / "yaicli"
    return get_home_dir() / ".config" / "yaicli"


def get_history_file() -> Path:
    """Resolve the REPL history file (XDG state dir when configured)."""
    xdg_state = os.environ.get("XDG_STATE_HOME", "").strip()
    if xdg_state:
        return Path(xdg_state).expanduser() / "yaicli" / "history"
    return get_home_dir() / ".yaicli_history"


def get_sessions_dir() -> Path:
    """Root of the per-project chat session store (v0.21 K13).

    Sessions are HOME-derived (``~/.yaicli/sessions``), not XDG-derived: they are
    user data that should follow the home directory, and keeping them out of
    ``$XDG_CONFIG_HOME`` avoids mixing state with the editable config. Resolved
    lazily from the environment so tests can point ``HOME`` at a temp dir.
    """
    return get_home_dir() / ".yaicli" / "sessions"


def project_sessions_key(cwd: Optional[Union[str, Path]] = None) -> str:
    """Stable 16-hex-char key for a project directory (the resolved cwd).

    ``sha256(str(Path(cwd).resolve()))[:16]``: stable across runs, symlink
    normalised, and deliberately not human readable so directory listings do not
    leak usernames or project names. Two different directories always map to
    different keys (16 hex chars = 64 bits is plenty for local projects).
    """
    project_dir = Path(cwd) if cwd is not None else Path.cwd()
    try:
        resolved = project_dir.resolve()
    except OSError:  # pragma: no cover - deleted cwd / permission edge
        resolved = project_dir.absolute()
    return hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]


def get_project_sessions_dir(cwd: Optional[Union[str, Path]] = None) -> Path:
    """Per-project session directory: ``get_sessions_dir()/<project key>``."""
    return get_sessions_dir() / project_sessions_key(cwd)


HISTORY_FILE = get_history_file()
CONFIG_DIR = get_config_dir()
CONFIG_PATH = CONFIG_DIR / "config.ini"
ROLES_DIR = CONFIG_DIR / "roles"
FUNCTIONS_DIR = CONFIG_DIR / "functions"
FUNCTIONS_MANIFEST_PATH = CONFIG_DIR / "functions_manifest.json"
MCP_JSON_PATH = CONFIG_DIR / "mcp.json"
TOOL_PERMISSIONS_PATH = CONFIG_DIR / "tool_permissions.json"
TOOL_AUDIT_PATH = CONFIG_DIR / "tool_audit.jsonl"

# Default configuration values
DEFAULT_CODE_THEME = "monokai"
DEFAULT_PROVIDER = "openai"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5.2"
DEFAULT_SHELL_NAME = "auto"
DEFAULT_ROLE = "DEFAULT"
DEFAULT_OS_NAME = "auto"
DEFAULT_STREAM: BOOL_STR = "true"
DEFAULT_TEMPERATURE: float = 0.3
DEFAULT_FREQUENCY_PENALTY: float = 0.0
DEFAULT_TOP_P: float = 1.0
DEFAULT_MAX_TOKENS: int = 1024
DEFAULT_MAX_HISTORY: int = 500
DEFAULT_AUTO_SUGGEST: BOOL_STR = "true"
DEFAULT_SHOW_REASONING: BOOL_STR = "true"
DEFAULT_TIMEOUT: int = 60
DEFAULT_EXTRA_HEADERS: str = "{}"
DEFAULT_EXTRA_BODY: str = "{}"
DEFAULT_INTERACTIVE_ROUND: int = 25
# Legacy flat chat dir and the DEFAULT_CONFIG_MAP value for CHAT_HISTORY_DIR.
# v0.21 K13: unless CHAT_HISTORY_DIR is explicitly overridden (a value different
# from this built-in default), FileChatManager stores sessions per project under
# get_project_sessions_dir(). The constant still anchors TOOL_OUTPUT_DIR.
DEFAULT_CHAT_HISTORY_DIR: Path = Path(gettempdir()) / "yaicli/chats"
DEFAULT_MAX_SAVED_CHATS = 20
DEFAULT_JUSTIFY: JustifyMethod = "default"
DEFAULT_ROLE_MODIFY_WARNING: BOOL_STR = "true"
DEFAULT_ENABLE_FUNCTIONS: BOOL_STR = "true"
DEFAULT_SHOW_FUNCTION_OUTPUT: BOOL_STR = "true"
# low/high/medium for openai, default/null for groq
DEFAULT_REASONING_EFFORT: Optional[Literal["low", "high", "medium", "default", "null"]] = None
# Anthropic only: send disable_parallel_tool_use (one tool call per response when true)
DEFAULT_DISABLE_PARALLEL_TOOL_USE: BOOL_STR = "true"
DEFAULT_ENABLE_MCP: BOOL_STR = "false"
DEFAULT_SHOW_MCP_OUTPUT: BOOL_STR = "false"
# MCP hardening (v0.22 K16): each MCP list/call operation is bounded by this
# timeout (seconds; 0 = no timeout) and at most MCP_MAX_TOOLS tools are injected
# per request (0 = unlimited).
DEFAULT_MCP_TIMEOUT: int = 30
DEFAULT_MCP_MAX_TOOLS: int = 64
# MiniMax only: request reasoning separately (interleaved thinking)
DEFAULT_MINIMAX_REASONING_SPLIT: BOOL_STR = "true"
DEFAULT_MAX_TOOL_CALL_DEPTH: int = 8
DEFAULT_TOOL_CONFIRM: BOOL_STR = "true"
# Session-wide tool permission mode (v0.21 K10):
#   readonly -> auto-allow read/network tools, hard-deny write/exec tools
#   standard -> v0.19 behaviour (rules -> --allowed-tools -> --yes -> prompt/deny)
#   trusted  -> auto-allow every non-dangerous tool (danger-classified shell still asks)
DEFAULT_TOOL_POLICY = "standard"
TOOL_POLICY_MODES = ("readonly", "standard", "trusted")
DEFAULT_EXCLUDE_PARAMS: str = ""  # Empty by default

# Agent context / tool-output economy (v0.19 K02)
DEFAULT_TOOL_OUTPUT_MAX_CHARS: int = 32000
DEFAULT_TOOL_OUTPUT_DIR: Path = DEFAULT_CHAT_HISTORY_DIR / "tool-outputs"
# Terminal rendering of tool results (v0.19.1): independent from the model-facing
# cap above, so a long result can be fully available to the model while the
# terminal only shows a compact head preview. 0 = show everything.
DEFAULT_TOOL_DISPLAY_MAX_LINES: int = 15
DEFAULT_TOOL_DISPLAY_MAX_CHARS: int = 4000
# Max characters of the tool arguments echoed on the ``@Function call:`` line.
DEFAULT_TOOL_CALL_PREVIEW_MAX_CHARS: int = 300
# 0 means "derive from the model context window (70%)" at request time.
DEFAULT_CONTEXT_BUDGET_TOKENS: int = 0
# Project instructions auto-loaded into the system prompt (v0.21 K12)
DEFAULT_ENABLE_PROJECT_CONTEXT: BOOL_STR = "true"
DEFAULT_PROJECT_CONTEXT_MAX_CHARS: int = 20000
# Shell tool guardrails (v0.19 K03)
DEFAULT_TOOL_TIMEOUT: int = 120
DEFAULT_TOOL_TIMEOUT_MAX: int = 600
DEFAULT_TOOL_ENV_INHERIT: BOOL_STR = "false"
DEFAULT_WORKSPACE_ROOT: str = ""
# Error retry policy (v0.19 K05)
DEFAULT_RETRY_ENABLED: BOOL_STR = "true"
DEFAULT_RETRY_MAX: int = 2
DEFAULT_RETRY_BASE_DELAY: float = 1.0
DEFAULT_RETRY_MAX_DELAY: float = 8.0
DEFAULT_EXIT_ON_DEPTH_LIMIT: BOOL_STR = "true"
# Tool audit log (v0.19 K06)
DEFAULT_TOOL_AUDIT: BOOL_STR = "true"
# Observability: usage/cost reporting (v0.22 K17)
DEFAULT_SHOW_USAGE: BOOL_STR = "true"
# JSON overrides for the built-in price table: {"model-prefix": {"input": 0.15, "output": 0.6}}
# (USD per 1M tokens). Empty = only the built-in table is used.
DEFAULT_MODEL_PRICING: str = "{}"
# Tool schema narrowing (v0.22 K19): comma-separated glob patterns matched against
# builtin and MCP tool names; empty = every tool is offered to the model.
DEFAULT_ENABLED_TOOLS: str = ""
# Secret redaction before tool output / sessions are written to disk (v0.22 K20).
DEFAULT_REDACT_SECRETS: BOOL_STR = "true"
# Headless output (v0.19 K04)
DEFAULT_OUTPUT_FORMAT: str = "text"

# Providers known to not support vision/image input
NO_VISION_PROVIDERS = {"cohere", "cohere-bedrock", "cohere-sagemaker", "huggingface", "chatglm", "modelscope"}


SHELL_PROMPT = """You are YAICLI, a shell command generator.
The context conversation may contain other types of messages,
but you should only respond with a single valid {_shell} shell command for {_os}.
Do not include any explanations, comments, or formatting — only the command as plain text, avoiding Markdown formatting.
"""

DEFAULT_PROMPT = """
You are YAICLI, a system management and programing assistant,
You are managing {_os} operating system with {_shell} shell.
Your responses should be concise and use Markdown format (but dont't use ```markdown),
unless the user explicitly requests more details.
"""

CODER_PROMPT = (
    "You are YAICLI, a code assistant. "
    "You are helping with programming tasks. "
    "Your responses must ONLY contain code, with NO explanation, NO markdown formatting, and NO preamble. "
    "If user does not specify the language, provide Python code. "
    "Do not wrap code in markdown code blocks (```) or language indicators."
)


class DefaultRoleNames(StrEnum):  # type: ignore
    SHELL = "Shell Command Generator"
    DEFAULT = "DEFAULT"
    CODER = "Code Assistant"


DEFAULT_ROLES: dict[str, dict[str, Any]] = {
    DefaultRoleNames.SHELL.value: {"name": DefaultRoleNames.SHELL.value, "prompt": SHELL_PROMPT},  # type: ignore
    DefaultRoleNames.DEFAULT.value: {"name": DefaultRoleNames.DEFAULT.value, "prompt": DEFAULT_PROMPT},  # type: ignore
    DefaultRoleNames.CODER.value: {"name": DefaultRoleNames.CODER.value, "prompt": CODER_PROMPT},  # type: ignore
}

# DEFAULT_CONFIG_MAP is a dictionary of the configuration options.
# The key is the name of the configuration option.
# The value is a dictionary with the following keys:
# - value: the default value of the configuration option
# - env_key: the environment variable key of the configuration option
# - type: the type of the configuration option, dict -> json, bool -> boolstr
DEFAULT_CONFIG_MAP = {
    # Core API settings
    "PROVIDER": {"value": DEFAULT_PROVIDER, "env_key": "YAI_PROVIDER", "type": str},
    "BASE_URL": {"value": "", "env_key": "YAI_BASE_URL", "type": str},
    "API_KEY": {"value": "", "env_key": "YAI_API_KEY", "type": str},
    "MODEL": {"value": DEFAULT_MODEL, "env_key": "YAI_MODEL", "type": str},
    # System detection hints
    "SHELL_NAME": {"value": DEFAULT_SHELL_NAME, "env_key": "YAI_SHELL_NAME", "type": str},
    "OS_NAME": {"value": DEFAULT_OS_NAME, "env_key": "YAI_OS_NAME", "type": str},
    "DEFAULT_ROLE": {"value": DEFAULT_ROLE, "env_key": "YAI_DEFAULT_ROLE", "type": str},
    # API call parameters
    "STREAM": {"value": DEFAULT_STREAM, "env_key": "YAI_STREAM", "type": bool},
    "TEMPERATURE": {"value": DEFAULT_TEMPERATURE, "env_key": "YAI_TEMPERATURE", "type": float},
    "FREQUENCY_PENALTY": {"value": DEFAULT_FREQUENCY_PENALTY, "env_key": "YAI_FREQUENCY_PENALTY", "type": float},
    "TOP_P": {"value": DEFAULT_TOP_P, "env_key": "YAI_TOP_P", "type": float},
    "MAX_TOKENS": {"value": DEFAULT_MAX_TOKENS, "env_key": "YAI_MAX_TOKENS", "type": int},
    "TIMEOUT": {"value": DEFAULT_TIMEOUT, "env_key": "YAI_TIMEOUT", "type": int},
    "EXTRA_HEADERS": {"value": DEFAULT_EXTRA_HEADERS, "env_key": "YAI_EXTRA_HEADERS", "type": dict},
    "EXTRA_BODY": {"value": DEFAULT_EXTRA_BODY, "env_key": "YAI_EXTRA_BODY", "type": dict},
    "REASONING_EFFORT": {"value": DEFAULT_REASONING_EFFORT, "env_key": "YAI_REASONING_EFFORT", "type": str},
    "DISABLE_PARALLEL_TOOL_USE": {
        "value": DEFAULT_DISABLE_PARALLEL_TOOL_USE,
        "env_key": "YAI_DISABLE_PARALLEL_TOOL_USE",
        "type": bool,
    },
    "INTERACTIVE_ROUND": {
        "value": DEFAULT_INTERACTIVE_ROUND,
        "env_key": "YAI_INTERACTIVE_ROUND",
        "type": int,
    },
    # UI/UX settings
    "CODE_THEME": {"value": DEFAULT_CODE_THEME, "env_key": "YAI_CODE_THEME", "type": str},
    "MAX_HISTORY": {"value": DEFAULT_MAX_HISTORY, "env_key": "YAI_MAX_HISTORY", "type": int},
    "AUTO_SUGGEST": {"value": DEFAULT_AUTO_SUGGEST, "env_key": "YAI_AUTO_SUGGEST", "type": bool},
    "SHOW_REASONING": {"value": DEFAULT_SHOW_REASONING, "env_key": "YAI_SHOW_REASONING", "type": bool},
    "JUSTIFY": {"value": DEFAULT_JUSTIFY, "env_key": "YAI_JUSTIFY", "type": str},
    # Chat history settings
    "CHAT_HISTORY_DIR": {"value": DEFAULT_CHAT_HISTORY_DIR, "env_key": "YAI_CHAT_HISTORY_DIR", "type": str},
    "MAX_SAVED_CHATS": {"value": DEFAULT_MAX_SAVED_CHATS, "env_key": "YAI_MAX_SAVED_CHATS", "type": int},
    # Role settings
    "ROLE_MODIFY_WARNING": {"value": DEFAULT_ROLE_MODIFY_WARNING, "env_key": "YAI_ROLE_MODIFY_WARNING", "type": bool},
    # Function settings
    "ENABLE_FUNCTIONS": {"value": DEFAULT_ENABLE_FUNCTIONS, "env_key": "YAI_ENABLE_FUNCTIONS", "type": bool},
    "SHOW_FUNCTION_OUTPUT": {
        "value": DEFAULT_SHOW_FUNCTION_OUTPUT,
        "env_key": "YAI_SHOW_FUNCTION_OUTPUT",
        "type": bool,
    },
    # Tool schema narrowing (v0.22 K19): comma-separated tool-name globs.
    "ENABLED_TOOLS": {"value": DEFAULT_ENABLED_TOOLS, "env_key": "YAI_ENABLED_TOOLS", "type": str},
    "ENABLE_MCP": {"value": DEFAULT_ENABLE_MCP, "env_key": "YAI_ENABLE_MCP", "type": bool},
    "SHOW_MCP_OUTPUT": {"value": DEFAULT_SHOW_MCP_OUTPUT, "env_key": "YAI_SHOW_MCP_OUTPUT", "type": bool},
    "MCP_TIMEOUT": {"value": DEFAULT_MCP_TIMEOUT, "env_key": "YAI_MCP_TIMEOUT", "type": int},
    "MCP_MAX_TOOLS": {"value": DEFAULT_MCP_MAX_TOOLS, "env_key": "YAI_MCP_MAX_TOOLS", "type": int},
    "MAX_TOOL_CALL_DEPTH": {"value": DEFAULT_MAX_TOOL_CALL_DEPTH, "env_key": "YAI_MAX_TOOL_CALL_DEPTH", "type": int},
    "TOOL_CONFIRM": {"value": DEFAULT_TOOL_CONFIRM, "env_key": "YAI_TOOL_CONFIRM", "type": bool},
    "TOOL_POLICY": {"value": DEFAULT_TOOL_POLICY, "env_key": "YAI_TOOL_POLICY", "type": str},
    "EXCLUDE_PARAMS": {"value": DEFAULT_EXCLUDE_PARAMS, "env_key": "YAI_EXCLUDE_PARAMS", "type": str},
    # Agent context / tool-output economy
    "TOOL_OUTPUT_MAX_CHARS": {
        "value": DEFAULT_TOOL_OUTPUT_MAX_CHARS,
        "env_key": "YAI_TOOL_OUTPUT_MAX_CHARS",
        "type": int,
    },
    "TOOL_OUTPUT_DIR": {"value": str(DEFAULT_TOOL_OUTPUT_DIR), "env_key": "YAI_TOOL_OUTPUT_DIR", "type": str},
    # Terminal display only (the model still receives TOOL_OUTPUT_MAX_CHARS)
    "TOOL_DISPLAY_MAX_LINES": {
        "value": DEFAULT_TOOL_DISPLAY_MAX_LINES,
        "env_key": "YAI_TOOL_DISPLAY_MAX_LINES",
        "type": int,
    },
    "TOOL_DISPLAY_MAX_CHARS": {
        "value": DEFAULT_TOOL_DISPLAY_MAX_CHARS,
        "env_key": "YAI_TOOL_DISPLAY_MAX_CHARS",
        "type": int,
    },
    "TOOL_CALL_PREVIEW_MAX_CHARS": {
        "value": DEFAULT_TOOL_CALL_PREVIEW_MAX_CHARS,
        "env_key": "YAI_TOOL_CALL_PREVIEW_MAX_CHARS",
        "type": int,
    },
    "CONTEXT_BUDGET_TOKENS": {
        "value": DEFAULT_CONTEXT_BUDGET_TOKENS,
        "env_key": "YAI_CONTEXT_BUDGET_TOKENS",
        "type": int,
    },
    # Project instructions auto-loaded into the system prompt (v0.21 K12)
    "ENABLE_PROJECT_CONTEXT": {
        "value": DEFAULT_ENABLE_PROJECT_CONTEXT,
        "env_key": "YAI_ENABLE_PROJECT_CONTEXT",
        "type": bool,
    },
    "PROJECT_CONTEXT_MAX_CHARS": {
        "value": DEFAULT_PROJECT_CONTEXT_MAX_CHARS,
        "env_key": "YAI_PROJECT_CONTEXT_MAX_CHARS",
        "type": int,
    },
    # Shell tool guardrails
    "TOOL_TIMEOUT": {"value": DEFAULT_TOOL_TIMEOUT, "env_key": "YAI_TOOL_TIMEOUT", "type": int},
    "TOOL_ENV_INHERIT": {"value": DEFAULT_TOOL_ENV_INHERIT, "env_key": "YAI_TOOL_ENV_INHERIT", "type": bool},
    "WORKSPACE_ROOT": {"value": DEFAULT_WORKSPACE_ROOT, "env_key": "YAI_WORKSPACE_ROOT", "type": str},
    # Error retry policy
    "RETRY_ENABLED": {"value": DEFAULT_RETRY_ENABLED, "env_key": "YAI_RETRY_ENABLED", "type": bool},
    "RETRY_MAX": {"value": DEFAULT_RETRY_MAX, "env_key": "YAI_RETRY_MAX", "type": int},
    "RETRY_BASE_DELAY": {"value": DEFAULT_RETRY_BASE_DELAY, "env_key": "YAI_RETRY_BASE_DELAY", "type": float},
    "RETRY_MAX_DELAY": {"value": DEFAULT_RETRY_MAX_DELAY, "env_key": "YAI_RETRY_MAX_DELAY", "type": float},
    "EXIT_ON_DEPTH_LIMIT": {"value": DEFAULT_EXIT_ON_DEPTH_LIMIT, "env_key": "YAI_EXIT_ON_DEPTH_LIMIT", "type": bool},
    # Tool audit log
    "TOOL_AUDIT": {"value": DEFAULT_TOOL_AUDIT, "env_key": "YAI_TOOL_AUDIT", "type": bool},
    # Usage / cost reporting (v0.22 K17)
    "SHOW_USAGE": {"value": DEFAULT_SHOW_USAGE, "env_key": "YAI_SHOW_USAGE", "type": bool},
    "MODEL_PRICING": {"value": DEFAULT_MODEL_PRICING, "env_key": "YAI_MODEL_PRICING", "type": dict},
    # Secret redaction before tool output/sessions are written to disk (v0.22 K20)
    "REDACT_SECRETS": {"value": DEFAULT_REDACT_SECRETS, "env_key": "YAI_REDACT_SECRETS", "type": bool},
    # MiniMax specific settings
    "MINIMAX_REASONING_SPLIT": {
        "value": DEFAULT_MINIMAX_REASONING_SPLIT,
        "env_key": "YAI_MINIMAX_REASONING_SPLIT",
        "type": bool,
    },
}

DEFAULT_CONFIG_INI = f"""[core]
PROVIDER={DEFAULT_PROVIDER}
BASE_URL={DEFAULT_CONFIG_MAP["BASE_URL"]["value"]}
API_KEY={DEFAULT_CONFIG_MAP["API_KEY"]["value"]}
MODEL={DEFAULT_CONFIG_MAP["MODEL"]["value"]}

# auto detect shell and os (or specify manually, e.g., bash, zsh, powershell.exe)
SHELL_NAME={DEFAULT_CONFIG_MAP["SHELL_NAME"]["value"]}
OS_NAME={DEFAULT_CONFIG_MAP["OS_NAME"]["value"]}

DEFAULT_ROLE={DEFAULT_CONFIG_MAP["DEFAULT_ROLE"]["value"]}
# true: streaming response, false: non-streaming
STREAM={DEFAULT_CONFIG_MAP["STREAM"]["value"]}

# LLM parameters
TEMPERATURE={DEFAULT_CONFIG_MAP["TEMPERATURE"]["value"]}
FREQUENCY_PENALTY={DEFAULT_CONFIG_MAP["FREQUENCY_PENALTY"]["value"]}
TOP_P={DEFAULT_CONFIG_MAP["TOP_P"]["value"]}
MAX_TOKENS={DEFAULT_CONFIG_MAP["MAX_TOKENS"]["value"]}
TIMEOUT={DEFAULT_CONFIG_MAP["TIMEOUT"]["value"]}
# json string
EXTRA_HEADERS=
# json string
EXTRA_BODY=
REASONING_EFFORT=

# Interactive mode parameters
INTERACTIVE_ROUND={DEFAULT_CONFIG_MAP["INTERACTIVE_ROUND"]["value"]}

# UI/UX
CODE_THEME={DEFAULT_CONFIG_MAP["CODE_THEME"]["value"]}
# Max entries kept in history file
MAX_HISTORY={DEFAULT_CONFIG_MAP["MAX_HISTORY"]["value"]}
AUTO_SUGGEST={DEFAULT_CONFIG_MAP["AUTO_SUGGEST"]["value"]}
# Print reasoning content or not
SHOW_REASONING={DEFAULT_CONFIG_MAP["SHOW_REASONING"]["value"]}
# Text alignment (default, left, center, right, full)
JUSTIFY={DEFAULT_CONFIG_MAP["JUSTIFY"]["value"]}

# Chat history settings
CHAT_HISTORY_DIR={DEFAULT_CONFIG_MAP["CHAT_HISTORY_DIR"]["value"]}
MAX_SAVED_CHATS={DEFAULT_CONFIG_MAP["MAX_SAVED_CHATS"]["value"]}

# Role settings
# Set to false to disable warnings about modified built-in roles
ROLE_MODIFY_WARNING={DEFAULT_CONFIG_MAP["ROLE_MODIFY_WARNING"]["value"]}

# Function settings
# Set to false to disable sending functions in API requests
ENABLE_FUNCTIONS={DEFAULT_CONFIG_MAP["ENABLE_FUNCTIONS"]["value"]}
# Set to false to disable showing function output when calling functions
SHOW_FUNCTION_OUTPUT={DEFAULT_CONFIG_MAP["SHOW_FUNCTION_OUTPUT"]["value"]}
# Comma-separated tool-name globs to offer the model (empty = all tools).
# Builtin and MCP tools are both matched; MCP names carry the _mcp__ prefix.
# Example: fs_read_file,fs_list_directory,execute_*
ENABLED_TOOLS=

# MCP settings
# Set to false to disable MCP in API requests
ENABLE_MCP={DEFAULT_CONFIG_MAP["ENABLE_MCP"]["value"]}
# Set to false to disable showing MCP output when calling MCP tools
SHOW_MCP_OUTPUT={DEFAULT_CONFIG_MAP["SHOW_MCP_OUTPUT"]["value"]}
# Seconds one MCP list/call operation may take (0 = no timeout)
MCP_TIMEOUT={DEFAULT_CONFIG_MAP["MCP_TIMEOUT"]["value"]}
# Max MCP tools offered to the model per request (0 = unlimited)
MCP_MAX_TOOLS={DEFAULT_CONFIG_MAP["MCP_MAX_TOOLS"]["value"]}

# Observability & cost (v0.22 K17)
# Print one token/cost line after each interactive turn
SHOW_USAGE={DEFAULT_CONFIG_MAP["SHOW_USAGE"]["value"]}
# json string overriding the built-in price table, e.g.
# {{"gpt-4o": {{"input": 2.5, "output": 10}}}}  (USD per 1M tokens)
MODEL_PRICING=

# Provider-specific settings
# MiniMax: request reasoning content separately (interleaved thinking); ignored by others
MINIMAX_REASONING_SPLIT={DEFAULT_CONFIG_MAP["MINIMAX_REASONING_SPLIT"]["value"]}
# Anthropic: true = one tool call per response (compatibility default); false = allow parallel calls
DISABLE_PARALLEL_TOOL_USE={DEFAULT_CONFIG_MAP["DISABLE_PARALLEL_TOOL_USE"]["value"]}

# Maximum number of tool calls to make in a single request
MAX_TOOL_CALL_DEPTH={DEFAULT_CONFIG_MAP["MAX_TOOL_CALL_DEPTH"]["value"]}

# Ask for confirmation before executing each tool/function call.
# Set to false to execute tool calls silently (previous behavior).
# Tools permanently allowed are stored in tool_permissions.json next to this file.
TOOL_CONFIRM={DEFAULT_CONFIG_MAP["TOOL_CONFIRM"]["value"]}

# Session-wide tool permission policy: readonly | standard | trusted
# readonly: auto-allow read/network tools only; write/exec tools are always denied
# standard: ask for confirmation / use tool_permissions.json rules (default)
# trusted: auto-allow every non-dangerous tool (dangerous shell commands still ask)
TOOL_POLICY={DEFAULT_CONFIG_MAP["TOOL_POLICY"]["value"]}

# Comma-separated list of API parameters to exclude from requests
# Example: temperature,top_p,frequency_penalty
EXCLUDE_PARAMS=

# Agent context settings
# Maximum characters of a single tool result kept in the model context
# (head and tail are kept, the full output is saved to TOOL_OUTPUT_DIR).
# Set to 0 to disable truncation.
TOOL_OUTPUT_MAX_CHARS={DEFAULT_CONFIG_MAP["TOOL_OUTPUT_MAX_CHARS"]["value"]}
# Directory where full (untruncated) tool outputs are saved
TOOL_OUTPUT_DIR={DEFAULT_CONFIG_MAP["TOOL_OUTPUT_DIR"]["value"]}
# Redact known secret shapes (API keys, tokens, private keys, ...) before tool
# output and saved sessions are written to disk. The model still sees the real
# content; only the on-disk copies are sanitized. Set to false to keep raw bytes.
REDACT_SECRETS={DEFAULT_CONFIG_MAP["REDACT_SECRETS"]["value"]}
# Terminal display of a tool result: only the first N lines / characters are
# shown; the model still receives TOOL_OUTPUT_MAX_CHARS characters.
# Set either to 0 to show everything (not recommended for large outputs).
TOOL_DISPLAY_MAX_LINES={DEFAULT_CONFIG_MAP["TOOL_DISPLAY_MAX_LINES"]["value"]}
TOOL_DISPLAY_MAX_CHARS={DEFAULT_CONFIG_MAP["TOOL_DISPLAY_MAX_CHARS"]["value"]}
# Max characters of the tool arguments echoed on the "@Function call:" line
# (0 = print the raw arguments). Long values are summarized as <N chars>.
TOOL_CALL_PREVIEW_MAX_CHARS={DEFAULT_CONFIG_MAP["TOOL_CALL_PREVIEW_MAX_CHARS"]["value"]}
# Token budget for one request; 0 = derive 70% of the model context window
CONTEXT_BUDGET_TOKENS={DEFAULT_CONFIG_MAP["CONTEXT_BUDGET_TOKENS"]["value"]}

# Project context settings (v0.21 K12)
# Auto-load AGENTS.md / CLAUDE.md / .yaicli.md from the current directory up to the
# git root and add them to the system prompt. Set to false to disable (no file reads).
ENABLE_PROJECT_CONTEXT={DEFAULT_CONFIG_MAP["ENABLE_PROJECT_CONTEXT"]["value"]}
# Max characters of project instructions added to the system prompt
# (0 = no cap; the excess is cut and a warning names the files involved).
PROJECT_CONTEXT_MAX_CHARS={DEFAULT_CONFIG_MAP["PROJECT_CONTEXT_MAX_CHARS"]["value"]}

# Shell tool settings
# Maximum seconds a shell command may run
TOOL_TIMEOUT={DEFAULT_CONFIG_MAP["TOOL_TIMEOUT"]["value"]}
# true: pass the full parent environment to shell commands (previous behavior)
TOOL_ENV_INHERIT={DEFAULT_CONFIG_MAP["TOOL_ENV_INHERIT"]["value"]}
# Commands may only run inside this directory (empty = current directory)
WORKSPACE_ROOT=

# Reliability settings
# Retry rate-limit / network / timeout / 5xx failures
RETRY_ENABLED={DEFAULT_CONFIG_MAP["RETRY_ENABLED"]["value"]}
RETRY_MAX={DEFAULT_CONFIG_MAP["RETRY_MAX"]["value"]}
RETRY_BASE_DELAY={DEFAULT_CONFIG_MAP["RETRY_BASE_DELAY"]["value"]}
# Maximum delay between retries in seconds (caps the exponential backoff)
RETRY_MAX_DELAY={DEFAULT_CONFIG_MAP["RETRY_MAX_DELAY"]["value"]}
# Exit non-zero in one-shot mode when the tool-call depth limit is reached
EXIT_ON_DEPTH_LIMIT={DEFAULT_CONFIG_MAP["EXIT_ON_DEPTH_LIMIT"]["value"]}

# Write one JSON line per tool-call decision to TOOL_AUDIT_PATH
TOOL_AUDIT={DEFAULT_CONFIG_MAP["TOOL_AUDIT"]["value"]}
"""
