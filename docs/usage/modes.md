# Mode Switching (Chat / Execute)

YAICLI offers multiple interaction modes to suit different needs. This page explains each mode and how to switch between them.

## Available Modes

YAICLI has three primary interaction modes:

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

When in interactive mode (chat or execute), you can switch modes in several ways:

#### Using Shift+Tab Key

Press the `Shift+Tab` key to toggle between Chat and Execute modes.

#### Using Commands

Type `/mode` followed by the mode name:

```
/mode chat   # Switch to chat mode
/mode exec   # Switch to execute mode
```

#### Visual Indicators

The prompt changes to indicate your current mode:
- Chat mode: `💬 >`
- Execute mode: `🚀 >`

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
Execute command? [e]dit, [y]es, [n]o (n): 
```

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
Loading chat: Python tips
```

## Next Steps

- Learn more about [CLI shortcuts and hotkeys](cli.md)
- Explore [configuration options](configuration.md)
- Check out all available [commands](commands.md)
