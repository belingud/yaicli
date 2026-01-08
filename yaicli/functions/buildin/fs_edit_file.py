import json
from pathlib import Path
from typing import List, Dict

from instructor import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """
    Edit a file by applying multiple text replacements or line-based modifications.
    Returns results as JSON.
    """

    file_path: str = Field(
        ...,
        json_schema_extra={
            "example": "/path/to/file.txt",
        },
        description="Path to the file to edit.",
    )
    edits: List[Dict[str, str]] = Field(
        ...,
        json_schema_extra={
            "example": [
                {"type": "replace", "old": "old_text", "new": "new_text"},
                {"type": "insert_line", "line_number": "5", "content": "new line"},
            ],
        },
        description="List of edit operations. Each operation is a dict with 'type' and relevant fields.",
    )
    dry_run: bool = Field(
        default=False,
        json_schema_extra={
            "example": False,
        },
        description="If True, show what would be changed without actually modifying the file.",
    )

    class Config:
        title = "fs_edit_file"

    @classmethod
    def execute(cls, file_path: str, edits: List[Dict[str, str]], dry_run: bool = False) -> str:
        """
        Edit a file by applying multiple modifications and return result as JSON.

        Supported edit types:
        - replace: {"type": "replace", "old": "text", "new": "text"}
        - replace_line: {"type": "replace_line", "line_number": "N", "new": "text"}
        - insert_line: {"type": "insert_line", "line_number": "N", "content": "text"}
        - delete_line: {"type": "delete_line", "line_number": "N"}
        - append: {"type": "append", "content": "text"}

        Args:
            file_path: Path to the file to edit.
            edits: List of edit operations.
            dry_run: If True, preview changes without modifying the file.

        Returns:
            str: JSON string with edit results.
        """
        result = {
            "path": file_path,
            "success": False,
            "dry_run": dry_run,
            "original_size": 0,
            "original_lines": 0,
            "modified_size": 0,
            "modified_lines": 0,
            "changes": [],
            "error": None,
        }

        try:
            path = Path(file_path).expanduser().resolve()

            # Check if file exists
            if not path.exists():
                result["error"] = "File does not exist"
                return json.dumps(result, ensure_ascii=False, indent=2)

            if not path.is_file():
                result["error"] = "Not a file"
                return json.dumps(result, ensure_ascii=False, indent=2)

            # Read current content
            with open(path, "r", encoding="utf-8") as f:
                original_content = f.read()
                lines = original_content.splitlines(keepends=True)

            if not lines and original_content:
                lines = [original_content]

            result["original_size"] = len(original_content)
            result["original_lines"] = len(lines)

            modified_content = original_content
            modified_lines = lines.copy()
            changes = []

            # Apply edits
            for i, edit in enumerate(edits):
                edit_type = edit.get("type", "")
                change_info = {"edit_number": i + 1, "type": edit_type, "success": False, "message": None}

                if edit_type == "replace":
                    old_text = edit.get("old", "")
                    new_text = edit.get("new", "")

                    if old_text in modified_content:
                        count = modified_content.count(old_text)
                        modified_content = modified_content.replace(old_text, new_text)
                        modified_lines = modified_content.splitlines(keepends=True)
                        change_info["success"] = True
                        change_info["message"] = f"Replaced {count} occurrence(s)"
                    else:
                        change_info["message"] = "Text not found"

                elif edit_type == "replace_line":
                    line_num = int(edit.get("line_number", 0))
                    new_content = edit.get("new", "")

                    if 1 <= line_num <= len(modified_lines):
                        modified_lines[line_num - 1] = new_content + "\n"
                        modified_content = "".join(modified_lines)
                        change_info["success"] = True
                        change_info["message"] = f"Replaced line {line_num}"
                    else:
                        change_info["message"] = f"Line {line_num} out of range"

                elif edit_type == "insert_line":
                    line_num = int(edit.get("line_number", 0))
                    content = edit.get("content", "")

                    if 0 <= line_num <= len(modified_lines):
                        modified_lines.insert(line_num, content + "\n")
                        modified_content = "".join(modified_lines)
                        change_info["success"] = True
                        change_info["message"] = f"Inserted line at position {line_num}"
                    else:
                        change_info["message"] = f"Line {line_num} out of range"

                elif edit_type == "delete_line":
                    line_num = int(edit.get("line_number", 0))

                    if 1 <= line_num <= len(modified_lines):
                        del modified_lines[line_num - 1]
                        modified_content = "".join(modified_lines)
                        change_info["success"] = True
                        change_info["message"] = f"Deleted line {line_num}"
                    else:
                        change_info["message"] = f"Line {line_num} out of range"

                elif edit_type == "append":
                    content = edit.get("content", "")
                    if not modified_content.endswith("\n"):
                        modified_content += "\n"
                    modified_content += content + "\n"
                    modified_lines = modified_content.splitlines(keepends=True)
                    change_info["success"] = True
                    change_info["message"] = "Appended content"

                else:
                    change_info["message"] = f"Unknown edit type: '{edit_type}'"

                changes.append(change_info)

            result["modified_size"] = len(modified_content)
            result["modified_lines"] = len(modified_lines)
            result["changes"] = changes

            if not dry_run:
                # Write changes
                with open(path, "w", encoding="utf-8") as f:
                    f.write(modified_content)

            result["success"] = True

            return json.dumps(result, ensure_ascii=False, indent=2)

        except ValueError as e:
            result["error"] = f"Invalid edit operation: {str(e)}"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)
