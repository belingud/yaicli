# Getting Started with YAICLI

YAICLI is a powerful yet lightweight command-line AI assistant that brings the capabilities of Large Language Models (LLMs) like GPT-4o directly to your terminal. This guide will help you get up and running quickly.

## Quick Start

After [installation](install.md), you can start using YAICLI immediately:

```bash
# Get a quick answer
ai "What is the capital of France?"

# Start an interactive chat session
ai --chat

# Generate and execute shell commands
ai --shell "Create a backup of my Documents folder"

# Generate code snippets (default is Python)
ai --code "Write a function to sort a list"
```

## First-time Setup

1. Run `ai` once to generate the default configuration file
2. Edit `~/.config/yaicli/config.ini` to add your API key
3. Customize other settings as needed

## Configuration

YAICLI uses a layered configuration approach:
- Environment variables (highest priority)
- Config file (`~/.config/yaicli/config.ini`)
- Sensible defaults (lowest priority)

You can view the default configuration template with:

```bash
ai --template
```

## Basic Usage Patterns

### Direct Queries

Get quick answers without entering interactive mode:

```bash
ai "What is quantum computing?"
```

### Interactive Chat Mode

Start a persistent conversation with context tracking:

```bash
ai --chat "Python programming"
```

### Command Generation

Get AI to generate and optionally execute shell commands:

```bash
ai --shell "Find all large files in my home directory"
```

### Code Generation

Generate code snippets with syntax highlighting:

```bash
ai --code "Create a web scraper for news headlines"
```

## Next Steps

- Explore [detailed usage documentation](usage/commands.md)
- Learn about [configuration options](usage/configuration.md)
- Check out available [LLM providers](providers/overview.md)
- Discover [advanced features](advanced/prompts.md)
