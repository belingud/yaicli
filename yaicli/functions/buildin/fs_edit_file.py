import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yaicli.function_schema import OpenAISchema
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
        description=(
            "List of edit operations, applied in order. Supported operations and their required keys:\n"
            "- replace: {'type': 'replace', 'old': <non-empty str>, 'new': <str>} — replaces every "
            "occurrence of 'old' with 'new'; 'old' must be non-empty and differ from 'new'\n"
            "- replace_line: {'type': 'replace_line', 'line_number': <1-based int>, 'new': <str>}\n"
            "- insert_line: {'type': 'insert_line', 'line_number': <0..N>, 'content': <str>}\n"
            "- delete_line: {'type': 'delete_line', 'line_number': <1-based int>}\n"
            "- append: {'type': 'append', 'content': <str>}\n"
            "Every operation must succeed, otherwise the file is left completely unchanged."
        ),
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

    @staticmethod
    def _require_str(edit: Dict[str, Any], key: str) -> Tuple[Optional[str], Optional[str]]:
        """Validate that ``edit[key]`` is a string. Returns (value, error_message)."""
        if key not in edit:
            return None, f"Missing required key '{key}'"
        value = edit[key]
        if not isinstance(value, str):
            return None, f"Invalid '{key}': expected a string, got {type(value).__name__}"
        return value, None

    @staticmethod
    def _parse_line_number(edit: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
        """Validate and parse ``edit['line_number']``. Returns (line_number, error_message)."""
        if "line_number" not in edit:
            return None, "Missing required key 'line_number'"
        raw = edit["line_number"]
        if isinstance(raw, bool):
            return None, f"Invalid 'line_number': expected an integer, got {raw!r}"
        try:
            return int(raw), None
        except (TypeError, ValueError):
            return None, f"Invalid 'line_number': expected an integer, got {raw!r}"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Atomically replace ``path`` with ``content``.

        The new content is written to a temporary file in the same directory and then
        moved into place with ``os.replace``, so a failed/interrupted write can never
        truncate or corrupt the original file. The original permission bits are kept.
        """
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            try:
                os.chmod(tmp_path, stat.S_IMODE(path.stat().st_mode))
            except OSError:
                pass
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

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

        Edits are all-or-nothing: if any edit fails, nothing is written to the file.

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

        if not isinstance(edits, list):
            result["error"] = "Invalid 'edits': expected a list of edit operations"
            return json.dumps(result, ensure_ascii=False, indent=2)

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
            failed_count = 0

            # Apply edits: validate each one before touching the in-memory content.
            for i, edit in enumerate(edits):
                change_info = {"edit_number": i + 1, "type": None, "success": False, "message": None}

                if not isinstance(edit, dict):
                    change_info["message"] = f"Invalid edit: expected an object, got {type(edit).__name__}"
                    failed_count += 1
                    changes.append(change_info)
                    continue

                edit_type = edit.get("type", "")
                change_info["type"] = edit_type

                if edit_type == "replace":
                    old_text, error = cls._require_str(edit, "old")
                    if error is None and old_text == "":
                        error = "Invalid 'old': must be a non-empty string"
                    new_text, new_error = cls._require_str(edit, "new")
                    error = error or new_error

                    if error is None and old_text == new_text:
                        error = "Invalid 'replace': 'old' and 'new' are identical"

                    if error is not None:
                        change_info["message"] = error
                    elif old_text in modified_content:
                        count = modified_content.count(old_text)
                        modified_content = modified_content.replace(old_text, new_text)
                        modified_lines = modified_content.splitlines(keepends=True)
                        change_info["success"] = True
                        change_info["message"] = f"Replaced {count} occurrence(s)"
                    else:
                        change_info["message"] = "Text not found"

                elif edit_type == "replace_line":
                    line_num, error = cls._parse_line_number(edit)
                    new_content, new_error = cls._require_str(edit, "new")
                    error = error or new_error

                    if error is not None:
                        change_info["message"] = error
                    elif 1 <= line_num <= len(modified_lines):
                        modified_lines[line_num - 1] = new_content + "\n"
                        modified_content = "".join(modified_lines)
                        change_info["success"] = True
                        change_info["message"] = f"Replaced line {line_num}"
                    else:
                        change_info["message"] = f"Line {line_num} out of range"

                elif edit_type == "insert_line":
                    line_num, error = cls._parse_line_number(edit)
                    content, content_error = cls._require_str(edit, "content")
                    error = error or content_error

                    if error is not None:
                        change_info["message"] = error
                    elif 0 <= line_num <= len(modified_lines):
                        modified_lines.insert(line_num, content + "\n")
                        modified_content = "".join(modified_lines)
                        change_info["success"] = True
                        change_info["message"] = f"Inserted line at position {line_num}"
                    else:
                        change_info["message"] = f"Line {line_num} out of range"

                elif edit_type == "delete_line":
                    line_num, error = cls._parse_line_number(edit)

                    if error is not None:
                        change_info["message"] = error
                    elif 1 <= line_num <= len(modified_lines):
                        del modified_lines[line_num - 1]
                        modified_content = "".join(modified_lines)
                        change_info["success"] = True
                        change_info["message"] = f"Deleted line {line_num}"
                    else:
                        change_info["message"] = f"Line {line_num} out of range"

                elif edit_type == "append":
                    content, error = cls._require_str(edit, "content")

                    if error is not None:
                        change_info["message"] = error
                    else:
                        if not modified_content.endswith("\n"):
                            modified_content += "\n"
                        modified_content += content + "\n"
                        modified_lines = modified_content.splitlines(keepends=True)
                        change_info["success"] = True
                        change_info["message"] = "Appended content"

                else:
                    change_info["message"] = (
                        f"Unknown edit type: {edit_type!r} "
                        "(expected replace/replace_line/insert_line/delete_line/append)"
                    )

                if not change_info["success"]:
                    failed_count += 1
                changes.append(change_info)

            result["modified_size"] = len(modified_content)
            result["modified_lines"] = len(modified_lines)
            result["changes"] = changes

            # Data-first: never write a partially-applied edit list.
            if failed_count:
                result["error"] = (
                    f"{failed_count} of {len(edits)} edit(s) failed; no changes were written to the file"
                )
                return json.dumps(result, ensure_ascii=False, indent=2)

            if dry_run:
                result["success"] = True
                return json.dumps(result, ensure_ascii=False, indent=2)

            cls._atomic_write(path, modified_content)
            result["success"] = True

            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)
