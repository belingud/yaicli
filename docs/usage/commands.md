# Command Reference

YAICLI provides a versatile command-line interface with multiple options and modes. This page covers all available commands and options.

## Basic Syntax

```
ai [OPTIONS] [PROMPT]
```

Where `PROMPT` is the text input for the agent. If not provided, YAICLI reads from stdin when it is
piped; with no prompt and no stdin it starts the interactive REPL. Use `-p/--print` to force a
single one-shot run, and see [Headless & Scripting](headless.md) for the full scripting contract.

## Command Line Reference

Here's a comprehensive list of all available options:

### Core Options

| Option | Short | Description |
|--------|-------|-------------|
| `--help` | `-h` | Show help message and exit |
| `--verbose` | `-V` | Show verbose output (loaded config, API calls, etc.) |
| `--version` | `-v` | Show version and exit (fast path; does not read config) |
| `--template` | | Show the default config file template and exit |
| `--list-providers` | | List available providers and exit |

### Headless / Scripting Options

| Option | Short | Description |
|--------|-------|-------------|
| `--print` | `-p` | Explicit one-shot mode: run once, never start the REPL |
| `--output-format text\|json\|stream-json` | | Output format for the result (default `text`; `stream-json` is NDJSON events) |
| `--quiet` | `-q` | Only print the answer to stdout (no labels/progress) |
| `--max-turns N` | | Maximum tool-call rounds for this run (overrides `MAX_TOOL_CALL_DEPTH`) |
| `--yes` | `-y` | Auto-approve `read`-level tools only; write/exec tools still need a rule |
| `--allowed-tools "a,b*"` | | Per-run tool allowlist, comma-separated names or globs |
| `--cwd DIR` | | Working directory / workspace root for the run |
| `--fail-on-tool-denied` | | Exit with code `3` when a tool was denied |

See [Headless & Scripting](headless.md) for JSON schemas, exit codes and signal handling, and
[Permissions & Safety](permissions.md) for `--yes` / `--allowed-tools` semantics.

### Mode Options

| Option | Short | Description |
|--------|-------|-------------|
| `--chat` | `-c` | Start in interactive chat mode |
| `--shell` | `-s` | Generate and optionally execute shell commands (in a non-TTY: print only) |
| `--code` | | Generate code in plaintext |
| `--print` | `-p` | Explicit one-shot mode (see above) |

### LLM Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--model` | `-M` | Specify the model to use | Configured default |
| `--temperature` | `-T` | Set temperature (randomness) | 0.3 |
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
| `--install-functions` | Export editable copies of the built-in functions into the config dir (built-ins work without this; existing files are skipped) | |
| `--reinstall-functions` | Overwrite exported built-in copies with the current version; custom files are kept | |
| `--list-functions` | List loaded tools, their source (`builtin`/`user`) and stale-copy warnings | |
| `--enable-functions` / `--disable-functions` | Enable/disable function calling in API requests | enabled |
| `--show-function-output` / `--hide-function-output` | Show/hide function output | show |

See [Advanced Usage — Function Calling](advanced.md#function-calling) for custom functions,
updating after an upgrade, and built-in safety contracts. See
[Permissions & Safety](permissions.md) for the confirmation protocol, rules and audit log.

### MCP Options

| Option | Description | Default |
|--------|-------------|---------|
| `--enable-mcp` / `--disable-mcp` | Enable/disable MCP in API requests | disabled |
| `--show-mcp-output` / `--hide-mcp-output` | Show/hide MCP output | hide |
| `--list-mcp` | List all available MCP | |

### Image Options

| Option | Short | Description |
|--------|-------|-------------|
| `--image` | `-i` | Image file path or URL to include with the prompt. Can be specified multiple times. |

## Common Command Examples

```bash
# Agent task: let the model pick and run tools
ai "Use your tools to find the 3 largest files here and write a summary to REPORT.md"

# One-shot with machine-readable output
ai -p "summarize the git log" --output-format json

# Answer-only output (for pipelines)
ai -q -p "list the open TODOs in src/"

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

# Send an image to a vision model
ai --image photo.jpg "What is in this image?"

# Send multiple images for comparison
ai -i img1.png -i img2.png "Compare these screenshots"

# Send an image URL
ai --image https://example.com/photo.jpg "Describe this"

# Image-only (no text prompt)
ai --image diagram.png
```

## Interactive Mode Commands

When in interactive chat or shell mode, you can use these special commands:

| Command | Description |
|---------|-------------|
| `/help` or `/?` | Show help message |
| `/clear` | Clear conversation history |
| `/his` | Show chat history |
| `/list` | List saved chats |
| `/save <title>` | Save current chat with title |
| `/load <index>` | Load a saved chat |
| `/del <index>` | Delete a saved chat |
| `/exit` | Exit the application |
| `/mode chat\|exec` | Switch between chat and execute modes |
| `/add <path>` | Add file or directory to context |
| `/context` or `/ctx` | Show estimated context/token usage for the current conversation |
| `/context <subcmd>` | Manage file context (`list`, `add`, `remove`, `clear`) |
| `/compact [keep_rounds]` | Compact the conversation, keeping the last N turns |
| `/permissions` | List session approvals, the persistent allowlist and the numbered rules |
| `/permissions revoke <tool-or-index>` | Remove a persistent permission by tool name or rule number (the tool will ask again) |
| `/show-output` | Open the full-screen viewer listing every tool output of the current turn (same as `Ctrl+O`) |

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
| `Shift+Tab` | Toggle between Chat/Execute modes |
| `Ctrl+C` | Clear the current input line; during generation it cancels the turn; press twice quickly to exit |
| `Ctrl+D` | Exit (exit code 0) |
| `Ctrl+R` | Search history |
| `Ctrl+O` | Open the full-screen tool-output viewer for this turn (`q`/`Esc` to close); works during generation too (stream pauses while viewing) |
| `↑/↓` | Navigate through history |

## Next Steps

- Learn about [configuration options](configuration.md)
- Explore different [interaction modes](modes.md)
- Discover [CLI shortcuts and hotkeys](cli.md)
