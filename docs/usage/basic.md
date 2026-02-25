# Basic Usage

YAICLI offers multiple ways to interact with AI models directly from your command line.

## Quick Start

Get a quick answer.

```bash
ai "What is the capital of France?"
```

Start an interactive chat session
```bash
ai --chat
```

Generate and execute shell commands
```bash
ai --shell "Create a backup of my Documents folder"
```

Generate code snippets, default in Python
```bash
ai --code "Write a Python function to sort a list"
```

Read stdin from pipe
```bash
cat app.py | ai "Explain what this code does"
```

Debug with verbose mode
```bash
ai --verbose "Explain quantum computing"
```

## Image Input

Send images to vision-capable models directly from the command line using `--image` / `-i`:

```bash
# Describe a local image
ai --image photo.jpg "What is in this image?"

# Compare multiple images
ai -i img1.png -i img2.png "What are the differences?"

# Use an image URL
ai --image https://example.com/diagram.png "Explain this diagram"

# Send image without text prompt
ai --image photo.jpg
```

Supported formats: JPEG (`.jpg`, `.jpeg`), PNG (`.png`), GIF (`.gif`), WebP (`.webp`).

> **Note**: Image input works in single-shot mode only (not `--chat`). Providers without vision support will show a warning and ignore the images.

## Command Line Reference

```
 Usage: ai [OPTIONS] [PROMPT]

 YAICLI: Your AI assistant in the command line.

 Call with a PROMPT to get a direct answer, use --shell to execute as command, or use --chat for an interactive session.

╭─ Arguments ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   prompt      [PROMPT]  The prompt to send to the LLM. Reads from stdin if available. [default: None]                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ──────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-completion            Install completion for the current shell.                                              │
│ --show-completion               Show completion for the current shell, to copy it or customize the installation.       │
│ --help                -h        Show this message and exit.                                                            │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ LLM Options ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --model        -M                 TEXT                       Specify the model to use.                                 │
│ --temperature  -T                 FLOAT RANGE [0.0<=x<=2.0]  Specify the temperature to use. [default: 0.3]            │
│ --top-p        -P                 FLOAT RANGE [0.0<=x<=1.0]  Specify the top-p to use. [default: 1.0]                  │
│ --max-tokens                      INTEGER RANGE [x>=1]       Specify the max tokens to use. [default: 2048]            │
│ --stream           --no-stream                               Specify whether to stream the response. (default: stream) │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Role Options ─────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --role         -r      TEXT  Specify the assistant role to use. [default: DEFAULT]                                     │
│ --create-role          TEXT  Create a new role with the specified name.                                                │
│ --delete-role          TEXT  Delete a role with the specified name.                                                    │
│ --list-roles                 List all available roles.                                                                 │
│ --show-role            TEXT  Show the role with the specified name.                                                    │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Chat Options ─────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --chat        -c        Start in interactive chat mode.                                                                │
│ --list-chats            List saved chat sessions.                                                                      │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Shell Options ────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --shell  -s        Generate and optionally execute a shell command (non-interactive).                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Code Options ─────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --code          Generate code in plaintext (non-interactive).                                                          │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Other Options ────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --verbose         -V                                                        Show verbose output (e.g., loaded config). │
│ --template                                                                  Show the default config file template and  │
│                                                                             exit.                                      │
│ --show-reasoning      --hide-reasoning                                      Show reasoning content from the LLM.       │
│                                                                             (default: show)                            │
│ --justify         -j                      [default|left|center|right|full]  Specify the justify to use.                │
│                                                                             [default: default]                         │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Function Options ─────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-functions                                   Install default functions.                                       │
│ --list-functions                                      List all available functions.                                    │
│ --enable-functions        --disable-functions         Enable/disable function calling in API requests (default:        │
│                                                       disabled)                                                        │
│ --show-function-output    --hide-function-output      Show the output of functions (default: show)                     │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ MCP Options ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --enable-mcp         --disable-mcp          Enable/disable MCP in API requests (default: disabled)                     │
│                                             [default: disable-mcp]                                                     │
│ --show-mcp-output    --hide-mcp-output      Show the output of MCP (default: show)                                     │
│ --list-mcp                                  List all available mcp.                                                    │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Image Options ───────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --image  -i      TEXT  Image file path or URL to include with the prompt. Can be specified multiple times.            │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```
