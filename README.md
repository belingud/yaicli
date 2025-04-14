# YAICLI - Your AI Interface in Command Line

[![PyPI version](https://img.shields.io/pypi/v/yaicli?style=for-the-badge)](https://pypi.org/project/yaicli/)
![GitHub License](https://img.shields.io/github/license/belingud/yaicli?style=for-the-badge)
![PyPI - Downloads](https://img.shields.io/pypi/dm/yaicli?logo=pypi&style=for-the-badge)
![Pepy Total Downloads](https://img.shields.io/pepy/dt/yaicli?style=for-the-badge&logo=python)

YAICLI is a compact yet potent command-line AI assistant, allowing you to engage with Large Language Models (LLMs) such as ChatGPT's gpt-4o directly via your terminal. It offers multiple operation modes for everyday conversations, generating and executing shell commands, and one-shot quick queries.

Support regular and deep thinking models.

> [!WARNING]
> This is a work in progress, some features could change or be removed in the future.

## Features

- **Multiple Operation Modes**:
  - **Chat Mode (💬)**: Interactive conversation with the AI assistant
  - **Execute Mode (🚀)**: Generate and execute shell commands specific to your OS and shell
  - **Temp Mode**: Quick queries without entering interactive mode

- **Smart Environment Detection**:
  - Automatically detects your operating system and shell
  - Customizes responses and commands for your specific environment

- **Rich Terminal Interface**:
  - Markdown rendering for formatted responses
  - Streaming responses for real-time feedback
  - Color-coded output for better readability

- **Configurable**:
  - Customizable API endpoints
  - Support for different LLM providers
  - Adjustable response parameters

- **Keyboard Shortcuts**:
  - Tab to switch between Chat and Execute modes
  - `↑/↓` to navigate history
  - `Ctrl+R` to search history

- **History**:
  - Save and recall previous queries

## Installation

### Prerequisites

- Python 3.9 or higher

### Install from PyPI

```bash
# Install by pip
pip install yaicli

# Install by pipx
pipx install yaicli

# Install by uv
uv tool install yaicli
```

### Install from Source

```bash
git clone https://github.com/yourusername/yaicli.git
cd yaicli
pip install .
```

## Configuration

On first run, YAICLI will create a default configuration file at `~/.config/yaicli/config.ini`. You'll need to edit this file to add your API key and customize other settings.

Just run `ai`, and it will create the config file for you. Then you can edit it to add your api key.

### Configuration File

The default configuration file is located at `~/.config/yaicli/config.ini`. Look at the example below:

```ini
[core]
PROVIDER=OPENAI
BASE_URL=https://api.openai.com/v1
API_KEY=your_api_key_here
MODEL=gpt-4o

# auto detect shell and os
SHELL_NAME=auto
OS_NAME=auto

# if you want to use custom completions path, you can set it here
COMPLETION_PATH=/chat/completions
# if you want to use custom answer path, you can set it here
ANSWER_PATH=choices[0].message.content

# true: streaming response
# false: non-streaming response
STREAM=true
CODE_THEME=monokia

TEMPERATURE=0.7
TOP_P=1.0
MAX_TOKENS=1024
```

### Configuration Options

Below are the available configuration options and override environment variables:

- **BASE_URL**: API endpoint URL (default: OpenAI API), env: YAI_BASE_URL
- **API_KEY**: Your API key for the LLM provider, env: YAI_API_KEY
- **MODEL**: The model to use (e.g., gpt-4o, gpt-3.5-turbo), default: gpt-4o, env: YAI_MODEL
- **SHELL_NAME**: Shell to use (auto for automatic detection), default: auto, env: YAI_SHELL_NAME
- **OS_NAME**: OS to use (auto for automatic detection), default: auto, env: YAI_OS_NAME
- **COMPLETION_PATH**: Path for completions endpoint, default: /chat/completions, env: YAI_COMPLETION_PATH
- **ANSWER_PATH**: Json path expression to extract answer from response, default: choices[0].message.content, env: YAI_ANSWER_PATH
- **STREAM**: Enable/disable streaming responses, default: true, env: YAI_STREAM
- **CODE_THEME**: Theme for code blocks, default: monokia, env: YAI_CODE_THEME
- **TEMPERATURE**: Temperature for response generation (default: 0.7), env: YAI_TEMPERATURE
- **TOP_P**: Top-p sampling for response generation (default: 1.0), env: YAI_TOP_P
- **MAX_TOKENS**: Maximum number of tokens for response generation (default: 1024), env: YAI_MAX_TOKENS
- **MAX_HISTORY**: Max history size, default: 500, env: YAI_MAX_HISTORY

Default config of `COMPLETION_PATH` and `ANSWER_PATH` is OpenAI compatible. If you are using OpenAI or other OpenAI compatible LLM provider, you can use the default config.

If you wish to use other providers that are not compatible with the openai interface, you can use the following config:

- claude:
  - BASE_URL: https://api.anthropic.com/v1
  - COMPLETION_PATH: /messages
  - ANSWER_PATH: content.0.text
- cohere:
  - BASE_URL: https://api.cohere.com/v2
  - COMPLETION_PATH: /chat
  - ANSWER_PATH: message.content.[0].text
- google:
  - BASE_URL: https://generativelanguage.googleapis.com/v1beta/openai
  - COMPLETION_PATH: /chat/completions
  - ANSWER_PATH: choices[0].message.content

You can use google OpenAI complete endpoint and leave `COMPLETION_PATH` and `ANSWER_PATH` as default. BASE_URL: https://generativelanguage.googleapis.com/v1beta/openai. See https://ai.google.dev/gemini-api/docs/openai

Claude also has a testable OpenAI-compatible interface, you can just use Calude endpoint and leave `COMPLETION_PATH` and `ANSWER_PATH` as default. See: https://docs.anthropic.com/en/api/openai-sdk

If you not sure how to config `COMPLETION_PATH` and `ANSWER_PATH`, here is a guide:
1. **Find the API Endpoint**:
   - Visit the documentation of the LLM provider you want to use.
   - Find the API endpoint for the completion task. This is usually under the "API Reference" or "Developer Documentation" section.
2. **Identify the Response Structure**:
   - Look for the structure of the response. This typically includes fields like `choices`, `completion`, etc.
3. **Identify the Path Expression**:
   Forexample, claude response structure like this:
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
      "role": "assistant",
      "stop_reason": "end_turn",
      "stop_sequence": null,
      "type": "message",
      "usage": {
        "input_tokens": 2095,
        "output_tokens": 503
      }
    }
   ```
    We are looking for the `text` field, so the path should be 1.Key `content`, 2.First obj `[0]`, 3.Key `text`. So it should be `content.[0].text`.

**CODE_THEME**

You can find the list of code theme here: https://pygments.org/styles/

Default: monokia
![monikia](artwork/monokia.png)

## Usage

### Basic Usage

```bash
# One-shot mode
ai "What is the capital of France?"

# Chat mode
ai --chat

# Shell command generation mode
ai --shell "Create a backup of my Documents folder"

# Verbose mode for debugging
ai --verbose "Explain quantum computing"
```

### Command Line Options

Arguments:
- `<PROMPT>`: Argument

Options:
- `--install-completion`: Install completion for the current shell
- `--show-completion`: Show completion for the current shell, to copy it or customize the installation
- `--help` or `-h`: Show this message and exit
- `--template`: Show the config template.

Run Options:
- `--verbose` or `-V`: Show verbose information
- `--chat` or `-c`: Start in chat mode
- `--shell` or `-s`: Generate and execute shell command

```bash
ai -h

Usage: ai [OPTIONS] [PROMPT]

 yaicli - Your AI interface in cli.

╭─ Arguments ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   prompt      [PROMPT]  The prompt send to the LLM                                                                                                                      │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --template                      Show the config template.                                                                                                               │
│ --install-completion            Install completion for the current shell.                                                                                               │
│ --show-completion               Show completion for the current shell, to copy it or customize the installation.                                                        │
│ --help                -h        Show this message and exit.                                                                                                             │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Run Option ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --chat     -c        Start in chat mode                                                                                                                                 │
│ --shell    -s        Generate and execute shell command                                                                                                                 │
│ --verbose  -V        Show verbose information                                                                                                                           │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### Interactive Mode

In interactive mode (chat or shell), you can:
- Type your queries and get responses
- Use `Tab` to switch between Chat and Execute modes
- Type '/exit' to exit
- Type '/clear' to clear history
- Type '/his' to show history

### Shell Command Generation

In Execute mode:
1. Enter your request in natural language
2. YAICLI will generate an appropriate shell command
3. Review the command
4. Confirm to execute or reject

### Keyboard Shortcuts
- `Tab`: Switch between Chat and Execute modes
- `Ctrl+C`: Exit
- `Ctrl+R`: Search history
- `↑/↓`: Navigate history

### Stdin
You can also pipe input to YAICLI:
```bash
echo "What is the capital of France?" | ai
```

```bash
cat demo.py | ai "How to use this tool?"
```

### History
Support max history size. Set MAX_HISTORY in config file. Default is 500.

## Examples

### Have a Chat

```bash
$ ai "What is the capital of France?"
Assistant:
The capital of France is Paris.
```

### Command Gen and Run

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

Press TAB to change in chat and exec mode
Type /clear to clear chat history
Type /his to see chat history
Press Ctrl+C or type /exit to exit

💬 > Tell me about the solar system

Assistant:
Certainly! Here’s a brief overview of the solar system:

 • Sun: The central star of the solar system, providing light and energy.
 • Planets:
    • Mercury: Closest to the Sun, smallest planet.
    • Venus: Second planet, known for its thick atmosphere and high surface temperature.
    • Earth: Third planet, the only known planet to support life.
    • Mars: Fourth planet, often called the "Red Planet" due to its reddish appearance.
    • Jupiter: Largest planet, a gas giant with many moons.
    • Saturn: Known for its prominent ring system, also a gas giant.
    • Uranus: An ice giant, known for its unique axial tilt.
    • Neptune: Another ice giant, known for its deep blue color.
 • Dwarf Planets:
    • Pluto: Once considered the ninth planet, now classified as

🚀 > Check the current directory size
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
🚀 >
```

### Execute Mode Example

```bash
$ ai --shell "Find all PDF files in my Downloads folder"
Assistant:
find ~/Downloads -type f -name "*.pdf"
╭─ Command ──────────────────────────────╮
│ find ~/Downloads -type f -name "*.pdf" │
╰────────────────────────────────────────╯
Execute command? [e]dit, [y]es, [n]o (n): y
Output:

/Users/username/Downloads/document1.pdf
/Users/username/Downloads/report.pdf
...
```

## Technical Implementation

YAICLI is built using several Python libraries:

- **Typer**: Provides the command-line interface
- **Rich**: Provides terminal content formatting and beautiful display
- **prompt_toolkit**: Provides interactive command-line input experience
- **httpx**: Handles API requests
- **jmespath**: Parses JSON responses

## Contributing

Contributions of code, issue reports, or feature suggestions are welcome.

## License

[Apache License 2.0](LICENSE)

---

*YAICLI - Making your terminal smarter*
