# Basic Usage

YAICLI offers multiple ways to interact with AI models directly from your command line.

## Quick Start

Give the agent a multi-step task (it picks and runs tools itself):

```bash
ai "Use your tools to find the 3 largest files here and write a summary to REPORT.md"
```

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

> This help snapshot is abbreviated; run `ai --help` for the authoritative current
> options (see also [Command Reference](commands.md) and
> [Headless & Scripting](headless.md)).

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

When you omit the prompt, YAICLI sends a minimal prompt (`Describe the image.`,
or `Describe these images.` for several images) together with the image.

Supported formats: JPEG (`.jpg`, `.jpeg`), PNG (`.png`), GIF (`.gif`), WebP (`.webp`).

> **Note**: Image input works in single-shot mode only (not `--chat`). Providers without vision support will show a warning and ignore the images.

## Command Line Reference

The authoritative list is `ai --help`. A representative snapshot (stable defaults; your config may
change default values):

```

 Usage: ai [OPTIONS] [PROMPT]

 YAICLI: a lightweight agent in your terminal.

 Call with a PROMPT to get a direct answer, use --shell to generate a command, or use
 --chat for an interactive session.

 Scripting: stdout only carries the result, diagnostics go to stderr, and the exit code
 is script-friendly (0 ok / 1 error / 2 usage / 3 denied / 130 SIGINT / 141 EPIPE).
 Use -p/--print with --output-format json (or stream-json) for machine-readable output.

 Example:
     ai "What is the capital of France?"
     ai -p "Summarize this file" > summary.md
     ai -p "List the TODO comments in src" --output-format json | jq -r .content
     ai -p "Summarize this repo" --json | jq -r .content
     echo "error log" | ai -p "Explain these errors"
     ai -p "Run the tests and summarize failures" -y --fail-on-tool-denied
     ai --code "Write a fibonacci generator in Python"
     ai --chat "What's the meaning of life"  # Start a chat session with a title
     ai --chat  # Start a temporary chat session
     ai --resume  # Continue the newest chat session of this project
     ai --shell "Start docker image python:3.13.5-alpine3.22 with ports 8080"

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   prompt      [PROMPT]  The prompt to send to the LLM. Reads from stdin if available.            │
│                         [default: None]                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-completion            Install completion for the current shell.                        │
│ --show-completion               Show completion for the current shell, to copy it or customize   │
│                                 the installation.                                                │
│ --help                -h        Show this message and exit.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ LLM Options ────────────────────────────────────────────────────────────────────────────────────╮
│ --model        -M                 TEXT                       Specify the model to use.           │
│ --temperature  -T                 FLOAT RANGE [0.0<=x<=2.0]  Specify the temperature to use.     │
│                                                              [default: 0.3]                      │
│ --top-p        -P                 FLOAT RANGE [0.0<=x<=1.0]  Specify the top-p to use.           │
│                                                              [default: 1.0]                      │
│ --max-tokens                      INTEGER RANGE [x>=1]       Specify the max tokens to use.      │
│                                                              [default: 6144]                     │
│ --stream           --no-stream                               Specify whether to stream the       │
│                                                              response. (default: stream)         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Role Options ───────────────────────────────────────────────────────────────────────────────────╮
│ --role         -r      TEXT  Specify the assistant role to use. [default: master]                │
│ --create-role          TEXT  Create a new role with the specified name.                          │
│ --delete-role          TEXT  Delete a role with the specified name.                              │
│ --list-roles                 List all available roles.                                           │
│ --show-role            TEXT  Show the role with the specified name.                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Chat Options ───────────────────────────────────────────────────────────────────────────────────╮
│ --chat        -c        Start in interactive chat mode.                                          │
│ --resume                Resume the most recent chat session for the current project.             │
│ --list-chats            List saved chat sessions.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Headless Options ───────────────────────────────────────────────────────────────────────────────╮
│ --print                -p                               Explicit one-shot run: print the result  │
│                                                         only (no REPL, no prompts).              │
│ --output-format                [text|json|stream-json]  Output format: text, json or stream-json │
│                                                         (NDJSON events).                         │
│                                                         [default: text]                          │
│ --quiet                -q                               Only print the answer on stdout (no      │
│                                                         labels, panels or progress).             │
│ --json                                                  Shorthand for --output-format json       │
│                                                         (machine-readable one-shot output).      │
│ --max-turns                    INTEGER RANGE [x>=1]     Override the maximum number of tool-call │
│                                                         rounds (MAX_TOOL_CALL_DEPTH).            │
│                                                         [default: None]                          │
│ --yes                  -y                               Non-interactive approval: auto-allow     │
│                                                         read-level tools only.                   │
│ --allowed-tools                TEXT                     Comma-separated per-run tool allowlist,  │
│                                                         glob patterns allowed (e.g.              │
│                                                         "fs_*,execute_shell_command").           │
│ --cwd                          TEXT                     Run as if started in DIR; also used as   │
│                                                         the tool workspace root.                 │
│                                                         [default: None]                          │
│ --fail-on-tool-denied                                   Exit with code 3 when a tool call was    │
│                                                         denied.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Shell Options ──────────────────────────────────────────────────────────────────────────────────╮
│ --shell  -s        Generate a shell command; in a non-interactive run only print it (execute     │
│                    with --yes).                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Code Options ───────────────────────────────────────────────────────────────────────────────────╮
│ --code          Generate code in plaintext (non-interactive).                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Other Options ──────────────────────────────────────────────────────────────────────────────────╮
│ --version         -v                                                  Show version and exit.     │
│ --verbose         -V                                                  Show verbose output (e.g., │
│                                                                       loaded config).            │
│ --template                                                            Show the default config    │
│                                                                       file template and exit.    │
│ --list-providers                                                      List the available         │
│                                                                       providers and exit.        │
│ --show-reasoning      --hide-reasoning                                Show reasoning content     │
│                                                                       from the LLM. (default:    │
│                                                                       show)                      │
│ --justify         -j                      [default|left|center|right  Specify the justify to     │
│                                           |full]                      use.                       │
│                                                                       [default: default]         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Function Options ───────────────────────────────────────────────────────────────────────────────╮
│ --install-functions                                       Export editable copies of builtin      │
│                                                           functions (builtins load               │
│                                                           automatically; existing files are      │
│                                                           skipped).                              │
│ --reinstall-functions                                     Refresh exported builtin function      │
│                                                           copies (preserves user-defined         │
│                                                           functions).                            │
│ --list-functions                                          List loaded tools and their source     │
│                                                           (builtin/user).                        │
│ --enable-functions        --disable-functions             Enable/disable function calling in API │
│                                                           requests (default: enabled)            │
│ --show-function-output    --hide-function-output          Show the output of functions (default: │
│                                                           show)                                  │
│ --tools                                             TEXT  Comma-separated tool-name globs to     │
│                                                           offer the model (empty = all tools;    │
│                                                           MCP tools use the _mcp__ prefix, e.g.  │
│                                                           fs_*,web_search or _mcp__github_*).    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ MCP Options ────────────────────────────────────────────────────────────────────────────────────╮
│ --enable-mcp         --disable-mcp          Enable/disable MCP in API requests (default:         │
│                                             disabled)                                            │
│                                             [default: disable-mcp]                               │
│ --show-mcp-output    --hide-mcp-output      Show the output of MCP (default: show)               │
│ --list-mcp                                  List all available mcp.                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Image Options ──────────────────────────────────────────────────────────────────────────────────╮
│ --image  -i      TEXT  Image file path or URL to include with the prompt. Can be specified       │
│                        multiple times.                                                           │
│                        [default: None]                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯

```

> See [Command Reference](commands.md) for the option tables with short descriptions, and
> [Headless & Scripting](headless.md) for the machine-output contract.
