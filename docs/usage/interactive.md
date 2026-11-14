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
Model: gpt-4o
Press Shift+Tab to toggle plan mode (normal ↔ plan, read-only)
/help|?            : Show help message
/clear             : Clear chat history
/his               : Show chat history
/list|/chats       : List saved chats
/save <title>      : Save current chat
/load <index>      : Load a saved chat
/del|/delete <index>: Delete a saved chat
/add <path>        : Add @file/dir to context
/context, /ctx     : Show context/token usage; manage context (list, add, remove, clear, budget)
/cost              : Show session token usage and estimated cost
/compact [keep_rounds]: Compact history, keeping the last N turn groups (default 5)
/permissions [revoke <tool-or-index>]: List/revoke tool permissions and session grants
/show-output       : View this turn's tool outputs (same as Ctrl+O)
/undo              : Undo the last file change made by a tool
/model [name]      : Show or switch the model for this session
/role [name]       : Show or switch the assistant role
/retry             : Re-run the last user turn (e.g. after an API error)
/exit|Ctrl+D       : Exit (Ctrl+D also exits)
/mode chat|exec    : Switch mode (Case insensitive)
!<command>         : Execute shell command directly (e.g., !ls -al)
Ctrl+C             : Clear input / cancel turn; press twice to exit
Alt+Enter/Ctrl+J   : Insert a newline (Enter still submits)
  Tip: Type '@' for file paths and '/' for slash commands; use Tab/arrows to select
Plan mode: Shift+Tab / /plan · plan files under ~/.config/yaicli/plans
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
Model: gpt-4o
Press Shift+Tab to toggle plan mode (normal ↔ plan, read-only)
/help|?            : Show help message
/clear             : Clear chat history
/his               : Show chat history
/list|/chats       : List saved chats
/save <title>      : Save current chat
/load <index>      : Load a saved chat
/del|/delete <index>: Delete a saved chat
/add <path>        : Add @file/dir to context
/context, /ctx     : Show context/token usage; manage context (list, add, remove, clear, budget)
/cost              : Show session token usage and estimated cost
/compact [keep_rounds]: Compact history, keeping the last N turn groups (default 5)
/permissions [revoke <tool-or-index>]: List/revoke tool permissions and session grants
/show-output       : View this turn's tool outputs (same as Ctrl+O)
/undo              : Undo the last file change made by a tool
/model [name]      : Show or switch the model for this session
/role [name]       : Show or switch the assistant role
/retry             : Re-run the last user turn (e.g. after an API error)
/exit|Ctrl+D       : Exit (Ctrl+D also exits)
/mode chat|exec    : Switch mode (Case insensitive)
!<command>         : Execute shell command directly (e.g., !ls -al)
Ctrl+C             : Clear input / cancel turn; press twice to exit
Alt+Enter/Ctrl+J   : Insert a newline (Enter still submits)
  Tip: Type '@' for file paths and '/' for slash commands; use Tab/arrows to select
Plan mode: Shift+Tab / /plan · plan files under ~/.config/yaicli/plans
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 💬 >
```

## Prompt

The prompt is a single fixed line: the mode icon plus `>`. Nothing else is inlined, so the
cursor always starts in the same column regardless of the model, role or working directory.

```text
 💬 >
```

- The model, the last-known context usage and the per-turn token/cost figures are shown on the
  dim status line that closes each answer, for example
  `gpt-4o · context 12% · tokens 1,234 in / 567 out · $0.0021 · 1.2s · stop`. The current model is
  also printed in the welcome banner (`Model: gpt-4o`) and `/model` changes it immediately.
- The working directory, git branch and assistant role are **not** shown. In particular, a custom
  `DEFAULT_ROLE` (for example `master`) is ordinary assistant configuration, not repository
  state: the prompt never inspects the repository.
- `Shift+Tab` toggles the read-only plan mode, and the input line becomes `[plan] 💬 >`.
  Chat and execute mode switching is done with `/mode chat|exec`; their icons are 💬 chat,
  🚀 execute (and 📝 temporary session).
- The status line is interactive-only and obeys `SHOW_USAGE`; headless/one-shot runs never render
  it, and the context percentage stays cached (refreshed after every completed turn and after
  `/compact`, `/clear`, `/load` and `/model`).

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
- `/cost` - Show session token usage, estimated cost, per-model breakdown and tool metrics
- `/compact [keep_rounds]` - Compact the conversation, keeping the last N turns
- `/model` - Show the current model and provider
- `/model <name>` - Switch the model for this session: the provider client is rebuilt on the next
  request, the chat history is kept, and the change is not written to the config file. The notice
  names the previous model so you can revert with `/model <old-name>`.
- `/role` - Show the current role and the available roles
- `/role <name>` - Switch the assistant role for this session (case-insensitive; an unknown name
  lists the available roles). The change is session-only; restart to use the configured role.
- `/retry` - Re-run the last user turn from its pre-turn snapshot. Useful after an API error: the
  failed turn's partial messages are discarded before the same input is sent again.
- `/permissions` - List (and revoke) persistent tool approval rules
- `/show-output` - Open the full-screen tool-output viewer for this turn
- `/undo` - Restore the last file change made by a tool in this session
- `!<command>` - Execute a shell command directly
- `/exit` - Exit the application
- `/mode chat|exec` - Switch between chat and execute modes
- `/plan [subcommand]` - Toggle read-only plan mode or manage saved plans (see [Plan Mode](plan-mode.md))
- `/todo` - Show the current plan todos

Typing `/` opens the slash-command completion menu: every command is listed with a one-line
description, `/co` filters the list, and `Tab`/arrow keys select an entry. `@` path completion
still works as before and shares the same prompt.

## Usage & cost

Each turn closes with one dim status line: the current model and context usage, then what the
turn cost (v0.22 K17), for example:

```text
gpt-4o · context 12% · tokens 1,234 in / 567 out · $0.0021 · 1.2s · stop
```

The numbers come from the provider when it reports them; a provider that reports no usage gets a
clearly estimated count instead. Unknown model pricing simply omits the `$` segment. The line is
controlled by `SHOW_USAGE` (default `true`) and only appears in interactive output — headless /
JSON runs report usage through their structured output instead.

- `/cost` prints the session totals (tokens in/out, requests, estimated flag), a per-model
  breakdown, the estimated USD cost, tool-call count/duration/result size and the last finish
  reason. It works even when the model has no known price ("unknown model pricing").
- When the model hits the output token limit, the answer is truncated at `finish_reason="length"`;
  YAICLI prints one `Response stopped at MAX_TOKENS; ...` warning to stderr — raise `MAX_TOKENS`
  to get complete answers.
- Prices are approximate built-in estimates (USD per 1M tokens); override them with
  `MODEL_PRICING` for exact accounting. See [Context & Limits](context-limits.md).

## Keyboard Shortcuts

- `Shift+Tab` - Toggle plan mode (normal ↔ plan, read-only); `/mode chat|exec` switches chat/execute
- `Ctrl+C` - Clear the current input line; during generation it cancels the turn. Press `Ctrl+C`
  twice quickly to exit (single press keeps the session alive)
- `Ctrl+D` - Exit (exit code 0)
- `Ctrl+R` - Search history
- `Ctrl+O` - Open the full-screen tool-output viewer for this turn (`↑/↓` select, `Tab` switch
  pane, `f` full text, `q`/`Esc` close). It also works while the assistant is generating:
  generation continues in the background and closing the viewer redraws the accumulated answer
- `↑/↓` - Navigate through history
- `Alt+Enter` (or `Esc` then `Enter`) - Insert a newline instead of submitting
- `Ctrl+J` - Insert a newline (same as `Alt+Enter`); `Enter` still submits the whole input
- `/` - Open the slash-command completion menu (see [Commands](#commands))

Multiline text is useful for pasting or composing long prompts; press `Enter` once you are done
to send the whole buffer as one turn.

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
 gpt-4o · context 12% · tokens 1,234 in / 567 out · $0.0021 · 1.2s · stop
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

Since v0.21, saved chats are isolated per project: each working directory has its own store under
`~/.yaicli/sessions/`. Sessions record the model, provider, role and working directory they were
created with, and `ai --resume` continues the newest session of the current project. Use
`CHAT_HISTORY_DIR` (or `YAI_CHAT_HISTORY_DIR`) only if you want the old flat directory.

`ai --chat "<title>"` loads a session by title from the current project; when the title does not
exist it prints an explicit notice and starts a new session with that title. Listing with
`ai --list-chats` uses the invocation directory (the callback runs before `--cwd` applies) — use
`/list` inside the REPL for the current project.

See [Chat Sessions & Resume](sessions.md) for the layout, metadata, `--resume` and migration of old
sessions.
