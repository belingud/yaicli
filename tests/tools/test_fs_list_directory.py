"""Test fs_list_directory function."""
import json
from pathlib import Path

from yaicli.functions.buildin.fs_list_directory import Function


class TestFSListDirectory:
    def test_execute_default(self, tmp_path):
        """Test listing directory with default parameters."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "subdir").mkdir()
        
        result = Function.execute(str(tmp_path))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["path"] == str(tmp_path)
        assert "items" in result_dict
        assert len(result_dict["items"]) == 3

    def test_execute_show_hidden_files(self, tmp_path):
        """Test listing directory with hidden files."""
        (tmp_path / "normal.txt").write_text("content")
        (tmp_path / ".hidden.txt").write_text("hidden")
        
        result = Function.execute(str(tmp_path), show_hidden=True)
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        item_names = [item["name"] for item in result_dict["items"]]
        assert "normal.txt" in item_names
        assert ".hidden.txt" in item_names

    def test_execute_hide_hidden_files(self, tmp_path):
        """Test listing directory without hidden files."""
        (tmp_path / "normal.txt").write_text("content")
        (tmp_path / ".hidden.txt").write_text("hidden")
        
        result = Function.execute(str(tmp_path), show_hidden=False)
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        item_names = [item["name"] for item in result_dict["items"]]
        assert "normal.txt" in item_names
        assert ".hidden.txt" not in item_names

    def test_execute_recursive(self, tmp_path):
        """Test recursive directory listing."""
        (tmp_path / "file1.txt").write_text("content1")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("content2")
        nested = subdir / "nested"
        nested.mkdir()
        (nested / "file3.txt").write_text("content3")
        
        result = Function.execute(str(tmp_path), recursive=True)
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert len(result_dict["items"]) == 5
        
        item_names = [item["name"] for item in result_dict["items"]]
        assert "file1.txt" in item_names
        assert "file2.txt" in item_names
        assert "file3.txt" in item_names

    def test_execute_non_recursive(self, tmp_path):
        """Test non-recursive directory listing."""
        (tmp_path / "file1.txt").write_text("content1")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("content2")
        
        result = Function.execute(str(tmp_path), recursive=False)
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert len(result_dict["items"]) == 2
        
        item_names = [item["name"] for item in result_dict["items"]]
        assert "file1.txt" in item_names
        assert "subdir" in item_names

    def test_execute_empty_directory(self, tmp_path):
        """Test listing an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        
        result = Function.execute(str(empty_dir))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert len(result_dict["items"]) == 0

    def test_execute_nonexistent_directory(self):
        """Test listing a non-existent directory."""
        result = Function.execute("/nonexistent/directory")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Directory does not exist" in result_dict["error"]

    def test_execute_path_is_file(self, tmp_path):
        """Test listing when path is a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        result = Function.execute(str(test_file))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Not a directory" in result_dict["error"]

    def test_execute_item_structure(self, tmp_path):
        """Test that items have correct structure."""
        (tmp_path / "test.txt").write_text("content")
        (tmp_path / "test_dir").mkdir()
        
        result = Function.execute(str(tmp_path))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        
        for item in result_dict["items"]:
            assert "name" in item
            assert "type" in item
            assert "size" in item
            assert "path" in item
            assert item["type"] in ["file", "directory", "other"]

    def test_execute_file_size(self, tmp_path):
        """Test that file sizes are correct."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")
        
        result = Function.execute(str(tmp_path))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        
        file_item = next(item for item in result_dict["items"] if item["name"] == "test.txt")
        assert file_item["size"] == 11

    def test_execute_directory_size(self, tmp_path):
        """Test that directory sizes are None."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        
        result = Function.execute(str(tmp_path))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        
        dir_item = next(item for item in result_dict["items"] if item["name"] == "test_dir")
        assert dir_item["size"] is None

    def test_execute_item_paths(self, tmp_path):
        """Test that item paths are correct (relative paths)."""
        (tmp_path / "test.txt").write_text("content")
        
        result = Function.execute(str(tmp_path))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        
        file_item = result_dict["items"][0]
        assert file_item["path"] == "test.txt"

    def test_execute_recursive_item_paths(self, tmp_path):
        """Test that recursive listing has correct paths (relative paths)."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "test.txt").write_text("content")
        
        result = Function.execute(str(tmp_path), recursive=True)
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        
        file_item = next(item for item in result_dict["items"] if item["name"] == "test.txt")
        assert file_item["path"] == "subdir/test.txt"

    def test_execute_special_characters_in_names(self, tmp_path):
        """Test listing files with special characters in names."""
        (tmp_path / "file with spaces.txt").write_text("content")
        (tmp_path / "file-with-dashes.txt").write_text("content")
        (tmp_path / "file_with_underscores.txt").write_text("content")
        
        result = Function.execute(str(tmp_path))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        item_names = [item["name"] for item in result_dict["items"]]
        assert "file with spaces.txt" in item_names
        assert "file-with-dashes.txt" in item_names
        assert "file_with_underscores.txt" in item_names

    def test_execute_returns_json_string(self, tmp_path):
        """Test that execute returns a valid JSON string."""
        result = Function.execute(str(tmp_path))
        
        assert isinstance(result, str)
        
        result_dict = json.loads(result)
        assert isinstance(result_dict, dict)

    def test_execute_symlinks(self, tmp_path):
        """Test listing directory with symlinks."""
        (tmp_path / "original.txt").write_text("content")
        (tmp_path / "link.txt").symlink_to("original.txt")
        
        result = Function.execute(str(tmp_path))
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        item_names = [item["name"] for item in result_dict["items"]]
        assert "original.txt" in item_names
        assert "link.txt" in item_names
