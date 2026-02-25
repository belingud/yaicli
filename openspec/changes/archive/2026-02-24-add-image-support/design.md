## Context

YAICLI supports 35+ LLM providers through a layered architecture: `entry.py` (Typer CLI) → `cli.py` (orchestrator) → `LLMClient` → `Provider`. All providers implement a `Provider` ABC with a `_convert_messages()` method that transforms internal `ChatMessage` objects into API-specific dicts.

Currently, `ChatMessage.content` is `Optional[str]` — plain text only. There is no mechanism to carry binary or multimodal data through the message pipeline.

Providers fall into 4 families with distinct image API formats:
- **OpenAI-compatible** (~25 providers): content becomes an array of `{type: "text"}` and `{type: "image_url"}` blocks
- **Anthropic** (3 providers): content becomes an array of `{type: "text"}` and `{type: "image", source: {...}}` blocks
- **Gemini** (2 providers): uses `types.Part.from_bytes()` Python objects in a contents list
- **Ollama** (1 provider): keeps `content` as string, adds a separate `images` array of base64 strings on the message dict

Remaining providers (Cohere, HuggingFace, ChatGLM, ModelScope) have limited or no vision API support.

## Goals / Non-Goals

**Goals:**
- Users can pass one or more images via `--image/-i` (local path or URL) in single-shot mode
- Local images are validated and base64-encoded; URLs are passed through
- Each provider family formats images correctly for its API
- Providers without vision support gracefully degrade (warning + text-only)
- No new external dependencies

**Non-Goals:**
- Image support in interactive `--chat` mode (future enhancement, possibly via `@image` syntax)
- Image generation or editing
- Automatic image resizing or optimization
- Provider-level capability detection (e.g., querying which models support vision)
- Streaming image uploads or Files API integration

## Decisions

### D1: Add `images` field to `ChatMessage` rather than making `content` a union type

**Choice**: Add a new `images: List[ImageData]` field to `ChatMessage`.

**Alternative considered**: Change `content` from `Optional[str]` to `Optional[Union[str, List[ContentBlock]]]`. This would be more "correct" per the OpenAI content-block model, but would require updating every place that reads `msg.content` across the entire codebase (providers, client, printer, history, tests).

**Rationale**: The `images` field is additive — no existing code breaks. Each provider's `_convert_messages()` checks for `msg.images` and formats accordingly. This also matches Ollama's native API shape (separate `images` array). The cost is a slight impedance mismatch with OpenAI/Anthropic's content-block format, but that's handled entirely within `_convert_messages()`.

### D2: `ImageData` dataclass carries pre-processed data

```
@dataclass
class ImageData:
    data: str           # base64 string (local) or URL string (remote)
    media_type: str     # MIME type: "image/jpeg", "image/png", etc.
    is_url: bool        # True → data is a URL; False → data is base64
```

All processing (file reading, base64 encoding, MIME detection) happens at the CLI entry point before the message enters the pipeline. Providers receive ready-to-use data and only need to format it.

### D3: Image processing at CLI boundary, not in providers

**Choice**: Validate and encode images in `entry.py` (or a utility called from there), before `CLI.__init__`.

**Rationale**: Keeps providers simple — they receive `ImageData` and just format it. Validation errors (file not found, unsupported format) surface immediately with clear CLI error messages. No provider needs to know about file I/O.

### D4: OpenAI-compatible base handles most providers

**Choice**: Update the base `Provider._convert_messages()` to handle images in OpenAI format. Only Anthropic, Gemini, and Ollama override this behavior.

**Rationale**: ~25 of 35 providers inherit the base OpenAI-format conversion. Handling images there gives automatic support to all OpenAI-compatible providers. The 3 non-OpenAI families (Anthropic, Gemini, Ollama) each have their own `_convert_messages()` already and will add image handling in their overrides.

### D5: URL images use provider-native URL support where available

**Choice**: For URL images, pass the URL directly to providers that support URL-based image input (OpenAI, Anthropic, Mistral, Groq). For providers that only accept base64 (Ollama native API), the URL case requires fetching and encoding at the CLI layer.

**Update**: For simplicity in v1, URL images are always passed as-is. If a provider doesn't support URLs, the API will return an error. Users can work around this by downloading the image locally first. Fetching URLs at the CLI layer can be added later.

### D6: `--image` is repeatable, images attach to the user message only

**Choice**: `--image` can be specified multiple times. All images attach to the single user message in the conversation.

**Rationale**: Multi-image is useful for comparison tasks ("compare these two screenshots"). Images always belong to the user turn — no need to support images on system or assistant messages.

### D7: Graceful degradation for non-vision providers

**Choice**: When images are provided but the provider has no known vision support, print a warning via `console.print()` and send the text-only message (strip images).

**Implementation**: A simple set of provider keys known to lack vision support. This is a soft check — we don't prevent the call, just warn. The set can be maintained as a constant.

## Risks / Trade-offs

**[Large images inflate request size]** → Base64 encoding increases data by ~33%. A 5MB image becomes ~6.7MB in the request. No mitigation in v1; users should manage image sizes. Future: optional resize.

**[URL images may not work with all providers]** → Ollama's native API only accepts base64. Sending a URL will fail. → Mitigation: Document which providers support URL vs base64. Future: auto-fetch URLs when needed.

**[No capability detection]** → We don't know at runtime if the user's chosen model supports vision. → Mitigation: Let the API error propagate with a clear message. This avoids maintaining a model-capability database.

**[Chat mode unsupported in v1]** → Users in `--chat` mode cannot send images mid-conversation. → Mitigation: Document as known limitation. The `@image` syntax for chat mode is a natural follow-up.

## Open Questions

- Should there be a file size limit enforced client-side (e.g., 20MB) to prevent accidental huge uploads, or let the API enforce its own limits?
- For Ollama with URL images: should v1 auto-fetch and encode, or just let it error and document the limitation?
