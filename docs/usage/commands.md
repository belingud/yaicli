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
| `/add <path>` | Add file or directory to context |
| `/context <subcmd>` | Manage context (alias: `/ctx`) |

#### Context Management Commands

The `/add` and `/context` commands help you manage files and directories in the conversation context:

| Command | Description |
|---------|-------------|
| `/add <path>` | Add a file or directory to the persistent context |
| `/context list` or `/ctx list` | List all items in current context |
| `/context clear` or `/ctx clear` | Remove all items from context |
| `/context add <path>` | Add item to context (same as `/add`) |
| `/context remove <path>` or `/ctx remove <path>` | Remove specific item from context |

**Context Features:**

- **Persistent**: Items added with `/add` stay in context for the entire session
- **Smart reading**: Files are read and formatted for AI consumption
- **Directory support**: Directories are scanned recursively (2 levels deep by default)
- **Auto-ignores**: Skips `.git`, `node_modules`, `__pycache__`, `.venv`, etc.
- **Flexible matching**: Use partial paths or filenames for removal

**Example:**

```bash
💬 > /add src/main.py
Added file to context: /path/to/src/main.py

💬 > /add tests/
Added directory to context: /path/to/tests/

💬 > /context list
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Type   ┃ Path                          ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ FILE   │ src/main.py                   │
│ DIR    │ tests/                        │
└────────┴───────────────────────────────┘

💬 > /context remove main.py
Removed from context: /path/to/src/main.py

💬 > /ctx clear
Context cleared.
```

### @ File References

In addition to persistent context, you can temporarily reference files using the `@` symbol directly in your queries:

**Syntax:**

```bash
# Single file reference
@filename

# Multiple files
@file1.py @file2.py

# Paths with spaces (use quotes)
@"my document.txt"
@'path with spaces/file.md'
```

**How it works:**

1. Type `@` followed by a file path
2. Press `Tab` for auto-completion and file browser
3. Use arrow keys to select files
4. The file content is automatically included in that message only
5. References are replaced with filenames in the final message

**Example:**

```bash
# Quick file analysis
💬 > @README.md Summarize this project

# Compare files
💬 > @config.json @config.example.json What changed?

# Use with quotes for spaces
💬 > @"my notes.txt" Create a todo list from these notes

# Path completion
💬 > @src/ma[Tab]
# Shows: src/main.py, src/math.py, etc.
```

**Differences from `/add`:**

| Feature | `/add` | `@` reference |
|---------|--------|---------------|
| Duration | Entire session | Single message only |
| Storage | Persistent context | Temporary inclusion |
| Best for | Codebases you'll discuss repeatedly | Quick one-time file checks |
| Management | Manual add/remove | Automatic per message |

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
