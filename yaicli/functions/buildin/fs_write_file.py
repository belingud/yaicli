import json
from pathlib import Path

from pydantic import Field

from yaicli.function_schema import OpenAISchema


class Function(OpenAISchema):
    """
    Write content to a file and return result as JSON.
    """

    file_path: str = Field(
        ...,
        json_schema_extra={
            "example": "/path/to/file.txt",
        },
        description="Path to the file to write.",
    )
    content: str = Field(
        ...,
        json_schema_extra={
            "example": "Hello, World!",
        },
        description="Content to write to the file.",
    )
    encoding: str = Field(
        default="utf-8",
        json_schema_extra={
            "example": "utf-8",
        },
        description="File encoding (default: utf-8).",
    )
    append: bool = Field(
        default=False,
        json_schema_extra={
            "example": False,
        },
        description="If True, append to the file instead of overwriting (default: False).",
    )

    class Config:
        title = "fs_write_file"

    @classmethod
    def execute(cls, file_path: str, content: str, encoding: str = "utf-8", append: bool = False) -> str:
        """
        Write content to a file and return result as JSON.

        Args:
            file_path: Path to the file to write.
            content: Content to write to the file.
            encoding: File encoding (default: utf-8).
            append: If True, append to the file instead of overwriting.

        Returns:
            str: JSON string with operation result.
        """
        result = {
            "path": file_path,
            "success": False,
            "mode": "append" if append else "write",
            "size": 0,
            "error": None,
        }

        try:
            path = Path(file_path).expanduser().resolve()

            # Security check: prevent writing to sensitive system files
            dangerous_paths = ["/etc/", "/sys/", "/proc/", "/dev/"]
            if any(str(path).startswith(dp) for dp in dangerous_paths):
                result["error"] = "Cannot write to system directory"
                return json.dumps(result, ensure_ascii=False, indent=2)

            # Create parent directories if they don't exist
            path.parent.mkdir(parents=True, exist_ok=True)

            mode = "a" if append else "w"
            with open(path, mode, encoding=encoding) as f:
                f.write(content)

            file_size = path.stat().st_size
            result["success"] = True
            result["size"] = file_size

            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)
