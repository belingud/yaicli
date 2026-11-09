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
| `Ctrl+O`             | Open the full-screen tool-output viewer for this turn (`↑/↓` select, `Tab` switch pane, `f` full text, `q`/`Esc` close). Also works while the assistant is generating: generation continues in the background and closing the viewer redraws the accumulated answer |
| `↑/↓`                | Navigate through command history  |
| `Alt+Enter` (`Esc`, `Enter`) | Insert a newline instead of submitting the prompt |
| `Ctrl+J`             | Insert a newline (same as `Alt+Enter`); `Enter` still submits the whole input |
| `/`                  | Open the slash-command completion menu (all commands with descriptions; `/co` filters; `Tab`/arrows select) |
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
| `/cost`            | Show session token usage and estimated cost |
| `/compact [keep_rounds]` | Compact the conversation, keeping the last N turn groups |
| `/model [name]`    | Show or switch the model for this session  |
| `/role [name]`     | Show or switch the assistant role          |
| `/retry`           | Re-run the last user turn from its pre-turn snapshot |
| `!<command>`       | Execute a shell command directly           |

With `!<command>`, you can execute a shell command directly without leaving the interactive mode. For example, `!ls -al` will list files in the current directory, `!git status` will show the git status, etc.

## Chat Sessions & Resume

Chat sessions are saved per working directory in `~/.yaicli/sessions/` since v0.21; see
[Chat Sessions & Resume](sessions.md) for the store layout, metadata and migration of old sessions.

| Command | Behaviour |
| --- | --- |
| `ai --chat` | Start a temporary interactive session |
| `ai --chat "<title>"` | Continue the session with that title in the current project. A missing title prints an explicit notice and starts a new persistent session with that title (never a silent fallback) |
| `ai --resume` | Continue the **newest** saved session of the current project (implies `--chat`). With no saved session it prints an explicit notice and starts a new temporary session |
| `ai --list-chats` | List saved sessions of the invocation directory (the callback runs before `--cwd` applies) |

`--resume` is interactive only: combined with `-p/--print` or a non-text `--output-format` it is
ignored with a warning and the run continues one-shot; the same happens when stdin is redirected.
It takes no title — use `--chat "<title>"` to load a specific session. Run `ai` from the project
directory (or use `--cwd`) so the per-project store matches the session you want.

## Auto-Suggestion

YAICLI offers auto-suggestions based on your command history. As you type, it shows light gray text suggesting completions from your history:

- Press `→` (right arrow) to accept the full suggestion
- Continue typing to ignore the suggestion
- Press `Esc` then `f` to accept one word of the suggestion

To disable auto-suggestions, set `AUTO_SUGGEST=false` in your configuration.

## Multi-line and Long Input

The prompt supports multiline editing: press `Alt+Enter` (or `Esc` then `Enter`) or `Ctrl+J` to
insert a newline, and `Enter` alone to submit the whole buffer. This is handy for pasting logs or
composing long instructions. The prompt shows the current model and the last-known
context-usage percentage on the line above the input, so the cursor position never changes
(see [Interactive Mode](interactive.md#prompt)).

For long or multi-line prompts in scripts, pass the text as a quoted argument or pipe it:

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
