from enum import StrEnum
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Literal

from rich.console import JustifyMethod

BOOL_STR = Literal["true", "false", "yes", "no", "y", "n", "1", "0", "on", "off"]


class JustifyEnum(StrEnum):
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
CMD_HELP = ("/help", "?")

EXEC_MODE = "exec"
CHAT_MODE = "chat"
TEMP_MODE = "temp"
CODE_MODE = "code"

HISTORY_FILE = Path("~/.yaicli_history").expanduser()
CONFIG_PATH = Path("~/.config/yaicli/config.ini").expanduser()
ROLES_DIR = CONFIG_PATH.parent / "roles"
FUNCTIONS_DIR = CONFIG_PATH.parent / "functions"

# Default configuration values
DEFAULT_CODE_THEME = "monokai"
DEFAULT_PROVIDER = "openai"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o"
DEFAULT_SHELL_NAME = "auto"
DEFAULT_OS_NAME = "auto"
DEFAULT_STREAM: BOOL_STR = "true"
DEFAULT_TEMPERATURE: float = 0.5
DEFAULT_TOP_P: float = 1.0
DEFAULT_MAX_TOKENS: int = 1024
DEFAULT_MAX_HISTORY: int = 500
DEFAULT_AUTO_SUGGEST: BOOL_STR = "true"
DEFAULT_SHOW_REASONING: BOOL_STR = "true"
DEFAULT_TIMEOUT: int = 60
DEFAULT_INTERACTIVE_ROUND: int = 25
DEFAULT_CHAT_HISTORY_DIR: Path = Path(gettempdir()) / "yaicli/chats"
DEFAULT_MAX_SAVED_CHATS = 20
DEFAULT_JUSTIFY: JustifyMethod = "default"
DEFAULT_ROLE_MODIFY_WARNING: BOOL_STR = "true"
DEFAULT_ENABLE_FUNCTIONS: BOOL_STR = "true"
DEFAULT_SHOW_FUNCTION_OUTPUT: BOOL_STR = "true"


class EventTypeEnum(StrEnum):
    """Enumeration of possible event types from the SSE stream."""

    ERROR = "error"
    REASONING = "reasoning"
    REASONING_END = "reasoning_end"
    CONTENT = "content"
    FINISH = "finish"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_END = "tool_call_end"
    TOOL_RESULT = "tool_result"
    TOOL_CALLS_FINISH = "tool_calls_finish"


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


class DefaultRoleNames(StrEnum):
    SHELL = "Shell Command Generator"
    DEFAULT = "DEFAULT"
    CODER = "Code Assistant"


DEFAULT_ROLES: dict[str, dict[str, Any]] = {
    DefaultRoleNames.SHELL: {"name": DefaultRoleNames.SHELL, "prompt": SHELL_PROMPT},
    DefaultRoleNames.DEFAULT: {"name": DefaultRoleNames.DEFAULT, "prompt": DEFAULT_PROMPT},
    DefaultRoleNames.CODER: {"name": DefaultRoleNames.CODER, "prompt": CODER_PROMPT},
}

# DEFAULT_CONFIG_MAP is a dictionary of the configuration options.
# The key is the name of the configuration option.
# The value is a dictionary with the following keys:
# - value: the default value of the configuration option
# - env_key: the environment variable key of the configuration option
# - type: the type of the configuration option
DEFAULT_CONFIG_MAP = {
    # Core API settings
    "BASE_URL": {"value": DEFAULT_BASE_URL, "env_key": "YAI_BASE_URL", "type": str},
    "API_KEY": {"value": "", "env_key": "YAI_API_KEY", "type": str},
    "MODEL": {"value": DEFAULT_MODEL, "env_key": "YAI_MODEL", "type": str},
    # System detection hints
    "SHELL_NAME": {"value": DEFAULT_SHELL_NAME, "env_key": "YAI_SHELL_NAME", "type": str},
    "OS_NAME": {"value": DEFAULT_OS_NAME, "env_key": "YAI_OS_NAME", "type": str},
    # API call parameters
    "STREAM": {"value": DEFAULT_STREAM, "env_key": "YAI_STREAM", "type": bool},
    "TEMPERATURE": {"value": DEFAULT_TEMPERATURE, "env_key": "YAI_TEMPERATURE", "type": float},
    "TOP_P": {"value": DEFAULT_TOP_P, "env_key": "YAI_TOP_P", "type": float},
    "MAX_TOKENS": {"value": DEFAULT_MAX_TOKENS, "env_key": "YAI_MAX_TOKENS", "type": int},
    "TIMEOUT": {"value": DEFAULT_TIMEOUT, "env_key": "YAI_TIMEOUT", "type": int},
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
}

DEFAULT_CONFIG_INI = f"""[core]
PROVIDER={DEFAULT_PROVIDER}
BASE_URL={DEFAULT_CONFIG_MAP["BASE_URL"]["value"]}
API_KEY={DEFAULT_CONFIG_MAP["API_KEY"]["value"]}
MODEL={DEFAULT_CONFIG_MAP["MODEL"]["value"]}

# auto detect shell and os (or specify manually, e.g., bash, zsh, powershell.exe)
SHELL_NAME={DEFAULT_CONFIG_MAP["SHELL_NAME"]["value"]}
OS_NAME={DEFAULT_CONFIG_MAP["OS_NAME"]["value"]}

# true: streaming response, false: non-streaming
STREAM={DEFAULT_CONFIG_MAP["STREAM"]["value"]}

# LLM parameters
TEMPERATURE={DEFAULT_CONFIG_MAP["TEMPERATURE"]["value"]}
TOP_P={DEFAULT_CONFIG_MAP["TOP_P"]["value"]}
MAX_TOKENS={DEFAULT_CONFIG_MAP["MAX_TOKENS"]["value"]}
TIMEOUT={DEFAULT_CONFIG_MAP["TIMEOUT"]["value"]}

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
# Set to false to disable showing function output in the response
SHOW_FUNCTION_OUTPUT={DEFAULT_CONFIG_MAP["SHOW_FUNCTION_OUTPUT"]["value"]}
"""
