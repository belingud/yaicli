"""Constants used in yaicli."""

CMD_CLEAR = "/clear"
CMD_EXIT = "/exit"
CMD_HISTORY = "/his"
CMD_MODE = "/mode"

EXEC_MODE = "exec"
CHAT_MODE = "chat"
TEMP_MODE = "temp"

DEFAULT_CONFIG_PATH = "~/.config/yaicli/config.ini"
DEFAULT_CODE_THEME = "monokai"

SHELL_PROMPT = """Your are a Shell Command Generator.
Generate a command EXCLUSIVELY for {_os} OS with {_shell} shell.
If details are missing, offer the most logical solution.
Ensure the output is a valid shell command.
Combine multiple steps with `&&` when possible.
Supply plain text only, avoiding Markdown formatting."""

DEFAULT_PROMPT = (
    "You are YAICLI, a system management and programing assistant, "
    "You are managing {_os} operating system with {_shell} shell. "
    "Your responses should be concise and use Markdown format, "
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
    "BASE_URL": {"value": "https://api.openai.com/v1", "env_key": "YAI_BASE_URL", "type": str},
    "API_KEY": {"value": "", "env_key": "YAI_API_KEY", "type": str},
    "MODEL": {"value": "gpt-4o", "env_key": "YAI_MODEL", "type": str},
    # System detection hints
    "SHELL_NAME": {"value": "auto", "env_key": "YAI_SHELL_NAME", "type": str},
    "OS_NAME": {"value": "auto", "env_key": "YAI_OS_NAME", "type": str},
    # API response parsing
    "COMPLETION_PATH": {"value": "chat/completions", "env_key": "YAI_COMPLETION_PATH", "type": str},
    "ANSWER_PATH": {"value": "choices[0].message.content", "env_key": "YAI_ANSWER_PATH", "type": str},
    # API call parameters
    "STREAM": {"value": "true", "env_key": "YAI_STREAM", "type": bool},
    "TEMPERATURE": {"value": "0.7", "env_key": "YAI_TEMPERATURE", "type": float},
    "TOP_P": {"value": "1.0", "env_key": "YAI_TOP_P", "type": float},
    "MAX_TOKENS": {"value": "1024", "env_key": "YAI_MAX_TOKENS", "type": int},
    # UI/UX settings
    "CODE_THEME": {"value": DEFAULT_CODE_THEME, "env_key": "YAI_CODE_THEME", "type": str},
    "MAX_HISTORY": {"value": "500", "env_key": "YAI_MAX_HISTORY", "type": int},
    "AUTO_SUGGEST": {"value": "true", "env_key": "YAI_AUTO_SUGGEST", "type": bool},
}

DEFAULT_CONFIG_INI = f"""[core]
PROVIDER=openai
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

# UI/UX
CODE_THEME={DEFAULT_CONFIG_MAP["CODE_THEME"]["value"]}
MAX_HISTORY={DEFAULT_CONFIG_MAP["MAX_HISTORY"]["value"]} # Max entries kept in history file
AUTO_SUGGEST={DEFAULT_CONFIG_MAP["AUTO_SUGGEST"]["value"]}
"""
