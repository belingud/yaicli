# Mode Switching (Chat / Execute)

YAICLI offers multiple interaction modes to suit different needs. This page explains each mode and how to switch between them.

## Available Modes

YAICLI has three primary interaction modes, plus a read-only plan mode you can toggle inside the REPL:

### 1. Chat Mode (💬)

Chat mode provides a natural conversation experience with the LLM, maintaining context and formatting responses with markdown.

**Features:**
- Full conversation history and context tracking
- Markdown and code formatting
- Reasoning display for complex queries
- Persistent chat storage and management

**Best for:**
- Extended conversations
- Complex questions requiring context
- Learning and exploration

### 2. Execute Mode (🚀)

Execute mode specializes in generating and safely running shell commands based on natural language descriptions.

**Features:**
- OS-specific command generation
- Command review and editing before execution
- Command output display
- Safe execution with confirmation

**Best for:**
- System administration tasks
- File operations
- Command discovery
- Automating repetitive tasks

### 3. Quick Query Mode (Default)

The default non-interactive mode gives you quick answers without entering a persistent session.

**Features:**
- Direct answers to questions
- Support for piped input
- Image input support via `--image` / `-i`
- Fast responses with minimal overhead

**Best for:**
- One-off questions
- Quick information lookups
- Image analysis with vision models
- Script integration

### 4. Plan Mode (`[plan] 💬`)

Plan mode is a persistent, **read-only** phase toggled in the interactive REPL with `Shift+Tab`
(or `/plan`): the model inspects the project with read/network tools and a fixed read-only shell
allowlist, submits a structured plan with `submit_plan`, and waits for your approval before it gets
the normal tool set back and executes the plan step by step. See [Plan Mode](plan-mode.md).

**Features:**
- No writes while planning; write/exec tools are not offered and forced calls are refused
- Approval panel (`[a]`pprove & execute, `[e]`dit, `[r]`edo, `[s]`ave only, `Esc` cancel)
- Todo-driven execution; plans persist per project and can be revised in place

**Best for:**
- Multi-file changes you want to review before anything is written
- Tasks where the approach matters as much as the result

## Switching Between Modes

### Command Line Switches

Use these flags when starting YAICLI:

```bash
# Start in chat mode
ai --chat "Optional chat title"

# Start in execute mode
ai --shell "Create a backup script"

# Quick query (default mode)
ai "What is the capital of France?"

# Quick query with image input
ai --image photo.jpg "What is in this image?"
```

### Interactive Mode Switching

When in interactive mode (chat, execute or plan), you can switch modes in several ways:

#### Using Shift+Tab Key

Press `Shift+Tab` to toggle the read-only **plan mode** on and off (normal ↔ plan). In execute
mode it first returns to chat mode and then enters plan mode. The plan approval panel accepts
`a`/`e`/`r`/`s` and `Esc` to cancel a submission. See [Plan Mode](plan-mode.md).

#### Using Commands

Chat and execute modes are switched with `/mode`, and plan mode with `/plan` (or `Shift+Tab`):

```
/mode chat   # Switch to chat mode
/mode exec   # Switch to execute mode
/plan        # Toggle plan mode (read-only)
```

#### Visual Indicators

The prompt changes to indicate your current mode:
- Chat mode: `💬 >`
- Execute mode: `🚀 >`
- Plan mode: `[plan] 💬 >`

## Mode Behavior

### Chat Mode Behavior

In chat mode:
- The AI responds conversationally with rich formatting
- Context is maintained between interactions
- Input is treated as a conversation prompt

**Example:**
```
💬 > Tell me about quantum computing
Assistant:
Quantum computing uses quantum bits (qubits) that can exist in multiple
states simultaneously due to superposition...
```

### Execute Mode Behavior

In execute mode:
- The AI interprets input as a request for a command
- Generates appropriate commands for your OS and shell
- Displays the command for review before execution

**Example:**
```
🚀 > Find all PDF files in my Downloads folder
Assistant:
find ~/Downloads -name "*.pdf"
╭─ Suggest Command ─────────────────────╮
│ find ~/Downloads -name "*.pdf"        │
╰─────────────────────────────────────────╯
Execute command? [e]dit, [y]es, [n]o (y):
```

The default answer is **yes**: pressing `Enter` without typing another choice executes the
generated command. Type `n` to cancel or `e` to edit it first.

## Chat Persistence

When starting a chat session with a title, the conversation is automatically saved:

```bash
ai --chat "Python tips"
```

A chat started without a title is treated as temporary but can be saved later:

```
💬 > /save "Python tips"
Chat saved as: Python tips
```

You can list, load, and manage saved chats:

```
💬 > /list
Saved chats:
1. Python tips (2023-07-01)
2. Work project (2023-06-28)

💬 > /load 1
Loaded chat: Python tips
```

Since v0.21, sessions are saved per working directory under `~/.yaicli/sessions/`. `ai --resume`
continues the newest session of the current project, and `--chat "<title>"` prints an explicit
notice when the title does not exist. See [Chat Sessions & Resume](sessions.md).

## Next Steps

- Learn more about [plan mode](plan-mode.md)
- Learn more about [CLI shortcuts and hotkeys](cli.md)
- Explore [configuration options](configuration.md)
- Check out all available [commands](commands.md)
