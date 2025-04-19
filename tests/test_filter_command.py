import pytest
from yaicli.utils import filter_command


def test_filter_command_basic():
    """test basic command filtering"""
    command = "ls -la"
    assert filter_command(command) == "ls -la"


@pytest.mark.parametrize("input_cmd,expected", [
    ("```\nls -la\n```", "ls -la"),
    ("```ls -la```", "ls -la"),
])
def test_filter_command_with_code_block(input_cmd, expected):
    """test code block"""
    assert filter_command(input_cmd) == expected

@pytest.mark.parametrize("input_cmd,expected", [
    ("```bash\nls -la\n```", "ls -la"),
    ("```zsh\nls -la\n```", "ls -la"),
    ("```shell\nls -la\n```", "ls -la"),
    ("```sh\nls -la\n```", "ls -la"),
])
def test_filter_command_with_shell_type(input_cmd, expected):
    """test shell type declaration code block"""
    assert filter_command(input_cmd) == expected

def test_filter_command_multiline():
    """test multiline command"""
    command = "```\ncd /tmp\nls -la\n```"
    assert filter_command(command) == "cd /tmp\nls -la"

def test_filter_command_with_spaces():
    """test command with extra spaces"""
    command = "```bash  \n  ls -la  \n  ```"
    assert filter_command(command) == "ls -la"

def test_filter_command_empty_block():
    """test empty code block"""
    command = "```\n\n```"
    assert filter_command(command) == ""

def test_filter_command_nested_blocks():
    """test nested code block"""
    command = "```bash\n```echo hello```\n```"
    assert filter_command(command) == "```echo hello```"


def test_filter_command_plaintext():
    """test command with plain text"""
    command = "```plaintext\nls -la\n```"
    assert filter_command(command) == "ls -la"


@pytest.mark.parametrize("input_cmd", [
    "",
    "   ",
    "\n \t ",
])
def test_filter_command_empty_or_whitespace(input_cmd):
    """test empty or whitespace only command"""
    assert filter_command(input_cmd) == ""


def test_filter_command_multiline_no_closing_ticks():
    """test multiline command without closing ticks"""
    command = "```bash\ncd /path/to/somewhere\necho 'done'"
    assert filter_command(command) == "cd /path/to/somewhere\necho 'done'"
