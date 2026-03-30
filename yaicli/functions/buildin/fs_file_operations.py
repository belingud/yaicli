import json
import shutil
from datetime import datetime
from pathlib import Path

from yaicli.function_schema import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """
    Perform various file system operations and return results as JSON.
    """

    operation: str = Field(
        ...,
        json_schema_extra={
            "example": "create_dir",
        },
        description="Operation to perform. Options: 'create_dir', 'delete', 'move', 'copy', 'exists', 'get_info'.",
    )
    path: str = Field(
        ...,
        json_schema_extra={
            "example": "/path/to/file_or_directory",
        },
        description="Path to the file or directory to operate on.",
    )
    destination: str = Field(
        default="",
        json_schema_extra={
            "example": "/path/to/destination",
        },
        description="Destination path (required for 'move' and 'copy' operations).",
    )

    class Config:
        title = "fs_file_operations"

    @classmethod
    def execute(cls, operation: str, path: str, destination: str = "") -> str:
        """
        Perform file system operations and return results as JSON.

        Args:
            operation: Operation to perform.
            path: Path to the file or directory.
            destination: Destination path (for move/copy operations).

        Returns:
            str: JSON string with operation result.
        """
        result = {"operation": operation, "path": path, "success": False, "error": None}

        # Security check for dangerous paths - do this before path resolution
        dangerous_paths = ["/etc/", "/sys/", "/proc/", "/dev/", "/bin/", "/usr/", "/sbin/"]

        try:
            if operation == "delete":
                if any(path.startswith(dp) for dp in dangerous_paths):
                    result["error"] = "Cannot delete from system directory"
                    return json.dumps(result, ensure_ascii=False, indent=2)

            elif operation == "move":
                if not destination:
                    result["error"] = "Destination path is required for 'move' operation"
                    return json.dumps(result, ensure_ascii=False, indent=2)
                if any(path.startswith(dp) for dp in dangerous_paths) or any(
                    destination.startswith(dp) for dp in dangerous_paths
                ):
                    result["error"] = "Cannot move to/from system directories"
                    return json.dumps(result, ensure_ascii=False, indent=2)
                result["destination"] = destination

            elif operation == "copy":
                if not destination:
                    result["error"] = "Destination path is required for 'copy' operation"
                    return json.dumps(result, ensure_ascii=False, indent=2)
                if any(destination.startswith(dp) for dp in dangerous_paths):
                    result["error"] = "Cannot copy to system directory"
                    return json.dumps(result, ensure_ascii=False, indent=2)
                result["destination"] = destination

            # Now resolve paths after security checks
            file_path = Path(path).expanduser().resolve()

            if operation == "create_dir":
                return cls._create_directory(file_path)

            elif operation == "delete":
                return cls._delete(file_path)

            elif operation == "move":
                dest_path = Path(destination).expanduser().resolve()
                return cls._move(file_path, dest_path)

            elif operation == "copy":
                dest_path = Path(destination).expanduser().resolve()
                return cls._copy(file_path, dest_path)

            elif operation == "exists":
                return cls._check_exists(file_path)

            elif operation == "get_info":
                return cls._get_info(file_path)

            else:
                result["error"] = f"Unknown operation '{operation}'"
                return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _create_directory(path: Path) -> str:
        """Create a directory and return result as JSON."""
        result = {"operation": "create_dir", "path": str(path), "success": False, "error": None}

        try:
            if path.exists():
                if path.is_dir():
                    result["success"] = True
                    result["message"] = "Directory already exists"
                else:
                    result["error"] = "Path exists but is not a directory"
            else:
                path.mkdir(parents=True, exist_ok=True)
                result["success"] = True
                result["message"] = "Directory created"

            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _delete(path: Path) -> str:
        """Delete a file or directory and return result as JSON."""
        result = {"operation": "delete", "path": str(path), "success": False, "type": None, "error": None}

        try:
            if not path.exists():
                result["error"] = "Path does not exist"
                return json.dumps(result, ensure_ascii=False, indent=2)

            if path.is_file():
                result["type"] = "file"
                path.unlink()
            elif path.is_dir():
                result["type"] = "directory"
                shutil.rmtree(path)
            else:
                result["error"] = "Path is neither a file nor a directory"
                return json.dumps(result, ensure_ascii=False, indent=2)

            result["success"] = True
            result["message"] = f"{result['type'].capitalize()} deleted"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _move(source: Path, destination: Path) -> str:
        """Move a file or directory and return result as JSON."""
        result = {
            "operation": "move",
            "source": str(source),
            "destination": str(destination),
            "success": False,
            "error": None,
        }

        try:
            if not source.exists():
                result["error"] = "Source does not exist"
                return json.dumps(result, ensure_ascii=False, indent=2)

            # If destination is a directory, move into it
            if destination.is_dir():
                destination = destination / source.name
                result["destination"] = str(destination)

            shutil.move(str(source), str(destination))
            result["success"] = True
            result["message"] = "Moved successfully"

            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _copy(source: Path, destination: Path) -> str:
        """Copy a file or directory and return result as JSON."""
        result = {
            "operation": "copy",
            "source": str(source),
            "destination": str(destination),
            "success": False,
            "type": None,
            "error": None,
        }

        try:
            if not source.exists():
                result["error"] = "Source does not exist"
                return json.dumps(result, ensure_ascii=False, indent=2)

            if source.is_file():
                result["type"] = "file"
                # If destination is a directory, copy into it
                if destination.is_dir():
                    destination = destination / source.name
                    result["destination"] = str(destination)
                shutil.copy2(str(source), str(destination))
            elif source.is_dir():
                result["type"] = "directory"
                shutil.copytree(str(source), str(destination), dirs_exist_ok=True)
            else:
                result["error"] = "Source is neither a file nor a directory"
                return json.dumps(result, ensure_ascii=False, indent=2)

            result["success"] = True
            result["message"] = f"{result['type'].capitalize()} copied"

            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _check_exists(path: Path) -> str:
        """Check if a path exists and return result as JSON."""
        result = {"operation": "exists", "path": str(path), "exists": False, "type": None, "size": None}

        if not path.exists():
            return json.dumps(result, ensure_ascii=False, indent=2)

        result["exists"] = True

        if path.is_file():
            result["type"] = "file"
            result["size"] = path.stat().st_size
        elif path.is_dir():
            result["type"] = "directory"
        else:
            result["type"] = "other"

        return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _get_info(path: Path) -> str:
        """Get detailed information about a file or directory and return as JSON."""
        result = {"operation": "get_info", "path": str(path), "success": False, "info": None, "error": None}

        try:
            if not path.exists():
                result["error"] = "Path does not exist"
                return json.dumps(result, ensure_ascii=False, indent=2)

            stat = path.stat()
            info = {
                "type": "file" if path.is_file() else "directory" if path.is_dir() else "other",
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "permissions": oct(stat.st_mode)[-3:],
            }

            if path.is_dir():
                try:
                    info["item_count"] = len(list(path.iterdir()))
                except PermissionError:
                    info["item_count"] = None

            result["success"] = True
            result["info"] = info

            return json.dumps(result, ensure_ascii=False, indent=2)

        except PermissionError:
            result["error"] = "Permission denied"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)
