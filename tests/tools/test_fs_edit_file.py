"""Test fs_edit_file function."""

import json

from yaicli.functions.buildin.fs_edit_file import Function


class TestFSEditFile:
    def test_execute_file_not_exists(self):
        """Test editing a non-existent file."""
        result = Function.execute("/nonexistent/file.txt", [])
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["error"] == "File does not exist"

    def test_execute_path_is_directory(self, tmp_path):
        """Test editing when path is a directory."""
        result = Function.execute(str(tmp_path), [])
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["error"] == "Not a file"

    def test_execute_replace_text(self, tmp_path):
        """Test replacing text in a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World\nGoodbye World")

        edits = [{"type": "replace", "old": "World", "new": "Universe"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["original_size"] == 25
        assert result_dict["modified_size"] == 31
        assert len(result_dict["changes"]) == 1
        assert result_dict["changes"][0]["success"] is True
        assert result_dict["changes"][0]["message"] == "Replaced 2 occurrence(s)"

        content = test_file.read_text()
        assert content == "Hello Universe\nGoodbye Universe"

    def test_execute_replace_text_not_found(self, tmp_path):
        """Test replacing text that doesn't exist."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        edits = [{"type": "replace", "old": "Universe", "new": "Galaxy"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["changes"][0]["success"] is False
        assert result_dict["changes"][0]["message"] == "Text not found"

    def test_execute_replace_line(self, tmp_path):
        """Test replacing a specific line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3")

        edits = [{"type": "replace_line", "line_number": "2", "new": "New Line 2"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["changes"][0]["success"] is True
        assert result_dict["changes"][0]["message"] == "Replaced line 2"

        content = test_file.read_text()
        assert "New Line 2" in content

    def test_execute_replace_line_out_of_range(self, tmp_path):
        """Test replacing a line that doesn't exist."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2")

        edits = [{"type": "replace_line", "line_number": "10", "new": "New Line"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["changes"][0]["success"] is False
        assert result_dict["changes"][0]["message"] == "Line 10 out of range"

    def test_execute_insert_line(self, tmp_path):
        """Test inserting a line at a specific position."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 3")

        edits = [{"type": "insert_line", "line_number": "1", "content": "Line 2"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["changes"][0]["success"] is True
        assert result_dict["changes"][0]["message"] == "Inserted line at position 1"

        content = test_file.read_text()
        assert "Line 1\nLine 2\nLine 3" in content

    def test_execute_insert_line_at_end(self, tmp_path):
        """Test inserting a line at the end of the file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2")

        edits = [{"type": "insert_line", "line_number": "2", "content": "Line 3"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["changes"][0]["success"] is True

    def test_execute_delete_line(self, tmp_path):
        """Test deleting a specific line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3")

        edits = [{"type": "delete_line", "line_number": "2"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["changes"][0]["success"] is True
        assert result_dict["changes"][0]["message"] == "Deleted line 2"

        content = test_file.read_text()
        assert "Line 2" not in content

    def test_execute_delete_line_out_of_range(self, tmp_path):
        """Test deleting a line that doesn't exist."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1")

        edits = [{"type": "delete_line", "line_number": "5"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["changes"][0]["success"] is False
        assert result_dict["changes"][0]["message"] == "Line 5 out of range"

    def test_execute_append(self, tmp_path):
        """Test appending content to a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Original content")

        edits = [{"type": "append", "content": "Appended content"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["changes"][0]["success"] is True
        assert result_dict["changes"][0]["message"] == "Appended content"

        content = test_file.read_text()
        assert "Original content" in content
        assert "Appended content" in content

    def test_execute_dry_run(self, tmp_path):
        """Test dry run mode doesn't modify the file."""
        test_file = tmp_path / "test.txt"
        original_content = "Original content"
        test_file.write_text(original_content)

        edits = [{"type": "replace", "old": "Original", "new": "Modified"}]
        result = Function.execute(str(test_file), edits, dry_run=True)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["dry_run"] is True

        content = test_file.read_text()
        assert content == original_content

    def test_execute_multiple_edits(self, tmp_path):
        """Test applying multiple edits in one call."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3")

        edits = [
            {"type": "replace", "old": "Line 1", "new": "First Line"},
            {"type": "replace_line", "line_number": "2", "new": "Second Line"},
            {"type": "append", "content": "Line 4"},
        ]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert len(result_dict["changes"]) == 3
        assert all(change["success"] for change in result_dict["changes"])

    def test_execute_unknown_edit_type(self, tmp_path):
        """Test with an unknown edit type."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")

        edits = [{"type": "unknown_type", "value": "test"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["changes"][0]["success"] is False
        assert "Unknown edit type" in result_dict["changes"][0]["message"]

    def test_execute_empty_file(self, tmp_path):
        """Test editing an empty file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        edits = [{"type": "append", "content": "First line"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["original_size"] == 0
        assert result_dict["modified_size"] > 0

    def test_execute_file_without_newline(self, tmp_path):
        """Test editing a file without trailing newline."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2")

        edits = [{"type": "append", "content": "Line 3"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True

        content = test_file.read_text()
        assert content.endswith("Line 3\n")
