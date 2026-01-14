"""Tests for path completer."""

import pytest
from prompt_toolkit.document import Document

from yaicli.completer import AtPathCompleter


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a test workspace with files and directories."""
    (tmp_path / "file1.txt").write_text("content1")
    (tmp_path / "file2.py").write_text("print('hello')")
    (tmp_path / ".hidden").write_text("hidden content")

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "nested.md").write_text("# Nested")

    # Add file with spaces
    (tmp_path / "space file.txt").write_text("space content")

    return tmp_path


@pytest.fixture
def completer(temp_workspace):
    """Create a completer with test workspace as base."""
    return AtPathCompleter(base_dir=temp_workspace)


def test_at_trigger_completion(completer, temp_workspace):
    """Test @ trigger provides completions."""
    doc = Document("analyze @file", cursor_position=len("analyze @file"))
    completions = list(completer.get_completions(doc, None))

    # Should have completions for files starting with 'file'
    assert len(completions) > 0
    # Text should NOT have @ (only display has it, but we check text as display is FormattedText)
    assert all("file" in c.text for c in completions)


def test_at_trigger_shows_hidden_files(completer, temp_workspace):
    """Test that hidden files are shown."""
    # Test with empty @ to list all files
    doc = Document("@", cursor_position=len("@"))
    completions = list(completer.get_completions(doc, None))

    # Should show .hidden file among other files
    texts = [c.text for c in completions]
    assert any(".hidden" in t for t in texts), f"Available files: {texts}"


def test_command_based_completion(completer, temp_workspace):
    """Test completion after /add command."""
    doc = Document("/add file", cursor_position=len("/add file"))
    completions = list(completer.get_completions(doc, None))

    # Should have completions
    assert len(completions) > 0
    # Text should have file (display is FormattedText so we check text)
    assert any("file" in c.text for c in completions)


def test_context_add_completion(completer, temp_workspace):
    """Test completion after /context add command."""
    doc = Document("/context add sub", cursor_position=len("/context add sub"))
    completions = list(completer.get_completions(doc, None))

    # Should find subdir
    assert len(completions) > 0
    assert any("subdir" in c.text for c in completions)


def test_directory_suffix(completer, temp_workspace):
    """Test that directories get / suffix."""
    doc = Document("@sub", cursor_position=len("@sub"))
    completions = list(completer.get_completions(doc, None))

    # subdir should have / suffix
    assert any(c.text.endswith("/") for c in completions)


def test_no_completions_without_trigger(completer):
    """Test that completions are not shown without @ or command."""
    doc = Document("regular text", cursor_position=len("regular text"))
    completions = list(completer.get_completions(doc, None))

    assert len(completions) == 0


def test_relative_paths(completer, temp_workspace):
    """Test that paths are relative to base_dir."""
    doc = Document("@file1", cursor_position=len("@file1"))
    completions = list(completer.get_completions(doc, None))

    # Paths should be relative, not absolute
    for c in completions:
        assert not c.text.startswith("/")
        assert not c.text.startswith(str(temp_workspace))


def test_space_add_quotes(completer, temp_workspace):
    """Test that files with spaces are automatically quoted."""
    doc = Document("@spac", cursor_position=len("@spac"))
    completions = list(completer.get_completions(doc, None))

    assert len(completions) > 0
    space_files = [c for c in completions if "space file" in c.text]
    assert len(space_files) > 0
    # Should be quoted
    assert space_files[0].text == '"space file.txt"'
