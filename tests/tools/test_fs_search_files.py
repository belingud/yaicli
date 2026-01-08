"""Test fs_search_files function."""
import json
from pathlib import Path

from yaicli.functions.buildin.fs_search_files import Function


class TestFSSearchFiles:
    def test_execute_default(self, tmp_path):
        """Test searching files with default parameters."""
        (tmp_path / "test1.txt").write_text("content1")
        (tmp_path / "test2.txt").write_text("content2")
        
        result = Function.execute(str(tmp_path), "test*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["search_path"] == str(tmp_path)
        assert result_dict["pattern"] == "test*.txt"
        assert "matches" in result_dict
        assert len(result_dict["matches"]) == 2

    def test_execute_with_wildcard(self, tmp_path):
        """Test searching with wildcard pattern."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "other.txt").write_text("content3")
        
        result = Function.execute(str(tmp_path), "file*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "file1.txt" in file_names
        assert "file2.txt" in file_names
        assert "other.txt" not in file_names

    def test_execute_recursive(self, tmp_path):
        """Test recursive search (always recursive in implementation)."""
        (tmp_path / "file1.txt").write_text("content1")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("content2")
        nested = subdir / "nested"
        nested.mkdir()
        (nested / "file3.txt").write_text("content3")
        
        result = Function.execute(str(tmp_path), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert len(result_dict["matches"]) == 3

    def test_execute_with_exclude(self, tmp_path):
        """Test searching with exclude patterns."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.py").write_text("content2")
        (tmp_path / "test.txt").write_text("content3")
        
        result = Function.execute(str(tmp_path), "*.txt", exclude_patterns=["test*"])
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "file1.txt" in file_names
        assert "test.txt" not in file_names

    def test_execute_with_multiple_excludes(self, tmp_path):
        """Test searching with multiple exclude patterns."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "test.txt").write_text("content3")
        (tmp_path / "other.txt").write_text("content4")
        
        result = Function.execute(str(tmp_path), "*.txt", exclude_patterns=["test*", "other*"])
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "file1.txt" in file_names
        assert "file2.txt" in file_names
        assert "test.txt" not in file_names
        assert "other.txt" not in file_names

    def test_execute_no_matches(self, tmp_path):
        """Test searching when no files match."""
        (tmp_path / "file1.txt").write_text("content1")
        
        result = Function.execute(str(tmp_path), "*.py")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert len(result_dict["matches"]) == 0

    def test_execute_nonexistent_directory(self):
        """Test searching in a non-existent directory."""
        result = Function.execute("/nonexistent/directory", "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Search path does not exist" in result_dict["error"]

    def test_execute_path_is_file(self, tmp_path):
        """Test searching when path is a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        result = Function.execute(str(test_file), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is False
        assert "Search path is not a directory" in result_dict["error"]

    def test_execute_file_structure(self, tmp_path):
        """Test that file info has correct structure."""
        (tmp_path / "test.txt").write_text("content")
        
        result = Function.execute(str(tmp_path), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        
        file_info = result_dict["matches"][0]
        assert "path" in file_info
        assert "name" in file_info
        assert "size" in file_info
        assert "full_path" in file_info
        assert "directory" in file_info

    def test_execute_file_size(self, tmp_path):
        """Test that file sizes are correct."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")
        
        result = Function.execute(str(tmp_path), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["matches"][0]["size"] == 11

    def test_execute_file_paths(self, tmp_path):
        """Test that file paths are correct."""
        (tmp_path / "test.txt").write_text("content")
        
        result = Function.execute(str(tmp_path), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["matches"][0]["full_path"] == str(tmp_path / "test.txt")

    def test_execute_recursive_file_paths(self, tmp_path):
        """Test that recursive search has correct paths."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "test.txt").write_text("content")
        
        result = Function.execute(str(tmp_path), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["matches"][0]["full_path"] == str(subdir / "test.txt")

    def test_execute_case_sensitive(self, tmp_path):
        """Test case-sensitive search."""
        (tmp_path / "file.txt").write_text("content1")
        (tmp_path / "File.txt").write_text("content2")
        
        result = Function.execute(str(tmp_path), "file.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "file.txt" in file_names

    def test_execute_with_question_mark(self, tmp_path):
        """Test searching with question mark wildcard."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "file10.txt").write_text("content3")
        
        result = Function.execute(str(tmp_path), "file?.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "file1.txt" in file_names
        assert "file2.txt" in file_names
        assert "file10.txt" not in file_names

    def test_execute_with_brackets(self, tmp_path):
        """Test searching with bracket patterns."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "file3.txt").write_text("content3")
        
        result = Function.execute(str(tmp_path), "file[12].txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "file1.txt" in file_names
        assert "file2.txt" in file_names
        assert "file3.txt" not in file_names

    def test_execute_hidden_files(self, tmp_path):
        """Test searching for hidden files."""
        (tmp_path / "normal.txt").write_text("content1")
        (tmp_path / ".hidden.txt").write_text("content2")
        
        result = Function.execute(str(tmp_path), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "normal.txt" in file_names
        assert ".hidden.txt" in file_names

    def test_execute_exclude_hidden_files(self, tmp_path):
        """Test excluding hidden files."""
        (tmp_path / "normal.txt").write_text("content1")
        (tmp_path / ".hidden.txt").write_text("content2")
        
        result = Function.execute(str(tmp_path), "*.txt", exclude_patterns=[".*"])
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "normal.txt" in file_names
        assert ".hidden.txt" not in file_names

    def test_execute_empty_directory(self, tmp_path):
        """Test searching in an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        
        result = Function.execute(str(empty_dir), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert len(result_dict["matches"]) == 0

    def test_execute_returns_json_string(self, tmp_path):
        """Test that execute returns a valid JSON string."""
        (tmp_path / "test.txt").write_text("content")
        
        result = Function.execute(str(tmp_path), "*.txt")
        
        assert isinstance(result, str)
        
        result_dict = json.loads(result)
        assert isinstance(result_dict, dict)

    def test_execute_with_special_characters(self, tmp_path):
        """Test searching files with special characters."""
        (tmp_path / "file with spaces.txt").write_text("content1")
        (tmp_path / "file-with-dashes.txt").write_text("content2")
        
        result = Function.execute(str(tmp_path), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "file with spaces.txt" in file_names
        assert "file-with-dashes.txt" in file_names

    def test_execute_recursive_exclude(self, tmp_path):
        """Test excluding files in recursive search."""
        (tmp_path / "file1.txt").write_text("content1")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("content2")
        (subdir / "test.txt").write_text("content3")
        
        result = Function.execute(str(tmp_path), "*.txt", exclude_patterns=["test*"])
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert "file1.txt" in file_names
        assert "file2.txt" in file_names
        assert "test.txt" not in file_names

    def test_execute_directory_pattern(self, tmp_path):
        """Test searching for directories."""
        (tmp_path / "file.txt").write_text("content")
        (tmp_path / "dir1").mkdir()
        (tmp_path / "dir2").mkdir()
        
        result = Function.execute(str(tmp_path), "dir*")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        file_names = [f["name"] for f in result_dict["matches"]]
        assert len(file_names) == 0
        assert "file.txt" not in file_names

    def test_execute_all_files(self, tmp_path):
        """Test searching for all files."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.py").write_text("content2")
        (tmp_path / "dir").mkdir()
        
        result = Function.execute(str(tmp_path), "*")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert len(result_dict["matches"]) == 2

    def test_execute_max_results(self, tmp_path):
        """Test max_results parameter."""
        for i in range(10):
            (tmp_path / f"file{i}.txt").write_text(f"content{i}")
        
        result = Function.execute(str(tmp_path), "*.txt", max_results=5)
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert len(result_dict["matches"]) == 5
        assert result_dict["truncated"] is True

    def test_execute_excluded_count(self, tmp_path):
        """Test excluded_count in result."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.pyc").write_text("content2")
        (tmp_path / "test.txt").write_text("content3")
        
        result = Function.execute(str(tmp_path), "*.txt", exclude_patterns=["test*"])
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["excluded_count"] >= 1

    def test_execute_total_scanned(self, tmp_path):
        """Test total_scanned in result."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "file3.py").write_text("content3")
        
        result = Function.execute(str(tmp_path), "*.txt")
        result_dict = json.loads(result)
        
        assert result_dict["success"] is True
        assert result_dict["total_scanned"] == 3
        assert result_dict["match_count"] == 2
