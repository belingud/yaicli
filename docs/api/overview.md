# API Overview

YAICLI provides a flexible architecture that supports multiple LLM providers and integration points.

## Architecture

YAICLI is designed with a modular architecture that separates concerns:

- **CLI Module**: Handles user interaction and command parsing
- **API Client**: Manages communication with LLM providers
- **Config Manager**: Handles layered configuration
- **History Manager**: Maintains conversation history with LRU functionality
- **Printer**: Formats and displays responses with rich formatting

## Configuration Options

The following table shows the main configuration options available in YAICLI:

| Option                 | Description                                 | Default                  | Env Variable               |
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
| `TEMPERATURE`          | Response randomness                         | `0.7`                    | `YAI_TEMPERATURE`          |
| `TOP_P`                | Top-p sampling                              | `1.0`                    | `YAI_TOP_P`                |
| `MAX_TOKENS`           | Max response tokens                         | `1024`                   | `YAI_MAX_TOKENS`           |
| `MAX_HISTORY`          | Max history entries                         | `500`                    | `YAI_MAX_HISTORY`          |
| `ENABLE_FUNCTIONS`     | Enable function calling                     | `true`                   | `YAI_ENABLE_FUNCTIONS`     |
| `SHOW_FUNCTION_OUTPUT` | Show function output when calling function  | `true`                   | `YAI_SHOW_FUNCTION_OUTPUT` |
| `ENABLE_MCP`           | Enable MCP tools                            | `false`                  | `YAI_ENABLE_MCP`           |
| `SHOW_MCP_OUTPUT`      | Show MCP output when calling mcp            | `true`                   | `YAI_SHOW_MCP_OUTPUT`      |

## Dependencies

YAICLI relies on the following core libraries:

| Library                                                         | Purpose                                            |
| --------------------------------------------------------------- | -------------------------------------------------- |
| [Typer](https://typer.tiangolo.com/)                            | Command-line interface with type hints             |
| [Rich](https://rich.readthedocs.io/)                            | Terminal formatting and beautiful display          |
| [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/) | Interactive input with history and auto-completion |
| [json-repair](https://github.com/mangiucugna/json_repair)       | Repair LLM function call arguments                 |

## Extension Points

YAICLI provides several extension points:

### Custom Functions

You can create custom functions in `~/.config/yaicli/functions/` that follow this structure:


### Custom LLM Providers
