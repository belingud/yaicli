# Tool Integration

YAICLI supports tool integration through Function Call and MCP (Machine Comprehension Protocol).

## Function Calling

Function calling allows LLM models to call functions to accomplish tasks.

### Built-in Functions

YAICLI comes with several built-in functions:

```bash
# Install default functions
ai --install-functions

# List available functions
ai --list-functions
```

The default functions include:

- `execute_shell_command`: Execute shell commands safely
- `fetch_webpage`: Retrieve content from a webpage
- `get_weather`: Get weather information for a location

### Custom Functions

You can create custom functions by adding Python files to the `~/.config/yaicli/functions/` directory.

Here's an example of a custom function:


```python
# TODO: add a sample
```

### Using Function Calling

To enable function calling in a query:

```bash
ai 'check the current dir total size' --enable-functions
```

Example output:

```
Assistant:
Thinking:

▌ Okay, the user wants to check the current directory's total size. Hmm, how do I do that in macOS with zsh?
▌ I remember that the command to get disk usage is usually 'du'. But wait, the default 'du' might not give the total size of the
▌ current directory directly. Let me think. Oh right, if I use 'du -sh' with the current directory, that should give the total size
▌ in human-readable format.
▌ Wait, but sometimes the -s option summarizes the directory. So 'du -sh .' would calculate the total size of the current directory
▌ and its subdirectories. That should work. Let me confirm the syntax. Yeah, 'du -sh .' is the right command here.

@Function call: execute_shell_command({"shell_command": "du -sh ."})
╭─ Function output ─────╮
│ Exit code: 0, Output: │
│ 156M    .             │
│                       │
╰───────────────────────╯

Current directory size: 156M (using du -sh .).
```

## MCP (Machine Comprehension Protocol)

MCP is a protocol that allows AI models to use external tools, similar to function calling but with a standardized interface.

### Configuring MCP

Configure your MCP tools in `~/.config/yaicli/mcp.json`.

### Using MCP

To enable MCP in a query:

```bash
ai 'What is the latest exchange rate between BTC and USD?' --enable-mcp
```

Example output:

```
@Mcp call: bing_search({"query": "latest exchange rate between BTC and US dollar"})
╭─ Mcp output ──────────────────────────────────────────────────────────────────────╮
│ [                                                                                 │
│   {                                                                               │
│     "id": "result_1751024997243_0",                                               │
│     "title": "BTC to USD - Bitcoin to US Dollar Conversion - Exchange Rates",     │
│     "link": "https://www.exchange-rates.org/converter/btc-usd",                   │
│     "snippet": "11 小时之前 · 1 Bitcoin = 107,304 US Dollars as of June 27..."   │
│   },                                                                              │
│   ...                                                                             │
│ ]                                                                                 │
╰─────────────────────────────────────────────────────────────────────────────────────

Here are some current exchange rates for Bitcoin (BTC) to US Dollar (USD):

 1 Exchange-Rates.org:
   ₿1 Bitcoin = 💵107,304 US Dollars (as of June 27, 2025, 03:00 AM UTC).
   Link
```

## Configuring Tools

### Enabling Tools

You can enable tools globally in your config file:

```ini
# Function settings
ENABLE_FUNCTIONS=true
SHOW_FUNCTION_OUTPUT=true

# MCP settings
ENABLE_MCP=false
SHOW_MCP_OUTPUT=false
```

Or enable them per query:

```bash
ai "Check weather in San Francisco" --enable-functions
ai "Latest news about AI" --enable-mcp
``` 