import pytest


def test_filter_command_basic(cli):
    """test basic command filtering"""
    command = "ls -la"
    assert cli._filter_command(command) == "ls -la"


@pytest.mark.parametrize("input_cmd,expected", [
    ("```\nls -la\n```", "ls -la"),
    ("```ls -la```", "ls -la"),
])
def test_filter_command_with_code_block(cli, input_cmd, expected):
    """test code block"""
    assert cli._filter_command(input_cmd) == expected

@pytest.mark.parametrize("input_cmd,expected", [
    ("```bash\nls -la\n```", "ls -la"),
    ("```zsh\nls -la\n```", "ls -la"),
    ("```shell\nls -la\n```", "ls -la"),
    ("```sh\nls -la\n```", "ls -la"),
])
def test_filter_command_with_shell_type(cli, input_cmd, expected):
    """test shell type declaration code block"""
    assert cli._filter_command(input_cmd) == expected

def test_filter_command_multiline(cli):
    """test multiline command"""
    command = "```\ncd /tmp\nls -la\n```"
    assert cli._filter_command(command) == "cd /tmp\nls -la"

def test_filter_command_with_spaces(cli):
    """test command with extra spaces"""
    command = "```bash  \n  ls -la  \n  ```"
    assert cli._filter_command(command) == "ls -la"

def test_filter_command_empty_block(cli):
    """test empty code block"""
    command = "```\n\n```"
    assert cli._filter_command(command) == ""

def test_filter_command_nested_blocks(cli):
    """test nested code block"""
    command = "```bash\n```echo hello```\n```"
    assert cli._filter_command(command) == "```echo hello```"
