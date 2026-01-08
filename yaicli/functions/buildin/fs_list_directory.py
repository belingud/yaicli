import json
import os
from pathlib import Path

from instructor import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """
    List the contents of a directory and return as JSON.
    """

    directory_path: str = Field(
        ...,
        json_schema_extra={
            "example": "/path/to/directory",
        },
        description="Path to the directory to list.",
    )
    show_hidden: bool = Field(
        default=False,
        json_schema_extra={
            "example": False,
        },
        description="Include hidden files (files starting with '.') in the listing (default: False).",
    )
    recursive: bool = Field(
        default=False,
        json_schema_extra={
            "example": False,
        },
        description="List subdirectories recursively (default: False).",
    )

    class Config:
        title = "fs_list_directory"

    @classmethod
    def execute(cls, directory_path: str, show_hidden: bool = False, recursive: bool = False) -> str:
        """
        List the contents of a directory and return as JSON.

        Args:
            directory_path: Path to the directory to list.
            show_hidden: Include hidden files in the listing.
            recursive: List subdirectories recursively.

        Returns:
            str: JSON string with directory listing.
        """
        result = {"path": directory_path, "success": False, "items": [], "total_count": 0, "error": None}

        try:
            path = Path(directory_path).expanduser().resolve()

            # Security check: ensure path exists and is a directory
            if not path.exists():
                result["error"] = "Directory does not exist"
                return json.dumps(result, ensure_ascii=False, indent=2)

            if not path.is_dir():
                result["error"] = "Not a directory"
                return json.dumps(result, ensure_ascii=False, indent=2)

            items = []

            if recursive:
                for root, dirs, files in os.walk(path):
                    root_path = Path(root)
                    rel_root = root_path.relative_to(path) if root_path != path else Path(".")

                    # Filter hidden items if needed
                    if not show_hidden:
                        dirs[:] = [d for d in dirs if not d.startswith(".")]
                        files = [f for f in files if not f.startswith(".")]

                    for dir_name in sorted(dirs):
                        rel_path = rel_root / dir_name if rel_root != Path(".") else Path(dir_name)
                        items.append({"name": dir_name, "path": str(rel_path), "type": "directory", "size": None})

                    for file_name in sorted(files):
                        file_path = root_path / file_name
                        rel_path = rel_root / file_name if rel_root != Path(".") else Path(file_name)
                        try:
                            size = file_path.stat().st_size
                        except Exception:
                            size = None

                        items.append({"name": file_name, "path": str(rel_path), "type": "file", "size": size})
            else:
                file_items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))

                if not show_hidden:
                    file_items = [item for item in file_items if not item.name.startswith(".")]

                for item in file_items:
                    item_data = {"name": item.name, "path": item.name, "type": None, "size": None}

                    if item.is_dir():
                        item_data["type"] = "directory"
                    elif item.is_file():
                        item_data["type"] = "file"
                        try:
                            item_data["size"] = item.stat().st_size
                        except Exception:
                            pass
                    else:
                        item_data["type"] = "other"

                    items.append(item_data)

            result["success"] = True
            result["items"] = items
            result["total_count"] = len(items)

            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)
