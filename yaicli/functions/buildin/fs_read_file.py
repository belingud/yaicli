import json
from pathlib import Path
from typing import List

from yaicli.function_schema import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """
    Read one or more files in a single call and return their contents as JSON.
    """

    file_paths: List[str] = Field(
        ...,
        examples=[["/path/to/file1.txt", "/path/to/file2.txt"]],
        description=(
            "File paths to read. Pass a list of paths to read several files in a single call; "
            "a single path string is also accepted for backward compatibility."
        ),
    )
    encoding: str = Field(
        default="utf-8",
        json_schema_extra={
            "example": "utf-8",
        },
        description="File encoding (default: utf-8).",
    )

    class Config:
        title = "fs_read_file"

    @classmethod
    def execute(cls, file_paths: List[str], encoding: str = "utf-8") -> str:
        """
        Read one or more files in a single call and return their contents as JSON.

        Args:
            file_paths: List of file paths to read in a single call. A single path
                string is also accepted for backward compatibility.
            encoding: File encoding (default: utf-8).

        Returns:
            str: JSON string with file contents or error information.
        """
        # Normalize to a list of paths. The model-facing schema advertises an array,
        # but old tool calls may still pass a single path string (or a tuple).
        if isinstance(file_paths, str):
            paths_list = [file_paths]
        elif isinstance(file_paths, (list, tuple)):
            paths_list = list(file_paths)
        else:
            return json.dumps(
                {
                    "error": (
                        "file_paths must be a list of file paths (a single path string is also accepted), "
                        f"got {type(file_paths).__name__}"
                    )
                },
                ensure_ascii=False,
            )

        if not paths_list:
            return json.dumps({"error": "No file paths provided"}, ensure_ascii=False)

        # Limits
        max_files = 50
        max_file_size = 10 * 1024 * 1024  # 10 MB per file
        max_total_size = 50 * 1024 * 1024  # 50 MB total

        if len(paths_list) > max_files:
            return json.dumps(
                {"error": f"Too many files ({len(paths_list)}). Maximum: {max_files}"}, ensure_ascii=False
            )

        is_single_file = len(paths_list) == 1
        files_data = []
        success_count = 0
        error_count = 0
        total_size = 0

        for file_path in paths_list:
            file_info = {"path": file_path, "success": False, "content": None, "size": 0, "error": None}

            try:
                path = Path(file_path).expanduser().resolve()

                # Check existence
                if not path.exists():
                    file_info["error"] = "File does not exist"
                    error_count += 1
                    files_data.append(file_info)
                    continue

                if not path.is_file():
                    file_info["error"] = "Not a file"
                    error_count += 1
                    files_data.append(file_info)
                    continue

                # Check file size
                file_size = path.stat().st_size
                if file_size > max_file_size:
                    file_info["error"] = f"File too large ({file_size} bytes). Max: {max_file_size} bytes"
                    error_count += 1
                    files_data.append(file_info)
                    continue

                # Check total size
                if total_size + file_size > max_total_size:
                    file_info["error"] = "Total size limit exceeded"
                    error_count += 1
                    files_data.append(file_info)
                    continue

                # Read file
                with open(path, "r", encoding=encoding) as f:
                    content = f.read()

                total_size += file_size
                success_count += 1

                file_info["success"] = True
                file_info["content"] = content
                file_info["size"] = file_size
                files_data.append(file_info)

            except UnicodeDecodeError:
                file_info["error"] = f"Unable to decode with encoding '{encoding}'"
                error_count += 1
                files_data.append(file_info)

            except PermissionError:
                file_info["error"] = "Permission denied"
                error_count += 1
                files_data.append(file_info)

            except Exception as e:
                file_info["error"] = str(e)
                error_count += 1
                files_data.append(file_info)

        # Build result
        if is_single_file:
            return json.dumps(files_data[0], ensure_ascii=False, indent=2)
        else:
            result = {
                "total_files": len(paths_list),
                "success_count": success_count,
                "error_count": error_count,
                "total_size": total_size,
                "files": files_data,
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
