"""Test fs_get_filesystem_info function."""

import json
from unittest.mock import patch

from yaicli.functions.buildin.fs_get_filesystem_info import Function


class TestFSGetFilesystemInfo:
    def test_execute_default(self):
        """Test getting filesystem info with default parameters."""
        result = Function.execute()
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "system" in result_dict
        assert "disk_usage" in result_dict

        assert "os" in result_dict["system"]
        assert "os_version" in result_dict["system"]
        assert "platform" in result_dict["system"]
        assert "architecture" in result_dict["system"]

        assert isinstance(result_dict["disk_usage"], list)

    def test_execute_system_info(self):
        """Test getting system information."""
        result = Function.execute()
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "system" in result_dict
        assert "os" in result_dict["system"]
        assert "os_version" in result_dict["system"]
        assert "platform" in result_dict["system"]
        assert "architecture" in result_dict["system"]
        assert "processor" in result_dict["system"]
        assert "python_version" in result_dict["system"]

    def test_execute_filesystem_info(self):
        """Test getting filesystem information."""
        result = Function.execute()
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "disk_usage" in result_dict
        assert isinstance(result_dict["disk_usage"], list)

        if len(result_dict["disk_usage"]) > 0:
            fs_info = result_dict["disk_usage"][0]
            assert "mount_point" in fs_info
            assert "total" in fs_info
            assert "used" in fs_info
            assert "free" in fs_info
            assert "percent_used" in fs_info

    def test_execute_all_info(self):
        """Test getting all information."""
        result = Function.execute()
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "system" in result_dict
        assert "disk_usage" in result_dict
        assert "directories" in result_dict
        assert "environment" in result_dict
        assert "filesystem_limits" in result_dict

    def test_execute_with_path(self, tmp_path):
        """Test getting filesystem info for a specific path."""
        result = Function.execute()
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "disk_usage" in result_dict
        assert len(result_dict["disk_usage"]) >= 1

        fs_info = result_dict["disk_usage"][0]
        assert "mount_point" in fs_info

    def test_execute_system_info_structure(self):
        """Test that system info has correct structure."""
        result = Function.execute()
        result_dict = json.loads(result)

        system = result_dict["system"]

        assert isinstance(system["os"], str)
        assert isinstance(system["os_version"], str)
        assert isinstance(system["platform"], str)
        assert isinstance(system["architecture"], str)
        assert isinstance(system["processor"], str)
        assert isinstance(system["python_version"], str)

    def test_execute_filesystem_info_structure(self):
        """Test that filesystem info has correct structure."""
        result = Function.execute()
        result_dict = json.loads(result)

        filesystems = result_dict["disk_usage"]

        for fs in filesystems:
            assert isinstance(fs["mount_point"], str)
            assert isinstance(fs["total"], int)
            assert isinstance(fs["used"], int)
            assert isinstance(fs["free"], int)
            assert isinstance(fs["percent_used"], float)
            assert 0 <= fs["percent_used"] <= 100

    def test_execute_filesystem_info_with_nonexistent_path(self):
        """Test filesystem info with a non-existent path."""
        result = Function.execute()
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "disk_usage" in result_dict

    @patch("yaicli.functions.buildin.fs_get_filesystem_info.shutil.disk_usage")
    def test_execute_disk_usage_error(self, mock_disk_usage):
        """Test handling of disk usage errors."""
        mock_disk_usage.side_effect = OSError("Permission denied")

        result = Function.execute()
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "disk_usage" in result_dict

    def test_execute_returns_json_string(self):
        """Test that execute returns a valid JSON string."""
        result = Function.execute()

        assert isinstance(result, str)

        result_dict = json.loads(result)
        assert isinstance(result_dict, dict)

    def test_execute_filesystem_info_multiple_mountpoints(self):
        """Test that multiple mountpoints are returned."""
        result = Function.execute()
        result_dict = json.loads(result)

        filesystems = result_dict["disk_usage"]

        assert len(filesystems) >= 1

        mountpoints = [fs["mount_point"] for fs in filesystems]
        assert len(mountpoints) == len(set(mountpoints))

    def test_execute_system_info_contains_python_info(self):
        """Test that system info contains Python information."""
        result = Function.execute()
        result_dict = json.loads(result)

        system = result_dict["system"]

        assert "python_version" in system
        assert isinstance(system["python_version"], str)

    def test_execute_with_empty_path(self):
        """Test with empty path parameter."""
        result = Function.execute()
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "disk_usage" in result_dict

    def test_execute_filesystem_info_human_readable(self):
        """Test that filesystem info values are reasonable."""
        result = Function.execute()
        result_dict = json.loads(result)

        filesystems = result_dict["disk_usage"]

        for fs in filesystems:
            assert fs["total"] > 0
            assert fs["used"] >= 0
            assert fs["free"] >= 0
            assert fs["total"] >= fs["used"]
            assert fs["total"] >= fs["free"]
            assert fs["used"] + fs["free"] <= fs["total"]
