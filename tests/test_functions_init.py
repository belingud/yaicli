"""Tests for yaicli.functions lifecycle callbacks (install/reinstall/list/manifest)."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

import yaicli.functions as functions_mod
import yaicli.tools.function as loading_mod
from yaicli.functions import (
    BUILDIN_DIR,
    build_manifest,
    detect_stale_copies,
    install_functions,
    iter_buildin_files,
    print_functions,
    print_mcp,
    read_manifest,
    reinstall_functions,
    sha256_file,
    warn_stale_copies_once,
    write_manifest,
)

#: The real bundled templates, copied into the temporary FUNCTIONS_DIR by the callbacks.
REAL_BUILDIN_DIR = BUILDIN_DIR

BUILTIN_FILE_NAMES = {path.name for path in iter_buildin_files(REAL_BUILDIN_DIR)}


def _printed(console: MagicMock) -> list[str]:
    return [str(call.args[0]) for call in console.print.call_args_list if call.args]


def _write_manifest(manifest: dict) -> None:
    functions_mod.FUNCTIONS_MANIFEST_PATH.write_text(json.dumps(manifest))


@pytest.fixture(autouse=True)
def function_env(tmp_path, monkeypatch):
    """Isolate FUNCTIONS_DIR/manifest/consoles in a temp dir for every test."""
    functions_dir = tmp_path / "functions"
    manifest_path = tmp_path / "functions_manifest.json"
    console = MagicMock()
    error_console = MagicMock()
    monkeypatch.setattr(functions_mod, "FUNCTIONS_DIR", functions_dir)
    monkeypatch.setattr(functions_mod, "FUNCTIONS_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(functions_mod, "console", console)
    monkeypatch.setattr(functions_mod, "error_console", error_console)
    monkeypatch.setattr(functions_mod, "_stale_warned", False)
    return SimpleNamespace(
        dir=functions_dir,
        manifest=manifest_path,
        console=console,
        error_console=error_console,
        tmp=tmp_path,
    )


class TestInstallFunctions:
    """`--install-functions` exports editable copies; it never overwrites user files."""

    def test_install_copies_buildin(self, function_env):
        """install_functions copies every bundled file into a fresh FUNCTIONS_DIR."""
        with pytest.raises(typer.Exit):
            install_functions(None, True)

        assert {path.name for path in function_env.dir.glob("*.py")} == BUILTIN_FILE_NAMES
        printed = _printed(function_env.console)
        assert any("Installing buildin functions" in text for text in printed)
        assert sum("Installed" in text for text in printed) == len(BUILTIN_FILE_NAMES)

    def test_install_creates_missing_dir(self, function_env):
        """The directory is created on demand (only by the install callbacks)."""
        assert not function_env.dir.exists()

        with pytest.raises(typer.Exit):
            install_functions(None, True)

        assert function_env.dir.is_dir()

    def test_install_is_idempotent(self, function_env):
        """A second install skips every existing file."""
        with pytest.raises(typer.Exit):
            install_functions(None, True)
        function_env.console.reset_mock()

        with pytest.raises(typer.Exit):
            install_functions(None, True)

        printed = _printed(function_env.console)
        assert any("already exists, skipping" in text for text in printed)
        assert not any(text.startswith("Installed ") for text in printed)

    def test_install_never_overwrites_existing_user_file(self, function_env):
        """A user's customized/own file is preserved by install."""
        function_env.dir.mkdir(parents=True)
        custom = function_env.dir / "fs_read_file.py"
        custom.write_text("# my custom version\n")

        with pytest.raises(typer.Exit):
            install_functions(None, True)

        assert custom.read_text() == "# my custom version\n"
        assert any("already exists, skipping" in text for text in _printed(function_env.console))

    def test_install_writes_manifest(self, function_env):
        """Install records the package version and the sha256 of every builtin."""
        with pytest.raises(typer.Exit):
            install_functions(None, True)

        manifest = read_manifest()
        assert manifest is not None
        assert manifest["manifest_version"] == 1
        assert isinstance(manifest["package_version"], str) and manifest["package_version"]
        assert set(manifest["builtins"]) == BUILTIN_FILE_NAMES
        for name, entry in manifest["builtins"].items():
            assert entry["sha256"] == sha256_file(REAL_BUILDIN_DIR / name)
            assert entry["function"] == Path(name).stem


class TestReinstallFunctions:
    """`--reinstall-functions` refreshes builtin copies and drops obsolete ones."""

    def test_reinstall_into_empty_dir(self, function_env):
        with pytest.raises(typer.Exit):
            reinstall_functions(None, True)

        assert {path.name for path in function_env.dir.glob("*.py")} == BUILTIN_FILE_NAMES
        printed = _printed(function_env.console)
        assert any("Reinstalling builtin functions" in text for text in printed)
        assert any("Reinstalled" in text for text in printed)

    def test_reinstall_overwrites_modified_builtin(self, function_env):
        """Modified builtin copies are restored to the packaged version."""
        function_env.dir.mkdir(parents=True)
        target = function_env.dir / "fs_read_file.py"
        target.write_text("# old/stale version\n")

        with pytest.raises(typer.Exit):
            reinstall_functions(None, True)

        assert target.read_text() == (REAL_BUILDIN_DIR / "fs_read_file.py").read_text()

    def test_reinstall_preserves_custom_file(self, function_env):
        """Custom files whose name is not a builtin are never touched."""
        function_env.dir.mkdir(parents=True)
        custom = function_env.dir / "my_custom.py"
        custom.write_text("# my custom function\n")

        with pytest.raises(typer.Exit):
            reinstall_functions(None, True)

        assert custom.read_text() == "# my custom function\n"

    def test_reinstall_removes_obsolete_untouched_copy(self, function_env):
        """A copy that was last installed as a builtin but no longer ships is removed."""
        function_env.dir.mkdir(parents=True)
        obsolete = function_env.dir / "removed_tool.py"
        obsolete.write_text("# old builtin\n")
        _write_manifest({"builtins": {"removed_tool.py": {"sha256": sha256_file(obsolete)}}})

        with pytest.raises(typer.Exit):
            reinstall_functions(None, True)

        assert not obsolete.exists()
        assert any("Removed stale function copy" in text for text in _printed(function_env.console))

    def test_reinstall_preserves_modified_obsolete_copy(self, function_env):
        """A user-edited copy of a removed builtin is kept (it is a custom tool now)."""
        function_env.dir.mkdir(parents=True)
        obsolete = function_env.dir / "removed_tool.py"
        obsolete.write_text("# customized after install\n")
        _write_manifest({"builtins": {"removed_tool.py": {"sha256": "0" * 64}}})

        with pytest.raises(typer.Exit):
            reinstall_functions(None, True)

        assert obsolete.read_text() == "# customized after install\n"
        assert any("Kept modified function copy" in text for text in _printed(function_env.console))

    def test_reinstall_rewrites_manifest(self, function_env):
        """Reinstall refreshes the manifest to describe the packaged builtins."""
        _write_manifest(
            {
                "manifest_version": 1,
                "package_version": "0.0.1",
                "builtins": {"removed_tool.py": {"sha256": "0" * 64}},
            }
        )

        with pytest.raises(typer.Exit):
            reinstall_functions(None, True)

        manifest = read_manifest()
        assert set(manifest["builtins"]) == BUILTIN_FILE_NAMES
        for name, entry in manifest["builtins"].items():
            assert entry["sha256"] == sha256_file(REAL_BUILDIN_DIR / name)

    def test_reinstall_tolerates_missing_manifest(self, function_env):
        """Upgrading from a version without a manifest still reinstalls cleanly."""
        with pytest.raises(typer.Exit):
            reinstall_functions(None, True)

        assert {path.name for path in function_env.dir.glob("*.py")} == BUILTIN_FILE_NAMES
        assert read_manifest() is not None


class TestManifestHelpers:
    def test_read_manifest_missing_returns_none(self, function_env):
        assert read_manifest() is None

    def test_read_manifest_malformed_returns_none(self, function_env):
        function_env.manifest.write_text("not json{{{")
        assert read_manifest() is None

    def test_read_manifest_normalizes_missing_builtins(self, function_env):
        _write_manifest({"package_version": "1.0.0"})
        assert read_manifest()["builtins"] == {}

    def test_read_manifest_non_dict_root_returns_none(self, function_env):
        function_env.manifest.write_text(json.dumps(["nope"]))
        assert read_manifest() is None

    def test_write_and_read_roundtrip(self, function_env):
        manifest = build_manifest()
        assert write_manifest(manifest) is True
        assert read_manifest() == manifest

    def test_write_manifest_failure_warns_instead_of_raising(self, function_env, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file, not a dir")
        failed_path = blocker / "nested" / "functions_manifest.json"

        assert write_manifest({"builtins": {}}, failed_path) is False
        assert any("could not write functions manifest" in text for text in _printed(function_env.error_console))

    def test_sha256_file_matches_hashlib(self, function_env):
        target = function_env.tmp / "payload.bin"
        target.write_bytes(b"hello world")

        assert sha256_file(target) == hashlib.sha256(b"hello world").hexdigest()

    def test_build_manifest_describes_package_builtins(self):
        manifest = build_manifest()

        assert manifest["manifest_version"] == 1
        assert isinstance(manifest["package_version"], str) and manifest["package_version"]
        assert set(manifest["builtins"]) == BUILTIN_FILE_NAMES

    def test_iter_buildin_files_skips_private_and_sorts(self, tmp_path):
        buildin = tmp_path / "buildin"
        buildin.mkdir()
        (buildin / "_private.py").write_text("x = 1\n")
        (buildin / "b.py").write_text("x = 1\n")
        (buildin / "a.py").write_text("x = 1\n")
        (buildin / "not_python.txt").write_text("x\n")

        assert [path.name for path in iter_buildin_files(buildin)] == ["a.py", "b.py"]


class TestStaleCopies:
    """Stale copies are detected from the manifest but only ever produce one warning."""

    def _installed_old_copy(self, function_env, name="fs_read_file.py", content="# old copy\n") -> Path:
        function_env.dir.mkdir(parents=True, exist_ok=True)
        copy = function_env.dir / name
        copy.write_text(content)
        return copy

    def test_no_manifest_means_no_stale_copies(self, function_env):
        self._installed_old_copy(function_env)

        assert detect_stale_copies() == []

    def test_untouched_old_copy_is_stale(self, function_env):
        """A copy matching the recorded hash while the package changed is stale."""
        copy = self._installed_old_copy(function_env)
        _write_manifest({"builtins": {"fs_read_file.py": {"sha256": sha256_file(copy)}}})

        assert detect_stale_copies() == ["fs_read_file.py"]

    def test_edited_copy_is_not_reported(self, function_env):
        """A user-edited copy is an intentional override, not a stale copy."""
        copy = self._installed_old_copy(function_env)
        _write_manifest({"builtins": {"fs_read_file.py": {"sha256": sha256_file(copy)}}})
        copy.write_text("# customized by the user\n")

        assert detect_stale_copies() == []

    def test_fresh_copy_is_not_stale(self, function_env):
        """A copy identical to the packaged file is up to date."""
        function_env.dir.mkdir(parents=True)
        copy = function_env.dir / "fs_read_file.py"
        copy.write_text((REAL_BUILDIN_DIR / "fs_read_file.py").read_text())
        _write_manifest({"builtins": {"fs_read_file.py": {"sha256": sha256_file(copy)}}})

        assert detect_stale_copies() == []

    def test_removed_builtin_copy_is_stale(self, function_env):
        """Copies of builtins removed from the package are stale too."""
        copy = self._installed_old_copy(function_env, name="removed_tool.py", content="# old builtin\n")
        _write_manifest({"builtins": {"removed_tool.py": {"sha256": sha256_file(copy)}}})

        assert detect_stale_copies() == ["removed_tool.py"]

    def test_warn_stale_copies_once(self, function_env):
        copy = self._installed_old_copy(function_env)
        _write_manifest({"builtins": {"fs_read_file.py": {"sha256": sha256_file(copy)}}})

        assert warn_stale_copies_once() == ["fs_read_file.py"]
        messages = _printed(function_env.error_console)
        assert len(messages) == 1
        assert "out of date" in messages[0]
        assert "reinstall-functions" in messages[0]

        assert warn_stale_copies_once() == []
        assert len(_printed(function_env.error_console)) == 1

    def test_no_warning_when_nothing_is_stale(self, function_env):
        assert warn_stale_copies_once() == []
        function_env.error_console.print.assert_not_called()


class TestPrintFunctions:
    """`--list-functions` lists loaded tools with their source."""

    def test_lists_loaded_tools_with_source(self, function_env, monkeypatch):
        functions = [
            SimpleNamespace(name="fs_read_file", source="builtin"),
            SimpleNamespace(name="my_custom", source="user"),
        ]
        monkeypatch.setattr("yaicli.tools.function.list_functions", lambda: functions)

        with pytest.raises(typer.Exit):
            print_functions(None, True)

        printed = _printed(function_env.console)
        assert any("Found 2 function(s)" in text for text in printed)
        assert "fs_read_file (builtin)" in printed
        assert "my_custom (user)" in printed

    def test_empty_map_reports_nothing(self, function_env, monkeypatch):
        monkeypatch.setattr("yaicli.tools.function.list_functions", lambda: [])

        with pytest.raises(typer.Exit):
            print_functions(None, True)

        assert any("No installed functions found" in text for text in _printed(function_env.console))

    def test_fresh_config_dir_lists_twelve_builtins(self, function_env, monkeypatch):
        """Acceptance: a config dir without a functions/ dir lists the 12 bundled tools."""
        missing_dir = function_env.tmp / "missing_functions"
        monkeypatch.setattr(loading_mod, "FUNCTIONS_DIR", missing_dir)
        monkeypatch.setattr(loading_mod, "_func_name_map", None)
        monkeypatch.setattr(loading_mod, "_gemini_functions_cache", None)

        with pytest.raises(typer.Exit):
            print_functions(None, True)

        printed = _printed(function_env.console)
        builtin_lines = [text for text in printed if text.endswith(" (builtin)")]
        assert len(builtin_lines) == len(BUILTIN_FILE_NAMES)
        assert "fs_read_file (builtin)" in printed
        assert not missing_dir.exists(), "listing must not create FUNCTIONS_DIR"
        assert not function_env.manifest.exists(), "listing must not write a manifest"

    def test_lists_user_override_and_warns_about_stale_copy(self, function_env, monkeypatch):
        """A stale installed copy is listed as ``user`` and produces one stderr warning."""
        function_env.dir.mkdir(parents=True)
        stale_copy = function_env.dir / "fs_read_file.py"
        outdated_source = (REAL_BUILDIN_DIR / "fs_read_file.py").read_text() + "\n# stale copy marker\n"
        stale_copy.write_text(outdated_source)
        _write_manifest({"builtins": {"fs_read_file.py": {"sha256": sha256_file(stale_copy)}}})
        monkeypatch.setattr(loading_mod, "FUNCTIONS_DIR", function_env.dir)
        monkeypatch.setattr(loading_mod, "_func_name_map", None)
        monkeypatch.setattr(loading_mod, "_gemini_functions_cache", None)

        with pytest.raises(typer.Exit):
            print_functions(None, True)

        printed = _printed(function_env.console)
        assert "fs_read_file (user)" in printed
        warnings = _printed(function_env.error_console)
        assert any("out of date" in text and "reinstall-functions" in text for text in warnings)
        assert len(warnings) == 1


class TestPrintMcp:
    """Tests for print_mcp."""

    def test_no_mcp_config(self, function_env, monkeypatch, tmp_path):
        """Reports when no MCP config file exists."""
        monkeypatch.setattr(functions_mod, "MCP_JSON_PATH", tmp_path / "mcp.json")

        with pytest.raises(typer.Exit):
            print_mcp(None, True)

        assert any("No mcp config found" in text for text in _printed(function_env.console))

    def test_prints_mcp_config(self, function_env, monkeypatch, tmp_path):
        """Prints the MCP config JSON when the file exists."""
        mcp_path = tmp_path / "mcp.json"
        mcp_path.write_text(json.dumps({"servers": {"a": 1}}))
        monkeypatch.setattr(functions_mod, "MCP_JSON_PATH", mcp_path)

        with pytest.raises(typer.Exit):
            print_mcp(None, True)

        function_env.console.print_json.assert_called_once()
