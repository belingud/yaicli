# YAICLI: Your AI assistant in the command line.

[![PyPI version](https://img.shields.io/pypi/v/yaicli?style=for-the-badge)](https://pypi.org/project/yaicli/)
![GitHub License](https://img.shields.io/github/license/belingud/yaicli?style=for-the-badge)
![PyPI - Downloads](https://img.shields.io/pypi/dm/yaicli?logo=pypi&style=for-the-badge)
![Pepy Total Downloads](https://img.shields.io/pepy/dt/yaicli?style=for-the-badge&logo=python)

YAICLI is a powerful yet lightweight command-line AI assistant that brings the capabilities of Large Language Models (
LLMs) like GPT-4o directly to your terminal. Interact with AI through multiple modes: have natural conversations,
generate and execute shell commands, or get quick answers without leaving your workflow.

**Supports both standard and deep reasoning models across all major LLM providers.**

<a href="https://asciinema.org/a/vyreM0n576GjGL2asjI3QzUIY" target="_blank"><img src="https://asciinema.org/a/vyreM0n576GjGL2asjI3QzUIY.svg" width="85%"/></a>

> [!NOTE]
> YAICLI is actively developed. While core functionality is stable, some features may evolve in future releases.

> We support Function Call since v0.5.0!

## ✨ Key Features

### 🔄 Multiple Interaction Modes

- **💬 Chat Mode**: Engage in persistent conversations with full context tracking
- **🚀 Execute Mode**: Generate and safely run OS-specific shell commands
- **⚡ Quick Query**: Get instant answers without entering interactive mode

### 🧠 Smart Environment Awareness

- **Auto-detection**: Identifies your shell (bash/zsh/PowerShell/CMD) and OS
- **Safe Command Execution**: 3-step verification before running any command
- **Flexible Input**: Pipe content directly (`cat log.txt | ai "analyze this"`)

### 🔌 Universal LLM Compatibility

- **OpenAI-Compatible**: Works with any OpenAI-compatible API endpoint
- **Multi-Provider Support**: Using litellm to support all major LLM providers

### 💻 Enhanced Terminal Experience

- **Real-time Streaming**: See responses as they're generated with cursor animation
- **Rich History Management**: LRU-based history with 500 entries by default
- **Syntax Highlighting**: Beautiful code formatting with customizable themes

### 🛠️ Developer-Friendly

- **Layered Configuration**: Environment variables > Config file > Sensible defaults
- **Debugging Tools**: Verbose mode with detailed API tracing

### 📚 Function Calling

- **Function Calling**: Enable function calling in API requests
- **Function Output**: Show the output of functions

![What is life](artwork/reasoning_example.png)

## 📦 Installation

### Prerequisites

- Python 3.9 or higher

### Quick Install

```bash
# Using pip (recommended for most users)
pip install yaicli

# Using pipx (isolated environment)
pipx install yaicli

# Using uv (faster installation)
uv tool install yaicli
```

### Install from Source

```bash
git clone https://github.com/belingud/yaicli.git
cd yaicli
pip install .
```

## ⚙️ Configuration

YAICLI uses a simple configuration file to store your preferences and API keys.

### First-time Setup

1. Run `ai` once to generate the default configuration file
2. Edit `~/.config/yaicli/config.ini` to add your API key
3. Customize other settings as needed

### Configuration File Structure

The default configuration file is located at `~/.config/yaicli/config.ini`. You can use `ai --template` to see default
settings, just as below:

```ini
[core]
PROVIDER=openai
BASE_URL=https://api.openai.com/v1
API_KEY=
MODEL=gpt-4o

# auto detect shell and os (or specify manually, e.g., bash, zsh, powershell.exe)
SHELL_NAME=auto
OS_NAME=auto

# true: streaming response, false: non-streaming
STREAM=true

# LLM parameters
TEMPERATURE=0.5
TOP_P=1.0
MAX_TOKENS=1024
TIMEOUT=60
REASONING_EFFORT=

# Interactive mode parameters
INTERACTIVE_ROUND=25

# UI/UX
CODE_THEME=monokai
# Max entries kept in history file
MAX_HISTORY=500
AUTO_SUGGEST=true
# Print reasoning content or not
SHOW_REASONING=true
# Text alignment (default, left, center, right, full)
JUSTIFY=default

# Chat history settings
CHAT_HISTORY_DIR=<tmpdir>/yaicli/chats
MAX_SAVED_CHATS=20

# Role settings
# Set to false to disable warnings about modified built-in roles
ROLE_MODIFY_WARNING=true

# Function settings
# Set to false to disable sending functions in API requests
ENABLE_FUNCTIONS=true
# Set to false to disable showing function output in the response
SHOW_FUNCTION_OUTPUT=true
```

### Configuration Options Reference

| Option                 | Description                                 | Default                     | Env Variable               |
| ---------------------- | ------------------------------------------- | --------------------------- | -------------------------- |
| `PROVIDER`             | LLM provider (openai, claude, cohere, etc.) | `openai`                    | `YAI_PROVIDER`             |
| `BASE_URL`             | API endpoint URL                            | `https://api.openai.com/v1` | `YAI_BASE_URL`             |
| `API_KEY`              | Your API key                                | -                           | `YAI_API_KEY`              |
| `MODEL`                | LLM model to use                            | `gpt-4o`                    | `YAI_MODEL`                |
| `SHELL_NAME`           | Shell type                                  | `auto`                      | `YAI_SHELL_NAME`           |
| `OS_NAME`              | Operating system                            | `auto`                      | `YAI_OS_NAME`              |
| `STREAM`               | Enable streaming                            | `true`                      | `YAI_STREAM`               |
| `TIMEOUT`              | API timeout (seconds)                       | `60`                        | `YAI_TIMEOUT`              |
| `INTERACTIVE_ROUND`    | Interactive mode rounds                     | `25`                        | `YAI_INTERACTIVE_ROUND`    |
| `CODE_THEME`           | Syntax highlighting theme                   | `monokai`                   | `YAI_CODE_THEME`           |
| `TEMPERATURE`          | Response randomness                         | `0.7`                       | `YAI_TEMPERATURE`          |
| `TOP_P`                | Top-p sampling                              | `1.0`                       | `YAI_TOP_P`                |
| `MAX_TOKENS`           | Max response tokens                         | `1024`                      | `YAI_MAX_TOKENS`           |
| `MAX_HISTORY`          | Max history entries                         | `500`                       | `YAI_MAX_HISTORY`          |
| `AUTO_SUGGEST`         | Enable history suggestions                  | `true`                      | `YAI_AUTO_SUGGEST`         |
| `SHOW_REASONING`       | Enable reasoning display                    | `true`                      | `YAI_SHOW_REASONING`       |
| `JUSTIFY`              | Text alignment                              | `default`                   | `YAI_JUSTIFY`              |
| `CHAT_HISTORY_DIR`     | Chat history directory                      | `<tempdir>/yaicli/chats`    | `YAI_CHAT_HISTORY_DIR`     |
| `MAX_SAVED_CHATS`      | Max saved chats                             | `20`                        | `YAI_MAX_SAVED_CHATS`      |
| `ROLE_MODIFY_WARNING`  | Warn user when modifying role               | `true`                      | `YAI_ROLE_MODIFY_WARNING`  |
| `ENABLE_FUNCTIONS`     | Enable function calling                     | `true`                      | `YAI_ENABLE_FUNCTIONS`     |
| `SHOW_FUNCTION_OUTPUT` | Show function output in response            | `true`                      | `YAI_SHOW_FUNCTION_OUTPUT` |

### LLM Provider Configuration

YAICLI works with all major LLM providers. The default configuration is set up for OpenAI, but you can easily switch to
other providers.

#### Pre-configured Provider Settings

| Provider                       | BASE_URL                                                  |
| ------------------------------ | --------------------------------------------------------- |
| **OpenAI** (default)           | `https://api.openai.com/v1`                               |
| **Claude** (native API)        | `https://api.anthropic.com/v1`                            |
| **Claude** (OpenAI-compatible) | `https://api.anthropic.com/v1/openai`                     |
| **Cohere**                     | `https://api.cohere.com`                                  |
| **Gemini**                     | `https://generativelanguage.googleapis.com/v1beta/openai` |

> **Note**: Many providers offer OpenAI-compatible endpoints that work with the default settings.
>
> - Google Gemini: https://ai.google.dev/gemini-api/docs/openai
> - Claude: https://docs.anthropic.com/en/api/openai-sdk

If you not sure about base_url or just use the default provider base_url, just leave it blank.

```ini
[core]
PROVIDER=cohere
BASE_URL=
API_KEY=xxx
MODEL=command-r-plus
```

### Syntax Highlighting Themes

YAICLI supports all Pygments syntax highlighting themes. You can set your preferred theme in the config file:

```ini
CODE_THEME = monokai
```

Browse available themes at: https://pygments.org/styles/

![monokia theme example](artwork/monokia.png)

## 🚀 Usage

### Quick Start

```bash
# Get a quick answer
ai "What is the capital of France?"

# Start an interactive chat session
ai --chat

# Generate and execute shell commands
ai --shell "Create a backup of my Documents folder"

# Generate code snippets, default in Python
ai --code "Write a Python function to sort a list"

# Analyze code from a file
cat app.py | ai "Explain what this code does"

# Debug with verbose mode
ai --verbose "Explain quantum computing"
```

### Command Line Reference

```
 Usage: ai [OPTIONS] [PROMPT]

 YAICLI: Your AI assistant in the command line.
 Call with a PROMPT to get a direct answer, use --shell to execute as command, or use --chat for an interactive session.

╭─ Arguments ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   prompt      [PROMPT]  The prompt to send to the LLM. Reads from stdin if available. [default: None]                             │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-completion            Install completion for the current shell.                                                         │
│ --show-completion               Show completion for the current shell, to copy it or customize the installation.                  │
│ --help                -h        Show this message and exit.                                                                       │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ LLM Options ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --model        -M                 TEXT                       Specify the model to use.                                            │
│ --temperature  -T                 FLOAT RANGE [0.0<=x<=2.0]  Specify the temperature to use. [default: 0.5]                       │
│ --top-p        -P                 FLOAT RANGE [0.0<=x<=1.0]  Specify the top-p to use. [default: 1.0]                             │
│ --max-tokens   -M                 INTEGER RANGE [x>=1]       Specify the max tokens to use. [default: 1024]                       │
│ --stream           --no-stream                               Specify whether to stream the response. (default: stream)            │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Role Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --role         -r      TEXT  Specify the assistant role to use. [default: DEFAULT]                                                │
│ --create-role          TEXT  Create a new role with the specified name.                                                           │
│ --delete-role          TEXT  Delete a role with the specified name.                                                               │
│ --list-roles                 List all available roles.                                                                            │
│ --show-role            TEXT  Show the role with the specified name.                                                               │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Chat Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --chat        -c        Start in interactive chat mode.                                                                           │
│ --list-chats            List saved chat sessions.                                                                                 │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Shell Options ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --shell  -s        Generate and optionally execute a shell command (non-interactive).                                             │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Code Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --code          Generate code in plaintext (non-interactive).                                                                     │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Other Options ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --verbose         -V                                                        Show verbose output (e.g., loaded config).            │
│ --template                                                                  Show the default config file template and exit.       │
│ --show-reasoning      --hide-reasoning                                      Show reasoning content from the LLM. (default: show)  │
│ --justify         -j                      [default|left|center|right|full]  Specify the justify to use. [default: default]        │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Function Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-functions                                   Install default functions.                                                  │
│ --list-functions                                      List all available functions.                                               │
│ --enable-functions        --disable-functions         Enable/disable function calling in API requests (default: disabled)         │
│ --show-function-output    --hide-function-output      Show the output of functions (default: show)                                │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### Interactive Mode Features

<table>
<tr>
<td width="50%">

**Commands**

- `/help|?` - Show help message
- `/clear` - Clear conversation history
- `/his` - Show command history
- `/list` - List saved chats
- `/save <title>` - Save current chat with title
- `/load <index>` - Load a saved chat
- `/del <index>` - Delete a saved chat
- `/exit` - Exit the application
- `/mode chat|exec` - Switch modes

**Keyboard Shortcuts**

- `Tab` - Toggle between Chat/Execute modes
- `Ctrl+C` or `Ctrl+D` - Exit
- `Ctrl+R` - Search history
- `↑/↓` - Navigate through history

</td>
<td width="50%">

**Chat Mode** (💬)

- Natural conversations with context
- Markdown and code formatting
- Reasoning display for complex queries

**Execute Mode** (🚀)

- Generate shell commands from descriptions
- Review commands before execution
- Edit commands before running
- Safe execution with confirmation

</td>
</tr>
</table>

### Chat Persistent

The `<PROMPT>` parameter in the chat mode will be used as a title to persist the chat content to the file system, with
the save directory being a temporary directory, which may vary between machines, and it is determined on the first run.

If the `<PROMPT>` parameter is not specified when entering `chat` mode, the session will be treated as a temporary
session and will not be persisted. Of course, you can also manually call the `/save <title>` command to save during the
chat.
When you run the same `chat` command again, the previous session will be automatically loaded.

```bash
$ ai --chat "meaning of life"
```

> !NOTE: Chat mode is not supported when you redirect input to `ai` command.
>
> ```bash
> $ cat error.log | ai --chat "Explain this error"
> ```
>
> The above command will be parsed as `ai "cat error.log | ai "Explain this error"`.

**Start a temporary chat session**

```bash
$ ai --chat
```

**Save a temporary chat session**

```bash
$ ai --chat
Starting a temporary chat session (will not be saved automatically)
...
 💬 > hi
Assistant:
Hello! How can I assist you today?
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 💬 > /save "hello"
Chat saved as: hello
Session is now marked as persistent and will be auto-saved on exit.
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 💬 >
```

**Start a persistent chat session**

```bash
$ ai --chat "check disk usage"
```

**Load a saved chat session**

```bash
$ ai --chat hello
Chat title: hello

 ██    ██  █████  ██  ██████ ██      ██
  ██  ██  ██   ██ ██ ██      ██      ██
   ████   ███████ ██ ██      ██      ██
    ██    ██   ██ ██ ██      ██      ██
    ██    ██   ██ ██  ██████ ███████ ██

Welcome to YAICLI!
Current: Persistent Session: hello
Press TAB to switch mode
/clear             : Clear chat history
/his               : Show chat history
/list              : List saved chats
/save <title>      : Save current chat
/load <index>      : Load a saved chat
/del <index>       : Delete a saved chat
/exit|Ctrl+D|Ctrl+C: Exit
/mode chat|exec    : Switch mode (Case insensitive)
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 💬 > /his
Chat History:
1 User: hi
    Assistant:
    Hello! How can I assist you today?
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 💬 >
```

### Input Methods

**Direct Input**

```bash
ai "What is the capital of France?"
```

**Piped Input**

```bash
echo "What is the capital of France?" | ai
```

**File Analysis**

```bash
cat demo.py | ai "Explain this code"
```

**Combined Input**

```bash
cat error.log | ai "Why am I getting these errors in my Python app?"
```

### Role Management

```bash
# Create a new role, you need to input the role description
ai --create-role "Philosopher Master"

# List all roles
ai --list-roles

# Show a role
ai --show-role "Philosopher Master"

# Delete a role
ai --delete-role "Philosopher Master"
```

Once you create a role, you can use it in the `--role` option.

```bash
# Use a specific role
ai --role "Philosopher Master" "What is the meaning of life?"

# Use a role in chat
ai --chat --role "Philosopher Master"
```

### History Management

YAICLI maintains a history of your interactions (default: 500 entries) stored in `~/.yaicli_history`. You can:

- Configure history size with `MAX_HISTORY` in config
- Search history with `Ctrl+R` in interactive mode
- View recent commands with `/his` command

## 📱 Examples

### Quick Answer Mode

```bash
$ ai "What is the capital of France?"
Assistant:
The capital of France is Paris.
```

### Command Generation & Execution

```bash
$ ai -s 'Check the current directory size'
Assistant:
du -sh .
╭─ Command ─╮
│ du -sh .  │
╰───────────╯
Execute command? [e]dit, [y]es, [n]o (n): e
Edit command, press enter to execute:
du -sh ./
Output:
109M    ./
```

### Code Generation

In code mode, select the language for code generation. If none is specified, Python is the default.

The `--code` mode outputs plain text, making it easy to copy, paste, or redirect to a file, especially when using the standard model.

When using a deep reasoning model, the thinking content is displayed with syntax highlighting. To disable this, use the `--no-show-reasoning` option or set `SHOW_REASONING` to `false` in the configuration.

```bash
$ ai --code 'Write a fib generator'
def fib_generator():
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b
```

### Chat Mode Example

```bash
$ ai --chat
Starting a temporary chat session (will not be saved automatically)

 ██    ██  █████  ██  ██████ ██      ██
  ██  ██  ██   ██ ██ ██      ██      ██
   ████   ███████ ██ ██      ██      ██
    ██    ██   ██ ██ ██      ██      ██
    ██    ██   ██ ██  ██████ ███████ ██

Welcome to YAICLI!
Current: Temporary Session (use /save to make persistent)
Press TAB to switch mode
/clear             : Clear chat history
/his               : Show chat history
/list              : List saved chats
/save <title>      : Save current chat
/load <index>      : Load a saved chat
/del <index>       : Delete a saved chat
/exit|Ctrl+D|Ctrl+C: Exit
/mode chat|exec    : Switch mode (Case insensitive)
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 💬 > Tell me about the solar system

Assistant:
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

🚀 > Check the current directory size
Assistant:
du -sh .
╭─ Suggest Command ─╮
│ du -sh .          │
╰───────────────────╯
Execute command? [e]dit, [y]es, [n]o (n): e
Edit command: du -sh ./
--- Executing ---
 55M    ./
--- Finished ---
🚀 >
```

### Execute Mode Example

```bash
$ ai --shell "Find all PDF files in my Downloads folder"
Assistant:
find ~/Downloads -type f -name "*.pdf"
╭─ Suggest Command ───────────────────────╮
│ find ~/Downloads -type f -iname "*.pdf" │
╰─────────────────────────────────────────╯
Execute command? [e]dit, [y]es, [n]o (n): y
Output:

/Users/username/Downloads/document1.pdf
/Users/username/Downloads/report.pdf
...
```

### Code Mode Example

```bash
$ ai --code "write a fib generator" --model deepseek-r1
```

![fib code example](artwork/reasoning_code_example.png)

### Function Call

To use function call, you need to install default functions by `ai --install-functions`.
After that, you can check the functions by `ai --list-functions`.
You can also define your own functions by adding them to the config folder in `~/.config/yaicli/functions/` (`C:\Users\<user>\.config\yaicli\functions` on Windows).

`--enable-functions` option is corresponds to the configuration key `ENABLE_FUNCTIONS`.

```shell
ai 'check the current dir total size' --enable-functions
Assistant:
Thinking:

▌ Okay, the user wants to check the current directory's total size. Hmm, how do I do that in macOS with zsh?
▌ I remember that the command to get disk usage is usually 'du'. But wait, the default 'du' might not give the total size of the
▌ current directory directly. Let me think. Oh right, if I use 'du -sh' with the current directory, that should give the total size
▌ in human-readable format.
▌ Wait, but sometimes the -s option summarizes the directory. So 'du -sh .' would calculate the total size of the current directory
▌ and its subdirectories. That should work. Let me confirm the syntax. Yeah, 'du -sh .' is the right command here.
▌ The user is using zsh, but the 'du' command is standard, so it should be available. I need to execute this shell command. The
▌ function provided is execute_shell_command, so I'll call that with the shell command 'du -sh .' as the argument.
▌ I should make sure the parameters are correctly formatted. The function requires a shell_command string. Alright, that's all.
▌ Let's generate the tool call.

{"index":0,"finish_reason":"tool_calls","delta":{"role":"assistant","content":null,"audio":null,"tool_calls":[{"id":"call_202505141526
36cc3f776ae8f14b56_0","index":0,"type":"function","function":{"name":"execute_shell_command","arguments":"{"shell_command": "du -sh
."}","outputs":null},"code_interpreter":null,"retrieval":null,"drawing_tool":null,"web_browser":null,"search_intent":null,"search_resu
lt":null}],"tool_call_id":null,"attachments":null,"metadata":null}}
@Function call: execute_shell_command({"shell_command": "du -sh ."})
╭─ Function output ─────╮
│ Exit code: 0, Output: │
│ 156M    .             │
│                       │
╰───────────────────────╯
Thinking:

▌ Okay, the user asked to check the current directory's total size. I used the 'du -sh .' command, which stands for disk usage,
▌ summarize, and current directory. The output was "156M". So I need to present this in a concise way.
▌ First, confirm the command was executed. Then, report the result clearly. Since the user didn't ask for extra details, keep it
▌ simple. Just state the total size as 156MB. Maybe mention the command used for transparency. Alright, that should cover it without
▌ overcomplicating.

Current directory size: 156M (using du -sh .).
```

## 💻 Technical Details

### Architecture

YAICLI is designed with a modular architecture that separates concerns and makes the codebase maintainable:

- **CLI Module**: Handles user interaction and command parsing
- **API Client**: Manages communication with LLM providers
- **Config Manager**: Handles layered configuration
- **History Manager**: Maintains conversation history with LRU functionality
- **Printer**: Formats and displays responses with rich formatting

### Dependencies

| Library                                                         | Purpose                                            |
| --------------------------------------------------------------- | -------------------------------------------------- |
| [Typer](https://typer.tiangolo.com/)                            | Command-line interface with type hints             |
| [Rich](https://rich.readthedocs.io/)                            | Terminal formatting and beautiful display          |
| [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/) | Interactive input with history and auto-completion |

## 👨‍💻 Contributing

Contributions are welcome! Here's how you can help:

- **Bug Reports**: Open an issue describing the bug and how to reproduce it
- **Feature Requests**: Suggest new features or improvements
- **Code Contributions**: Submit a PR with your changes
- **Documentation**: Help improve or translate the documentation

## 📃 License

[Apache License 2.0](LICENSE)

---

<p align="center"><i>YAICLI - Your AI Command Line Interface</i></p>
