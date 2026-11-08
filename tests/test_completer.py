"""Tests for the REPL completers (``@path`` and slash commands)."""

from unittest.mock import MagicMock

import pytest
from prompt_toolkit.document import Document

from yaicli.cmd_handler import COMMAND_INFO, CmdHandler, command_completions
from yaicli.completer import AtPathCompleter, ReplCompleter, SlashCommandCompleter


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


def _completions(completer, text):
    """Run a completer against a document holding ``text`` before the cursor."""
    return list(completer.get_completions(Document(text, cursor_position=len(text)), None))


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


# ---------------------------------------------------------------------------
# slash-command completion + composition with @path completion
# ---------------------------------------------------------------------------
def _all_slash_completions():
    return _completions(SlashCommandCompleter(), "/")


def _completion_texts(completions):
    return [completion.text for completion in completions]


def test_slash_lists_every_registered_command():
    """/ lists every command registered in CmdHandler.commands (slash spellings)."""
    handler = CmdHandler(MagicMock())
    registered = {command for command in handler.commands if command.startswith("/")}
    completions = _all_slash_completions()

    assert set(_completion_texts(completions)) == registered
    assert {"/cost", "/model", "/role", "/retry", "/compact", "/context"} <= registered


def test_slash_completions_have_descriptions():
    """Every completion carries a non-empty one-line description in its meta."""
    completions = _all_slash_completions()
    assert completions
    for completion in completions:
        assert completion.display_meta_text, f"{completion.text} has no description"


def test_slash_prefix_filters_commands():
    """/co filters the menu to commands starting with "/co"."""
    completions = _completions(SlashCommandCompleter(), "/co")

    assert set(_completion_texts(completions)) == {"/compact", "/context", "/cost"}
    assert all(completion.start_position == -len("/co") for completion in completions)


def test_slash_prefix_is_case_insensitive():
    completions = _completions(SlashCommandCompleter(), "/CO")
    assert set(_completion_texts(completions)) == {"/compact", "/context", "/cost"}


def test_slash_alias_is_offered():
    completions = _completions(SlashCommandCompleter(), "/ct")
    assert "/ctx" in _completion_texts(completions)

    completions = _completions(SlashCommandCompleter(), "/ch")
    assert "/chats" in _completion_texts(completions)


def test_slash_meta_uses_shared_metadata_description():
    completions = _completions(SlashCommandCompleter(), "/cost")

    assert len(completions) == 1
    assert completions[0].display_meta_text == next(
        info.description for info in COMMAND_INFO if info.command == "/cost"
    )


def test_slash_completion_ignores_arguments_and_plain_text():
    """Only the first token is a command: arguments and normal text are not completed."""
    slash = SlashCommandCompleter()

    assert _completions(slash, "/model gpt-4o") == []
    assert _completions(slash, "/add file") == []
    assert _completions(slash, "hello ") == []
    assert _completions(slash, "@file") == []


def test_slash_completions_match_command_metadata_helper():
    """command_completions() is the single shared source (commands + aliases)."""
    pairs = command_completions()
    assert ("/cost", "Show session token usage and estimated cost") in pairs
    assert ("/ctx", dict(pairs)["/context"]) in pairs


def test_repl_completer_keeps_at_path_completion(temp_workspace):
    """Composing the slash completer must not break normal @path completion."""
    repl = ReplCompleter(base_dir=temp_workspace)
    completions = _completions(repl, "analyze @file")

    assert completions
    assert any("file" in completion.text for completion in completions)


def test_repl_completer_keeps_context_command_path_completion(temp_workspace):
    repl = ReplCompleter(base_dir=temp_workspace)

    assert any("subdir" in completion.text for completion in _completions(repl, "/context add sub"))
    assert any("file" in completion.text for completion in _completions(repl, "/add file"))


def test_repl_completer_offers_commands_and_paths():
    repl = ReplCompleter()

    assert {"/cost", "/model", "/role", "/retry"} <= set(_completion_texts(_completions(repl, "/")))
    assert _completions(repl, "regular text") == []
