# Interactive Mode

YAICLI provides an interactive mode where you can have ongoing conversations with AI models.

Run `ai --chat <title>` to start interactive session.

```bash
ai --chat "What's the meaning of life"

 ██    ██  █████  ██  ██████ ██      ██
  ██  ██  ██   ██ ██ ██      ██      ██
   ████   ███████ ██ ██      ██      ██
    ██    ██   ██ ██ ██      ██      ██
    ██    ██   ██ ██  ██████ ███████ ██

Welcome to YAICLI!
Current: Persistent Session: What's the meaning of life
Press Shift+Tab to switch mode
/help|?            : Show help message
/clear             : Clear chat history
/his               : Show chat history
/list              : List saved chats
/save <title>      : Save current chat
/load <index>      : Load a saved chat
/del <index>       : Delete a saved chat
/add <path>        : Add @file/dir to context
/context, /ctx     : Manage context (list, add, remove, clear)
  Tip: Type '@' for path completion, use Tab/arrows to select
!<command>         : Execute shell command directly (e.g., !ls -al)
/exit|Ctrl+D       : Exit
Ctrl+C             : Clear input / cancel turn; press twice to exit
/mode chat|exec    : Switch mode (Case insensitive)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 💬 >
```

Or use `ai --chat` to start a temporary session.

```bash
ai --chat

 ██    ██  █████  ██  ██████ ██      ██
  ██  ██  ██   ██ ██ ██      ██      ██
   ████   ███████ ██ ██      ██      ██
    ██    ██   ██ ██ ██      ██      ██
    ██    ██   ██ ██  ██████ ███████ ██

Welcome to YAICLI!
Current: Temporary Session (use /save to make persistent)
Press Shift+Tab to switch mode
/help|?            : Show help message
/clear             : Clear chat history
/his               : Show chat history
/list              : List saved chats
/save <title>      : Save current chat
/load <index>      : Load a saved chat
/del <index>       : Delete a saved chat
/add <path>        : Add @file/dir to context
/context, /ctx     : Manage context (list, add, remove, clear)
  Tip: Type '@' for path completion, use Tab/arrows to select
!<command>         : Execute shell command directly (e.g., !ls -al)
/exit|Ctrl+D       : Exit
Ctrl+C             : Clear input / cancel turn; press twice to exit
/mode chat|exec    : Switch mode (Case insensitive)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 💬 >
```

## Commands

- `/help|?` - Show help message
- `/clear` - Clear conversation history
- `/his` - Show chat history
- `/list` - List saved chats
- `/save <title>` - Save current chat with title
- `/load <index>` - Load a saved chat
- `/del <index>` - Delete a saved chat
- `/add <path>` - Add a file or directory to the persistent context
- `/context` or `/ctx` - Show context/token usage, or manage file context (`list`, `add`, `remove`, `clear`)
- `/compact [keep_rounds]` - Compact the conversation, keeping the last N turns
- `/permissions` - List (and revoke) persistent tool approval rules
- `/show-output` - Open the full-screen tool-output viewer for this turn
- `!<command>` - Execute a shell command directly
- `/exit` - Exit the application
- `/mode chat|exec` - Switch modes

## Keyboard Shortcuts

- `Shift+Tab` - Toggle between Chat/Execute modes
- `Ctrl+C` - Clear the current input line; during generation it cancels the turn. Press `Ctrl+C`
  twice quickly to exit (single press keeps the session alive)
- `Ctrl+D` - Exit (exit code 0)
- `Ctrl+R` - Search history
- `Ctrl+O` - Open the full-screen tool-output viewer for this turn (`↑/↓` select, `Tab` switch
  pane, `f` full text, `q`/`Esc` close). It also works while the assistant is generating:
  generation continues in the background and closing the viewer redraws the accumulated answer
- `↑/↓` - Navigate through history

## Chat Mode (💬)

In Chat Mode, you can have natural conversations with the AI while maintaining context:
- Full conversation history is maintained
- Markdown and code formatting is supported
- Reasoning display for complex queries is available

```bash
$ ai --chat
...
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 💬 > Tell me about the solar system

A:
Solar System Overview

 • Central Star: The Sun (99% of system mass, nuclear fusion).
 • Planets: 8 total.
    • Terrestrial (rocky): Mercury, Venus, Earth, Mars.
    • Gas Giants: Jupiter, Saturn.
    • Ice Giants: Uranus, Neptune.
 • Moons: Over 200 (e.g., Earth: 1, Jupiter: 95).
 • Smaller Bodies:
    • Asteroids (between Mars/Venus), comets ( icy, distant), * dwarf planets* (Pluto, Ceres).
 • Oort Cloud: spherical shell of icy objects ~1–100,000天文單位 (AU) from Sun).
 • Heliosphere: Solar wind boundary protecting Earth from cosmic radiation.

Key Fact: Earth is the only confirmed habitable planet.
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
```

## Execute Mode (🚀)

Execute Mode allows you to generate shell commands from natural language descriptions:
- Generate shell commands from descriptions
- Review commands before execution
- Edit commands before running
- Safe execution with confirmation

```bash
🚀 > Find all PDF files in my Downloads folder
Assistant:
find ~/Downloads -type f -name "*.pdf"
╭─ Suggest Command ──────────────────────╮
│ find ~/Downloads -type f -name "*.pdf" │
╰────────────────────────────────────────╯
Execute command? [e]dit, [y]es, [n]o (y):
Executing...
/Users/username/Downloads/document1.pdf
/Users/username/Downloads/report.pdf
...
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
```

## Saved Chat

Your chats will save in `CHAT_HISTORY_DIR` key in `~/.config/yaicli/config.ini`.

You can use `ai --template` to see default `CHAT_HISTORY_DIR` value, it's a temp fold created by Python, will save in `config.ini` when you first run `ai`.
