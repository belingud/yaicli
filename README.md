# YAICLI - Your AI Command Line Interface

[![PyPI version](https://img.shields.io/pypi/v/yaicli?style=for-the-badge)](https://pypi.org/project/yaicli/)
![GitHub License](https://img.shields.io/github/license/belingud/yaicli?style=for-the-badge)
![PyPI - Downloads](https://img.shields.io/pypi/dm/yaicli?logo=pypi&style=for-the-badge)
![Pepy Total Downloads](https://img.shields.io/pepy/dt/yaicli?style=for-the-badge&logo=python)

YAICLI is a powerful yet lightweight command-line AI assistant that brings the capabilities of Large Language Models (LLMs) like GPT-4o directly to your terminal. Interact with AI through multiple modes: have natural conversations, generate and execute shell commands, or get quick answers without leaving your workflow.

**Supports both standard and deep reasoning models across all major LLM providers.**

<p align="center">
  <img src="https://vhs.charm.sh/vhs-5U1BBjJkTUBReRswsSgIVx.gif" alt="YAICLI Demo" width="85%">
</p>

> [!NOTE]
> YAICLI is actively developed. While core functionality is stable, some features may evolve in future releases.

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
- **Multi-Provider Support**: Easy configuration for Claude, Gemini, Cohere, etc.
- **Custom Response Parsing**: Extract exactly what you need with jmespath

### 💻 Enhanced Terminal Experience
- **Real-time Streaming**: See responses as they're generated with cursor animation
- **Rich History Management**: LRU-based history with 500 entries by default
- **Syntax Highlighting**: Beautiful code formatting with customizable themes

### 🛠️ Developer-Friendly
- **Layered Configuration**: Environment variables > Config file > Sensible defaults
- **Debugging Tools**: Verbose mode with detailed API tracing
- **Lightweight**: Minimal dependencies with focused functionality

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

The default configuration file is located at `~/.config/yaicli/config.ini`. You can use `ai --template` to see default settings, just as below:

```ini
[core]
PROVIDER=openai
BASE_URL=https://api.openai.com/v1
API_KEY=
MODEL=gpt-4o

# auto detect shell and os (or specify manually, e.g., bash, zsh, powershell.exe)
SHELL_NAME=auto
OS_NAME=auto

# API paths (usually no need to change for OpenAI compatible APIs)
COMPLETION_PATH=chat/completions
ANSWER_PATH=choices[0].message.content

# true: streaming response, false: non-streaming
STREAM=true

# LLM parameters
TEMPERATURE=0.7
TOP_P=1.0
MAX_TOKENS=1024
TIMEOUT=60

# Interactive mode parameters
INTERACTIVE_ROUND=25

# UI/UX
CODE_THEME=monokai
MAX_HISTORY=500 # Max entries kept in history file
AUTO_SUGGEST=true
```

### Configuration Options Reference

| Option | Description | Default | Env Variable |
|--------|-------------|---------|---------------|
| `BASE_URL` | API endpoint URL | `https://api.openai.com/v1` | `YAI_BASE_URL` |
| `API_KEY` | Your API key | - | `YAI_API_KEY` |
| `MODEL` | LLM model to use | `gpt-4o` | `YAI_MODEL` |
| `SHELL_NAME` | Shell type | `auto` | `YAI_SHELL_NAME` |
| `OS_NAME` | Operating system | `auto` | `YAI_OS_NAME` |
| `COMPLETION_PATH` | API completion path | `chat/completions` | `YAI_COMPLETION_PATH` |
| `ANSWER_PATH` | JSON path for response | `choices[0].message.content` | `YAI_ANSWER_PATH` |
| `STREAM` | Enable streaming | `true` | `YAI_STREAM` |
| `TIMEOUT` | API timeout (seconds) | `60` | `YAI_TIMEOUT` |
| `INTERACTIVE_ROUND` | Interactive mode rounds | `25` | `YAI_INTERACTIVE_ROUND` |
| `CODE_THEME` | Syntax highlighting theme | `monokai` | `YAI_CODE_THEME` |
| `TEMPERATURE` | Response randomness | `0.7` | `YAI_TEMPERATURE` |
| `TOP_P` | Top-p sampling | `1.0` | `YAI_TOP_P` |
| `MAX_TOKENS` | Max response tokens | `1024` | `YAI_MAX_TOKENS` |
| `MAX_HISTORY` | Max history entries | `500` | `YAI_MAX_HISTORY` |
| `AUTO_SUGGEST` | Enable history suggestions | `true` | `YAI_AUTO_SUGGEST` |

### LLM Provider Configuration

YAICLI works with all major LLM providers. The default configuration is set up for OpenAI, but you can easily switch to other providers.

#### Pre-configured Provider Settings

| Provider | BASE_URL | COMPLETION_PATH | ANSWER_PATH |
|----------|----------|-----------------|-------------|
| **OpenAI** (default) | `https://api.openai.com/v1` | `chat/completions` | `choices[0].message.content` |
| **Claude** (native API) | `https://api.anthropic.com/v1` | `messages` | `content[0].text` |
| **Claude** (OpenAI-compatible) | `https://api.anthropic.com/v1/openai` | `chat/completions` | `choices[0].message.content` |
| **Cohere** | `https://api.cohere.com/v2` | `chat` | `message.content[0].text` |
| **Google Gemini** | `https://generativelanguage.googleapis.com/v1beta/openai` | `chat/completions` | `choices[0].message.content` |

> **Note**: Many providers offer OpenAI-compatible endpoints that work with the default settings.
> - Google Gemini: https://ai.google.dev/gemini-api/docs/openai
> - Claude: https://docs.anthropic.com/en/api/openai-sdk

#### Custom Provider Configuration Guide

To configure a custom provider:

1. **Find the API Endpoint**:
   - Check the provider's API documentation for their chat completion endpoint

2. **Identify the Response Structure**:
   - Look at the JSON response format to find where the text content is located

3. **Set the Path Expression**:
   - Use jmespath syntax to specify the path to the text content

**Example**: For Claude's native API, the response looks like:
```json
{
  "content": [
    {
      "text": "Hi! My name is Claude.",
      "type": "text"
    }
  ],
  "id": "msg_013Zva2CMHLNnXjNJJKqJ2EF",
  "model": "claude-3-7-sonnet-20250219",
  "role": "assistant"
}
```

The path to extract the text is: `content.0.text`

### Syntax Highlighting Themes

YAICLI supports all Pygments syntax highlighting themes. You can set your preferred theme in the config file:

```ini
CODE_THEME=monokai
```

Browse available themes at: https://pygments.org/styles/

![monokai theme example](artwork/monokia.png)

## 🚀 Usage

### Quick Start

```bash
# Get a quick answer
ai "What is the capital of France?"

# Start an interactive chat session
ai --chat

# Generate and execute shell commands
ai --shell "Create a backup of my Documents folder"

# Analyze code from a file
cat app.py | ai "Explain what this code does"

# Debug with verbose mode
ai --verbose "Explain quantum computing"
```

### Command Line Reference

```
Usage: ai [OPTIONS] [PROMPT]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--chat` | `-c` | Start in interactive chat mode |
| `--shell` | `-s` | Generate and execute shell commands |
| `--help` | `-h` | Show help message and exit |
| `--verbose` | `-V` | Show detailed debug information |
| `--template` | | Display the config template |

### Interactive Mode Features

<table>
<tr>
<td width="50%">

**Commands**
- `/exit` - Exit the application
- `/clear` - Clear conversation history
- `/his` - Show command history
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

### Chat Mode Example

```bash
$ ai --chat

 ██    ██  █████  ██  ██████ ██      ██
  ██  ██  ██   ██ ██ ██      ██      ██
   ████   ███████ ██ ██      ██      ██
    ██    ██   ██ ██ ██      ██      ██
    ██    ██   ██ ██  ██████ ███████ ██

Welcome to YAICLI!
Press TAB to switch mode
/clear             : Clear chat history
/his               : Show chat history
/exit|Ctrl+D|Ctrl+C: Exit
/mode chat|exec    : Switch mode (Case insensitive)
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
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

## 💻 Technical Details

### Architecture

YAICLI is designed with a modular architecture that separates concerns and makes the codebase maintainable:

- **CLI Module**: Handles user interaction and command parsing
- **API Client**: Manages communication with LLM providers
- **Config Manager**: Handles layered configuration
- **History Manager**: Maintains conversation history with LRU functionality
- **Printer**: Formats and displays responses with rich formatting

### Dependencies

| Library | Purpose |
|---------|----------|
| [Typer](https://typer.tiangolo.com/) | Command-line interface with type hints |
| [Rich](https://rich.readthedocs.io/) | Terminal formatting and beautiful display |
| [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/) | Interactive input with history and auto-completion |
| [httpx](https://www.python-httpx.org/) | Modern HTTP client with async support |
| [jmespath](https://jmespath.org/) | JSON data extraction |

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
