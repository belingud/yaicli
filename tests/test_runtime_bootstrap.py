"""v0.19 K21 runtime-bootstrap tests.

The CLI must be usable on a read-only HOME / in containers and must be
side-effect free for read-only commands:

- ``--version`` / ``-v`` is answered by the tiny ``_faststart`` entry point
  without importing ``yaicli.config``/``yaicli.role``/``yaicli.cli`` and without
  writing any file;
- importing ``yaicli.config`` / ``yaicli.role`` / ``yaicli.chat`` never writes
  state; writes happen only through explicit entry points
  (``ensure_config_file``, role create/delete, chat save);
- config-dir resolution honours ``YAI_CONFIG_DIR`` > ``XDG_CONFIG_HOME`` >
  ``~/.config`` and never falls back to ``/.config`` for an empty ``HOME``;
- the first ``config.ini`` is created on demand with 0600 file / 0700 dir.

Every subprocess uses a private ``HOME`` under ``tmp_path`` and strips inherited
``YAI_*``/``XDG_*`` variables, so tests never touch the real user configuration.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

TEMPLATE_MARKER = "[core]"


def _clean_env(home: Path) -> dict:
    """Build a subprocess environment with a private HOME and no ambient YAI_/XDG."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("YAI_")}
    for key in (
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "APPDATA",
        "USERPROFILE",
        # The first-real-run test talks to a closed localhost port: never proxy it.
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        env.pop(key, None)
    env["HOME"] = str(home)
    env.setdefault("PATH", os.environ.get("PATH", ""))
    return env


def _run(args, *, home, env_extra=None, timeout=120):
    env = _clean_env(Path(home))
    if env_extra:
        env.update({key: str(value) for key, value in env_extra.items()})
    return subprocess.run(
        args,
        cwd=str(REPO_ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _assert_no_traceback(result):
    assert "Traceback (most recent call last)" not in result.stderr, result.stderr


def _tree(root: Path):
    """All paths below ``root`` (``root`` itself excluded)."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


class TestVersionFastPath:
    def test_python_m_yaicli_version_writes_nothing(self, tmp_path):
        """``python -m yaicli --version`` works in a cold HOME and creates no files."""
        from yaicli import __version__ as expected_version

        home = tmp_path / "home"
        home.mkdir()

        result = _run([sys.executable, "-m", "yaicli", "--version"], home=home)

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"yaicli {expected_version}"
        _assert_no_traceback(result)
        assert _tree(home) == []

    def test_static_version_matches_pyproject(self):
        """``yaicli.__version__`` stays in sync with pyproject.toml (bump2version)."""
        import re

        from yaicli import __version__

        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        assert match is not None, "pyproject.toml has no version"
        assert __version__ == match.group(1)

    def test_short_flag_version_writes_nothing(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()

        result = _run([sys.executable, "-m", "yaicli", "-v"], home=home)

        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("yaicli ")
        assert _tree(home) == []

    def test_version_does_not_import_config_or_role(self, tmp_path):
        """The fast path answers before the config/role/CLI stack is imported."""
        home = tmp_path / "home"
        home.mkdir()
        code = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from yaicli._faststart import main
            main(["--version"])
            for name in ("yaicli.config", "yaicli.role", "yaicli.cli", "yaicli.entry"):
                print("IMPORTED", name, name in sys.modules)
            """
        )

        result = _run([sys.executable, "-c", code], home=home)

        assert result.returncode == 0, result.stderr
        assert "IMPORTED yaicli.config False" in result.stdout
        assert "IMPORTED yaicli.role False" in result.stdout
        assert "IMPORTED yaicli.cli False" in result.stdout
        assert "IMPORTED yaicli.entry False" in result.stdout
        assert _tree(home) == []


class TestReadOnlyHome:
    @staticmethod
    def _read_only_dir(tmp_path, name="readonly-home") -> Path:
        path = tmp_path / name
        path.mkdir()
        path.chmod(0o500)
        return path

    def test_version_on_read_only_home(self, tmp_path):
        home = self._read_only_dir(tmp_path)
        try:
            result = _run([sys.executable, "-m", "yaicli", "--version"], home=home)
            assert result.returncode == 0, result.stderr
            assert result.stdout.startswith("yaicli ")
            _assert_no_traceback(result)
        finally:
            home.chmod(0o700)

    def test_help_on_read_only_home(self, tmp_path):
        home = self._read_only_dir(tmp_path)
        try:
            result = _run([sys.executable, "-m", "yaicli", "--help"], home=home)
            assert result.returncode == 0, result.stderr
            assert "Usage:" in result.stdout
            _assert_no_traceback(result)
        finally:
            home.chmod(0o700)

    def test_importing_state_modules_on_read_only_home_does_not_write(self, tmp_path):
        home = self._read_only_dir(tmp_path)
        code = "import yaicli.config, yaicli.role, yaicli.chat;print('IMPORTS_OK', yaicli.config.cfg['PROVIDER'])"
        try:
            result = _run([sys.executable, "-c", code], home=home)
            assert result.returncode == 0, result.stderr
            assert "IMPORTS_OK" in result.stdout
            _assert_no_traceback(result)
            assert _tree(home) == []
        finally:
            home.chmod(0o700)


class TestMetaCommandsWriteNothing:
    @pytest.mark.parametrize(
        ("flag", "stdout_marker"),
        [
            ("--help", "Usage:"),
            ("--template", TEMPLATE_MARKER),
            ("--list-roles", "DEFAULT"),
        ],
    )
    def test_cold_home_meta_command_creates_no_files(self, tmp_path, flag, stdout_marker):
        """Read-only commands must not materialise config/roles/chat state (K21)."""
        home = tmp_path / "home"
        home.mkdir()

        result = _run([sys.executable, "-m", "yaicli", flag], home=home)

        assert result.returncode == 0, result.stderr
        assert stdout_marker in result.stdout
        _assert_no_traceback(result)
        assert _tree(home) == []


class TestPathResolution:
    def _const_paths(self, home, env_extra=None):
        code = (
            "from yaicli.const import CONFIG_PATH, ROLES_DIR, HISTORY_FILE;"
            "print(CONFIG_PATH); print(ROLES_DIR); print(HISTORY_FILE)"
        )
        result = _run([sys.executable, "-c", code], home=home, env_extra=env_extra)
        assert result.returncode == 0, result.stderr
        config_path, roles_dir, history_file = result.stdout.strip().splitlines()
        return Path(config_path), Path(roles_dir), Path(history_file)

    def test_yai_config_dir_wins(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        custom = tmp_path / "custom-config"

        config_path, roles_dir, _ = self._const_paths(home, {"YAI_CONFIG_DIR": custom})

        assert config_path == custom / "config.ini"
        assert roles_dir == custom / "roles"

    def test_xdg_config_home(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        xdg_config = tmp_path / "xdg-config"

        config_path, roles_dir, _ = self._const_paths(home, {"XDG_CONFIG_HOME": xdg_config})

        assert config_path == xdg_config / "yaicli" / "config.ini"
        assert roles_dir == xdg_config / "yaicli" / "roles"

    def test_default_home_location(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()

        config_path, _, history_file = self._const_paths(home)

        assert config_path == home / ".config" / "yaicli" / "config.ini"
        assert history_file == home / ".yaicli_history"

    def test_empty_home_never_resolves_to_root(self, tmp_path):
        """``HOME=""`` must not fall back to ``/.config`` (container safety)."""
        config_path, _, history_file = self._const_paths(tmp_path, {"HOME": ""})

        assert not str(config_path).startswith("/.config")
        assert "yaicli-home" in config_path.parts
        assert not str(history_file).startswith("/.yaicli_history")

    def test_xdg_state_home_history(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        xdg_state = tmp_path / "xdg-state"

        _, _, history_file = self._const_paths(home, {"XDG_STATE_HOME": xdg_state})

        assert history_file == xdg_state / "yaicli" / "history"


class TestConfigFileOnDemand:
    def test_ensure_config_file_creates_private_file(self, tmp_path):
        """The explicit first-run entry point creates config.ini with 0600/0700."""
        import hashlib

        config_dir = tmp_path / "fresh-config"
        code = textwrap.dedent(
            """
            import hashlib
            from yaicli.config import ensure_config_file
            from yaicli.const import DEFAULT_CONFIG_INI

            path = ensure_config_file()
            print(path)
            print(hashlib.sha256(DEFAULT_CONFIG_INI.encode("utf-8")).hexdigest())
            """
        )

        result = _run(
            [sys.executable, "-c", code],
            home=tmp_path,
            env_extra={"YAI_CONFIG_DIR": config_dir},
        )

        assert result.returncode == 0, result.stderr
        printed_path, expected_digest = result.stdout.strip().splitlines()
        config_file = config_dir / "config.ini"
        assert printed_path == str(config_file)
        assert config_file.exists()
        assert hashlib.sha256(config_file.read_bytes()).hexdigest() == expected_digest
        assert (config_file.stat().st_mode & 0o777) == 0o600
        assert (config_dir.stat().st_mode & 0o777) == 0o700

    def test_import_does_not_create_config_file(self, tmp_path):
        """Importing config/role/chat leaves a cold HOME completely untouched."""
        home = tmp_path / "home"
        home.mkdir()
        config_dir = tmp_path / "cold-config"
        code = "import yaicli.config, yaicli.role, yaicli.chat;print('PROVIDER', yaicli.config.cfg['PROVIDER'])"

        result = _run(
            [sys.executable, "-c", code],
            home=home,
            env_extra={"YAI_CONFIG_DIR": config_dir},
        )

        assert result.returncode == 0, result.stderr
        assert "PROVIDER" in result.stdout
        assert not config_dir.exists()
        assert _tree(home) == []

    def test_first_real_run_creates_config_file(self, tmp_path):
        """The CLI's first real request materialises config.ini (K21 req 5)."""
        home = tmp_path / "home"
        home.mkdir()
        config_dir = tmp_path / "first-run-config"
        # Closed local port: the LLM call fails fast, but the first-run write
        # happens before the request, which is the behaviour under test here.
        result = _run(
            [sys.executable, "-m", "yaicli", "-p", "hi"],
            home=home,
            env_extra={
                "YAI_CONFIG_DIR": config_dir,
                "YAI_PROVIDER": "openai",
                "YAI_API_KEY": "sk-test",
                "YAI_BASE_URL": "http://127.0.0.1:1/v1",
                "YAI_MODEL": "gpt-4o",
                "YAI_RETRY_ENABLED": "false",
                "YAI_TIMEOUT": "1",
            },
        )

        config_file = config_dir / "config.ini"
        assert config_file.exists(), result.stderr
        assert (config_file.stat().st_mode & 0o777) == 0o600
        # The failed request is a handled error, never a raw traceback.
        assert "Traceback (most recent call last)" not in result.stderr, result.stderr


class TestFaststartModule:
    def test_broken_pipe_is_quiet(self, monkeypatch):
        """A closed stdout pipe is a success for the producer (no traceback)."""
        import yaicli._faststart as faststart
        import yaicli.entry as entry

        silenced = []
        monkeypatch.setattr(entry, "app", lambda: (_ for _ in ()).throw(BrokenPipeError()))
        monkeypatch.setattr(faststart, "_silence_broken_pipe", lambda: silenced.append(True))

        faststart.main(["--chat"])

        assert silenced == [True]

    def test_pyproject_console_scripts_route_through_faststart(self):
        """Both console scripts must use the fast entry point (K08/K21)."""
        tomllib = pytest.importorskip("tomllib")
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = pyproject["project"]["scripts"]

        assert scripts["ai"] == "yaicli._faststart:main"
        assert scripts["yaicli"] == "yaicli._faststart:main"
