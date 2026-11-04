# Frequently Asked Questions

This page addresses common questions and issues encountered when using YAICLI.

## General Questions

### What is YAICLI?

YAICLI is a lightweight agent that runs in your terminal. Given a task, it can plan, call its built-in tools (read/write files, search the web, run shell commands), read the results and continue until the task is done. It also works as a classic chat/quick-answer CLI and supports 30+ LLM providers.

### What LLM providers are supported?

YAICLI supports multiple providers including:
- OpenAI (GPT-5.1, GPT-5.2, etc.)
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

You can set your API key in two ways:
1. In the config file (`config.ini` inside the config directory — `~/.config/yaicli` by default,
   or `$YAI_CONFIG_DIR` / `$XDG_CONFIG_HOME/yaicli` when set)
2. As an environment variable (`export YAI_API_KEY="your-key"`) — preferred for scripts and
   shared machines

YAICLI does not load `.env` files; use one of the options above (a `.env` file has no effect).

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

For scripts, use `--output-format json` (single JSON object), `--output-format stream-json`
(NDJSON events) or `-q/--quiet` (answer only). See [Headless & Scripting](usage/headless.md).

### How do I disable streaming responses?

Use the `--no-stream` flag or set `STREAM=false` in your config:
```bash
ai --no-stream "What is the capital of France?"
```

### How do I change the code highlighting theme?

Set the `CODE_THEME` in your config file:
```ini
CODE_THEME = monokai
```

Use any other Pygments theme name here (comments must be on their own line).

### How do I execute shell commands safely?

Use shell mode with the `-s` or `--shell` flag:
```bash
ai -s "Find all PNG files in the current directory"
```
You'll be prompted to review and optionally edit commands before execution.

When the model runs `execute_shell_command` as a tool, the approval prompt, danger classification,
timeout and filtered environment apply automatically; see [Permissions & Safety](usage/permissions.md).

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

The built-in tools load directly from the installed package in v0.19+, so a normal upgrade needs
no extra step. If you previously exported function files with `ai --install-functions`, refresh
them with `ai --reinstall-functions` (custom files are kept). See
[Upgrade Notes](advanced/upgrade.md) for behaviour changes and new config keys.

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

Function calling is enabled by default and the 12 built-in tools load directly from the package —
there is no setup step:
```bash
ai "check the weather in New York"
ai --list-functions   # show the loaded tools (builtin/user)
```

If you need editable copies of the built-in definitions, export them with
`ai --install-functions`; a copy overrides the built-in with the same tool name. Every tool call is
confirmed by default; see [Permissions & Safety](usage/permissions.md).

### How do I create custom functions?

Add your function definitions to `~/.config/yaicli/functions/`; each file must define a
`Function(OpenAISchema)` class with a classmethod `execute`. Restart `ai` afterwards.

If you recently upgraded YAICLI and keep exported copies of the built-in definitions, run
`ai --reinstall-functions` so those copies match the new version (custom files are preserved).

See [Advanced Usage — Function Calling](usage/advanced.md#function-calling) for the complete
custom-function guide.

### How do I use MCP (Model Context Protocol)?

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
