"""Test fs_file_operations function."""
import json
import shutil
from pathlib import Path

from yaicli.functions.buildin.fs_file_operations import Function


class TestFSFileOperations:
    def test_execute_create_dir(self, tmp_path):
        """Test creating a directory."""
        new_dir = tmp_path / "new_directory"
        result = Function.execute("create_dir", str(new_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["message"] == "Directory created"
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_execute_create_dir_already_exists(self, tmp_path):
        """Test creating a directory that already exists."""
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()
        
        result = Function.execute("create_dir", str(existing_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["message"] == "Directory already exists"

    def test_execute_create_dir_nested(self, tmp_path):
        """Test creating nested directories."""
        nested_dir = tmp_path / "parent" / "child" / "grandchild"
        result = Function.execute("create_dir", str(nested_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert nested_dir.exists()
        assert nested_dir.is_dir()

    def test_execute_create_dir_path_is_file(self, tmp_path):
        """Test creating a directory when path is a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        result = Function.execute("create_dir", str(test_file))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "not a directory" in result_dict["error"].lower()

    def test_execute_delete_file(self, tmp_path):
        """Test deleting a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        result = Function.execute("delete", str(test_file))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["type"] == "file"
        assert result_dict["message"] == "File deleted"
        assert not test_file.exists()

    def test_execute_delete_directory(self, tmp_path):
        """Test deleting a directory."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")
        
        result = Function.execute("delete", str(test_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["type"] == "directory"
        assert result_dict["message"] == "Directory deleted"
        assert not test_dir.exists()

    def test_execute_delete_nonexistent(self, tmp_path):
        """Test deleting a non-existent path."""
        nonexistent = tmp_path / "nonexistent"
        
        result = Function.execute("delete", str(nonexistent))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert result_dict["error"] == "Path does not exist"

    def test_execute_delete_system_directory(self):
        """Test that deleting system directories is blocked."""
        result = Function.execute("delete", "/etc/passwd")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Cannot delete from system directory" in result_dict["error"]

    def test_execute_move_file(self, tmp_path):
        """Test moving a file."""
        src_file = tmp_path / "source.txt"
        src_file.write_text("content")
        dest_file = tmp_path / "destination.txt"
        
        result = Function.execute("move", str(src_file), str(dest_file))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["message"] == "Moved successfully"
        assert not src_file.exists()
        assert dest_file.exists()
        assert dest_file.read_text() == "content"

    def test_execute_move_directory(self, tmp_path):
        """Test moving a directory."""
        src_dir = tmp_path / "source_dir"
        src_dir.mkdir()
        (src_dir / "file.txt").write_text("content")
        dest_dir = tmp_path / "dest_dir"
        
        result = Function.execute("move", str(src_dir), str(dest_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert not src_dir.exists()
        assert dest_dir.exists()
        assert (dest_dir / "file.txt").exists()

    def test_execute_move_to_directory(self, tmp_path):
        """Test moving a file into a directory."""
        src_file = tmp_path / "source.txt"
        src_file.write_text("content")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        
        result = Function.execute("move", str(src_file), str(dest_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert not src_file.exists()
        assert (dest_dir / "source.txt").exists()

    def test_execute_move_no_destination(self, tmp_path):
        """Test move operation without destination."""
        src_file = tmp_path / "test.txt"
        src_file.write_text("content")
        
        result = Function.execute("move", str(src_file))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Destination path is required" in result_dict["error"]

    def test_execute_move_nonexistent_source(self, tmp_path):
        """Test moving a non-existent file."""
        result = Function.execute("move", "/nonexistent/file.txt", str(tmp_path / "dest.txt"))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert result_dict["error"] == "Source does not exist"

    def test_execute_move_system_directory(self):
        """Test that moving from/to system directories is blocked."""
        result = Function.execute("move", "/etc/passwd", "/tmp/test")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Cannot move to/from system directories" in result_dict["error"]

    def test_execute_copy_file(self, tmp_path):
        """Test copying a file."""
        src_file = tmp_path / "source.txt"
        src_file.write_text("content")
        dest_file = tmp_path / "destination.txt"
        
        result = Function.execute("copy", str(src_file), str(dest_file))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["type"] == "file"
        assert result_dict["message"] == "File copied"
        assert src_file.exists()
        assert dest_file.exists()
        assert dest_file.read_text() == "content"

    def test_execute_copy_directory(self, tmp_path):
        """Test copying a directory."""
        src_dir = tmp_path / "source_dir"
        src_dir.mkdir()
        (src_dir / "file.txt").write_text("content")
        dest_dir = tmp_path / "dest_dir"
        
        result = Function.execute("copy", str(src_dir), str(dest_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["type"] == "directory"
        assert src_dir.exists()
        assert dest_dir.exists()
        assert (dest_dir / "file.txt").exists()

    def test_execute_copy_to_directory(self, tmp_path):
        """Test copying a file into a directory."""
        src_file = tmp_path / "source.txt"
        src_file.write_text("content")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        
        result = Function.execute("copy", str(src_file), str(dest_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert src_file.exists()
        assert (dest_dir / "source.txt").exists()

    def test_execute_copy_no_destination(self, tmp_path):
        """Test copy operation without destination."""
        src_file = tmp_path / "test.txt"
        src_file.write_text("content")
        
        result = Function.execute("copy", str(src_file))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Destination path is required" in result_dict["error"]

    def test_execute_copy_nonexistent_source(self, tmp_path):
        """Test copying a non-existent file."""
        result = Function.execute("copy", "/nonexistent/file.txt", str(tmp_path / "dest.txt"))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert result_dict["error"] == "Source does not exist"

    def test_execute_copy_to_system_directory(self):
        """Test that copying to system directories is blocked."""
        result = Function.execute("copy", "/tmp/test", "/etc/passwd")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Cannot copy to system directory" in result_dict["error"]

    def test_execute_exists_file(self, tmp_path):
        """Test checking if a file exists."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        result = Function.execute("exists", str(test_file))
        result_dict = json.loads(result)
        
        assert result_dict["exists"] is True
        assert result_dict["type"] == "file"
        assert result_dict["size"] > 0

    def test_execute_exists_directory(self, tmp_path):
        """Test checking if a directory exists."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        
        result = Function.execute("exists", str(test_dir))
        result_dict = json.loads(result)
        
        assert result_dict["exists"] is True
        assert result_dict["type"] == "directory"
        assert result_dict["size"] is None

    def test_execute_exists_nonexistent(self, tmp_path):
        """Test checking if a non-existent path exists."""
        result = Function.execute("exists", str(tmp_path / "nonexistent"))
        result_dict = json.loads(result)
        
        assert result_dict["exists"] is False
        assert result_dict["type"] is None
        assert result_dict["size"] is None

    def test_execute_get_info_file(self, tmp_path):
        """Test getting information about a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        result = Function.execute("get_info", str(test_file))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["info"]["type"] == "file"
        assert result_dict["info"]["size"] > 0
        assert "modified" in result_dict["info"]
        assert "created" in result_dict["info"]
        assert "permissions" in result_dict["info"]

    def test_execute_get_info_directory(self, tmp_path):
        """Test getting information about a directory."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")
        
        result = Function.execute("get_info", str(test_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["info"]["type"] == "directory"
        assert result_dict["info"]["item_count"] == 1

    def test_execute_get_info_nonexistent(self, tmp_path):
        """Test getting information about a non-existent path."""
        result = Function.execute("get_info", str(tmp_path / "nonexistent"))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert result_dict["error"] == "Path does not exist"

    def test_execute_unknown_operation(self, tmp_path):
        """Test with an unknown operation."""
        result = Function.execute("unknown_op", str(tmp_path))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Unknown operation" in result_dict["error"]
