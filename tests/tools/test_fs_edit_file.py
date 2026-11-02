"""Test fs_edit_file function."""

import json
import stat

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

    def test_execute_edits_not_a_list(self, tmp_path):
        """Test that a non-list 'edits' argument is rejected."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = Function.execute(str(test_file), "not-a-list")
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "expected a list" in result_dict["error"]
        assert test_file.read_text() == "Hello World"

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
        """Test that a not-found replace fails the call and leaves the file untouched."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        edits = [{"type": "replace", "old": "Universe", "new": "Galaxy"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "no changes were written" in result_dict["error"]
        assert result_dict["changes"][0]["success"] is False
        assert result_dict["changes"][0]["message"] == "Text not found"
        assert test_file.read_text() == "Hello World"

    def test_execute_replace_empty_old_rejected(self, tmp_path):
        """An empty 'old' must be rejected instead of inserted between every character."""
        test_file = tmp_path / "test.txt"
        original = "def main():\n    return 42\n"
        test_file.write_text(original)

        edits = [{"type": "replace", "old": "", "new": "<X>"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["changes"][0]["success"] is False
        assert "non-empty" in result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

    def test_execute_replace_missing_old_rejected(self, tmp_path):
        """A missing 'old' key must be rejected, not silently default to ''."""
        test_file = tmp_path / "test.txt"
        original = "Hello World"
        test_file.write_text(original)

        edits = [{"type": "replace", "new": "Galaxy"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Missing required key 'old'" == result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

    def test_execute_replace_misnamed_old_key_rejected(self, tmp_path):
        """A misnamed key (e.g. 'old_text') must fail instead of corrupting the file."""
        test_file = tmp_path / "test.txt"
        original = "def main():\n    return 42\n"
        test_file.write_text(original)

        edits = [{"type": "replace", "old_text": "def main()", "new": "def hacked()"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["changes"][0]["success"] is False
        assert "Missing required key 'old'" == result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

    def test_execute_replace_wrong_old_type_rejected(self, tmp_path):
        """A non-string 'old' must be rejected."""
        test_file = tmp_path / "test.txt"
        original = "Hello World"
        test_file.write_text(original)

        edits = [{"type": "replace", "old": 123, "new": "x"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "expected a string" in result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

    def test_execute_replace_identical_old_new_rejected(self, tmp_path):
        """A no-op replace (old == new) must be rejected."""
        test_file = tmp_path / "test.txt"
        original = "Hello World"
        test_file.write_text(original)

        edits = [{"type": "replace", "old": "World", "new": "World"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "identical" in result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

    def test_execute_replace_ignores_unknown_extra_keys(self, tmp_path):
        """Extra keys that are not required may be ignored."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        edits = [{"type": "replace", "old": "World", "new": "There", "comment": "extra key"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text() == "Hello There"

    def test_execute_failure_prevents_partial_write(self, tmp_path):
        """If any edit fails, earlier successful edits must not be written either."""
        test_file = tmp_path / "test.txt"
        original = "Line 1\nLine 2\n"
        test_file.write_text(original)

        edits = [
            {"type": "replace", "old": "Line 1", "new": "First Line"},
            {"type": "replace", "old": "NOT_PRESENT", "new": "x"},
        ]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["changes"][0]["success"] is True
        assert result_dict["changes"][1]["success"] is False
        assert "1 of 2 edit(s) failed" in result_dict["error"]
        assert test_file.read_text() == original

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
        """Test replacing a line that doesn't exist fails without writing."""
        test_file = tmp_path / "test.txt"
        original = "Line 1\nLine 2"
        test_file.write_text(original)

        edits = [{"type": "replace_line", "line_number": "10", "new": "New Line"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["changes"][0]["success"] is False
        assert result_dict["changes"][0]["message"] == "Line 10 out of range"
        assert test_file.read_text() == original

    def test_execute_replace_line_invalid_line_number(self, tmp_path):
        """Test that a non-numeric line_number fails with a clear message."""
        test_file = tmp_path / "test.txt"
        original = "Line 1"
        test_file.write_text(original)

        edits = [{"type": "replace_line", "line_number": "abc", "new": "x"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Invalid 'line_number'" in result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

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

    def test_execute_insert_line_missing_content(self, tmp_path):
        """Test that a missing 'content' key fails the edit."""
        test_file = tmp_path / "test.txt"
        original = "Line 1"
        test_file.write_text(original)

        edits = [{"type": "insert_line", "line_number": "0"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Missing required key 'content'" in result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

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
        """Test deleting a line that doesn't exist fails without writing."""
        test_file = tmp_path / "test.txt"
        original = "Line 1"
        test_file.write_text(original)

        edits = [{"type": "delete_line", "line_number": "5"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["changes"][0]["success"] is False
        assert result_dict["changes"][0]["message"] == "Line 5 out of range"
        assert test_file.read_text() == original

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

    def test_execute_append_missing_content(self, tmp_path):
        """Test that a missing 'content' key fails the append edit."""
        test_file = tmp_path / "test.txt"
        original = "Original content"
        test_file.write_text(original)

        edits = [{"type": "append"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Missing required key 'content'" in result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

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

    def test_execute_dry_run_invalid_edit(self, tmp_path):
        """Test dry run reports failures without modifying the file."""
        test_file = tmp_path / "test.txt"
        original_content = "Original content"
        test_file.write_text(original_content)

        edits = [{"type": "replace", "old": "", "new": "Modified"}]
        result = Function.execute(str(test_file), edits, dry_run=True)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["dry_run"] is True
        assert test_file.read_text() == original_content

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
        """Test with an unknown edit type fails without writing."""
        test_file = tmp_path / "test.txt"
        original = "Test content"
        test_file.write_text(original)

        edits = [{"type": "unknown_type", "value": "test"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["changes"][0]["success"] is False
        assert "Unknown edit type" in result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

    def test_execute_non_dict_edit_rejected(self, tmp_path):
        """Test that a non-object edit entry fails without writing."""
        test_file = tmp_path / "test.txt"
        original = "Test content"
        test_file.write_text(original)

        edits = ["not-an-object"]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "expected an object" in result_dict["changes"][0]["message"]
        assert test_file.read_text() == original

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

    def test_execute_atomic_write_failure_keeps_original(self, tmp_path, monkeypatch):
        """Test that a write failure leaves the original file intact and cleans up temp files."""
        test_file = tmp_path / "test.txt"
        original = "Original content"
        test_file.write_text(original)

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("os.replace", boom)
        edits = [{"type": "replace", "old": "Original", "new": "Modified"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "disk full" in result_dict["error"]
        assert test_file.read_text() == original
        assert list(tmp_path.glob(".*.tmp")) == []

    def test_execute_atomic_write_preserves_permissions(self, tmp_path):
        """Test that the atomic write keeps the original file permission bits."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")
        test_file.chmod(0o640)

        edits = [{"type": "replace", "old": "World", "new": "There"}]
        result = Function.execute(str(test_file), edits)
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert test_file.read_text() == "Hello There"
        assert stat.S_IMODE(test_file.stat().st_mode) == 0o640
