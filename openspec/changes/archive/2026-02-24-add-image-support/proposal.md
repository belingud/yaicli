## Why

YAICLI is text-only today. Users cannot send images to vision-capable models (GPT-4V, Claude 3, Gemini, Llama 3.2 Vision, etc.) from the CLI. Most major LLM providers now support multimodal input, and CLI users need a way to leverage this without switching to a web UI.

## What Changes

- Add `--image` / `-i` CLI option that accepts a local file path or a URL
- Validate local images (existence, supported format, size) and encode to base64
- Pass URL images directly to providers that support them
- Extend internal `ChatMessage` schema with an `images` field to carry image data alongside text
- Update provider message conversion (`_convert_messages`) for 4 provider families to format images correctly for their APIs:
  - **OpenAI family** (~25 providers): `content` array with `image_url` blocks
  - **Anthropic family** (3 providers): `content` array with `image` + `source` blocks
  - **Gemini family** (2 providers): `types.Part.from_bytes()` in contents
  - **Ollama** (1 provider): separate `images` array on message dict
- Allow `--image` to be specified multiple times for multi-image input
- Providers without vision support receive text-only messages (images silently stripped with a warning)

## Capabilities

### New Capabilities

- `image-input`: Handles CLI image argument parsing, validation (format, size, existence), base64 encoding of local files, and URL detection. Defines supported formats (JPEG, PNG, GIF, WebP) and size limits.
- `image-message`: Extends internal message schema to carry image data and defines how each provider family converts image-bearing messages into their API-specific format.

### Modified Capabilities

(none -- no existing specs)

## Impact

- **CLI layer** (`entry.py`): New `--image/-i` option added to the Typer command
- **Schema layer** (`schemas.py`): `ChatMessage` dataclass gains an `images` field; new `ImageData` dataclass
- **Orchestration** (`cli.py`): `_build_messages()` must attach image data to the user message
- **Provider base** (`llms/provider.py`): Base `_convert_messages()` updated for OpenAI image format
- **Provider overrides**: `anthropic_provider.py`, `gemini_provider.py`, `ollama_provider.py` each need image handling in their `_convert_messages()`
- **New utility module**: Image validation and base64 encoding logic (e.g., `yaicli/utils.py` or a new `yaicli/image.py`)
- **Dependencies**: No new external dependencies required (base64, mimetypes, pathlib are stdlib)
- **Tests**: New test cases for image validation, encoding, and per-provider message conversion
