# CLI Shortcuts & Hotkeys

YAICLI offers a rich set of keyboard shortcuts and interactive features to enhance your command-line experience. This page covers all available shortcuts and interactive functionalities.

## Keyboard Shortcuts

### Global Shortcuts

These shortcuts work in all interactive modes:

| Shortcut             | Description                       |
| -------------------- | --------------------------------- |
| `Ctrl+C`             | Clear the current input line (during generation: cancel the turn); press twice quickly to exit |
| `Ctrl+D`             | Exit the application              |
| `Shift+Tab`          | Toggle between Chat/Execute modes |
| `Ctrl+R`             | Search command history            |
| `Ctrl+O`             | Show the last tool output in full (it is previewed head-only) |
| `↑/↓`                | Navigate through command history  |
| `Ctrl+L`             | Clear the screen                  |
| `Ctrl+A`             | Move cursor to beginning of line  |
| `Ctrl+E`             | Move cursor to end of line        |
| `Ctrl+U`             | Clear charactors before cursor    |
| `Ctrl+W`             | Delete word before cursor         |

### History Navigation

When searching history with `Ctrl+R`:

| Shortcut | Description                          |
| -------- | ------------------------------------ |
| `Ctrl+R` | Cycle through matching history items |
| `Enter`  | Select current history item          |
| `Esc`    | Cancel history search                |

## Interactive Commands

YAICLI provides special commands that begin with a slash (`/`) or an exclamation mark (`!`):

| Command            | Description                                |
| ------------------ | ------------------------------------------ |
| `/help` or `/?`    | Show help message                          |
| `/clear`           | Clear the current conversation history     |
| `/his`             | Show chat history                          |
| `/list`            | List all saved chat sessions               |
| `/save <title>`    | Save the current chat session with a title |
| `/load <index>`    | Load a saved chat session                  |
| `/del <index>`     | Delete a saved chat session                |
| `/exit`            | Exit the application                       |
| `/mode chat\|exec` | Switch between chat and execute modes      |
| `!<command>`       | Execute a shell command directly           |

With `!<command>`, you can execute a shell command directly without leaving the interactive mode. For example, `!ls -al` will list files in the current directory, `!git status` will show the git status, etc.

## Auto-Suggestion

YAICLI offers auto-suggestions based on your command history. As you type, it shows light gray text suggesting completions from your history:

- Press `→` (right arrow) to accept the full suggestion
- Continue typing to ignore the suggestion
- Press `Esc` then `f` to accept one word of the suggestion

To disable auto-suggestions, set `AUTO_SUGGEST=false` in your configuration.

## Multi-line and Long Input

The interactive prompt is deliberately single-line: `Enter` submits the current line, so
`Alt+Enter` / `Esc+Enter` also submit rather than insert a newline. For long or multi-line
prompts, pass the text as a quoted argument or pipe it:

```bash
# Quote a multi-line string
ai "$(cat prompt.txt)"

# Pipe content and add an instruction
cat error.log | ai "Explain these errors"

# Here-document
ai "$(cat <<'EOF'
Summarize the following log and list the root cause:
<paste log here>
EOF
)"
```

Piped stdin is combined with the prompt argument (stdin content comes first).

## Command Editing

When in Execute mode and reviewing a suggested command:

| Option | Description                       |
| ------ | --------------------------------- |
| `e`    | Edit the command before execution |
| `y`    | Execute the command as is         |
| `n`    | Cancel execution                  |

When editing a command:

- The full command is presented in an editable field
- Make your changes and press `Enter` to execute
- Press `Esc` to cancel the edit

## Visual Indicators

YAICLI uses visual indicators to help you understand the current state:

| Indicator           | Meaning                 |
| ------------------- | ----------------------- |
| `💬 >`              | Chat mode prompt        |
| `🚀 >`              | Execute mode prompt     |
| Cursor animation    | Processing your request |
| Syntax highlighting | Code in responses       |

## Input Methods

YAICLI accepts input through various methods:

### Direct Input

```bash
ai "What is the capital of France?"
```

### Piped Input

```bash
echo "What is the capital of France?" | ai
```

### File Analysis

```bash
cat error.log | ai "Explain these errors"
```

### Combined Input

```bash
cat data.csv | ai "Convert this CSV to JSON"
```

### Image Input

```bash
# Local image file
ai --image photo.jpg "What is in this image?"

# Multiple images
ai -i img1.png -i img2.png "Compare these"

# Image URL
ai --image https://example.com/photo.jpg "Describe this"
```

## Exit Codes

YAICLI returns a non-zero exit status for failures it can detect, so scripts and CI can
tell success from failure:

| Exit code | Meaning |
| --------- | ------- |
| `0` | Success (answer produced; informational commands such as `--version`, `--list-*`). |
| `1` | A handled failure: invalid/malformed configuration, unknown or misconfigured provider, missing/invalid API key or API error, retry exhaustion, no input/aborted action, or an unexpected error printed as `Unknown error: ...`. |
| `2` | Usage error: an invalid option or argument. |
| `3` | A tool call was denied and `--fail-on-tool-denied` was set. |
| `130` | Interrupted by SIGINT (Ctrl+C) during a one-shot run or generation. |
| `141` | Broken pipe (EPIPE); `ai --help \| head -1` is safe and exits `0`/`141`. |

A failure report such as `Unknown error: API_KEY is required` is accompanied by exit code
`1`; if you see a failure message with exit code `0`, that is a bug. Verify the current
build with:

```bash
ai --version; echo "exit=$?"
```

Inside the interactive `--chat` REPL, an error during one turn is printed and the session
continues; the process exits `0` when you leave the REPL normally. Use single-shot mode (`-p` or a
prompt argument) when you need the exit code to reflect the request outcome. The full scripting
contract (JSON output, signals, non-interactive approvals) is in
[Headless & Scripting](headless.md).

## Next Steps

- Learn about different [interaction modes](modes.md)
- Explore [configuration options](configuration.md)
- Check out [command references](commands.md)
