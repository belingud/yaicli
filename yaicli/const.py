from enum import StrEnum

CMD_CLEAR = "/clear"
CMD_EXIT = "/exit"
CMD_HISTORY = "/his"
CMD_MODE = "/mode"

EXEC_MODE = "exec"
CHAT_MODE = "chat"
TEMP_MODE = "temp"

DEFAULT_CONFIG_PATH = "~/.config/yaicli/config.ini"
DEFAULT_CODE_THEME = "monokai"
DEFAULT_COMPLETION_PATH = "chat/completions"
DEFAULT_ANSWER_PATH = "choices[0].message.content"
DEFAULT_PROVIDER = "openai"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o"
DEFAULT_SHELL_NAME = "auto"
DEFAULT_OS_NAME = "auto"
DEFAULT_STREAM = "true"
DEFAULT_TEMPERATURE: float = 0.7
DEFAULT_TOP_P: float = 1.0
DEFAULT_MAX_TOKENS: int = 1024
DEFAULT_MAX_HISTORY: int = 500
DEFAULT_AUTO_SUGGEST = "true"
DEFAULT_TIMEOUT: int = 60
DEFAULT_INTERACTIVE_ROUND: int = 25


class EventTypeEnum(StrEnum):
    """Enumeration of possible event types from the SSE stream."""

    ERROR = "error"
    REASONING = "reasoning"
    REASONING_END = "reasoning_end"
    CONTENT = "content"
    FINISH = "finish"


SHELL_PROMPT = """Your are a Shell Command Generator.
Generate a command EXCLUSIVELY for {_os} OS with {_shell} shell.
If details are missing, offer the most logical solution.
Ensure the output is a valid shell command.
Combine multiple steps with `&&` when possible.
Supply plain text only, avoiding Markdown formatting."""

DEFAULT_PROMPT = (
    "You are YAICLI, a system management and programing assistant, "
    "You are managing {_os} operating system with {_shell} shell. "
    "Your responses should be concise and use Markdown format (but dont't use ```markdown), "
    "unless the user explicitly requests more details."
)

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
    # API response parsing
    "COMPLETION_PATH": {"value": DEFAULT_COMPLETION_PATH, "env_key": "YAI_COMPLETION_PATH", "type": str},
    "ANSWER_PATH": {"value": DEFAULT_ANSWER_PATH, "env_key": "YAI_ANSWER_PATH", "type": str},
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
}

DEFAULT_CONFIG_INI = f"""[core]
PROVIDER={DEFAULT_PROVIDER}
BASE_URL={DEFAULT_CONFIG_MAP["BASE_URL"]["value"]}
API_KEY={DEFAULT_CONFIG_MAP["API_KEY"]["value"]}
MODEL={DEFAULT_CONFIG_MAP["MODEL"]["value"]}

# auto detect shell and os (or specify manually, e.g., bash, zsh, powershell.exe)
SHELL_NAME={DEFAULT_CONFIG_MAP["SHELL_NAME"]["value"]}
OS_NAME={DEFAULT_CONFIG_MAP["OS_NAME"]["value"]}

# API paths (usually no need to change for OpenAI compatible APIs)
COMPLETION_PATH={DEFAULT_CONFIG_MAP["COMPLETION_PATH"]["value"]}
ANSWER_PATH={DEFAULT_CONFIG_MAP["ANSWER_PATH"]["value"]}

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
MAX_HISTORY={DEFAULT_CONFIG_MAP["MAX_HISTORY"]["value"]} # Max entries kept in history file
AUTO_SUGGEST={DEFAULT_CONFIG_MAP["AUTO_SUGGEST"]["value"]}
"""
