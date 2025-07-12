# YAICLI: Your AI assistant in command line.

<p align="center">
  <img src="artwork/logo.png" width="150" alt="YAICLI Logo" />
</p>

<a href="https://www.producthunt.com/posts/yaicli?embed=true&utm_source=badge-featured&utm_medium=badge&utm_source=badge-yaicli" target="_blank"><img src="https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id=965413&theme=neutral&t=1747386335651" alt="Yaicli - Yaicli&#0058;&#0032;Your&#0032;AI&#0032;assistant&#0032;in&#0032;the&#0032;command&#0032;line&#0046; | Product Hunt" style="width: 250px; height: 54px;" width="250" height="54" /></a>

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

> We support MCP since v0.7.0!
> 
> We support Function Call since v0.5.0!

## ✨ Key Features

### 🔄 Multiple Interaction Modes

- **💬 Chat Mode**: Engage in persistent conversations with full context tracking
- **🚀 Execute Mode**: Generate and safely run OS-specific shell commands
- **⚡ Quick Query**: Get instant answers without entering interactive mode

### 🧠 Smart Environment Awareness

- **Auto-detection**: Identifies your shell (bash/zsh/PowerShell/CMD) and OS
- **Safe Command Execution**: Verification before running any command
- **Flexible Input**: Pipe content directly (`cat log.txt | ai "analyze this"`)

### 🔌 Universal LLM Compatibility

- **OpenAI-Compatible**: Works with any OpenAI-compatible API endpoint
- **Multi-Provider Support**: Support multiple providers

### 💻 Enhanced Terminal Experience

- **Real-time Streaming**: See responses as they're generated with cursor animation
- **Rich History Management**: Manage histories with 500 entries by default
- **Syntax Highlighting**: Beautiful code formatting with customizable themes

### 🛠️ Developer-Friendly

- **Layered Configuration**: Environment variables > Config file > Sensible defaults
- **Debugging Tools**: Verbose mode with detailed API tracing

### 📚 Function Calling & MCP

- **Function Calling**: Enable function/MCP calling in API requests
- **Function Output**: Show the output of functions/MCP

![What is life](artwork/reasoning_example.png)

Full document: https://belingud.github.io/yaicli/

## 📦 Installation

### Prerequisites

- Python 3.10 or higher

### Quick Install

```bash
# Using pip (recommended for most users)
pip install yaicli

# Using pipx (isolated environment)
pipx install yaicli

# Using uv (faster installation)
uv tool install yaicli
```

Yaicli has several optional dependencies group, you can copy below commands to install specific dependencies.

```shell
# install all denpendencies
pip install 'yaicli[all]'

# install with specific provider support
pip instsall 'yaicli[ollama,cohere,doubao,huggingface,gemini,mistral,anthropic]'
```

Install by `uv`.

```shell
# install all denpendencies
uv tool install 'yaicli[all]'

# install with specific provider support
uv tool instsall 'yaicli[ollama,cohere,doubao,huggingface,gemini,mistral,anthropic]'
```

### Install from Source

```bash
git clone https://github.com/belingud/yaicli.git
cd yaicli
pip install .
```

## Buildin Supported Providers

- AI21
- Anthropic/Claude
- Anthropic Bedrock
- Anthropic Vertex
- Cerebras
- Chatglm
- Chuts
- Cohere
- Cohere Badrock
- Cohere Sagemaker
- Deepseek
- Doubao
- Gemini
- Groq
- Huggingface
- Minimax
- Mistral
- ModelScope
- Ollama
- Openai
- Openai Azure
- Sambanova
- Siliconflow
- Spark
- Targon
- Together
- Vertex ai
- X AI
- Yi
- Unlimited OpenAI-compatible providers

## ⚙️ Configuration

YAICLI uses a simple configuration file to store your preferences and API keys.

### First-time Setup

1. Run `ai` once to generate the default configuration file
2. Edit `~/.config/yaicli/config.ini` to add your API key
3. Customize other settings as needed

### Configuration File Structure

The default configuration file is located at `~/.config/yaicli/config.ini`. You can use `ai --template` to see default

### Configuration Options Reference

| Option                 | Description                                 | Default                  | Env Variable               |
| ---------------------- | ------------------------------------------- | ------------------------ | -------------------------- |
| `PROVIDER`             | LLM provider (openai, claude, cohere, etc.) | `openai`                 | `YAI_PROVIDER`             |
| `BASE_URL`             | API endpoint URL                            | -                        | `YAI_BASE_URL`             |
| `API_KEY`              | Your API key                                | -                        | `YAI_API_KEY`              |
| `MODEL`                | LLM model to use                            | `gpt-4o`                 | `YAI_MODEL`                |
| `DEFAULT_ROLE`         | Default role                                | `DEFAULT`                | `YAI_DEFAULT_ROLE`         |
| `SHELL_NAME`           | Shell type                                  | `auto`                   | `YAI_SHELL_NAME`           |
| `OS_NAME`              | Operating system                            | `auto`                   | `YAI_OS_NAME`              |
| `STREAM`               | Enable streaming                            | `true`                   | `YAI_STREAM`               |
| `TIMEOUT`              | API timeout (seconds)                       | `60`                     | `YAI_TIMEOUT`              |
| `EXTRA_HEADERS`        | Extra headers                               | -                        | `YAI_EXTRA_HEADERS`        |
| `EXTRA_BODY`           | Extra body                                  | -                        | `YAI_EXTRA_BODY`           |
| `REASONING_EFFORT`     | Reasoning effort                            | -                        | `YAI_REASONING_EFFORT`     |
| `INTERACTIVE_ROUND`    | Interactive mode rounds                     | `25`                     | `YAI_INTERACTIVE_ROUND`    |
| `CODE_THEME`           | Syntax highlighting theme                   | `monokai`                | `YAI_CODE_THEME`           |
| `TEMPERATURE`          | Response randomness                         | `0.7`                    | `YAI_TEMPERATURE`          |
| `TOP_P`                | Top-p sampling                              | `1.0`                    | `YAI_TOP_P`                |
| `MAX_TOKENS`           | Max response tokens                         | `1024`                   | `YAI_MAX_TOKENS`           |
| `MAX_HISTORY`          | Max history entries                         | `500`                    | `YAI_MAX_HISTORY`          |
| `AUTO_SUGGEST`         | Enable history suggestions                  | `true`                   | `YAI_AUTO_SUGGEST`         |
| `SHOW_REASONING`       | Enable reasoning display                    | `true`                   | `YAI_SHOW_REASONING`       |
| `JUSTIFY`              | Text alignment                              | `default`                | `YAI_JUSTIFY`              |
| `CHAT_HISTORY_DIR`     | Chat history directory                      | `<tempdir>/yaicli/chats` | `YAI_CHAT_HISTORY_DIR`     |
| `MAX_SAVED_CHATS`      | Max saved chats                             | `20`                     | `YAI_MAX_SAVED_CHATS`      |
| `ROLE_MODIFY_WARNING`  | Warn user when modifying role               | `true`                   | `YAI_ROLE_MODIFY_WARNING`  |
| `ENABLE_FUNCTIONS`     | Enable function calling                     | `true`                   | `YAI_ENABLE_FUNCTIONS`     |
| `SHOW_FUNCTION_OUTPUT` | Show function output when calling function  | `true`                   | `YAI_SHOW_FUNCTION_OUTPUT` |
| `ENABLE_MCP`           | Enable MCP tools                            | `false`                  | `YAI_ENABLE_MCP`           |
| `SHOW_MCP_OUTPUT`      | Show MCP output when calling mcp            | `true`                   | `YAI_SHOW_MCP_OUTPUT`      |


### LLM Provider Configuration

YAICLI works with major LLM providers. The default configuration is set up for OpenAI, but you can easily switch to
other providers.

Note: blank `BASE_URL` (or no `BASE_URL`) means use provider default url.

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

If you not sure about base_url or just use the default provider base_url, just leave it blank or delete `BASE_URL`.

```ini
[core]
PROVIDER=cohere
BASE_URL=
API_KEY=xxx
MODEL=command-r-plus
```

#### Openai

Yaicli use `openai` as provider as default provider, `gpt-4o` as default model, you can add your api key to use as it is.

```ini
PROVIDER=openai
BASE_URL=
API_KEY=
MODEL=gpt-4o
```

Extra params:

```ini
# REASONING_EFFORT: [high, midium, low]
REASONING_EFFORT=
```

See official for more details: https://platform.openai.com/docs/guides/reasoning?api-mode=chat

#### Openai Azure

```ini
PROVIDER=openai-azure
BASE_URL=
API_KEY=
MODEL=gpt-4o
```

Support config keys:

```ini
AZURE_AD_TOKEN=
AZURE_ENDPOINT=
AZURE_DEPLOYMENT=
API_VERSION=
```

Support environment variables:

```shell
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_AD_TOKEN=
AZURE_OPENAI_ENDPOINT=
```

If `API_KEY` not set in config, will look for `AZURE_OPENAI_API_KEY` environment variable.

If `AZURE_AD_TOKEN` not set in config, will look for `AZURE_OPENAI_AD_TOKEN` environment variable.

If `BASE_URL` and `AZURE_ENDPOINT` not set in config, will look for `AZURE_OPENAI_ENDPOINT` environment variable.

#### Anghropic/Claude

```ini
PROVIDER=anthropic
API_KEY=
MODEL=claude-sonnet-4-20250514
```

If you want to access **Anthropic bedrock**, you need to set `AWS_SECRET_ACCESS_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SESSION_TOKEN` and `AWS_REGION` 
in config or environment variables.

```ini
PROVIDER=anthropic-bedrock
AWS_SECRET_ACCESS_KEY=
AWS_ACCESS_KEY_ID=
AWS_SESSION_TOKEN=
AWS_REGION=
MODEL=anthropic.claude-opus-4-20250514-v1:0
```

Support `ANTHROPIC_BEDROCK_BASE_URL` env or `BASE_URL` in config file, with same effect.

Also support **Anthropic vertex** with key `PROJECT_ID` and `CLOUD_ML_REGION` in config or environment variables.

```ini
PROVIDER=anthropic-vertex
PROJECT_ID=
CLOUD_ML_REGION=
```

You can set anthropic base url by `ANTHROPIC_VERTEX_BASE_URL` env, or set `BASE_URL` in config file, same effect.

#### Deepseek

```ini
PROVIDER=deepseek
API_KEY=
MODEL=deepseek-chat
```

#### OpenRouter

```ini
PROVIDER=openrouter
API_KEY=
MODEL=deepseek/deepseek-chat-v3-0324
```

#### Mistral

```ini
PROVIDER=mistral
API_KEY=
MODEL=codestral-latest
```

#### Gemini

Basic config:

```ini
PROVIDER=gemini
API_KEY=
MODEL=gemini-2.5-flash
```

Extra params:

```ini
TOP_K=
PRESENCE_PENALTY=
FREQUENCY_PENALTY=
SEED=
THINKING_BUDGET=
API_VERSION=
BASE_URL=
```

#### Vertex AI

```ini
PROVIDER=vertexai
MODEL=gemini-2.5-flash
PROJECT=
LOCATION=
```

#### Huggingface

Default `HF_PROVIDER` is `auto`.

```ini
HF_PROVIDER=auto
PROVIDER=huggingface
API_KEY=
MODEL=deepseek-ai/DeepSeek-R1-0528
```

See official docs for `HF_PROVIDER`: https://huggingface.co/docs/inference-providers/index

#### Groq

```ini
PROVIDER=groq
API_KEY=
MODEL=llama-3.3-70b-versatile
```

#### XAI

```ini
PROVIDER=xai
API_KEY=
MODEL=grok-3
```

#### Chatglm

```ini
PROVIDER=chatglm
API_KEY=
MODEL=glm-4-plus
```

Extra params:

Check offcial docs: https://bigmodel.cn/dev/api/normal-model/glm-4

```ini
# true or false
DO_SAMPLE=
```

#### Chutes

```ini
PROVIDER=chutes
API_KEY=
MODEL=deepseek-ai/DeepSeek-V3-0324
```

#### Cerebras

```ini
PROVIDER=cerebras
API_KEY=
MODEL=llama3.3-70b
```

#### AI21

```ini
PROVIDER=ai21
API_KEY=
MODEL=jamba-large-1.6
```

#### Sambanova

```ini
PROVIDER=sambanova
API_KEY=
MODEL=DeepSeek-V3-0324
```

Only a few models support tool call as below:

- Meta-Llama-3.1-8B-Instruct
- Meta-Llama-3.1-405B-Instruct
- Meta-Llama-3.3-70B-Instruct
- Llama-4-Scout-17B-16E-Instruct
- DeepSeek-V3-0324

See official docs for more detail: https://docs.sambanova.ai/cloud/docs/capabilities/function-calling

#### ModelScope

```ini
PROVIDER=modelscope
API_KEY=
MODEL=deepseek-ai/DeepSeek-V3-0324
```

#### Inifiniai

```ini
PROVIDER=infiniai
; BASE_URL=https://cloud.infini-ai.com/maas/v1
API_KEY=
MODEL=deepseek-v3
```

#### Siliconflow

```ini
PROVIDER=siliconflow
API_KEY=
MODEL=Qwen/Qwen3-32B
```

#### Yi

```ini
PROVIDER=yi
API_KEY=
MODEL=yi-lightning
```

#### Cohere

You have to install cohere dependencies, `pip install 'yaicli[cohere]'`

```ini
PROVIDER=cohere
API_KEY=
MODEL=command-a-03-2025
```

Check official docs: https://docs.cohere.com/docs/text-gen-quickstart

Support keys:

```ini
ENVIRONMENT=
```

For private deploy and Azure api, you need to set BASE_URL.

```ini
PROVIDER=cohere
API_KEY=
MODEL=command-a-03-2025
BASE_URL=<YOUR_ENDPOINT>
```

For Bedrock and Sagemaker cohere api, you have to set below keys:

See https://docs.cohere.com/docs/text-gen-quickstart.

```ini
PROVIDER=cohere-bedrock
; PROVIDER=cohere-sagemaker
API_KEY=
MODEL=command-a-03-2025

AWS_REGION=xx
AWS_ACCESS_KEY_ID=xx
AWS_SECRET_ACCESS_KEY=xx
AWS_SESSION_TOKEN=xx
```

Note `MODEL` for Sagemaker should be endpoint name

```ini
MODEL=<YOUR_ENDPOINT_NAME>
```

#### Doubao

You have to install doubao dependencies, `pip install 'yaicli[doubao]'`

Use doubao OpenAI compatible api, you can just set `API_KEY`.

```ini
PROVIDER=doubao
API_KEY=
MODEL=doubao-1-5-lite-32k-250115
```

If you are using access key, you have to set `AK` and `SK`.

```ini
PROVIDER=doubao
MODEL=doubao-1-5-lite-32k-250115
AK=XXX
SK=XXX
```

#### Ollama

You have to install ollama dependencies, `pip install 'yaicli[ollama]'`

```ini
PROVIDER=ollama
; BASE_URL=http://localhost:11434
MODEL=qwen3:32b
```

Support options:

```ini
TEMPERATURE=
TOP_P=
SEED=
NUM_PREDICT=
NUM_CTX=
NUM_BATCH=
NUM_GPU=
MAIN_GPU=
LOW_VRAM=
F16_KV=
LOGITS_ALL=
VOCAB_ONLY=
USE_MMAP=
USE_MLOCK=
NUM_THREAD=
```

NOTE: Ollama provider not support extra body

#### Bailian

> Only support model API call, not support application API call.

```ini
PROVIDER=bailian
API_KEY=
MODEL=qwen-plus
```

#### Bailian Intl

Bailian international platform.

```ini
PROVIDER=bailian-intl
API_KEY=
MODEL=qwen-plus
```

#### Nvida nim

```ini
PROVIDER=nvida
API_KEY=
MODEL=qwen/qwen3-235b-a22b
EXTRA_BODY={"chat_template_kwargs": {"thinking": false}}
```

> `chat_template_kwargs` is for Qwen3 and ibm/granite models, you disable thinking as above config.

#### Together

Using together openai-compatible capabilities

```ini
PROVIDER=together
API_KEY=
MODEL=Qwen/Qwen3-235B-A22B-fp8-tput
```

#### Spark

```ini
PROVIDER=spark
API_KEY=
MODEL=4.0Ultra
```

Or you can use your `APP_ID` and `API_SECRET`.

```ini
PROVIDER=spark
APP_ID=
APP_SECRET=
MODEL=4.0Ultra
```


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

### MCP

Add your MCP config in `~/.config/yaicli/mcp.json` (`C:\Users\<user>\.config\yaicli\mcp.json` on Windows.).

`--enable-mcp` option is corresponds to the configuration key `ENABLE_MCP`.

Example:

```shell
ai 'What is the latest exchange rate between the BTC and the US dollar?' --enable-mcp --show-mcp-output

Assistant:

@Mcp call: bing_search({"query": "latest exchange rate between BTC and US dollar"})
╭─ Mcp output ──────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ [                                                                                                                         │
│   {                                                                                                                       │
│     "id": "result_1751024997243_0",                                                                                       │
│     "title": "BTC to USD - Bitcoin to US Dollar Conversion - Exchange Rates",                                             │
│     "link": "https://www.exchange-rates.org/converter/btc-usd",                                                           │
│     "snippet": "11 小时之前 · 1 Bitcoin = 107,304 US Dollars as of June 27, 2025 03:00 AM UTC. You can get live exchange  │
│ rates between Bitcoin and US Dollars using exchange-rates.org, which aggregates …"                                        │
│   },                                                                                                                      │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
Here are some current exchange rates for Bitcoin (BTC) to US Dollar (USD):                                                   

 1 Exchange-Rates.org:                                                                                                       
   ₿1 Bitcoin = 💵107,304 US Dollars (as of June 27, 2025, 03:00 AM UTC).                                                    
   Link                                                                                                                      
 2 BTC.CurrencyRate.Today:                                                                                                   
   Live Bitcoin to US Dollars exchange rate.                                                                                 
   Link                                                                                                                      
 3 Xe.com:                                                                                                                   
   Latest conversion rate and information about Bitcoin to US Dollars.                                                       
   Link                                                                                                                      
 4 BestExchangeRates.com:                                                                                                    
   Current BTC to USD market data, including charts and historic rates.                                                      
   Link                                                                                                                      
 5 Investing.com:                                                                                                            
   Bitcoin price analysis and live BTC to USD updates.                                                                       
   Link                                                                                                                      

For the most accurate and up-to-date rate, I recommend checking one of these sources directly.                               
```

![mcp](artwork/mcp_example.png)


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
| [json-repair](https://github.com/mangiucugna/json_repair)       | Repair llm function call arguments                 |

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
