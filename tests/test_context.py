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

        at_content, cleaned_input, at_images = context_manager.parse_at_references(user_input)

        assert "file1.txt" in cleaned_input
        assert "@file1.txt" not in cleaned_input
        # Should replace with 'file1.txt'
        assert "'file1.txt'" in cleaned_input

        assert "Referenced files for this query:" in at_content
        assert "## File: file1.txt" in at_content
        assert "content1" in at_content

        # No images in text-only references
        assert at_images == []

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
        at_content, cleaned_input, at_images = context_manager.parse_at_references("Check @missing.txt")
        assert at_content == ""
        assert cleaned_input == "Check @missing.txt"  # Should remain unchanged if not found
        assert at_images == []

        # 2. Image file — now detected as image, not binary skip
        at_content, cleaned_input, at_images = context_manager.parse_at_references("Check @binary.png")
        assert at_content == ""  # No text content for images
        assert "'binary.png'" in cleaned_input
        assert len(at_images) == 1
        assert at_images[0].media_type == "image/png"
        assert at_images[0].is_url is False

        # 3. Large file
        at_content, cleaned_input, at_images = context_manager.parse_at_references("Check @large.txt")
        assert at_content == ""  # Should warn but not include content
        assert "large.txt" in cleaned_input
        assert at_images == []

        # 4. Mixed valid text and image
        at_content, cleaned_input, at_images = context_manager.parse_at_references("Check @file1.txt and @binary.png")
        assert "file1.txt" in at_content
        assert "content1" in at_content
        assert "'file1.txt'" in cleaned_input
        assert "'binary.png'" in cleaned_input
        assert len(at_images) == 1
        assert at_images[0].media_type == "image/png"

        # 5. Quoted path with space
        (temp_workspace / "space file.txt").write_text("space content")
        at_content, cleaned_input, at_images = context_manager.parse_at_references('Check @"space file.txt"')
        assert "space file.txt" in at_content
        assert "space content" in at_content
        assert "'space file.txt'" in cleaned_input
        assert at_images == []

    finally:
        os.chdir(original_cwd)


def test_parse_at_references_image_files(context_manager, temp_workspace):
    """Test parse_at_references with various image file types."""
    import os

    original_cwd = os.getcwd()
    os.chdir(temp_workspace)

    # Create image files
    (temp_workspace / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0test")
    (temp_workspace / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (temp_workspace / "anim.gif").write_bytes(b"GIF89a")
    (temp_workspace / "pic.webp").write_bytes(b"RIFF")

    try:
        # Single image
        at_content, cleaned_input, at_images = context_manager.parse_at_references("Describe @photo.jpg")
        assert at_content == ""
        assert "'photo.jpg'" in cleaned_input
        assert len(at_images) == 1
        assert at_images[0].media_type == "image/jpeg"

        # Multiple images
        at_content, cleaned_input, at_images = context_manager.parse_at_references("Compare @photo.jpg and @icon.png")
        assert at_content == ""
        assert "'photo.jpg'" in cleaned_input
        assert "'icon.png'" in cleaned_input
        assert len(at_images) == 2
        media_types = {img.media_type for img in at_images}
        assert media_types == {"image/jpeg", "image/png"}

        # Mixed image + text
        at_content, cleaned_input, at_images = context_manager.parse_at_references("Check @photo.jpg and @file1.txt")
        assert "file1.txt" in at_content
        assert "content1" in at_content
        assert "'photo.jpg'" in cleaned_input
        assert "'file1.txt'" in cleaned_input
        assert len(at_images) == 1
        assert at_images[0].media_type == "image/jpeg"

        # webp support
        at_content, cleaned_input, at_images = context_manager.parse_at_references("Show @pic.webp")
        assert len(at_images) == 1
        assert at_images[0].media_type == "image/webp"

    finally:
        os.chdir(original_cwd)


def test_parse_at_references_unreadable_image(context_manager, temp_workspace):
    """Test graceful degradation when image file cannot be read."""
    import os
    import sys

    original_cwd = os.getcwd()
    os.chdir(temp_workspace)

    img = temp_workspace / "locked.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0")

    try:
        # Skip on Windows where chmod doesn't work the same way
        if sys.platform != "win32":
            img.chmod(0o000)
            at_content, cleaned_input, at_images = context_manager.parse_at_references("Show @locked.jpg")
            assert at_images == []  # Should gracefully handle the error
            assert "'locked.jpg'" in cleaned_input  # Reference still cleaned
    finally:
        if sys.platform != "win32":
            img.chmod(0o644)
        os.chdir(original_cwd)
