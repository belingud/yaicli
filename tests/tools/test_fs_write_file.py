"""Test fs_write_file function."""

import json

from yaicli.functions.buildin.fs_write_file import Function


class TestFSWriteFile:
    def test_execute_write_new_file(self, tmp_path):
        """Test writing to a new file."""
        test_file = tmp_path / "test.txt"

        result = Function.execute(str(test_file), "Hello World")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["path"] == str(test_file)
        assert result_dict["size"] == 11
        assert result_dict["mode"] == "write"
        assert test_file.exists()
        assert test_file.read_text() == "Hello World"

    def test_execute_overwrite_existing_file(self, tmp_path):
        """Test overwriting an existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Original content")

        result = Function.execute(str(test_file), "New content")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["size"] == 11
        assert test_file.read_text() == "New content"

    def test_execute_append_to_file(self, tmp_path):
        """Test appending to an existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Original content")

        result = Function.execute(str(test_file), " Appended", append=True)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["mode"] == "append"
        assert test_file.read_text() == "Original content Appended"

    def test_execute_append_to_nonexistent_file(self, tmp_path):
        """Test appending to a non-existent file."""
        test_file = tmp_path / "test.txt"

        result = Function.execute(str(test_file), "New content", append=True)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["mode"] == "append"
        assert test_file.read_text() == "New content"

    def test_execute_empty_content(self, tmp_path):
        """Test writing empty content."""
        test_file = tmp_path / "test.txt"

        result = Function.execute(str(test_file), "")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["size"] == 0
        assert test_file.read_text() == ""

    def test_execute_large_content(self, tmp_path):
        """Test writing large content."""
        test_file = tmp_path / "test.txt"
        content = "Line\n" * 10000

        result = Function.execute(str(test_file), content)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["size"] == len(content)
        assert test_file.read_text() == content

    def test_execute_multiline_content(self, tmp_path):
        """Test writing multiline content."""
        test_file = tmp_path / "test.txt"
        content = "Line 1\nLine 2\nLine 3"

        result = Function.execute(str(test_file), content)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text() == content

    def test_execute_special_characters(self, tmp_path):
        """Test writing special characters."""
        test_file = tmp_path / "test.txt"
        content = "Hello 世界! 🌍\nTest\tTabbed"

        result = Function.execute(str(test_file), content, encoding="utf-8")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text(encoding="utf-8") == content

    def test_execute_with_custom_encoding(self, tmp_path):
        """Test writing with custom encoding."""
        test_file = tmp_path / "test.txt"
        content = "Hello World"

        result = Function.execute(str(test_file), content, encoding="utf-8")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text(encoding="utf-8") == content

    def test_execute_path_is_directory(self, tmp_path):
        """Test writing when path is a directory."""
        result = Function.execute(str(tmp_path), "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Is a directory" in result_dict["error"]

    def test_execute_parent_directory_not_exists(self, tmp_path):
        """Test writing when parent directory doesn't exist (should create it)."""
        test_file = tmp_path / "nonexistent" / "test.txt"

        result = Function.execute(str(test_file), "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.exists()
        assert test_file.read_text() == "content"

    def test_execute_write_to_system_directory(self):
        """Test that writing to system directories is blocked."""
        result = Function.execute("/etc/test.txt", "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Permission denied" in result_dict["error"]

    def test_execute_append_to_system_directory(self):
        """Test that appending to system directories is blocked."""
        result = Function.execute("/etc/test.txt", "content", append=True)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Permission denied" in result_dict["error"]

    def test_execute_result_structure(self, tmp_path):
        """Test that result has correct structure."""
        test_file = tmp_path / "test.txt"

        result = Function.execute(str(test_file), "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "path" in result_dict
        assert "size" in result_dict
        assert "mode" in result_dict
        assert "error" in result_dict

    def test_execute_size_accuracy(self, tmp_path):
        """Test that size is accurate."""
        test_file = tmp_path / "test.txt"
        content = "Hello World"

        result = Function.execute(str(test_file), content)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["size"] == len(content)

    def test_execute_returns_json_string(self, tmp_path):
        """Test that execute returns a valid JSON string."""
        test_file = tmp_path / "test.txt"

        result = Function.execute(str(test_file), "content")

        assert isinstance(result, str)

        result_dict = json.loads(result)
        assert isinstance(result_dict, dict)

    def test_execute_write_with_tabs(self, tmp_path):
        """Test writing content with tabs."""
        test_file = tmp_path / "test.txt"
        content = "Column1\tColumn2\tColumn3"

        result = Function.execute(str(test_file), content)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text() == content

    def test_execute_write_with_newlines(self, tmp_path):
        """Test writing content with different newline types."""
        test_file = tmp_path / "test.txt"
        content = "Line 1\r\nLine 2\rLine 3\n"

        result = Function.execute(str(test_file), content)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text() == "Line 1\nLine 2\nLine 3\n"

    def test_execute_append_preserves_existing_content(self, tmp_path):
        """Test that append preserves existing content."""
        test_file = tmp_path / "test.txt"
        original = "Original content"
        test_file.write_text(original)

        result = Function.execute(str(test_file), " Appended", append=True)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text().startswith(original)

    def test_execute_write_creates_parent_directories(self, tmp_path):
        """Test that write creates parent directories."""
        test_file = tmp_path / "nonexistent" / "nested" / "test.txt"

        result = Function.execute(str(test_file), "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.exists()
        assert test_file.read_text() == "content"

    def test_execute_write_binary_like_content(self, tmp_path):
        """Test writing binary-like content."""
        test_file = tmp_path / "test.txt"
        content = "Binary\x00data\x01here"

        result = Function.execute(str(test_file), content)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text() == content

    def test_execute_write_unicode_content(self, tmp_path):
        """Test writing unicode content."""
        test_file = tmp_path / "test.txt"
        content = "Hello 世界! Привет! مرحبا! こんにちは!"

        result = Function.execute(str(test_file), content, encoding="utf-8")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text(encoding="utf-8") == content

    def test_execute_overwrite_large_file(self, tmp_path):
        """Test overwriting a large file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("X" * 10000)

        result = Function.execute(str(test_file), "New content")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text() == "New content"
        assert result_dict["size"] == 11

    def test_execute_append_multiple_times(self, tmp_path):
        """Test appending multiple times."""
        test_file = tmp_path / "test.txt"

        Function.execute(str(test_file), "First", append=True)
        Function.execute(str(test_file), " Second", append=True)
        Function.execute(str(test_file), " Third", append=True)

        assert test_file.read_text() == "First Second Third"

    def test_execute_write_empty_file(self, tmp_path):
        """Test writing to an empty file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        result = Function.execute(str(test_file), "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text() == "content"

    def test_execute_error_field_none_on_success(self, tmp_path):
        """Test that error field is None on success."""
        test_file = tmp_path / "test.txt"

        result = Function.execute(str(test_file), "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["error"] is None

    def test_execute_error_field_set_on_failure(self, tmp_path):
        """Test that error field is set on failure."""
        result = Function.execute("/etc/test.txt", "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["error"] is not None

    def test_execute_write_to_readonly_directory(self, tmp_path):
        """Test writing to a read-only directory."""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)

        test_file = readonly_dir / "test.txt"

        try:
            result = Function.execute(str(test_file), "content")
            result_dict = json.loads(result)

            assert result_dict["success"] is False
            assert "Permission denied" in result_dict["error"]
        finally:
            readonly_dir.chmod(0o755)

    def test_execute_mode_write(self, tmp_path):
        """Test that mode is 'write' when not appending."""
        test_file = tmp_path / "test.txt"

        result = Function.execute(str(test_file), "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["mode"] == "write"

    def test_execute_mode_append(self, tmp_path):
        """Test that mode is 'append' when appending."""
        test_file = tmp_path / "test.txt"

        result = Function.execute(str(test_file), "content", append=True)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["mode"] == "append"

    def test_execute_expands_tilde(self, tmp_path):
        """Test that tilde is expanded in path."""
        test_file = tmp_path / "test.txt"

        result = Function.execute(str(test_file), "content")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.exists()
