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

YAICLI offers several optional dependency groups that you can install based on your needs:

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
ai --help
```

This should display the help information for YAICLI.

## First-Time Setup

After installation, run the tool once to generate the default configuration file:

```bash
ai
```

Then edit the configuration file located at `~/.config/yaicli/config.ini` to add your API key and customize settings:

```bash
# Open with your preferred editor
nano ~/.config/yaicli/config.ini
```

## Next Steps

- Learn how to [get started](getting-started.md) with YAICLI
- Explore [configuration options](usage/configuration.md)
- Check out [available providers](providers/overview.md)
