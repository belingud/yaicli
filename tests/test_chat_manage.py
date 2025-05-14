import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

from yaicli.chat import (
    Chat,
    ChatDeleteError,
    ChatLoadError,
    ChatSaveError,
    FileChatManager,
)


@pytest.fixture
def temp_chat_dir():
    """Create a temporary directory for chat history files that will be removed after tests."""
    with TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def chat_manager(temp_chat_dir, mock_console):
    """Create a FileChatManager with a temporary directory for testing."""
    chat_dir = Path(temp_chat_dir) / "chats"
    chat_dir.mkdir(parents=True, exist_ok=True)

    # Create a new manager with isolated configuration
    manager = FileChatManager()
    # Use instance attributes instead of class attributes for test isolation
    manager.chat_dir = chat_dir
    manager.max_saved_chats = 10
    # Force-clear the chats map to ensure a clean state
    manager._chats_map = None

    yield manager

    # Clean up all files after test
    for file in chat_dir.glob("*.json"):
        file.unlink(missing_ok=True)
    # Reset _chats_map to clear state between tests
    manager._chats_map = None


class TestFileChatManager:
    def test_init(self, chat_manager, temp_chat_dir):
        """Test initialization of FileChatManager."""
        # Check correct path including the 'chats' subdirectory
        expected_path = Path(temp_chat_dir) / "chats"
        assert chat_manager.chat_dir == expected_path
        assert chat_manager.max_saved_chats == 10
        assert chat_manager._chats_map is None

    def test_make_chat_title(self, chat_manager):
        """Test chat title generation."""
        # Test with prompt
        title = chat_manager.make_chat_title("This is a test prompt")
        assert title == "This is a test prompt"

        # Test with long prompt (should truncate)
        long_prompt = "A" * 150
        title = chat_manager.make_chat_title(long_prompt)
        assert len(title) == 100
        assert title == "A" * 100

        # Test without prompt (should use timestamp)
        with patch("time.time", return_value=12345):
            title = chat_manager.make_chat_title()
            assert title == "Chat-12345"

    def test_save_and_load_chat(self, chat_manager):
        """Test saving a chat and loading it back."""
        # Create sample chat
        chat = Chat(title="Test Chat")
        chat.add_message("user", "Hello")
        chat.add_message("assistant", "Hi there!")

        # Save the chat
        title = chat_manager.save_chat(chat)
        assert title == "Test Chat"

        # Verify chat is loaded correctly
        loaded_chat = chat_manager.load_chat_by_title("Test Chat")
        assert loaded_chat.title == "Test Chat"
        assert len(loaded_chat.history) == 2
        assert loaded_chat.history[0].content == "Hello"
        assert loaded_chat.history[1].content == "Hi there!"

    def test_save_chat_no_title(self, chat_manager):
        """Test saving a chat without a title."""
        chat = Chat(title="")
        chat.add_message("user", "Test message")

        with patch("time.time", return_value=12345):
            title = chat_manager.save_chat(chat)
            assert "Chat-12345" in title

    def test_save_chat_empty_history(self, chat_manager):
        """Test saving an empty chat history."""
        chat = Chat(title="Empty Chat")

        with pytest.raises(ChatSaveError) as excinfo:
            chat_manager.save_chat(chat)

        assert "No history in chat to save" in str(excinfo.value)

    def test_save_chat_overwrite_existing(self, chat_manager):
        """Test that saving a chat with an existing title overwrites the old chat."""
        # Create and save initial chat
        chat1 = Chat(title="Same Title")
        chat1.add_message("user", "First chat")
        chat_manager.save_chat(chat1)

        # Create and save another chat with the same title
        chat2 = Chat(title="Same Title")
        chat2.add_message("user", "Second chat")
        chat_manager.save_chat(chat2)

        # Load the chat and verify it's the second one
        loaded_chat = chat_manager.load_chat_by_title("Same Title")
        assert loaded_chat.history[0].content == "Second chat"

    def test_list_chats(self, chat_manager):
        """Test listing saved chats."""
        # Save a few chats
        chat1 = Chat(title="Title 1")
        chat1.add_message("user", "Chat 1")
        chat_manager.save_chat(chat1)

        chat2 = Chat(title="Title 2")
        chat2.add_message("user", "Chat 2")
        chat_manager.save_chat(chat2)

        chat3 = Chat(title="Title 3")
        chat3.add_message("user", "Chat 3")
        chat_manager.save_chat(chat3)

        # List chats
        chats = chat_manager.list_chats()

        # Verify list contains the saved chats
        assert len(chats) == 3
        titles = [chat.title for chat in chats]
        assert "Title 1" in titles
        assert "Title 2" in titles
        assert "Title 3" in titles

    def test_max_saved_chats(self, temp_chat_dir, mock_console):
        """Test that max_saved_chats is respected."""
        # Create an isolated test directory
        test_dir = Path(temp_chat_dir) / "max_saved_test"
        test_dir.mkdir(parents=True, exist_ok=True)

        # Create a dedicated manager for this test with max 2 saved chats
        manager = FileChatManager()
        manager.chat_dir = test_dir
        manager.max_saved_chats = 2
        manager._chats_map = None

        # Save 3 chats
        chat1 = Chat(title="Title 1")
        chat1.add_message("user", "Chat 1")
        manager.save_chat(chat1)
        time.sleep(0.1)  # Ensure different timestamps

        chat2 = Chat(title="Title 2")
        chat2.add_message("user", "Chat 2")
        manager.save_chat(chat2)
        time.sleep(0.1)  # Ensure different timestamps

        chat3 = Chat(title="Title 3")
        chat3.add_message("user", "Chat 3")
        manager.save_chat(chat3)

        # Should only keep the 2 most recent
        chats = manager.list_chats()
        assert len(chats) == 2
        titles = [chat.title for chat in chats]
        assert "Title 3" in titles
        assert "Title 2" in titles
        assert "Title 1" not in titles

        # Clean up
        for file in test_dir.glob("*.json"):
            file.unlink(missing_ok=True)

    def test_load_chat_by_index(self, chat_manager):
        """Test loading a chat by index."""
        # Save chats
        chat1 = Chat(title="Title 1")
        chat1.add_message("user", "Chat 1")
        chat_manager.save_chat(chat1)

        chat2 = Chat(title="Title 2")
        chat2.add_message("user", "Chat 2")
        chat_manager.save_chat(chat2)

        # Get the index of the first chat
        chats = chat_manager.list_chats()
        index = next((chat.idx for chat in chats if chat.title == "Title 1"), None)

        # Load by index
        loaded_chat = chat_manager.load_chat_by_index(index)
        assert loaded_chat.title == "Title 1"
        assert loaded_chat.history[0].content == "Chat 1"

    def test_load_nonexistent_chat(self, chat_manager):
        """Test loading a chat that doesn't exist."""
        # By index
        loaded_chat = chat_manager.load_chat_by_index("999")
        assert loaded_chat.idx == "999"
        assert not loaded_chat.history

        # By title
        loaded_chat = chat_manager.load_chat_by_title("Nonexistent Title")
        assert loaded_chat.title == "Nonexistent Title"
        assert not loaded_chat.history

    def test_validate_chat_index(self, chat_manager):
        """Test validation of chat indexes."""
        # Save a chat
        chat = Chat(title="Test")
        chat.add_message("user", "Test")
        chat_manager.save_chat(chat)

        # Get its index
        chats = chat_manager.list_chats()
        valid_index = chats[0].idx

        # Test validation
        assert chat_manager.validate_chat_index(valid_index) is True
        assert chat_manager.validate_chat_index("999") is False
        assert chat_manager.validate_chat_index(0) is False
        assert chat_manager.validate_chat_index(-1) is False

    def test_delete_chat(self, chat_manager):
        """Test deleting a chat."""
        # Ensure we start with an empty state
        chat_manager._chats_map = None
        for file in chat_manager.chat_dir.glob("*.json"):
            file.unlink(missing_ok=True)

        # Save a chat
        chat = Chat(title="TestToDelete")
        chat.add_message("user", "Test")
        chat_manager.save_chat(chat)

        # Get its index and path
        chat_manager.refresh_chats()  # Force refresh to ensure accurate data
        chats = chat_manager.list_chats()
        assert len(chats) == 1  # Verify we have exactly one chat
        chat_path = chats[0].path

        # Delete it by path
        result = chat_manager.delete_chat(chat_path)
        assert result is True

        # Verify it's gone - refresh chats explicitly
        chat_manager.refresh_chats()
        assert len(chat_manager.list_chats()) == 0

    def test_delete_nonexistent_chat(self, chat_manager):
        """Test deleting a chat that doesn't exist."""
        result = chat_manager.delete_chat_by_index("999")
        assert result is False

    def test_refresh_chats(self, chat_manager, temp_chat_dir):
        """Test refreshing chats from disk."""
        # Start with an empty directory
        for file in chat_manager.chat_dir.glob("*.json"):
            file.unlink(missing_ok=True)
        chat_manager._chats_map = None

        # Verify we're starting empty
        assert len(chat_manager.list_chats()) == 0

        # Save a single chat
        chat = Chat(title="RefreshTest")
        chat.add_message("user", "Test")
        chat_manager.save_chat(chat)

        # Modify _chats_map directly to simulate stale data
        chat_manager._chats_map = {"title": {}, "index": {}}

        # Refresh should load from disk
        chat_manager.refresh_chats()

        # Verify only our test chat is loaded
        chats = chat_manager.list_chats()
        assert len(chats) == 1
        assert chats[0].title == "RefreshTest"

    def test_parse_filename(self, chat_manager):
        """Test parsing of chat filenames."""
        # Standard filename
        chat_file = Path("20230401-120000-title-Test_Chat.json")
        chat = FileChatManager._parse_filename(chat_file)

        assert chat.title == "Test_Chat"
        assert chat.date == "2023-04-01 12:00"
        assert chat.path == chat_file

        # Filename with special characters
        chat_file = Path("20230401-120000-title-Test_Chat_With-Dashes.json")
        chat = FileChatManager._parse_filename(chat_file)

        assert chat.title == "Test_Chat_With-Dashes"

        # Filename with spaces in title
        chat_file = Path("20230401-120000-title-This is a test prompt.json")
        chat = FileChatManager._parse_filename(chat_file)

        assert chat.title == "This is a test prompt"
        assert chat.date == "2023-04-01 12:00"

        # Irregular filename
        chat_file = Path("irregular_filename.json")
        chat = FileChatManager._parse_filename(chat_file)

        assert chat.title == "irregular_filename"
        assert chat.date == ""

    def test_file_error_handling(self, chat_manager, monkeypatch):
        """Test handling of file errors."""
        # Test file not found
        with monkeypatch.context() as m:
            m.setattr(Path, "exists", lambda path: False)
            chat = chat_manager.load_chat_by_title("Nonexistent")
            assert chat.title == "Nonexistent"
            assert not chat.history

        # Test JSON decode error
        test_chat = Chat(title="Test")
        test_chat.add_message("user", "Test")
        chat_manager.save_chat(test_chat)
        chats = chat_manager.list_chats()
        index = chats[0].idx

        with monkeypatch.context() as m:

            def mock_open(*args, **kwargs):
                mock = MagicMock()
                mock.__enter__ = lambda self: self
                mock.__exit__ = lambda self, *args: None
                mock.read = lambda: "invalid json"
                return mock

            m.setattr("builtins.open", mock_open)
            with pytest.raises(ChatLoadError):
                chat_manager.load_chat_by_index(index)

    def test_delete_error_handling(self, chat_manager, monkeypatch):
        """Test handling of delete errors."""
        # Create a chat to delete
        chat = Chat(title="DeleteErrorTest")
        chat.add_message("user", "Test message")
        chat_manager.save_chat(chat)

        # Get the chat
        chats = chat_manager.list_chats()

        # Mock the unlink method to raise an OSError
        with monkeypatch.context() as m:

            def mock_unlink():
                raise OSError("Permission denied")

            m.setattr(Path, "unlink", lambda path: mock_unlink())

            # Test that ChatDeleteError is raised when OS prevents file deletion
            with pytest.raises(ChatDeleteError):
                chat_manager._delete_existing_chat_with_title(chats[0].title)
