# Command Overview

YAICLI provides a versatile command-line interface with multiple options and modes. This page covers all available commands and options.

## Basic Syntax

```
ai [OPTIONS] [PROMPT]
```

Where `PROMPT` is the text input for the AI assistant. If not provided, YAICLI will read from stdin if available.

## Command Line Reference

Here's a comprehensive list of all available options:

### Core Options

| Option | Short | Description |
|--------|-------|-------------|
| `--help` | `-h` | Show help message and exit |
| `--verbose` | `-V` | Show verbose output (loaded config, API calls, etc.) |
| `--template` | | Show the default config file template and exit |

### Mode Options

| Option | Short | Description |
|--------|-------|-------------|
| `--chat` | `-c` | Start in interactive chat mode |
| `--shell` | `-s` | Generate and optionally execute shell commands |
| `--code` | | Generate code in plaintext |

### LLM Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--model` | `-M` | Specify the model to use | Configured default |
| `--temperature` | `-T` | Set temperature (randomness) | 0.5 |
| `--top-p` | `-P` | Set top-p sampling | 1.0 |
| `--max-tokens` | | Set max tokens in response | 1024 |
| `--stream` / `--no-stream` | | Enable/disable streaming | stream |

### Role Options

| Option | Short | Description |
|--------|-------|-------------|
| `--role` | `-r` | Specify the assistant role to use |
| `--create-role` | | Create a new role with the specified name |
| `--delete-role` | | Delete a role with the specified name |
| `--list-roles` | | List all available roles |
| `--show-role` | | Show the role with the specified name |

### Chat Options

| Option | Description |
|--------|-------------|
| `--list-chats` | List saved chat sessions |

### Display Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--justify` | `-j` | Text alignment (default, left, center, right, full) | default |
| `--show-reasoning` / `--hide-reasoning` | | Show/hide reasoning content | show |

### Function Options

| Option | Description | Default |
|--------|-------------|---------|
| `--install-functions` | Install default functions | |
| `--list-functions` | List all available functions | |
| `--enable-functions` / `--disable-functions` | Enable/disable function calling | disabled |
| `--show-function-output` / `--hide-function-output` | Show/hide function output | show |

### MCP Options

| Option | Description | Default |
|--------|-------------|---------|
| `--enable-mcp` / `--disable-mcp` | Enable/disable MCP in API requests | disabled |
| `--show-mcp-output` / `--hide-mcp-output` | Show/hide MCP output | show |
| `--list-mcp` | List all available MCP | |

## Common Command Examples

```bash
# Get a quick answer
ai "What is the capital of France?"

# Start an interactive chat session
ai --chat

# Save chat with a title
ai --chat "Python programming tips"

# Generate and execute shell commands
ai --shell "Create a backup of my Documents folder"

# Generate code snippets (Python by default)
ai --code "Write a function to sort a list"

# Use a specific LLM model
ai --model gpt-4-turbo "Explain quantum computing"

# Adjust temperature for more creative responses
ai --temperature 0.8 "Write a poem about AI"

# Create a custom role
ai --create-role "SQL Expert"

# Use a custom role
ai --role "SQL Expert" "Optimize this query"

# Show verbose output for debugging
ai --verbose "Test query"
```

## Interactive Mode Commands

When in interactive chat or shell mode, you can use these special commands:

| Command | Description |
|---------|-------------|
| `/help` or `/?` | Show help message |
| `/clear` | Clear conversation history |
| `/his` | Show command history |
| `/list` | List saved chats |
| `/save <title>` | Save current chat with title |
| `/load <index>` | Load a saved chat |
| `/del <index>` | Delete a saved chat |
| `/exit` | Exit the application |
| `/mode chat\|exec` | Switch between chat and execute modes |

## Keyboard Shortcuts

| Shortcut | Description |
|----------|-------------|
| `Tab` | Toggle between Chat/Execute modes |
| `Ctrl+C` or `Ctrl+D` | Exit |
| `Ctrl+R` | Search history |
| `↑/↓` | Navigate through history |

## Next Steps

- Learn about [configuration options](configuration.md)
- Explore different [interaction modes](modes.md)
- Discover [CLI shortcuts and hotkeys](cli.md)
