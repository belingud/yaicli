import fnmatch
import json
import os
from pathlib import Path
from typing import List

from instructor import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """
    Search for files matching a pattern and return results as JSON.
    """

    search_path: str = Field(
        ...,
        json_schema_extra={
            "example": "/path/to/search",
        },
        description="Directory path to search in.",
    )
    pattern: str = Field(
        ...,
        json_schema_extra={
            "example": "*.py",
        },
        description="File name pattern to match (supports wildcards like *.txt, test_*.py).",
    )
    exclude_patterns: List[str] = Field(
        default_factory=list,
        json_schema_extra={
            "example": ["*.pyc", "__pycache__", ".git"],
        },
        description="Patterns to exclude from search results.",
    )
    max_results: int = Field(
        default=1000,
        json_schema_extra={
            "example": 1000,
        },
        description="Maximum number of results to return (default: 1000).",
    )

    class Config:
        title = "fs_search_files"

    @classmethod
    def execute(
        cls, search_path: str, pattern: str, exclude_patterns: List[str] | None = None, max_results: int = 1000
    ) -> str:
        """
        Search for files matching a pattern and return results as JSON.

        Args:
            search_path: Directory to search in.
            pattern: File name pattern (e.g., "*.py", "test_*.txt").
            exclude_patterns: Patterns to exclude.
            max_results: Maximum number of results.

        Returns:
            str: JSON string with search results.
        """
        if exclude_patterns is None:
            exclude_patterns = []

        result = {
            "search_path": search_path,
            "pattern": pattern,
            "success": False,
            "matches": [],
            "total_scanned": 0,
            "excluded_count": 0,
            "match_count": 0,
            "truncated": False,
            "error": None,
        }

        try:
            path = Path(search_path).expanduser().resolve()

            # Check if path exists
            if not path.exists():
                result["error"] = "Search path does not exist"
                return json.dumps(result, ensure_ascii=False, indent=2)

            if not path.is_dir():
                result["error"] = "Search path is not a directory"
                return json.dumps(result, ensure_ascii=False, indent=2)

            matches = []
            total_scanned = 0
            excluded_count = 0

            # Walk through directory tree
            for root, dirs, files in os.walk(path):
                root_path = Path(root)

                # Filter out excluded directories
                dirs_to_remove = []
                for d in dirs:
                    if cls._should_exclude(d, exclude_patterns):
                        dirs_to_remove.append(d)
                        excluded_count += 1

                for d in dirs_to_remove:
                    dirs.remove(d)

                # Check files
                for file_name in files:
                    total_scanned += 1

                    # Check if file should be excluded
                    if cls._should_exclude(file_name, exclude_patterns):
                        excluded_count += 1
                        continue

                    # Check if file matches pattern
                    if fnmatch.fnmatch(file_name, pattern):
                        file_path = root_path / file_name
                        rel_path = file_path.relative_to(path)

                        match_info = {
                            "name": file_name,
                            "path": str(rel_path),
                            "full_path": str(file_path),
                            "directory": str(rel_path.parent) if rel_path.parent != Path(".") else ".",
                            "size": None,
                        }

                        try:
                            match_info["size"] = file_path.stat().st_size
                        except Exception:
                            pass

                        matches.append(match_info)

                        # Check max results limit
                        if len(matches) >= max_results:
                            result["truncated"] = True
                            break

                if len(matches) >= max_results:
                    break

            result["success"] = True
            result["matches"] = matches
            result["total_scanned"] = total_scanned
            result["excluded_count"] = excluded_count
            result["match_count"] = len(matches)

            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _should_exclude(name: str, exclude_patterns: List[str]) -> bool:
        """Check if a name matches any exclude pattern."""
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False
