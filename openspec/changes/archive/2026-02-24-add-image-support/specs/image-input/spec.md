## ADDED Requirements

### Requirement: CLI accepts image arguments
The system SHALL provide an `--image` / `-i` CLI option that accepts one or more image sources. Each image source MUST be either a local file path or a URL string.

#### Scenario: Single local image
- **WHEN** user runs `ai --image /path/to/photo.jpg "What is this?"`
- **THEN** the system accepts the image path and includes it with the prompt

#### Scenario: Multiple images via repeated flag
- **WHEN** user runs `ai -i img1.png -i img2.png "Compare these"`
- **THEN** the system accepts both images and includes them with the prompt

#### Scenario: URL image
- **WHEN** user runs `ai --image https://example.com/photo.jpg "Describe this"`
- **THEN** the system accepts the URL and includes it with the prompt

#### Scenario: No prompt with image
- **WHEN** user runs `ai --image photo.jpg` without a text prompt
- **THEN** the system SHALL still send the image with an empty or minimal text prompt

### Requirement: Local image validation
The system SHALL validate local image files before processing. Validation MUST check file existence, file extension against supported formats, and file readability.

#### Scenario: File does not exist
- **WHEN** user provides a path to a non-existent file
- **THEN** the system SHALL exit with a clear error message indicating the file was not found

#### Scenario: Unsupported format
- **WHEN** user provides a file with an unsupported extension (e.g., `.bmp`, `.tiff`, `.svg`)
- **THEN** the system SHALL exit with an error listing the supported formats

#### Scenario: File is not readable
- **WHEN** user provides a path to a file without read permissions
- **THEN** the system SHALL exit with a clear error message

### Requirement: Supported image formats
The system SHALL support the following image formats: JPEG (`.jpg`, `.jpeg`), PNG (`.png`), GIF (`.gif`), and WebP (`.webp`). Format detection MUST be based on file extension.

#### Scenario: JPEG image accepted
- **WHEN** user provides a `.jpg` or `.jpeg` file
- **THEN** the system SHALL accept it with media type `image/jpeg`

#### Scenario: PNG image accepted
- **WHEN** user provides a `.png` file
- **THEN** the system SHALL accept it with media type `image/png`

#### Scenario: GIF image accepted
- **WHEN** user provides a `.gif` file
- **THEN** the system SHALL accept it with media type `image/gif`

#### Scenario: WebP image accepted
- **WHEN** user provides a `.webp` file
- **THEN** the system SHALL accept it with media type `image/webp`

### Requirement: Local images encoded to base64
The system SHALL read local image files and encode their contents as base64 strings. The encoding MUST produce a standard base64 string (no line breaks, no data URI prefix).

#### Scenario: Successful encoding
- **WHEN** a valid local image file is provided
- **THEN** the system SHALL read the file bytes and produce a base64-encoded string

#### Scenario: Large file encoding
- **WHEN** a valid but large image file is provided (e.g., 10MB)
- **THEN** the system SHALL encode it without error (no client-side size limit in v1)

### Requirement: URL detection
The system SHALL distinguish between local file paths and URLs. A string starting with `http://` or `https://` MUST be treated as a URL. All other strings MUST be treated as local file paths.

#### Scenario: HTTPS URL detected
- **WHEN** user provides `https://example.com/image.jpg`
- **THEN** the system SHALL treat it as a URL image (no file validation, no base64 encoding)

#### Scenario: HTTP URL detected
- **WHEN** user provides `http://example.com/image.jpg`
- **THEN** the system SHALL treat it as a URL image

#### Scenario: Relative path not treated as URL
- **WHEN** user provides `./images/photo.jpg`
- **THEN** the system SHALL treat it as a local file path

### Requirement: Image data representation
The system SHALL represent each processed image as an `ImageData` object containing: the data string (base64 or URL), the MIME media type, and a boolean indicating whether the data is a URL.

#### Scenario: Local image produces ImageData
- **WHEN** a local JPEG file is processed
- **THEN** an `ImageData` is created with `data` = base64 string, `media_type` = `"image/jpeg"`, `is_url` = `False`

#### Scenario: URL image produces ImageData
- **WHEN** a URL `https://example.com/photo.png` is provided
- **THEN** an `ImageData` is created with `data` = the URL string, `media_type` = `"image/png"` (inferred from extension), `is_url` = `True`

#### Scenario: URL without image extension
- **WHEN** a URL `https://example.com/image?id=123` has no recognizable extension
- **THEN** an `ImageData` is created with `media_type` = `"image/jpeg"` (default fallback), `is_url` = `True`
