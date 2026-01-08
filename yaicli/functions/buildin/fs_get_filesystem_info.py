import json
import os
import platform
import shutil
from pathlib import Path

from instructor import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """
    Get information about the filesystem and system configuration as JSON.
    """

    include_disk_usage: bool = Field(
        default=True,
        json_schema_extra={
            "example": True,
        },
        description="Include disk usage information for common mount points.",
    )

    class Config:
        title = "fs_get_filesystem_info"

    @classmethod
    def execute(cls, include_disk_usage: bool = True) -> str:
        """
        Get filesystem and system information as JSON.

        Args:
            include_disk_usage: Include disk usage information.

        Returns:
            str: JSON string with system and filesystem information.
        """
        result = {
            "success": True,
            "system": {},
            "directories": {},
            "environment": {},
            "disk_usage": [],
            "filesystem_limits": {},
            "error": None,
        }

        try:
            # System Information
            result["system"] = {
                "os": platform.system(),
                "os_version": platform.release(),
                "platform": platform.platform(),
                "architecture": platform.machine(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
            }

            # Current Directory Information
            result["directories"] = {"working_directory": str(Path.cwd()), "home_directory": str(Path.home())}

            # Environment Variables (selected)
            important_vars = ["PATH", "HOME", "USER", "SHELL", "TMPDIR", "TEMP", "TMP"]
            env_vars = {}
            for var in important_vars:
                value = os.environ.get(var)
                if value:
                    # Truncate long values
                    if len(value) > 100:
                        value = value[:100] + "..."
                    env_vars[var] = value
            result["environment"] = env_vars

            # Disk Usage
            if include_disk_usage:
                paths_to_check = [
                    Path.home(),
                    Path.cwd(),
                    Path("/tmp") if os.path.exists("/tmp") else None,
                    Path("/"),
                ]

                checked_devices = set()
                disk_usage_list = []

                for path in paths_to_check:
                    if path is None:
                        continue

                    try:
                        usage = shutil.disk_usage(path)

                        # Get device/mount point (avoid duplicates)
                        mount_point = cls._get_mount_point(path)
                        if mount_point in checked_devices:
                            continue
                        checked_devices.add(mount_point)

                        total = usage.total
                        used = usage.used
                        free = usage.free
                        percent = (used / total * 100) if total > 0 else 0

                        disk_usage_list.append(
                            {
                                "mount_point": mount_point,
                                "total": total,
                                "used": used,
                                "free": free,
                                "percent_used": round(percent, 2),
                            }
                        )

                    except Exception:
                        pass  # Skip paths that can't be accessed

                result["disk_usage"] = disk_usage_list

            # File System Limits
            try:
                if hasattr(os, "pathconf"):
                    name_max = os.pathconf("/", "PC_NAME_MAX")
                    path_max = os.pathconf("/", "PC_PATH_MAX")
                    result["filesystem_limits"] = {"max_filename_length": name_max, "max_path_length": path_max}
                else:
                    result["filesystem_limits"] = {"available": False, "message": "Not available on this platform"}
            except Exception:
                result["filesystem_limits"] = {"available": False, "message": "Unable to determine"}

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _get_mount_point(path: Path) -> str:
        """Get the mount point for a given path."""
        path = path.resolve()
        while not path.is_mount():
            parent = path.parent
            if parent == path:
                break
            path = parent
        return str(path)
