import pytest
from unittest.mock import patch
from yaicli.history import LimitedFileHistory


@pytest.fixture
def history_file(tmp_path):
    """Provides a temporary path for the history file."""
    return tmp_path / "test_history.txt"


class TestLimitedFileHistory:
    def test_init_creates_file(self, history_file):
        """Test that the history file is created lazily on first append."""
        assert not history_file.exists()  # File should not exist initially
        history = LimitedFileHistory(str(history_file), max_entries=10)

        # Append a string, which should trigger file creation by the parent class
        history.append_string("command1")

        # File should now exist
        assert history_file.exists()
        # Check that the content includes the command (accounting for timestamp)
        content = history_file.read_text()
        assert "+command1" in content

    def test_append_string_basic(self, history_file):
        """Test appending a few strings."""
        history = LimitedFileHistory(str(history_file), max_entries=10, trim_every=100)  # High trim_every
        history.append_string("command1")
        history.append_string("command2")

        content = history_file.read_text()
        assert "command1" in content
        assert "command2" in content
        assert content.count("# ") == 2  # Check for two timestamp entries

    def test_load_history_strings(self, history_file):
        """Test loading history strings from an existing file."""
        # Prepare a history file
        initial_content = (
            "# 1678886400\n+command1\n"  # Timestamp for 2023-03-15 12:00:00 UTC
            "# 1678886460\n+command2\n"
            "# 1678886520\n+command3\n"
        )
        history_file.write_text(initial_content)

        history = LimitedFileHistory(str(history_file), max_entries=10)
        loaded_strings = list(history.load_history_strings())

        # Should load in reverse chronological order (newest first)
        assert loaded_strings == ["command3", "command2", "command1"]

    def test_trim_history_called(self, history_file):
        """Test that _trim_history is called based on trim_every."""
        trim_threshold = 3
        history = LimitedFileHistory(str(history_file), max_entries=10, trim_every=trim_threshold)

        with patch.object(history, "_trim_history", wraps=history._trim_history) as mock_trim:
            # Append threshold - 1 entries
            for i in range(trim_threshold - 1):
                history.append_string(f"cmd{i}")  # cmd0, cmd1
            mock_trim.assert_not_called()

            # Append threshold-th entry
            history.append_string(f"cmd{trim_threshold - 1}")  # cmd2 -> Triggers trim
            assert mock_trim.call_count == 1  # First call

            # Append one more entry
            history.append_string(f"cmd{trim_threshold}")  # cmd3
            assert mock_trim.call_count == 1  # Count should still be 1

            # Append up to (but not including) the next trigger point
            for i in range(trim_threshold + 1, trim_threshold * 2 - 1):
                history.append_string(f"cmd{i}")  # cmd4
            assert mock_trim.call_count == 1  # Count should still be 1

            # Append the entry that triggers the second trim
            history.append_string(f"cmd{trim_threshold * 2 - 1}")  # cmd5 -> Triggers trim
            assert mock_trim.call_count == 2  # Second call

    def test_history_limit(self, history_file):
        """Test that history is correctly limited to max_entries."""
        max_entries = 5
        history = LimitedFileHistory(str(history_file), max_entries=max_entries, trim_every=1)

        num_entries = max_entries + 3
        for i in range(num_entries):
            # Use distinct commands to check which ones are kept
            history.append_string(f"command_{i}")

        # Verify in-memory history (load_history_strings)
        loaded_strings = list(history.load_history_strings())
        assert len(loaded_strings) == max_entries
        # Should contain the last max_entries commands in reverse order
        expected_strings = [f"command_{i}" for i in range(num_entries - 1, num_entries - max_entries - 1, -1)]
        assert loaded_strings == expected_strings

        # Verify file content after trimming
        content = history_file.read_text()
        lines = content.strip().split("\n")
        # Count timestamp lines to verify number of entries in file
        timestamp_lines = [line for line in lines if line.startswith("# ")]
        assert len(timestamp_lines) == max_entries
        # Check if the oldest command (command_0, command_1, command_2) are gone
        assert "command_0" not in content
        assert "command_1" not in content
        assert "command_2" not in content
        # Check if the newest commands are present
        for i in range(num_entries - max_entries, num_entries):
            assert f"command_{i}" in content

    def test_multiline_entry_trimming(self, history_file):
        """Test trimming when entries have multiple lines."""
        max_entries = 2
        history = LimitedFileHistory(str(history_file), max_entries=max_entries, trim_every=1)

        history.append_string("line1\nline2")  # Entry 1 (multi-line)
        history.append_string("line3")  # Entry 2
        history.append_string("line4\nline5\nline6")  # Entry 3 (multi-line)

        # File should only contain the last two entries (line3 and line4-6)
        content = history_file.read_text()
        assert "line1" not in content
        assert "line2" not in content
        assert "+line3" in content
        assert "+line4" in content
        assert "+line5" in content
        assert "+line6" in content
        assert content.count("# ") == max_entries

        # Verify loading strings
        loaded_strings = list(history.load_history_strings())
        assert loaded_strings == ["line4\nline5\nline6", "line3"]
