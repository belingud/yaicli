# YAICLI - Your AI Command Line Interface

YAICLI is a powerful command-line AI assistant tool that enables you to interact with Large Language Models (LLMs) like ChatGPT's gpt-4o through your terminal. It offers multiple operation modes for everyday conversations, generating and executing shell commands, and one-shot quick queries.

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
```

### Configuration Options

Below are the available configuration options and override environment variables:

- **BASE_URL**: API endpoint URL (default: OpenAI API), env: AI_BASE_URL
- **API_KEY**: Your API key for the LLM provider, env: AI_API_KEY
- **MODEL**: The model to use (e.g., gpt-4o, gpt-3.5-turbo), default: gpt-4o, env: AI_MODEL
- **SHELL_NAME**: Shell to use (auto for automatic detection), default: auto, env: AI_SHELL_NAME
- **OS_NAME**: OS to use (auto for automatic detection), default: auto, env: AI_OS_NAME
- **COMPLETION_PATH**: Path for completions endpoint, default: /chat/completions, env: AI_COMPLETION_PATH
- **ANSWER_PATH**: Json path expression to extract answer from response, default: choices[0].message.content, env: AI_ANSWER_PATH
- **STREAM**: Enable/disable streaming responses, default: true, env: AI_STREAM

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

- `<PROMPT>`: Argument
- `--verbose` or `-V`: Show verbose information
- `--chat` or `-c`: Start in chat mode
- `--shell` or `-s`: Generate and execute shell command
- `--install-completion`: Install completion for the current shell
- `--show-completion`: Show completion for the current shell, to copy it or customize the installation
- `--help` or `-h`: Show this message and exit

```bash
ai -h

 Usage: ai [OPTIONS] [PROMPT]

 yaicli. Your AI interface in cli.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   prompt      [PROMPT]  The prompt send to the LLM                                                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --verbose             -V        Show verbose information                                                                                                 │
│ --chat                -c        Start in chat mode                                                                                                       │
│ --shell               -s        Generate and execute shell command                                                                                       │
│ --install-completion            Install completion for the current shell.                                                                                │
│ --show-completion               Show completion for the current shell, to copy it or customize the installation.                                         │
│ --help                -h        Show this message and exit.                                                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯


```

### Interactive Mode

In interactive mode (chat or shell), you can:
- Type your queries and get responses
- Use `Tab` to switch between Chat and Execute modes
- Type 'exit' or 'quit' to exit

### Shell Command Generation

In Execute mode:
1. Enter your request in natural language
2. YAICLI will generate an appropriate shell command
3. Review the command
4. Confirm to execute or reject

## Examples

### Chat Mode Example

```bash
$ ai --chat
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

💬 >
```

### Execute Mode Example

```bash
$ ai --shell "Find all PDF files in my Downloads folder"

Generated command: find ~/Downloads -type f -name "*.pdf"
Execute this command? [y/n]: y

Executing command: find ~/Downloads -type f -name "*.pdf"

/Users/username/Downloads/document1.pdf
/Users/username/Downloads/report.pdf
...
```

## Technical Implementation

YAICLI is built using several Python libraries:

- **Typer**: Provides the command-line interface
- **Rich**: Provides terminal content formatting and beautiful display
- **prompt_toolkit**: Provides interactive command-line input experience
- **requests**: Handles API requests
- **jmespath**: Parses JSON responses

## Contributing

Contributions of code, issue reports, or feature suggestions are welcome.

## License

[Apache License 2.0](LICENSE)

---

*YAICLI - Making your terminal smarter*