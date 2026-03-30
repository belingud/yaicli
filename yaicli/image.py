import base64
from pathlib import Path
from urllib.parse import urlparse

import typer

from .schemas import ImageData

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

DEFAULT_MIME_TYPE = "image/jpeg"


def is_image_url(source: str) -> bool:
    """Check if the source string is a URL."""
    return source.startswith("http://") or source.startswith("https://")


def _get_mime_from_extension(ext: str) -> str:
    """Get MIME type from file extension, with fallback."""
    return EXTENSION_TO_MIME.get(ext.lower(), DEFAULT_MIME_TYPE)


def validate_local_image(path: str) -> Path:
    """Validate a local image file path.

    Checks file existence, supported format, and readability.
    Returns the resolved Path on success.
    Raises typer.BadParameter on failure.
    """
    p = Path(path).expanduser().resolve()

    if not p.exists():
        raise typer.BadParameter(f"Image file not found: {path}")

    ext = p.suffix.lower()
    if ext not in SUPPORTED_IMAGE_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_EXTENSIONS))
        raise typer.BadParameter(f"Unsupported image format '{ext}'. Supported: {supported}")

    if not p.is_file():
        raise typer.BadParameter(f"Not a file: {path}")

    try:
        with open(p, "rb") as f:
            f.read(1)
    except PermissionError:
        raise typer.BadParameter(f"Cannot read image file (permission denied): {path}")
    except OSError as e:
        raise typer.BadParameter(f"Cannot read image file: {path} ({e})")

    return p


def encode_local_image(path: str) -> ImageData:
    """Read a local image file, validate it, and encode to base64.

    Returns ImageData with base64-encoded data.
    """
    p = validate_local_image(path)
    data = p.read_bytes()
    b64 = base64.standard_b64encode(data).decode("utf-8")
    media_type = _get_mime_from_extension(p.suffix)
    return ImageData(data=b64, media_type=media_type, is_url=False)


def parse_image_url(url: str) -> ImageData:
    """Parse a URL image source into ImageData.

    Infers MIME type from URL extension, falls back to image/jpeg.
    """
    parsed = urlparse(url)
    path = Path(parsed.path)
    ext = path.suffix.lower()
    media_type = _get_mime_from_extension(ext) if ext else DEFAULT_MIME_TYPE
    return ImageData(data=url, media_type=media_type, is_url=True)


def process_image_source(source: str) -> ImageData:
    """Process an image source string (local path or URL) into ImageData."""
    if is_image_url(source):
        return parse_image_url(source)
    return encode_local_image(source)
