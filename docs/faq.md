# Frequently Asked Questions

This page addresses common questions and issues encountered when using YAICLI.

## General Questions

### What is YAICLI?

YAICLI is a command-line interface for interacting with Large Language Models (LLMs). It allows you to chat with AI assistants, generate shell commands, and get quick answers directly from your terminal.

### What LLM providers are supported?

YAICLI supports multiple providers including:
- OpenAI (GPT-4o, GPT-3.5, etc.)
- Google Gemini
- Claude (Anthropic)
- Cohere
- Mistral
- Ollama
- Many others (see [Providers Overview](providers/overview.md))

### Is an internet connection required?

Yes, for most providers. YAICLI communicates with LLM APIs that require internet access. However, you can use local models with providers like Ollama.

### How is my data handled?

YAICLI stores your conversation history locally. Your prompts and API responses are sent to the LLM provider you configure, according to their privacy policies. No data is sent to YAICLI developers.

## Installation & Setup

### Why am I getting "command not found" after installing?

Make sure your Python scripts directory is in your PATH. Try these solutions:

```bash
# Option 1: Find the installation location
which ai

# Option 2: Add to PATH (add to .bashrc or .zshrc)
export PATH="$HOME/.local/bin:$PATH"
```

### How do I set up my API key?

You can set your API key in three ways:
1. In the config file (`~/.config/yaicli/config.ini`)
2. As an environment variable (`export YAI_API_KEY="your-key"`)
3. Using a .env file in your project directory

### Can I use multiple API keys for different providers?

Yes! You can create separate configuration sections or switch providers using environment variables:

```bash
# Use OpenAI
export YAI_PROVIDER=openai
export YAI_API_KEY=sk-...

# Use Gemini (in another session or after changing vars)
export YAI_PROVIDER=gemini
export YAI_API_KEY=AI...
```

## Usage Questions

### How do I save a chat session?

In chat mode, use the `/save` command followed by a title:
```
💬 > /save "Python Tips"
```

Or start a named session that will be automatically saved:
```bash
ai --chat "Python Tips"
```

### How do I control output formatting?

Use the `--justify` option to control text alignment:
```bash
ai --justify center "Write a poem about AI"
```

Options include: `default`, `left`, `center`, `right`, and `full`.

### How do I disable streaming responses?

Use the `--no-stream` flag or set `STREAM=false` in your config:
```bash
ai --no-stream "What is the capital of France?"
```

### How do I change the code highlighting theme?

Set the `CODE_THEME` in your config file:
```ini
CODE_THEME = monokai  # or any other Pygments theme
```

### How do I execute shell commands safely?

Use shell mode with the `-s` or `--shell` flag:
```bash
ai -s "Find all PNG files in the current directory"
```
You'll be prompted to review and optionally edit commands before execution.

## Troubleshooting

### Why am I getting API errors?

Common causes:
- Invalid API key
- Rate limits or quota exceeded
- Network connectivity issues
- Incompatible model for your provider

Usually you will see a error message in output like `429 too many requests`.

Try running with the verbose flag to see detailed error information:
```bash
ai --verbose "Test query"
```

### How do I fix "SSL Certificate Verification Failed"?

This typically happens in corporate environments with SSL inspection. Try:

```bash
# Not recommended for security reasons, but may be necessary
export PYTHONWARNINGS="ignore:Unverified HTTPS request"
export REQUESTS_CA_BUNDLE=/path/to/corporate/certificate.pem
```

### How do I update YAICLI?

```bash
# Using pip
pip install --upgrade yaicli

# Using pipx
pipx upgrade yaicli

# Using uv
uv tool upgrade yaicli
```

### Why are my non-ASCII characters displaying incorrectly?

Make sure your terminal supports UTF-8 and has a compatible font. On Windows, you might need to:
```
chcp 65001  # Set console code page to UTF-8
```

## Advanced Questions

### How do I create custom roles?

Create a new role:
```bash
ai --create-role "SQL Expert"
```

Then use it:
```bash
ai --role "SQL Expert" "Optimize this query"
```

### Can I use function calling?

Yes, enable function calling with:
```bash
ai --enable-functions "Check the weather in New York"
```

Install default functions:
```bash
ai --install-functions
```

### How do I create custom functions?

Add your function definitions to:
```
~/.config/yaicli/functions/
```

See the [Usage Configuration Guide](usage/configuration.md#function-settings) for details on function configuration.

### How do I use MCP (Multi-provider Chain Protocol)?

Enable MCP with:
```bash
ai --enable-mcp "Search for the latest AI research papers"
```

Configure MCP in:
```
~/.config/yaicli/mcp.json
```

## Contributing

### How can I contribute to YAICLI?

We welcome contributions! See the [contributing guidelines](contributing.md) for details on:
- Reporting bugs
- Suggesting features
- Submitting pull requests
- Code standards

### Where can I report bugs or request features?

Please submit issues on the [GitHub repository](https://github.com/belingud/yaicli/issues).
