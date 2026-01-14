import pytest

from yaicli.context import ContextManager


@pytest.fixture
def temp_workspace(tmp_path):
    # Create some dummy files and directories
    (tmp_path / "file1.txt").write_text("content1")
    (tmp_path / "file2.py").write_text("print('hello')")

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "subfile.md").write_text("# Title")

    # Create ignored directory
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "ignore_me.py").write_text("pass")

    return tmp_path


@pytest.fixture
def context_manager():
    # Fresh instance for each test
    return ContextManager()


def test_add_file(context_manager, temp_workspace):
    file_path = temp_workspace / "file1.txt"
    assert context_manager.add(str(file_path)) is True
    assert str(file_path) in context_manager.items
    assert context_manager.items[str(file_path)].type == "file"


def test_add_directory(context_manager, temp_workspace):
    dir_path = temp_workspace / "subdir"
    assert context_manager.add(str(dir_path)) is True
    assert str(dir_path) in context_manager.items
    assert context_manager.items[str(dir_path)].type == "dir"


def test_add_non_existent(context_manager):
    assert context_manager.add("/path/to/nothing") is False


def test_remove_item(context_manager, temp_workspace):
    file_path = temp_workspace / "file1.txt"
    context_manager.add(str(file_path))
    assert str(file_path) in context_manager.items

    # Remove by full path
    assert context_manager.remove(str(file_path)) is True
    assert str(file_path) not in context_manager.items


def test_remove_by_partial_name(context_manager, temp_workspace):
    file_path = temp_workspace / "file1.txt"
    context_manager.add(str(file_path))

    # Remove by filename
    assert context_manager.remove("file1.txt") is True
    assert str(file_path) not in context_manager.items


def test_clear_context(context_manager, temp_workspace):
    context_manager.add(str(temp_workspace / "file1.txt"))
    context_manager.add(str(temp_workspace / "file2.py"))
    assert len(context_manager.items) == 2

    context_manager.clear()
    assert len(context_manager.items) == 0


def test_get_context_messages_file(context_manager, temp_workspace):
    file_path = temp_workspace / "file1.txt"
    context_manager.add(str(file_path))

    messages = context_manager.get_context_messages()
    assert len(messages) == 1
    assert messages[0].role == "system"
    assert "file1.txt" in messages[0].content
    assert "content1" in messages[0].content


def test_get_context_messages_dir_recursive(context_manager, temp_workspace):
    context_manager.add(str(temp_workspace))

    messages = context_manager.get_context_messages()
    content = messages[0].content

    # Should contain files in root
    assert "file1.txt" in content
    assert "content1" in content

    # Should contain files in subdir
    assert "subfile.md" in content
    assert "# Title" in content

    # Should NOT contain ignored .venv
    assert "ignore_me.py" not in content


def test_global_instance():
    # Verify the global instance exists
    from yaicli.context import ctx_mgr

    assert isinstance(ctx_mgr, ContextManager)


def test_parse_at_references(context_manager, temp_workspace):
    # Ensure current working directory is the temp workspace for relative path testing
    import os

    original_cwd = os.getcwd()
    os.chdir(temp_workspace)
    try:
        user_input = "Can you check @file1.txt and verify?"

        at_content, cleaned_input = context_manager.parse_at_references(user_input)

        assert "file1.txt" in cleaned_input
        assert "@file1.txt" not in cleaned_input
        # Should replace with 'file1.txt'
        assert "'file1.txt'" in cleaned_input

        assert "Referenced files for this query:" in at_content
        assert "## File: file1.txt" in at_content
        assert "content1" in at_content

    finally:
        os.chdir(original_cwd)


def test_parse_at_references_edge_cases(context_manager, temp_workspace):
    """Test parse_at_references with non-existent, binary, and large files."""
    import os

    original_cwd = os.getcwd()
    os.chdir(temp_workspace)

    # Create special files
    (temp_workspace / "binary.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (temp_workspace / "large.txt").write_text("a" * 1_000_001)

    try:
        # 1. Non-existent file
        at_content, cleaned_input = context_manager.parse_at_references("Check @missing.txt")
        assert at_content == ""
        assert cleaned_input == "Check @missing.txt"  # Should remain unchanged if not found

        # 2. Binary file
        at_content, cleaned_input = context_manager.parse_at_references("Check @binary.png")
        assert at_content == ""
        assert "binary.png" in cleaned_input
        assert "'binary.png'" in cleaned_input

        # 3. Large file
        at_content, cleaned_input = context_manager.parse_at_references("Check @large.txt")
        assert at_content == ""  # Should warn but not include content
        assert "large.txt" in cleaned_input
        # The current implementation might warn but return empty content string for individual file failure
        # Let's verify standard behavior: warnings are printed to console (mocked usually), content is empty

        # 4. Mixed valid and invalid
        at_content, cleaned_input = context_manager.parse_at_references("Check @file1.txt and @binary.png")
        assert "file1.txt" in at_content
        assert "content1" in at_content
        assert "binary.png" not in at_content
        assert "'file1.txt'" in cleaned_input
        assert "'binary.png'" in cleaned_input

        # 5. Quoted path with space
        (temp_workspace / "space file.txt").write_text("space content")
        at_content, cleaned_input = context_manager.parse_at_references('Check @"space file.txt"')
        assert "space file.txt" in at_content
        assert "space content" in at_content
        assert "'space file.txt'" in cleaned_input

    finally:
        os.chdir(original_cwd)
