## ADDED Requirements

### Requirement: ChatMessage carries image data
The `ChatMessage` dataclass SHALL include an `images` field of type `List[ImageData]`, defaulting to an empty list. Existing code that does not use images MUST continue to work without modification.

#### Scenario: Text-only message unchanged
- **WHEN** a `ChatMessage` is created with only `role` and `content`
- **THEN** `images` SHALL default to an empty list and all existing behavior is preserved

#### Scenario: Message with images
- **WHEN** a `ChatMessage` is created with `images=[ImageData(...)]`
- **THEN** the images SHALL be accessible via `msg.images` alongside `msg.content`

### Requirement: Images attach to user message only
When images are provided via CLI, the system SHALL attach all `ImageData` objects to the user's `ChatMessage` in `_build_messages()`. Images MUST NOT be attached to system or assistant messages.

#### Scenario: Single-shot with images
- **WHEN** user runs `ai --image photo.jpg "What is this?"`
- **THEN** the user message in the message list SHALL contain `images=[ImageData(...)]` and `content="What is this?"`

#### Scenario: System message has no images
- **WHEN** messages are built with image input
- **THEN** the system role message SHALL have an empty `images` list

### Requirement: OpenAI-compatible providers format images as content array
For providers using OpenAI-compatible format (base `_convert_messages`), when a message has images, the `content` field SHALL be converted from a string to an array of content blocks: one `{type: "text", text: "..."}` block for the text, plus one `{type: "image_url", image_url: {url: "..."}}` block per image.

#### Scenario: Base64 image in OpenAI format
- **WHEN** a message has an `ImageData` with `is_url=False`, `data="abc123"`, `media_type="image/jpeg"`
- **THEN** the converted message SHALL contain `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc123"}}`

#### Scenario: URL image in OpenAI format
- **WHEN** a message has an `ImageData` with `is_url=True`, `data="https://example.com/img.jpg"`
- **THEN** the converted message SHALL contain `{"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}}`

#### Scenario: Text-only message unchanged in OpenAI format
- **WHEN** a message has no images
- **THEN** `content` SHALL remain a plain string (not converted to array)

#### Scenario: Multiple images in OpenAI format
- **WHEN** a message has 2 images
- **THEN** the content array SHALL contain the text block plus 2 image_url blocks

### Requirement: Anthropic providers format images as content blocks
For Anthropic-family providers, when a message has images, the `content` field SHALL be an array with `{type: "image", source: {...}}` blocks followed by a `{type: "text", text: "..."}` block.

#### Scenario: Base64 image in Anthropic format
- **WHEN** a message has an `ImageData` with `is_url=False`, `data="abc123"`, `media_type="image/png"`
- **THEN** the converted message SHALL contain `{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc123"}}`

#### Scenario: URL image in Anthropic format
- **WHEN** a message has an `ImageData` with `is_url=True`, `data="https://example.com/img.jpg"`
- **THEN** the converted message SHALL contain `{"type": "image", "source": {"type": "url", "url": "https://example.com/img.jpg"}}`

#### Scenario: Images placed before text in Anthropic format
- **WHEN** a message has images and text content
- **THEN** image blocks SHALL appear before the text block in the content array

### Requirement: Gemini providers format images as Part objects
For Gemini-family providers, when a message has images, the content SHALL include `types.Part.from_bytes(data=<decoded_bytes>, mime_type=<media_type>)` objects alongside text parts.

#### Scenario: Base64 image in Gemini format
- **WHEN** a message has an `ImageData` with `is_url=False`, `data="abc123"`, `media_type="image/jpeg"`
- **THEN** the system SHALL decode the base64 data to bytes and create `types.Part.from_bytes(data=decoded_bytes, mime_type="image/jpeg")`

#### Scenario: URL image in Gemini format
- **WHEN** a message has an `ImageData` with `is_url=True`, `data="https://example.com/img.jpg"`
- **THEN** the system SHALL create `types.Part.from_uri(file_uri=url, mime_type=media_type)`

### Requirement: Ollama provider formats images as separate array
For the Ollama provider, when a message has images, the converted message dict SHALL include an `images` key containing a list of base64 strings. The `content` field SHALL remain a plain string.

#### Scenario: Base64 image in Ollama format
- **WHEN** a message has an `ImageData` with `is_url=False`, `data="abc123"`
- **THEN** the converted message SHALL include `"images": ["abc123"]` alongside `"content": "text"`

#### Scenario: URL image in Ollama format
- **WHEN** a message has an `ImageData` with `is_url=True`
- **THEN** the URL SHALL be included in the `images` array as-is (Ollama may or may not support it; no client-side fetch in v1)

#### Scenario: Multiple images in Ollama format
- **WHEN** a message has 2 images with base64 data
- **THEN** the `images` array SHALL contain both base64 strings

### Requirement: Graceful degradation for non-vision providers
When images are provided but the active provider is known to lack vision support, the system SHALL print a warning and send the text-only message with images stripped.

#### Scenario: Cohere with image
- **WHEN** user provides an image and the provider is `cohere`
- **THEN** the system SHALL print a warning to console and send the message without images

#### Scenario: Vision-capable provider with image
- **WHEN** user provides an image and the provider is `openai`
- **THEN** the system SHALL include the images in the message without warning
