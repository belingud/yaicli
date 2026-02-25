## 1. Schema & Data Model

- [x] 1.1 Add `ImageData` dataclass to `yaicli/schemas.py` with fields: `data` (str), `media_type` (str), `is_url` (bool)
- [x] 1.2 Add `images: List[ImageData]` field to `ChatMessage` dataclass with default empty list

## 2. Image Processing Utility

- [x] 2.1 Create `yaicli/image.py` with supported formats constant: `SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}` and extension-to-MIME mapping
- [x] 2.2 Implement `is_image_url(source: str) -> bool` — returns True if source starts with `http://` or `https://`
- [x] 2.3 Implement `validate_local_image(path: str)` — checks file exists, extension is supported, file is readable; raises `typer.BadParameter` on failure
- [x] 2.4 Implement `encode_local_image(path: str) -> ImageData` — reads file, base64-encodes, detects MIME from extension, returns `ImageData(data=b64, media_type=mime, is_url=False)`
- [x] 2.5 Implement `parse_image_url(url: str) -> ImageData` — infers MIME from URL extension (fallback `image/jpeg`), returns `ImageData(data=url, media_type=mime, is_url=True)`
- [x] 2.6 Implement `process_image_source(source: str) -> ImageData` — dispatches to URL or local path processing

## 3. CLI Integration

- [x] 3.1 Add `--image` / `-i` option to `entry.py` as a repeatable `List[str]` parameter in a new `ImageOptions` class
- [x] 3.2 Process image arguments in `main()`: call `process_image_source()` for each `--image` value, collect into `List[ImageData]`
- [x] 3.3 Pass `List[ImageData]` through to `CLI.__init__` or `CLI.run()` so it's available when building messages
- [x] 3.4 Update `CLI._build_messages()` to attach images to the user `ChatMessage` via the `images` field
- [x] 3.5 Allow image-only invocation (no text prompt): when `--image` is provided without a prompt argument, use empty string as content

## 4. Provider: OpenAI-Compatible Base

- [x] 4.1 Update `Provider._convert_messages()` in `yaicli/llms/provider.py`: when `msg.images` is non-empty, convert `content` from string to array of content blocks (`text` + `image_url` blocks)
- [x] 4.2 For base64 images: format as `{"type": "image_url", "image_url": {"url": "data:{media_type};base64,{data}"}}`
- [x] 4.3 For URL images: format as `{"type": "image_url", "image_url": {"url": "{data}"}}`
- [x] 4.4 Keep `content` as plain string when `msg.images` is empty (no behavior change)

## 5. Provider: Anthropic

- [x] 5.1 Update `_convert_messages()` in `yaicli/llms/providers/anthropic_provider.py`: when user message has images, build content array with image blocks before text block
- [x] 5.2 For base64 images: format as `{"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}`
- [x] 5.3 For URL images: format as `{"type": "image", "source": {"type": "url", "url": ...}}`

## 6. Provider: Gemini

- [x] 6.1 Update `_convert_messages()` in `yaicli/llms/providers/gemini_provider.py`: when message has images, add `types.Part.from_bytes()` or `types.Part.from_uri()` to the parts list
- [x] 6.2 For base64 images: decode base64 to bytes, create `types.Part.from_bytes(data=bytes, mime_type=media_type)`
- [x] 6.3 For URL images: create `types.Part.from_uri(file_uri=url, mime_type=media_type)`

## 7. Provider: Ollama

- [x] 7.1 Update `_convert_messages()` in `yaicli/llms/providers/ollama_provider.py`: when message has images, add `"images"` key to message dict with list of image data strings
- [x] 7.2 Keep `content` as plain string (do not convert to array)

## 8. Graceful Degradation

- [x] 8.1 Define `NO_VISION_PROVIDERS` set in `yaicli/const.py` (e.g., `{"cohere", "cohere-bedrock", "cohere-sagemaker", "huggingface", "chatglm", "modelscope"}`)
- [x] 8.2 Add check in `CLI._build_messages()` or `LLMClient`: if provider is in `NO_VISION_PROVIDERS` and images are present, print warning and strip images from the message

## 9. Tests

- [x] 9.1 Test `ImageData` dataclass creation and defaults
- [x] 9.2 Test `is_image_url()` with URLs, relative paths, absolute paths
- [x] 9.3 Test `validate_local_image()` with valid file, missing file, unsupported extension, unreadable file
- [x] 9.4 Test `encode_local_image()` produces correct base64 and media type
- [x] 9.5 Test `parse_image_url()` with URL with extension, URL without extension (fallback)
- [x] 9.6 Test base `_convert_messages()` with images produces OpenAI content array format
- [x] 9.7 Test Anthropic `_convert_messages()` with images produces correct image blocks
- [x] 9.8 Test Gemini `_convert_messages()` with images produces Part objects
- [x] 9.9 Test Ollama `_convert_messages()` with images produces `images` array
- [x] 9.10 Test graceful degradation: non-vision provider strips images and warns
- [x] 9.11 Test `_build_messages()` attaches images only to user message
