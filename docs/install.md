# Installation Guide

YAICLI can be installed using several methods. Choose the one that best suits your needs.

## Prerequisites

- Python 3.10 or higher

## Installation Methods

### Using pip (Recommended)

The simplest way to install YAICLI is using pip:

```bash
pip install yaicli
```

### Using pipx (Isolated Environment)

If you prefer to install the tool in an isolated environment:

```bash
pipx install yaicli
```

### Using uv (Faster Installation)

For faster installation with the uv package manager:

```bash
uv tool install yaicli
```

## Installing with Optional Dependencies

A plain `pip install yaicli` is **tools-complete**: every builtin tool (including `web_search`,
`fetch_webpage` extraction and filesystem/shell tools) and MCP work without extras. Optional groups
only add provider SDKs:

| Extra | What it adds |
| --- | --- |
| `all` | every optional provider SDK (including `anthropic[bedrock,vertex]`) |
| `bedrock` | Anthropic on AWS Bedrock (`anthropic[bedrock]`) |
| `vertex` | Anthropic on Google Vertex AI (`anthropic[vertex]`) |
| `ollama`, `cohere`, `doubao`, `huggingface`, `gemini`, `mistral`, `cerebras`, `fireworks` | that provider's SDK |

### All Dependencies

```bash
# Using pip
pip install 'yaicli[all]'

# Using uv
uv tool install 'yaicli[all]'
```

### Specific Provider Support

```bash
# Using pip
pip install 'yaicli[ollama,cohere,doubao,huggingface,gemini,mistral]'

# Using uv
uv tool install 'yaicli[ollama,cohere,doubao,huggingface,gemini,mistral]'
```

### Anthropic on Bedrock / Vertex

```bash
pip install 'yaicli[bedrock]'   # AWS Bedrock
pip install 'yaicli[vertex]'    # Google Vertex AI
```

## Installing from Source

For the latest development version:

```bash
git clone https://github.com/belingud/yaicli.git
cd yaicli
pip install .
```

## Verifying Installation

To verify that YAICLI was installed correctly:

```bash
ai --version            # fast path: prints the version, no config writes
ai --help               # full command reference
ai --list-functions     # should list 12 builtin tools (they work out of the box)
ai --list-providers     # should list the provider keys
```

`python -m yaicli --version` works as well if the `ai` script is not on your `PATH`.

## First-Time Setup

After installation, run a real command once (for example `ai "hi"`); the default configuration file
is created on first use:

```bash
ai "hi"
```

Then edit the configuration file to add your API key and customize settings. The config directory
is resolved in this order: `YAI_CONFIG_DIR` → `XDG_CONFIG_HOME/yaicli` → `%APPDATA%/yaicli`
(Windows) → `~/.config/yaicli`. The file is created with mode `0600` because it may contain an API
key; alternatively export the key and skip editing the file (plain `ai` with no prompt only prints
help and does not create state):

```bash
export YAI_API_KEY="sk-..."
```

```bash
# Open the config with your preferred editor (default path on Linux/macOS)
nano ~/.config/yaicli/config.ini
```

## Upgrading

Upgrade the package the same way you installed it:

```bash
pip install -U yaicli        # pip
pipx upgrade yaicli          # pipx
uv tool upgrade yaicli       # uv
```

### Do I need `--reinstall-functions`?

**Not for a normal upgrade.** Since v0.19 the built-in tool definitions load directly from the
installed package, so new versions take effect immediately.

You only need to refresh function files if you previously **exported copies** into the functions
directory (`ai --install-functions`) or edited a built-in tool:

```bash
ai --reinstall-functions    # refresh exported built-in copies (custom files are kept)
ai --list-functions         # verify sources and stale-copy warnings
```

A user function file with the same tool name as a built-in wins over the built-in. If a stale copy
is detected, YAICLI prints a one-line warning but keeps working.

See [Upgrade Notes](advanced/upgrade.md) for the complete v0.19 change list (new config keys,
environment filtering for shell tools, output truncation, permissions v2, headless flags, state
paths) and rollback instructions.

## Next Steps

- Learn how to [get started](getting-started.md) with the 3-step agent quick start
- Explore [configuration options](usage/configuration.md)
- Check out [available providers](providers/overview.md)
- Read the [page for headless and CI usage](usage/headless.md)
