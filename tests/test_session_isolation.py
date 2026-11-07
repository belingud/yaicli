"""v0.21 K13: per-project session isolation, metadata and ``--resume``.

Covers:
- the HOME-derived session store and the stable cwd hash (``const`` helpers);
- ``FileChatManager`` defaulting to the per-project directory while an explicit
  ``CHAT_HISTORY_DIR`` override keeps the old flat-directory behaviour;
- private modes for session dirs/files and the prompt-history file;
- persisted session metadata (model/provider/role/cwd/created_at/updated_at) with
  backward-compatible loading of legacy session JSON;
- ``--resume`` semantics and the explicit "new session" notice on a missed title;
- entry-level ``--resume`` wiring (implies chat, ignored in headless modes).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

import yaicli.cli as cli_module
from yaicli.chat import Chat, FileChatManager, resolve_default_chat_dir
from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.const import (
    DEFAULT_CHAT_HISTORY_DIR,
    DefaultRoleNames,
    get_project_sessions_dir,
    get_sessions_dir,
    project_sessions_key,
)
from yaicli.entry import app
from yaicli.history import LimitedFileHistory, prepare_history_file

runner = CliRunner()


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Point HOME at a temp dir (session store is HOME-derived)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("USERPROFILE", raising=False)
    return home


@pytest.fixture
def project(tmp_path, fake_home, monkeypatch):
    """A temporary project directory; cwd is switched to it."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    return project_dir


@pytest.fixture
def manager(project):
    """A FileChatManager using the default (per-project) session directory."""
    return FileChatManager()


@pytest.fixture
def error_console(monkeypatch):
    """Capture stderr notices from the CLI module."""
    console = MagicMock()
    monkeypatch.setattr(cli_module, "get_error_console", lambda: console)
    return console


@pytest.fixture
def stdout_console():
    return MagicMock()


def _make_cli(manager):
    cli = CLI(verbose=False, client=MagicMock(), chat_manager=manager)
    cli.console = MagicMock()
    return cli


def _printed(console):
    return [str(call.args[0]) for call in console.print.call_args_list if call.args]


def _save_session(manager, title, model="test-model", provider="test-provider", role="DEFAULT"):
    chat = Chat(title=title)
    chat.add_message("user", "hello")
    chat.update_metadata(model=model, provider=provider, role=role, cwd=str(Path.cwd()))
    manager.save_chat(chat)
    return chat


def _session_files(manager):
    return sorted(manager.chat_dir.glob("*.json"))


# --------------------------------------------------------------------------- #
# 1. sessions dir / project key helpers
# --------------------------------------------------------------------------- #
class TestSessionPaths:
    def test_sessions_dir_is_home_derived(self, fake_home, tmp_path, monkeypatch):
        """Sessions live under $HOME/.yaicli/sessions; XDG config does not move them."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
        assert get_sessions_dir() == fake_home / ".yaicli" / "sessions"

    def test_project_key_is_stable_and_distinct(self, tmp_path, monkeypatch):
        key = project_sessions_key(tmp_path)
        assert len(key) == 16
        int(key, 16)  # hex only

        # Same resolved directory -> same key (str/Path/relative spelling alike).
        assert project_sessions_key(str(tmp_path)) == key
        monkeypatch.chdir(tmp_path)
        assert project_sessions_key() == key
        assert project_sessions_key(".") == key

        other = tmp_path / "other-project"
        other.mkdir()
        assert project_sessions_key(other) != key

    def test_project_sessions_dir_layout(self, fake_home):
        project_dir = fake_home / "repo"
        project_dir.mkdir()
        expected = fake_home / ".yaicli" / "sessions" / project_sessions_key(project_dir)
        assert get_project_sessions_dir(project_dir) == expected
        assert get_project_sessions_dir() == fake_home / ".yaicli" / "sessions" / project_sessions_key()

    def test_symlinked_project_resolves_to_same_key(self, tmp_path, fake_home):
        real = tmp_path / "real-project"
        real.mkdir()
        link = tmp_path / "link-project"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
            pytest.skip("symlinks not supported")
        assert project_sessions_key(link) == project_sessions_key(real)


# --------------------------------------------------------------------------- #
# 2. FileChatManager default directory + override
# --------------------------------------------------------------------------- #
class TestSessionDirectory:
    def test_default_chat_dir_is_per_project(self, fake_home, project):
        manager = FileChatManager()
        expected = fake_home / ".yaicli" / "sessions" / project_sessions_key(project)
        assert manager.chat_dir == expected
        assert manager.chat_dir == resolve_default_chat_dir()

    def test_different_projects_get_different_dirs(self, fake_home, tmp_path, monkeypatch):
        project_a = tmp_path / "project-a"
        project_a.mkdir()
        project_b = tmp_path / "project-b"
        project_b.mkdir()

        monkeypatch.chdir(project_a)
        manager_a = FileChatManager()
        _save_session(manager_a, "Session A")

        monkeypatch.chdir(project_b)
        manager_b = FileChatManager()
        assert manager_b.chat_dir != manager_a.chat_dir

        # Each project only lists its own sessions.
        assert manager_b.list_chats() == []
        monkeypatch.chdir(project_a)
        manager_a_again = FileChatManager()
        assert [chat.title for chat in manager_a_again.list_chats()] == ["Session A"]

    def test_explicit_chat_history_dir_override_wins(self, fake_home, tmp_path, monkeypatch):
        """YAI_CHAT_HISTORY_DIR / config override keeps the old flat directory."""
        custom = tmp_path / "custom-chats"
        monkeypatch.setitem(cfg, "CHAT_HISTORY_DIR", str(custom))

        manager = FileChatManager()
        assert manager.chat_dir == custom
        _save_session(manager, "Flat Session")

        assert len(list(custom.glob("*.json"))) == 1
        # The default per-project store was not touched by an explicit override.
        assert not get_sessions_dir().exists()

    def test_default_value_means_per_project(self, fake_home, project):
        """A CHAT_HISTORY_DIR equal to the built-in default counts as "unset"."""
        assert cfg["CHAT_HISTORY_DIR"] == str(DEFAULT_CHAT_HISTORY_DIR)
        manager = FileChatManager()
        assert manager.chat_dir == get_project_sessions_dir()

    def test_env_override_uses_flat_dir_end_to_end(self, tmp_path):
        """YAI_CHAT_HISTORY_DIR set before startup keeps the flat directory (K13)."""
        repo_root = Path(__file__).resolve().parent.parent
        home = tmp_path / "home"
        home.mkdir()
        custom = tmp_path / "env-chats"
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("YAI_") and key not in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "USERPROFILE")
        }
        env.update({"HOME": str(home), "YAI_CHAT_HISTORY_DIR": str(custom)})

        code = "from yaicli.chat import FileChatManager; print(FileChatManager().chat_dir)"
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(repo_root),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(custom)
        assert not (home / ".yaicli" / "sessions").exists()

    def test_session_dir_and_file_modes(self, fake_home, project):
        manager = FileChatManager()
        _save_session(manager, "Modes")

        files = _session_files(manager)
        assert len(files) == 1
        if os.name == "posix":
            assert manager.chat_dir.stat().st_mode & 0o777 == 0o700
            assert get_sessions_dir().stat().st_mode & 0o777 == 0o700
            assert files[0].stat().st_mode & 0o777 == 0o600


# --------------------------------------------------------------------------- #
# 3. session metadata (persisted, backward compatible)
# --------------------------------------------------------------------------- #
class TestSessionMetadata:
    def test_metadata_persisted_to_json(self, manager):
        _save_session(manager, "Metadata")

        data = json.loads(_session_files(manager)[0].read_text(encoding="utf-8"))
        assert data["model"] == "test-model"
        assert data["provider"] == "test-provider"
        assert data["role"] == "DEFAULT"
        assert data["cwd"] == str(Path.cwd())
        assert data["created_at"]
        assert data["updated_at"]
        assert data["title"] == "Metadata"

        reloaded = manager.load_chat_by_title("Metadata")
        assert reloaded.model == "test-model"
        assert reloaded.provider == "test-provider"
        assert reloaded.role == "DEFAULT"
        assert reloaded.cwd == str(Path.cwd())
        assert reloaded.created_at == data["created_at"]
        assert reloaded.updated_at == data["updated_at"]

    def test_updated_at_advances_on_save(self, manager):
        chat = _save_session(manager, "Timestamps")
        first = json.loads(_session_files(manager)[0].read_text(encoding="utf-8"))["updated_at"]

        time.sleep(0.01)
        manager.save_chat(chat)
        second = json.loads(_session_files(manager)[0].read_text(encoding="utf-8"))["updated_at"]

        assert second > first
        reloaded = manager.load_chat_by_title("Timestamps")
        assert reloaded.created_at <= reloaded.updated_at

    def test_legacy_session_without_metadata_loads(self, manager):
        manager._ensure_chat_dir()
        legacy_file = manager.chat_dir / "20240101-120000-title-Legacy.json"
        legacy_file.write_text(
            json.dumps(
                {
                    "title": "Legacy",
                    "date": "2024-01-01T00:00:00",
                    "history": [{"role": "user", "content": "old message"}],
                }
            ),
            encoding="utf-8",
        )
        manager.refresh_chats()

        chat = manager.load_chat_by_title("Legacy")
        assert chat.title == "Legacy"
        assert chat.history[0].content == "old message"
        # Missing metadata fields default to empty strings, never raise.
        assert (chat.model, chat.provider, chat.role, chat.cwd) == ("", "", "", "")
        assert chat.created_at == ""
        assert chat.updated_at == ""

    def test_cli_save_records_current_config_and_cwd(self, project, monkeypatch):
        manager = FileChatManager()
        cli = _make_cli(manager)
        cli.chat = Chat(title="From CLI")
        cli.chat.add_message("user", "hi")
        cli.role_name = DefaultRoleNames.DEFAULT.value
        monkeypatch.setitem(cfg, "MODEL", "cli-model")
        monkeypatch.setitem(cfg, "PROVIDER", "cli-provider")

        cli._save_chat("From CLI")

        data = json.loads(_session_files(manager)[0].read_text(encoding="utf-8"))
        assert data["model"] == "cli-model"
        assert data["provider"] == "cli-provider"
        assert data["role"] == DefaultRoleNames.DEFAULT.value
        assert data["cwd"] == str(Path.cwd().resolve())
        assert data["created_at"] and data["updated_at"]

    def test_to_dict_and_from_dict_roundtrip_metadata(self):
        chat = Chat(title="RT")
        chat.update_metadata(model="m", provider="p", role="r", cwd="/tmp/proj")

        restored = Chat.from_dict(chat.to_dict())

        assert restored.title == "RT"
        assert (restored.model, restored.provider, restored.role) == ("m", "p", "r")
        assert restored.cwd == "/tmp/proj"
        assert restored.created_at == chat.created_at
        assert restored.updated_at == chat.updated_at

    def test_from_dict_without_metadata_is_legacy_compatible(self):
        restored = Chat.from_dict({"title": "Old", "date": "2024-01-01", "history": []})
        assert restored.title == "Old"
        assert (restored.model, restored.provider, restored.role, restored.cwd) == ("", "", "", "")


# --------------------------------------------------------------------------- #
# 4. resume / missed title semantics
# --------------------------------------------------------------------------- #
class TestResume:
    def test_resume_picks_newest_session_and_prints_notice(self, manager, error_console):
        _save_session(manager, "Older", model="old-model", provider="old-provider", role="old-role")
        time.sleep(0.05)
        _save_session(manager, "Newest", model="new-model", provider="new-provider", role="new-role")

        cli = _make_cli(manager)
        cli.resume = True
        with patch.object(CLI, "_run_repl"):
            cli.run(chat=True)

        assert cli.chat.title == "Newest"
        assert cli.chat.model == "new-model"
        assert cli.chat.provider == "new-provider"
        assert cli.chat.role == "new-role"
        assert cli.is_temp_session is False

        notices = _printed(cli.console)
        assert any(
            "Resumed session" in notice
            and "Newest" in notice
            and "new-model" in notice
            and "new-provider" in notice
            and "new-role" in notice
            for notice in notices
        )
        # Existing sessions are resumed, not re-created.
        assert error_console.print.call_count == 0

    def test_resume_with_no_sessions_prints_notice_and_starts_new(self, manager, error_console):
        cli = _make_cli(manager)
        cli.resume = True
        with patch.object(CLI, "_run_repl"):
            cli.run(chat=True)

        assert cli.chat.title == ""
        assert cli.chat.history == []
        assert cli.is_temp_session is True
        notices = _printed(error_console)
        assert any("No saved session" in notice for notice in notices)

    def test_resume_continues_the_conversation_history(self, manager, error_console):
        saved = _save_session(manager, "Continue Me")
        saved.add_message("assistant", "previous answer")
        manager.save_chat(saved)

        cli = _make_cli(manager)
        cli.resume = True
        with patch.object(CLI, "_run_repl"):
            cli.run(chat=True)

        assert [message.content for message in cli.chat.history if message.role == "assistant"] == [
            "previous answer"
        ]

    def test_startup_missed_title_prints_new_session_notice(self, manager, error_console):
        cli = _make_cli(manager)
        with patch.object(CLI, "_run_repl"):
            cli.run(chat=True, user_input="My Missing Session")

        assert cli.chat.title == "My Missing Session"
        assert cli.chat.history == []
        assert cli.is_temp_session is False
        notices = _printed(error_console)
        assert any(
            "No saved session titled" in notice and "My Missing Session" in notice for notice in notices
        )

    def test_startup_matching_title_loads_without_new_session_notice(self, manager, error_console):
        _save_session(manager, "Existing Session")

        cli = _make_cli(manager)
        with patch.object(CLI, "_run_repl"):
            cli.run(chat=True, user_input="Existing Session")

        assert cli.chat.title == "Existing Session"
        assert cli.chat.history[0].content == "hello"
        assert cli.is_temp_session is False
        assert error_console.print.call_count == 0


# --------------------------------------------------------------------------- #
# 5. prompt-history privacy
# --------------------------------------------------------------------------- #
class TestPromptHistoryPrivacy:
    def test_prepare_history_file_is_private(self, tmp_path):
        history_file = tmp_path / "state" / "yaicli" / "history"
        prepare_history_file(history_file)

        assert history_file.exists()
        if os.name == "posix":
            assert history_file.stat().st_mode & 0o777 == 0o600
            assert history_file.parent.stat().st_mode & 0o777 == 0o700

    def test_limited_history_repairs_legacy_mode(self, tmp_path):
        history_file = tmp_path / "history"
        history_file.write_text("", encoding="utf-8")
        if os.name == "posix":
            os.chmod(history_file, 0o644)

        history = LimitedFileHistory(str(history_file), max_entries=5, trim_every=1)
        history.append_string("secret prompt")

        if os.name == "posix":
            assert history_file.stat().st_mode & 0o777 == 0o600

    def test_chat_loop_tolerates_uncreatable_history(self, tmp_path, monkeypatch):
        """A history path that cannot be created must not crash the REPL (K21/K13)."""
        blocker = tmp_path / "blocked-parent"
        blocker.write_text("a file, not a directory", encoding="utf-8")
        monkeypatch.setattr(cli_module, "HISTORY_FILE", blocker / "history")
        error_console = MagicMock()
        monkeypatch.setattr(cli_module, "get_error_console", lambda: error_console)
        session_cls = MagicMock()
        monkeypatch.setattr(cli_module, "_prompt_session_class", lambda: session_cls)
        monkeypatch.setattr(cli_module, "_limited_history_class", lambda: MagicMock())
        monkeypatch.setattr(cli_module, "_at_path_completer_class", lambda: MagicMock())

        cli = CLI(verbose=False, client=MagicMock())
        with patch.object(CLI, "_setup_key_bindings"):
            cli.prepare_chat_loop()

        # Warning printed, session still created, no exception escaped.
        assert error_console.print.called
        assert session_cls.called


# --------------------------------------------------------------------------- #
# 6. entry-level --resume wiring
# --------------------------------------------------------------------------- #
class TestEntryResumeFlag:
    def _invoke(self, *args):
        mock_instance = MagicMock()
        mock_instance.had_error = False
        with patch("yaicli.cli.CLI", return_value=mock_instance) as mock_cls:
            mock_cls.evaluate_role_name.return_value = DefaultRoleNames.DEFAULT
            result = runner.invoke(app, list(args))
        return result, mock_cls, mock_instance

    def test_help_lists_resume(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--resume" in result.stdout

    def test_resume_implies_chat_mode(self):
        # CliRunner's stdin is not a TTY; patch entry's sys reference so the CLI
        # (mocked) is reached with chat=True instead of being downgraded.
        with patch("yaicli.entry.sys") as mock_sys:
            mock_sys.stdin.isatty.return_value = True
            result, _, mock_instance = self._invoke("--resume")

        assert result.exit_code == 0
        assert mock_instance.run.call_args.kwargs["chat"] is True
        assert mock_instance.configure_headless.call_args.kwargs["resume"] is True

    def test_resume_ignored_with_print(self):
        result, _, mock_instance = self._invoke("--resume", "-p", "hello")

        assert result.exit_code == 0
        assert mock_instance.run.call_args.kwargs["chat"] is False
        assert mock_instance.configure_headless.call_args.kwargs["resume"] is False
        assert "--resume is ignored" in result.stderr

    def test_resume_ignored_when_stdin_redirected(self):
        with patch("yaicli.entry.sys") as mock_sys:
            mock_sys.stdin.isatty.return_value = False
            result, _, mock_instance = self._invoke("--resume")

        assert result.exit_code == 0
        assert mock_instance.run.call_args.kwargs["chat"] is False
        assert "--resume is ignored when stdin was redirected" in result.stderr
