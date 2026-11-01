import base64
import json
from pathlib import Path
from typing import List

from yaicli.function_schema import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """
    Read one or multiple image files in a single call and return base64 encoded data as JSON.
    """

    image_paths: List[str] = Field(
        ...,
        examples=[["/path/to/image1.png", "/path/to/image2.png"]],
        description=(
            "Image paths to read. Pass a list of paths to read several images in a single call; "
            "a single path string is also accepted for backward compatibility."
        ),
    )
    max_bytes: int = Field(
        default=5 * 1024 * 1024,
        json_schema_extra={
            "example": 5242880,
        },
        description="Maximum file size per image in bytes (default: 5MB).",
    )

    class Config:
        title = "fs_read_image"

    @classmethod
    def execute(cls, image_paths: List[str], max_bytes: int = 5 * 1024 * 1024) -> str:
        """
        Read one or multiple image files in a single call and return base64 encoded data as JSON.

        Args:
            image_paths: List of image paths to read in a single call. A single path
                string is also accepted for backward compatibility.
            max_bytes: Maximum allowed file size per image in bytes.

        Returns:
            str: JSON string with image data.
        """
        # Normalize to a list of paths. The model-facing schema advertises an array,
        # but old tool calls may still pass a single path string (or a tuple).
        if isinstance(image_paths, str):
            paths_list = [image_paths]
        elif isinstance(image_paths, (list, tuple)):
            paths_list = list(image_paths)
        else:
            return json.dumps(
                {
                    "error": (
                        "image_paths must be a list of image paths (a single path string is also accepted), "
                        f"got {type(image_paths).__name__}"
                    )
                },
                ensure_ascii=False,
            )

        if not paths_list:
            return json.dumps({"error": "No image paths provided"}, ensure_ascii=False)

        max_images = 20
        if len(paths_list) > max_images:
            return json.dumps(
                {"error": f"Too many images ({len(paths_list)}). Maximum: {max_images}"}, ensure_ascii=False
            )

        is_single = len(paths_list) == 1
        valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico"}
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }

        images_data = []
        success_count = 0
        error_count = 0

        for image_path in paths_list:
            image_info = {
                "path": image_path,
                "success": False,
                "base64": None,
                "mime_type": None,
                "size": 0,
                "format": None,
                "error": None,
            }

            try:
                path = Path(image_path).expanduser().resolve()

                # Check existence
                if not path.exists():
                    image_info["error"] = "Image file does not exist"
                    error_count += 1
                    images_data.append(image_info)
                    continue

                if not path.is_file():
                    image_info["error"] = "Not a file"
                    error_count += 1
                    images_data.append(image_info)
                    continue

                # Check extension
                if path.suffix.lower() not in valid_extensions:
                    image_info["error"] = f"Unsupported format '{path.suffix}'"
                    error_count += 1
                    images_data.append(image_info)
                    continue

                # Check file size
                file_size = path.stat().st_size
                if file_size > max_bytes:
                    image_info["error"] = f"File too large ({file_size} bytes). Max: {max_bytes} bytes"
                    error_count += 1
                    images_data.append(image_info)
                    continue

                # Read and encode
                with open(path, "rb") as f:
                    image_data = f.read()

                base64_data = base64.b64encode(image_data).decode("utf-8")
                mime_type = mime_types.get(path.suffix.lower(), "application/octet-stream")

                success_count += 1
                image_info["success"] = True
                image_info["base64"] = base64_data
                image_info["mime_type"] = mime_type
                image_info["size"] = file_size
                image_info["format"] = path.suffix.upper()
                images_data.append(image_info)

            except PermissionError:
                image_info["error"] = "Permission denied"
                error_count += 1
                images_data.append(image_info)

            except Exception as e:
                image_info["error"] = str(e)
                error_count += 1
                images_data.append(image_info)

        # Build result
        if is_single:
            return json.dumps(images_data[0], ensure_ascii=False, indent=2)
        else:
            result = {
                "total_images": len(paths_list),
                "success_count": success_count,
                "error_count": error_count,
                "images": images_data,
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
