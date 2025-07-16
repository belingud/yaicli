# Configuration Guide

YAICLI uses a layered configuration system to store your preferences and API keys. This guide explains all available configuration options and how to customize them.

## Configuration Hierarchy

YAICLI follows this priority order for configuration:

1. Command-line arguments (highest priority)
2. Environment variables
3. Configuration file
4. Default values (lowest priority)

## Configuration File

### Location

The default configuration file is located at:

- Linux/macOS: `~/.config/yaicli/config.ini`
- Windows: `C:\Users\<username>\.config\yaicli\config.ini`

### First-time Setup

1. Run `ai` once to generate the default configuration file
2. Edit the file to add your API key and customize settings

### Viewing Default Configuration

To view the default configuration template:

```bash
ai --template
```

## Configuration File Structure

The configuration file uses the INI format with the following sections:

```ini
[core]
PROVIDER=openai
BASE_URL=
API_KEY=
MODEL=gpt-4o

DEFAULT_ROLE=DEFAULT
# auto detect shell and os (or specify manually, e.g., bash, zsh, powershell.exe)
SHELL_NAME=auto
OS_NAME=auto

# true: streaming response, false: non-streaming
STREAM=true

# LLM parameters
TEMPERATURE=0.3
TOP_P=1.0
MAX_TOKENS=1024
TIMEOUT=60
REASONING_EFFORT=

# Interactive mode parameters
INTERACTIVE_ROUND=25

# UI/UX
CODE_THEME=monokai
# Max entries kept in history file
MAX_HISTORY=500
AUTO_SUGGEST=true
# Print reasoning content or not
SHOW_REASONING=true
# Text alignment (default, left, center, right, full)
JUSTIFY=default

# Chat history settings
CHAT_HISTORY_DIR=<tmpdir>/yaicli/chats
MAX_SAVED_CHATS=20

# Role settings
# Set to false to disable warnings about modified built-in roles
ROLE_MODIFY_WARNING=true

# Function settings
# Set to false to disable sending functions in API requests
ENABLE_FUNCTIONS=true
# Set to false to disable showing function output in the response
SHOW_FUNCTION_OUTPUT=true

# MCP settings
ENABLE_MCP=false
SHOW_MCP_OUTPUT=false
```

## Configuration Options Reference

| Option                 | Description                                 | Default                  | Environment Variable       |
| ---------------------- | ------------------------------------------- | ------------------------ | -------------------------- |
| `PROVIDER`             | LLM provider (openai, claude, cohere, etc.) | `openai`                 | `YAI_PROVIDER`             |
| `BASE_URL`             | API endpoint URL                            | -                        | `YAI_BASE_URL`             |
| `API_KEY`              | Your API key                                | -                        | `YAI_API_KEY`              |
| `MODEL`                | LLM model to use                            | `gpt-4o`                 | `YAI_MODEL`                |
| `DEFAULT_ROLE`         | Default role                                | `DEFAULT`                | `YAI_DEFAULT_ROLE`         |
| `SHELL_NAME`           | Shell type                                  | `auto`                   | `YAI_SHELL_NAME`           |
| `OS_NAME`              | Operating system                            | `auto`                   | `YAI_OS_NAME`              |
| `STREAM`               | Enable streaming                            | `true`                   | `YAI_STREAM`               |
| `TIMEOUT`              | API timeout (seconds)                       | `60`                     | `YAI_TIMEOUT`              |
| `EXTRA_HEADERS`        | Extra headers                               | -                        | `YAI_EXTRA_HEADERS`        |
| `EXTRA_BODY`           | Extra body                                  | -                        | `YAI_EXTRA_BODY`           |
| `REASONING_EFFORT`     | Reasoning effort                            | -                        | `YAI_REASONING_EFFORT`     |
| `INTERACTIVE_ROUND`    | Interactive mode rounds                     | `25`                     | `YAI_INTERACTIVE_ROUND`    |
| `CODE_THEME`           | Syntax highlighting theme                   | `monokai`                | `YAI_CODE_THEME`           |
| `TEMPERATURE`          | Response randomness                         | `0.3`                    | `YAI_TEMPERATURE`          |
| `TOP_P`                | Top-p sampling                              | `1.0`                    | `YAI_TOP_P`                |
| `MAX_TOKENS`           | Max response tokens                         | `1024`                   | `YAI_MAX_TOKENS`           |
| `MAX_HISTORY`          | Max history entries                         | `500`                    | `YAI_MAX_HISTORY`          |
| `AUTO_SUGGEST`         | Enable history suggestions                  | `true`                   | `YAI_AUTO_SUGGEST`         |
| `SHOW_REASONING`       | Enable reasoning display                    | `true`                   | `YAI_SHOW_REASONING`       |
| `JUSTIFY`              | Text alignment                              | `default`                | `YAI_JUSTIFY`              |
| `CHAT_HISTORY_DIR`     | Chat history directory                      | `<tempdir>/yaicli/chats` | `YAI_CHAT_HISTORY_DIR`     |
| `MAX_SAVED_CHATS`      | Max saved chats                             | `20`                     | `YAI_MAX_SAVED_CHATS`      |
| `ROLE_MODIFY_WARNING`  | Warn when modifying built-in roles          | `true`                   | `YAI_ROLE_MODIFY_WARNING`  |
| `ENABLE_FUNCTIONS`     | Enable function calling                     | `true`                   | `YAI_ENABLE_FUNCTIONS`     |
| `SHOW_FUNCTION_OUTPUT` | Show function output                        | `true`                   | `YAI_SHOW_FUNCTION_OUTPUT` |
| `ENABLE_MCP`           | Enable MCP tools                            | `false`                  | `YAI_ENABLE_MCP`           |
| `SHOW_MCP_OUTPUT`      | Show MCP output                             | `true`                   | `YAI_SHOW_MCP_OUTPUT`      |
| `MAX_TOOL_CALL_DEPTH`  | Max tool calls in one request               | `8`                      | `YAI_MAX_TOOL_CALL_DEPTH`  |


## Syntax Highlighting Themes

YAICLI supports all Pygments syntax highlighting themes. Set your preferred theme with:

```ini
CODE_THEME = monokai
```

Browse available themes at: [https://pygments.org/styles/](https://pygments.org/styles/)

## Extra Headers and Body

You can add extra headers and body parameters to the API request:

```ini
EXTRA_HEADERS={"X-Extra-Header": "value"}
EXTRA_BODY={"extra_key": "extra_value"}
```

Example: Disable Qwen3's thinking behavior:

```ini
EXTRA_BODY={"enable_thinking": false}
```

Or limit thinking tokens:

```ini
EXTRA_BODY={"thinking_budget": 4096}
```

## Environment Variables

All configuration options can be set using environment variables with the `YAI_` prefix:

```bash
# Set API key via environment variable
export YAI_API_KEY="your-api-key"

# Use a different model
export YAI_MODEL="gpt-3.5-turbo"

# Disable streaming
export YAI_STREAM="false"
```

Environment variables take precedence over the configuration file settings.

## Provider-Specific Configuration

See the [Providers section](../providers/overview.md) for detailed configuration options for each supported LLM provider.
