# CLI Shortcuts & Hotkeys

YAICLI offers a rich set of keyboard shortcuts and interactive features to enhance your command-line experience. This page covers all available shortcuts and interactive functionalities.

## Keyboard Shortcuts

### Global Shortcuts

These shortcuts work in all interactive modes:

| Shortcut             | Description                       |
| -------------------- | --------------------------------- |
| `Ctrl+C` or `Ctrl+D` | Exit the application              |
| `Tab`                | Toggle between Chat/Execute modes |
| `Ctrl+R`             | Search command history            |
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

YAICLI provides special commands that begin with a slash (`/`):

| Command            | Description                                |
| ------------------ | ------------------------------------------ |
| `/help` or `/?`    | Show help message                          |
| `/clear`           | Clear the current conversation history     |
| `/his`             | Show command history                       |
| `/list`            | List all saved chat sessions               |
| `/save <title>`    | Save the current chat session with a title |
| `/load <index>`    | Load a saved chat session                  |
| `/del <index>`     | Delete a saved chat session                |
| `/exit`            | Exit the application                       |
| `/mode chat\|exec` | Switch between chat and execute modes      |

## Auto-Suggestion

YAICLI offers auto-suggestions based on your command history. As you type, it shows light gray text suggesting completions from your history:

- Press `→` (right arrow) to accept the full suggestion
- Continue typing to ignore the suggestion
- Press `Ctrl+→` to accept the next word of the suggestion

To disable auto-suggestions, set `AUTO_SUGGEST=false` in your configuration.

## Multi-line Input

To enter multi-line input:

1. Type your text normally
2. Press `Alt+Enter` or `Esc+Enter` to add a new line
3. Continue adding lines as needed
4. Press `Enter` on an empty line to submit

This is useful for:
- Writing multi-line code examples
- Composing complex prompts
- Structuring lists or tables

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
| `💬 >`               | Chat mode prompt        |
| `🚀 >`               | Execute mode prompt     |
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

## Next Steps

- Learn about different [interaction modes](modes.md)
- Explore [configuration options](configuration.md)
- Check out [command references](commands.md)
