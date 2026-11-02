# Advanced Features

YAICLI includes several advanced features to enhance your interaction with AI models.

## Chat Persistent Sessions

YAICLI allows you to save and manage chat sessions:

```bash
# Start a temporary chat session
$ ai --chat

# Start a persistent chat session with a title
$ ai --chat "Python programming help"

# List saved chat sessions
$ ai --list-chats
```

### Managing Chat Sessions

In a chat session, you can use these commands:
- `/save <title>` - Save the current session with a title
- `/list` - List all saved sessions
- `/load <index>` - Load a previously saved session
- `/del <index>` - Delete a saved session

### Persisting Chat Sessions

When you start a chat with a title, the session is automatically saved to disk:

```bash
$ ai --chat "check disk usage"
Chat title: check disk usage
```

The session will be persisted to `CHAT_HISTORY_DIR` by default.

## Role Management

YAICLI supports custom roles to guide AI behavior:

```bash
# Create a new role
ai --create-role "Python Expert"

# List all roles
ai --list-roles

# Show a role
ai --show-role "Python Expert"

# Delete a role
ai --delete-role "Python Expert"

# Use a specific role
ai --role "Python Expert" "How do I use decorators?"
```

## Function Calling

YAICLI supports function calling: the model can ask YAICLI to execute a local
function/tool (for example `fs_read_file`, `web_search`, or `execute_shell_command`)
and then continue the conversation with the result.

### Installing and updating functions

Built-in function definitions ship inside the installed package, but they are **not**
used from there. They must be copied into your config directory once and re-copied
after upgrades.

| Action | Command | Effect |
| --- | --- | --- |
| First-time install | `ai --install-functions` | Copies every built-in definition into `~/.config/yaicli/functions/`. Files that already exist are skipped. |
| List installed functions | `ai --list-functions` | Prints the function files currently loaded by YAICLI. |
| Update after an upgrade | `ai --reinstall-functions` | Overwrites the files whose names match the current built-ins with the definitions from the new version. Custom files (different file names) are preserved. |

Paths on Windows: `C:\Users\<user>\.config\yaicli\functions` (the non-Windows path is
`~/.config/yaicli/functions/`).

**After every `pip install -U yaicli`, `uv tool upgrade yaicli`, or other package-manager
upgrade, run `ai --reinstall-functions`.** Built-in schemas do change between releases —
for example `fs_read_file` and `fs_read_image` now take lists, and `fs_edit_file` validates
its operations — and the copy in your config directory is what the model actually sees.
`ai --install-functions` will *not* refresh files that already exist.

### Writing custom functions

Add a Python file to `~/.config/yaicli/functions/` (files starting with `_` are ignored).
It must define a class named `Function` that subclasses `yaicli.function_schema.OpenAISchema`
and a classmethod `execute`. The tool name is the pydantic model title (`class Config: title`).
Pydantic fields become the tool parameters; use `Field(description=...)` (and a class
docstring) so the model knows how to call it. Example:

```python
from pydantic import Field

from yaicli.function_schema import OpenAISchema


class Function(OpenAISchema):
    """Add two integers and return the result."""

    a: int = Field(..., description="First integer")
    b: int = Field(..., description="Second integer")

    class Config:
        title = "add_numbers"

    @classmethod
    def execute(cls, a: int, b: int) -> str:
        return str(a + b)
```

Restart `ai` after adding or changing a custom function; the loader executes every
`*.py` file in that directory at startup. `ai --reinstall-functions` never deletes custom
files, and `ai --install-functions` only adds built-in files that are missing.

### Enabling and controlling function calls

- Function calling is enabled by default (`ENABLE_FUNCTIONS=true`). Toggle it per run with
  `--enable-functions` / `--disable-functions`, or set `ENABLE_FUNCTIONS=false` in the config file.
- Function output is displayed by default; use `--hide-function-output` or set
  `SHOW_FUNCTION_OUTPUT=false` to hide it.
- Every call asks for confirmation by default (`TOOL_CONFIRM=true`); see
  [Tool Execution Confirmation](#tool-execution-confirmation) below for the four choices.
- `MAX_TOOL_CALL_DEPTH` (default `8`) bounds recursive tool-call rounds in one request.

### Reading Multiple Files in One Call

The built-in `fs_read_file` function accepts a list of file paths, so several
files can be read with a single tool call instead of one call per file:

```json
{"file_paths": ["src/main.py", "src/config.py"], "encoding": "utf-8"}
```

A single path string is still accepted for backward compatibility. The list contract is a
built-in schema change: run `ai --reinstall-functions` after upgrading to pick it up.

### Reading Multiple Images in One Call

The built-in `fs_read_image` function follows the same list-based contract, so several
images can be read and base64-encoded in one tool call:

```json
{"image_paths": ["artwork/before.png", "artwork/after.png"]}
```

A single path string is still accepted for backward compatibility. The same
`ai --reinstall-functions` rule applies after upgrading.

## MCP (Machine Comprehension Protocol)

MCP allows AI models to use external tools:

```bash
# Enable MCP in queries
ai 'What is the latest exchange rate between BTC and USD?' --enable-mcp
```

Configure MCP tools in `~/.config/yaicli/mcp.json`.

## Image Input (Vision)

YAICLI supports sending images to vision-capable models (GPT-5.2, Claude 3, Gemini, Llama 3.2 Vision, etc.) using the `--image` / `-i` option.

### Local Images

Pass a local image file path. The image will be validated and base64-encoded before sending:

```bash
ai --image photo.jpg "What is in this image?"
ai -i screenshot.png "Describe the UI layout"
```

Supported formats: JPEG (`.jpg`, `.jpeg`), PNG (`.png`), GIF (`.gif`), WebP (`.webp`).

### URL Images

Pass an image URL to send it directly to the provider:

```bash
ai --image https://example.com/diagram.png "Explain this architecture"
```

### Multiple Images

Use `-i` multiple times to send multiple images in one request:

```bash
ai -i before.png -i after.png "What changed between these two screenshots?"
```

### Image-Only Invocation

You can send an image without a text prompt:

```bash
ai --image photo.jpg
```

When no text prompt is given, YAICLI sends a minimal prompt (`Describe the image.`,
or `Describe these images.` for multiple images) so providers always receive a
valid user message.

### Provider Compatibility

Image input is automatically formatted for each provider family:

| Provider Family | Providers | Image Format |
|----------------|-----------|--------------|
| OpenAI-compatible | OpenAI, DeepSeek, Groq, Mistral, OpenRouter, etc. (~25) | `content` array with `image_url` blocks |
| Anthropic | Anthropic, Anthropic Bedrock, Anthropic Vertex | `content` array with `image` + `source` blocks |
| Gemini | Gemini, Vertex AI | `Part.from_bytes()` / `Part.from_uri()` |
| Ollama | Ollama | Separate `images` array (base64 only) |

Providers without vision support (Cohere, HuggingFace, ChatGLM, ModelScope) will show a warning and send text-only messages.

### Limitations

- Image input is supported in **single-shot mode only**, not in interactive `--chat` mode
- No client-side file size limit; the provider API enforces its own limits
- Ollama may not support URL images; use local files instead
- No automatic image resizing or optimization

## Custom Configuration

### LLM Provider Configuration

YAICLI works with many LLM providers. Configure your preferred provider in the config file:

```ini
[core]
PROVIDER=openai  # or cohere, gemini, ollama, etc.
BASE_URL=        # leave empty for default provider URL
API_KEY=your_api_key_here
MODEL=gpt-5.2
```

### Syntax Highlighting Themes

Change the code highlighting theme:

```ini
CODE_THEME = monokai
```

Browse available themes at: https://pygments.org/styles/

![monokia theme example](../assets/artwork/monokia.png)

### Extra Headers and Body Parameters

Add custom parameters to API requests:

```ini
EXTRA_HEADERS={"X-Extra-Header": "value"}
EXTRA_BODY={"extra_key": "extra_value"}
```

Example for Qwen3's thinking behavior:

```ini
EXTRA_BODY={"enable_thinking": false}
# Or limit thinking tokens:
EXTRA_BODY={"thinking_budget": 4096}
```
