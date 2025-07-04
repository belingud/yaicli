# Installation

## System Requirements

- Python 3.10 or higher

## Quick Install

### Using pip

```bash
# Using pip (recommended for most users)
pip install yaicli

# Using pipx (isolated environment)
pipx install yaicli

# Using uv (faster installation)
uv tool install yaicli
```

## Optional Dependencies

YAICLI has several optional dependency groups. You can use the following commands to install specific dependencies:

```bash
# Install all dependencies
pip install 'yaicli[all]'

# Install specific provider support
pip install 'yaicli[ollama,cohere,doubao,huggingface,gemini,mistral]'
```

### Using uv for dependencies

```bash
# Install all dependencies
uv tool install 'yaicli[all]'

# Install specific provider support
uv tool install 'yaicli[ollama,cohere,doubao,huggingface,gemini,mistral]'
```

## Install from Source

```bash
git clone https://github.com/belingud/yaicli.git
cd yaicli
pip install .
```

## Initial Configuration

YAICLI uses a simple configuration file to store your preferences and API keys.

### First-time Setup

1. Run `ai` once to generate the default configuration file
2. Edit `~/.config/yaicli/config.ini` to add your API key
3. Customize other settings as needed

The default configuration file is located at `~/.config/yaicli/config.ini`. You can use `ai --template` to see default settings. 