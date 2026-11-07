"""Tests for v0.21 K12: project context auto-load (AGENTS.md/CLAUDE.md/.yaicli.md)."""

import os
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

import yaicli.project_context as project_context
from yaicli.const import DEFAULT_CONFIG_INI, DEFAULT_CONFIG_MAP
from yaicli.project_context import (
    PROJECT_CONTEXT_HEADER,
    PROJECT_CONTEXT_FILENAMES,
    collect_project_context,
    find_git_root,
    iter_project_context_files,
    load_project_context,
)


def make_repo(root: Path, git_file: bool = False) -> Path:
    """Create a directory marked as a git root (``.git`` dir or worktree file)."""
    root.mkdir(parents=True, exist_ok=True)
    if git_file:
        (root / ".git").write_text("gitdir: /tmp/worktree/.git/worktrees/x\n", encoding="utf-8")
    else:
        (root / ".git").mkdir(exist_ok=True)
    return root


def write_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def fake_error_console(monkeypatch):
    """Capture the stderr warnings emitted by the project-context loader."""
    console = MagicMock()
    monkeypatch.setattr(project_context, "error_console", console)
    return console


def warnings_of(console: MagicMock) -> List[str]:
    return [str(call.args[0]) for call in console.print.call_args_list if call.args]


class TestDiscovery:
    """File discovery: git-root boundary, ordering and de-duplication."""

    def test_walks_from_cwd_up_to_git_root(self, tmp_path):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "root instructions")
        write_file(repo / "sub" / ".yaicli.md", "sub instructions")
        deep = repo / "sub" / "deep"
        deep.mkdir(parents=True)

        discovered = iter_project_context_files(deep)

        assert [path.name for path in discovered] == ["AGENTS.md", ".yaicli.md"]
        assert [path.parent.name for path in discovered] == ["repo", "sub"]

    def test_never_reads_above_git_root(self, tmp_path):
        # A stray instruction file outside the repository must never be loaded.
        write_file(tmp_path / "AGENTS.md", "outside instructions")
        repo = make_repo(tmp_path / "repo")
        deep = repo / "deep"
        deep.mkdir()

        discovered = iter_project_context_files(deep)

        assert discovered == []

    def test_git_worktree_file_marks_the_root(self, tmp_path):
        repo = make_repo(tmp_path / "worktree", git_file=True)
        write_file(repo / "CLAUDE.md", "worktree instructions")
        deep = repo / "pkg"
        deep.mkdir()

        assert find_git_root(deep) == repo
        assert [path.name for path in iter_project_context_files(deep)] == ["CLAUDE.md"]

    def test_find_git_root_from_nested_directory(self, tmp_path):
        repo = make_repo(tmp_path / "repo")
        nested = repo / "a" / "b"
        nested.mkdir(parents=True)

        assert find_git_root(nested) == repo
        assert find_git_root(repo) == repo

    def test_no_git_root_walks_up_to_filesystem_root(self, tmp_path):
        project = tmp_path / "plain" / "nested"
        project.mkdir(parents=True)
        write_file(tmp_path / "plain" / "AGENTS.md", "parent instructions")
        if find_git_root(project) is not None:
            pytest.skip("filesystem ancestors contain a git root")

        discovered = iter_project_context_files(project)

        assert [path.name for path in discovered] == ["AGENTS.md"]

    def test_priority_order_within_one_directory(self, tmp_path):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "CLAUDE.md", "claude")
        write_file(repo / "AGENTS.md", "agents")
        write_file(repo / ".yaicli.md", "yaicli")

        discovered = iter_project_context_files(repo)

        assert [path.name for path in discovered] == list(PROJECT_CONTEXT_FILENAMES)

    def test_directories_are_outer_to_inner(self, tmp_path):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "root")
        write_file(repo / "a" / "AGENTS.md", "a")
        write_file(repo / "a" / "b" / "CLAUDE.md", "b")
        deep = repo / "a" / "b"
        deep.mkdir(exist_ok=True)

        discovered = iter_project_context_files(deep)

        assert [path.parent for path in discovered] == [repo, repo / "a", repo / "a" / "b"]

    def test_symlinked_duplicate_loaded_once(self, tmp_path):
        if not hasattr(os, "symlink"):
            pytest.skip("symlinks are unavailable on this platform")
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "CLAUDE.md", "same instructions")
        try:
            os.symlink(repo / "CLAUDE.md", repo / "AGENTS.md")
        except OSError:
            pytest.skip("cannot create symlinks in this environment")

        discovered = iter_project_context_files(repo)

        assert len(discovered) == 1
        assert discovered[0].name == "AGENTS.md"

    def test_discovery_does_not_read_file_contents(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "x")

        def boom(*args, **kwargs):
            raise AssertionError("discovery must not read contents")

        monkeypatch.setattr(Path, "read_text", boom)

        assert [path.name for path in iter_project_context_files(repo)] == ["AGENTS.md"]


class TestNoFiles:
    """No instruction files means zero request cost and no ownership of the prompt."""

    def test_no_files_returns_empty_result(self, tmp_path, fake_error_console):
        repo = make_repo(tmp_path / "repo")

        result = collect_project_context(repo)

        assert result.text == ""
        assert result.has_content is False
        assert result.files == []
        assert result.truncated is False
        fake_error_console.print.assert_not_called()

    def test_load_uses_the_current_directory(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "from cwd")
        monkeypatch.chdir(repo)

        result = load_project_context()

        assert result.has_content is True
        assert "from cwd" in result.text
        assert result.paths[0].name == "AGENTS.md"


class TestDisabled:
    """ENABLE_PROJECT_CONTEXT=false must not touch the filesystem at all."""

    def test_disabled_performs_no_filesystem_reads(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "ignored")
        monkeypatch.chdir(repo)
        with patch.dict(project_context.cfg, {"ENABLE_PROJECT_CONTEXT": False}):
            monkeypatch.setattr(
                project_context,
                "iter_project_context_files",
                MagicMock(side_effect=AssertionError("disabled feature must not discover files")),
            )
            result = load_project_context()

        assert result.text == ""
        assert result.has_content is False

    def test_disabled_accepts_string_false(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "ignored")
        monkeypatch.chdir(repo)
        with patch.dict(project_context.cfg, {"ENABLE_PROJECT_CONTEXT": "false"}):
            monkeypatch.setattr(
                project_context,
                "iter_project_context_files",
                MagicMock(side_effect=AssertionError("disabled feature must not discover files")),
            )
            assert load_project_context().text == ""


class TestSizeCap:
    """The collected block is bounded; truncation warns exactly once on stderr."""

    def test_cap_truncates_and_warns_once(self, tmp_path, fake_error_console):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "A" * 500)

        result = collect_project_context(repo, limit=200)

        assert result.truncated is True
        assert len(result.text) <= 200
        assert result.files[0].kept_chars < result.files[0].original_chars
        messages = warnings_of(fake_error_console)
        assert len(messages) == 1
        assert "PROJECT_CONTEXT_MAX_CHARS=200" in messages[0]
        assert "AGENTS.md" in messages[0]
        assert "YAI_PROJECT_CONTEXT_MAX_CHARS" in messages[0]
        assert "ENABLE_PROJECT_CONTEXT=false" in messages[0]

    def test_cap_names_all_involved_files(self, tmp_path, fake_error_console):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "A" * 400)
        write_file(repo / ".yaicli.md", "B" * 400)

        result = collect_project_context(repo, limit=250)

        message = warnings_of(fake_error_console)[0]
        assert "AGENTS.md" in message
        assert ".yaicli.md" in message
        assert "skipped" in message
        assert len(result.text) <= 250

    def test_load_uses_configured_limit(self, tmp_path, monkeypatch, fake_error_console):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "C" * 1000)
        monkeypatch.chdir(repo)
        with patch.dict(project_context.cfg, {"ENABLE_PROJECT_CONTEXT": True, "PROJECT_CONTEXT_MAX_CHARS": 120}):
            result = load_project_context()

        assert len(result.text) <= 120
        assert result.truncated is True
        assert "PROJECT_CONTEXT_MAX_CHARS=120" in warnings_of(fake_error_console)[0]

    def test_zero_limit_disables_the_cap(self, tmp_path, monkeypatch, fake_error_console):
        repo = make_repo(tmp_path / "repo")
        content = "D" * 25000  # larger than the 20000 default
        write_file(repo / "AGENTS.md", content)
        monkeypatch.chdir(repo)
        with patch.dict(project_context.cfg, {"ENABLE_PROJECT_CONTEXT": True, "PROJECT_CONTEXT_MAX_CHARS": 0}):
            result = load_project_context()

        assert result.truncated is False
        assert content in result.text
        fake_error_console.print.assert_not_called()

    def test_cap_includes_the_prompt_heading(self, tmp_path):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "E" * 500)

        result = collect_project_context(repo, limit=200)

        assert len(result.text) <= 200
        assert result.truncated is True
        assert result.text.startswith(PROJECT_CONTEXT_HEADER)


class TestUnreadableFiles:
    """A bad file is skipped with one warning; the turn never raises."""

    def test_unreadable_file_is_skipped(self, tmp_path, monkeypatch, fake_error_console):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "AGENTS-UNREADABLE-CONTENT")
        write_file(repo / "CLAUDE.md", "readable instructions")
        original_read_text = Path.read_text

        def flaky_read_text(self, *args, **kwargs):
            if self.name == "AGENTS.md":
                raise PermissionError("permission denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", flaky_read_text)

        result = collect_project_context(repo)

        assert "readable instructions" in result.text
        assert "AGENTS-UNREADABLE-CONTENT" not in result.text
        messages = warnings_of(fake_error_console)
        assert len(messages) == 1
        assert "Could not read project context file" in messages[0]
        assert "AGENTS.md" in messages[0]

    def test_missing_cwd_does_not_crash(self, monkeypatch):
        def missing_cwd():
            raise OSError("current directory was removed")

        monkeypatch.setattr(Path, "cwd", staticmethod(missing_cwd))

        result = load_project_context()

        assert result.text == ""


class TestConfigKeys:
    """K12 adds two documented config keys (map + INI template + YAI_ env)."""

    def test_map_entries(self):
        assert DEFAULT_CONFIG_MAP["ENABLE_PROJECT_CONTEXT"] == {
            "value": "true",
            "env_key": "YAI_ENABLE_PROJECT_CONTEXT",
            "type": bool,
        }
        assert DEFAULT_CONFIG_MAP["PROJECT_CONTEXT_MAX_CHARS"] == {
            "value": 20000,
            "env_key": "YAI_PROJECT_CONTEXT_MAX_CHARS",
            "type": int,
        }

    def test_ini_template_contains_both_keys(self):
        assert "ENABLE_PROJECT_CONTEXT=true" in DEFAULT_CONFIG_INI
        assert "PROJECT_CONTEXT_MAX_CHARS=20000" in DEFAULT_CONFIG_INI

    def test_env_override_is_typed(self, tmp_path):
        import yaicli.config as config_module

        def mock_getenv(key, default=None):
            return {
                "YAI_ENABLE_PROJECT_CONTEXT": "false",
                "YAI_PROJECT_CONTEXT_MAX_CHARS": "4321",
            }.get(key, default)

        with (
            patch.object(config_module, "CONFIG_PATH", tmp_path / "config.ini"),
            patch("yaicli.config.getenv", side_effect=mock_getenv),
        ):
            config = config_module.Config(MagicMock())

        assert config["ENABLE_PROJECT_CONTEXT"] is False
        assert config["PROJECT_CONTEXT_MAX_CHARS"] == 4321


class TestCLIIntegration:
    """CLI._build_messages puts the project context after the role prompt."""

    @pytest.fixture
    def make_cli(self):
        from yaicli.cli import CLI
        from yaicli.role import role_mgr

        def factory():
            cli = CLI(
                client=MagicMock(),
                chat_manager=MagicMock(),
                role_manager=role_mgr,
                context_manager=MagicMock(),
            )
            cli.console = MagicMock()
            cli.context_manager.get_context_messages.return_value = []
            cli.context_manager.parse_at_references.return_value = ("", "hello", [])
            return cli

        return factory

    def test_build_messages_includes_project_context(self, tmp_path, monkeypatch, make_cli):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "PROJECT RULE: always run tests.")
        deep = repo / "pkg"
        deep.mkdir()
        monkeypatch.chdir(deep)
        cli = make_cli()

        messages = cli._build_messages("hello")

        assert [message.role for message in messages] == ["system", "user"]
        system_prompt = messages[0].content
        assert system_prompt.startswith(cli.role.prompt)
        assert "## Project context" in system_prompt
        assert "PROJECT RULE: always run tests." in system_prompt
        assert str(repo / "AGENTS.md") in system_prompt
        assert messages[-1].content == "hello"

    def test_build_messages_without_files_is_byte_identical(self, tmp_path, monkeypatch, make_cli):
        repo = make_repo(tmp_path / "repo")
        monkeypatch.chdir(repo)
        cli = make_cli()
        cli.chat.history = []

        messages = cli._build_messages("hello")

        # Pre-K12 payload: one system message with the role prompt, then the user message.
        assert [message.role for message in messages] == ["system", "user"]
        assert messages[0].content == cli.role.prompt
        assert messages[1].content == "hello"
        assert len([message for message in messages if message.role == "system"]) == 1

    def test_build_messages_keeps_context_message_order(self, tmp_path, monkeypatch, make_cli):
        from yaicli.schemas import ChatMessage

        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "project rule")
        monkeypatch.chdir(repo)
        cli = make_cli()
        cli.context_manager.get_context_messages.return_value = [ChatMessage(role="system", content="persistent ctx")]
        cli.context_manager.parse_at_references.return_value = ("at refs", "hello", [])

        messages = cli._build_messages("hello @f.txt")

        contents = [message.content for message in messages]
        assert contents[0].startswith(cli.role.prompt)
        assert "project rule" in contents[0]
        assert contents[1] == "persistent ctx"
        assert contents[2] == "at refs"
        assert contents[3] == "hello"

    def test_project_context_is_discovered_once_per_cli(self, tmp_path, monkeypatch, make_cli, fake_error_console):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "F" * 1000)
        monkeypatch.chdir(repo)
        with patch.dict(project_context.cfg, {"ENABLE_PROJECT_CONTEXT": True, "PROJECT_CONTEXT_MAX_CHARS": 150}):
            cli = make_cli()
            first = cli._build_messages("one")
            second = cli._build_messages("two")

        assert first[0].content == second[0].content
        assert len(warnings_of(fake_error_console)) == 1

    def test_disabled_project_context_keeps_payload_identical(self, tmp_path, monkeypatch, make_cli):
        repo = make_repo(tmp_path / "repo")
        write_file(repo / "AGENTS.md", "ignored")
        monkeypatch.chdir(repo)
        with patch.dict(project_context.cfg, {"ENABLE_PROJECT_CONTEXT": False}):
            monkeypatch.setattr(
                project_context,
                "iter_project_context_files",
                MagicMock(side_effect=AssertionError("disabled feature must not discover files")),
            )
            cli = make_cli()
            messages = cli._build_messages("hello")

        assert messages[0].content == cli.role.prompt
        assert messages[1].content == "hello"
