"""Tests for builtin direct-load, user override and per-file robustness (K01/K15)."""

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import yaicli.functions as functions_mod
import yaicli.tools as tools_mod
import yaicli.tools.function as func_mod

#: The real bundled templates inside the package (not patched in these tests).
REAL_BUILDIN_DIR = Path(func_mod.__file__).resolve().parent.parent / "functions" / "buildin"

#: The 12 tools bundled with the package (schema function names, == file stems).
BUILTIN_NAMES = {
    "execute_shell_command",
    "fetch_webpage",
    "fs_edit_file",
    "fs_file_operations",
    "fs_get_filesystem_info",
    "fs_list_directory",
    "fs_read_file",
    "fs_read_image",
    "fs_search_files",
    "fs_write_file",
    "get_weather",
    "web_search",
}

# Helper: write a valid function file using yaicli.function_schema
VALID_FUNC_SOURCE = textwrap.dedent("""\
    from yaicli.function_schema import OpenAISchema
    from pydantic import Field

    class Function(OpenAISchema):
        \"\"\"A test function.\"\"\"
        arg: str = Field(..., description="An argument")
        class Config:
            title = "test_func"
        @classmethod
        def execute(cls, arg: str) -> str:
            return arg
""")

# Helper: a user file whose schema name equals a bundled builtin -> it must override it.
OVERRIDE_FUNC_SOURCE = textwrap.dedent("""\
    from yaicli.function_schema import OpenAISchema
    from pydantic import Field

    class Function(OpenAISchema):
        \"\"\"User override of the bundled fs_read_file.\"\"\"
        arg: str = Field(..., description="An argument")
        class Config:
            title = "fs_read_file"
        @classmethod
        def execute(cls, arg: str) -> str:
            return "overridden:" + arg
""")

# Helper: a function file using old instructor import
OLD_FUNC_SOURCE = textwrap.dedent("""\
    from instructor import OpenAISchema
    from pydantic import Field

    class Function(OpenAISchema):
        \"\"\"An old function.\"\"\"
        arg: str = Field(..., description="An argument")
        class Config:
            title = "old_func"
        @classmethod
        def execute(cls, arg: str) -> str:
            return arg
""")

NO_SCHEMA_SOURCE = textwrap.dedent("""\
    from pydantic import BaseModel
    class Function(BaseModel):
        name: str = "bad"
        @classmethod
        def execute(cls):
            pass
""")

NO_EXECUTE_SOURCE = textwrap.dedent("""\
    from yaicli.function_schema import OpenAISchema
    from pydantic import Field
    class Function(OpenAISchema):
        \"\"\"No execute.\"\"\"
        arg: str = Field(...)
        class Config:
            title = "no_exec"
""")


@pytest.fixture(autouse=True)
def reset_caches(tmp_path, monkeypatch):
    """Reset every module-level cache and keep manifest lookups inside ``tmp_path``."""
    monkeypatch.setattr(func_mod, "_func_name_map", None)
    monkeypatch.setattr(func_mod, "_gemini_functions_cache", None)
    monkeypatch.setattr(func_mod, "_deprecated_warned", set())
    monkeypatch.setattr(tools_mod, "_openai_schemas_cache", None)
    monkeypatch.setattr(tools_mod, "_anthropic_schemas_cache", None)
    monkeypatch.setattr(functions_mod, "_stale_warned", False)
    monkeypatch.setattr(functions_mod, "FUNCTIONS_MANIFEST_PATH", tmp_path / "functions_manifest.json")


@pytest.fixture
def empty_buildin_dir(tmp_path, monkeypatch):
    """Patch BUILDIN_DIR to an empty dir so a test only exercises user functions."""
    buildin = tmp_path / "buildin"
    buildin.mkdir()
    monkeypatch.setattr(func_mod, "BUILDIN_DIR", buildin)
    return buildin


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    """Create a temporary FUNCTIONS_DIR and patch it."""
    funcs = tmp_path / "functions"
    funcs.mkdir()
    monkeypatch.setattr(func_mod, "FUNCTIONS_DIR", funcs)
    return funcs


@pytest.fixture
def error_console(monkeypatch):
    """Capture warnings that the loader sends to the stderr console."""
    mock = MagicMock()
    monkeypatch.setattr(func_mod, "get_error_console", lambda: mock)
    return mock


def _warn_messages(mock: MagicMock) -> list[str]:
    return [str(call.args[0]) for call in mock.print.call_args_list if call.args]


class TestBuiltinDirectLoad:
    """K01: the packaged tools load without any install step."""

    def test_loads_all_builtins_from_package(self, user_dir):
        """A fresh (empty) FUNCTIONS_DIR still yields all 12 bundled tools."""
        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES
        assert {func.source for func in result.values()} == {"builtin"}
        assert all(func.file_path is not None for func in result.values())

    def test_builtins_available_without_config_dir(self, tmp_path, monkeypatch):
        """A missing FUNCTIONS_DIR means 'builtins only' and is never created."""
        missing = tmp_path / "does-not-exist"
        monkeypatch.setattr(func_mod, "FUNCTIONS_DIR", missing)

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES
        assert not missing.exists(), "lookup must not create FUNCTIONS_DIR"

    def test_builtin_schemas_and_execute_are_usable(self, user_dir):
        """Every builtin exposes name/description/parameters and an execute callable."""
        result = func_mod.get_func_name_map()

        for name, function in result.items():
            assert function.name == name
            assert function.description
            assert isinstance(function.parameters, dict)
            assert "properties" in function.parameters
            assert callable(function.execute)
            assert function.func_cls.openai_schema["name"] == name

    def test_builtins_expose_risk_attribute(self, user_dir):
        """Every loaded Function carries a risk attribute (K06 integration point)."""
        result = func_mod.get_func_name_map()

        assert all(hasattr(func, "risk") for func in result.values())

    def test_risk_lookup_result_is_stored(self, user_dir, monkeypatch):
        """The risk class resolved for a tool is stored on the Function wrapper."""
        monkeypatch.setattr(func_mod, "_resolve_tool_risk", lambda name: f"risk:{name}")

        result = func_mod.get_func_name_map()

        assert result["fs_read_file"].risk == "risk:fs_read_file"

    def test_risk_tolerates_unavailable_risk_module(self):
        """A missing yaicli.tools.risk module degrades to ``None`` instead of raising."""
        with patch.dict(sys.modules, {"yaicli.tools.risk": None}):
            assert func_mod._resolve_tool_risk("fs_read_file") is None

    def test_gemini_format_uses_builtins(self, user_dir):
        """Gemini callables are generated from the merged map (requirement 6)."""
        callables = func_mod.get_functions_gemini_format()

        assert len(callables) == 12
        names = {func.__name__ for func in callables}
        assert names == BUILTIN_NAMES
        execute_shell = next(func for func in callables if func.__name__ == "execute_shell_command")
        assert execute_shell.__doc__


class TestUserOverride:
    """A user file whose schema function name matches a builtin replaces it."""

    def test_user_override_wins_by_schema_name(self, user_dir):
        """Even a differently named file overrides a builtin through its schema name."""
        (user_dir / "my_reader.py").write_text(OVERRIDE_FUNC_SOURCE)

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES
        overridden = result["fs_read_file"]
        assert overridden.source == "user"
        assert overridden.execute(arg="x") == "overridden:x"
        # Untouched builtins keep their builtin source.
        assert result["fs_search_files"].source == "builtin"

    def test_user_override_by_builtin_filename(self, user_dir):
        """Copying a builtin file name is the editable-copy workflow and must win."""
        (user_dir / "fs_read_file.py").write_text(OVERRIDE_FUNC_SOURCE)

        result = func_mod.get_func_name_map()

        assert result["fs_read_file"].source == "user"
        assert result["fs_read_file"].execute(arg="x") == "overridden:x"
        assert result["fs_read_file"].file_path == user_dir / "fs_read_file.py"

    def test_user_custom_function_is_added(self, user_dir):
        """A custom function is added next to the builtins."""
        (user_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES | {"test_func"}
        assert result["test_func"].source == "user"
        assert result["test_func"].execute(arg="hello") == "hello"

    def test_underscore_files_are_skipped(self, user_dir):
        """Files starting with ``_`` are not loaded."""
        (user_dir / "_private.py").write_text(VALID_FUNC_SOURCE)

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES


class TestBrokenFileRobustness:
    """K15: one broken file is skipped with one warning; everything else keeps working."""

    def test_broken_syntax_file_is_skipped(self, user_dir, error_console):
        """A syntax error in one file does not prevent the other tools from loading."""
        (user_dir / "broken.py").write_text("def broken(:\n")
        (user_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES | {"test_func"}
        messages = _warn_messages(error_console)
        assert len(messages) == 1
        assert "broken.py" in messages[0]
        assert "Skipping" in messages[0]
        assert "SyntaxError" in messages[0]

    def test_import_error_file_is_skipped(self, user_dir, error_console):
        """A missing top-level import in one file is an in-band skip."""
        (user_dir / "bad_import.py").write_text("import a_module_that_does_not_exist_xyz\n")

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES
        assert any("bad_import.py" in message for message in _warn_messages(error_console))

    def test_missing_function_class_is_skipped(self, user_dir, error_console):
        """A file without a ``Function`` class is skipped instead of raising."""
        (user_dir / "no_class.py").write_text("x = 1\n")

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES
        messages = _warn_messages(error_console)
        assert len(messages) == 1
        assert "Function" in messages[0]

    def test_missing_schema_is_skipped(self, user_dir, error_console):
        """A Function class that is not an OpenAISchema is skipped instead of raising."""
        (user_dir / "bad_func.py").write_text(NO_SCHEMA_SOURCE)

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES
        messages = _warn_messages(error_console)
        assert len(messages) == 1
        assert "yaicli.function_schema.OpenAISchema" in messages[0]

    def test_missing_execute_is_skipped(self, user_dir, error_console):
        """A Function class without ``execute`` is skipped instead of raising."""
        (user_dir / "no_exec.py").write_text(NO_EXECUTE_SOURCE)

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES
        messages = _warn_messages(error_console)
        assert len(messages) == 1
        assert "execute" in messages[0]

    def test_each_broken_file_warns_exactly_once(self, user_dir, error_console):
        """The warning is emitted once per broken file for the lifetime of the cache."""
        (user_dir / "broken_a.py").write_text("def broken(:\n")
        (user_dir / "broken_b.py").write_text("import a_module_that_does_not_exist_xyz\n")

        func_mod.get_func_name_map()
        func_mod.get_func_name_map()

        assert len(_warn_messages(error_console)) == 2

    def test_broken_file_does_not_break_gemini_format(self, user_dir, error_console):
        """Gemini callables are built from the surviving tools only."""
        (user_dir / "broken.py").write_text("def broken(:\n")

        callables = func_mod.get_functions_gemini_format()

        assert {func.__name__ for func in callables} == BUILTIN_NAMES


class TestDeprecatedImportWarning:
    """Legacy `instructor` imports warn once on stderr but keep loading."""

    def test_warns_on_instructor_import(self, user_dir, error_console):
        """A deprecation warning is printed for old instructor imports."""
        (user_dir / "old_func.py").write_text(OLD_FUNC_SOURCE)

        func_mod.get_func_name_map()

        messages = _warn_messages(error_console)
        assert any("deprecated" in message for message in messages)
        assert any("reinstall-functions" in message for message in messages)

    def test_warns_only_once_per_file(self, user_dir, error_console):
        """The same file only triggers the deprecation warning once."""
        (user_dir / "old_func.py").write_text(OLD_FUNC_SOURCE)

        func_mod._check_deprecated_import(user_dir / "old_func.py")
        func_mod._check_deprecated_import(user_dir / "old_func.py")

        assert len(_warn_messages(error_console)) == 1

    def test_no_warning_for_new_import(self, user_dir, error_console):
        """Files using yaicli.function_schema do not warn."""
        (user_dir / "new_func.py").write_text(VALID_FUNC_SOURCE)

        func_mod._check_deprecated_import(user_dir / "new_func.py")

        error_console.print.assert_not_called()


class TestCaching:
    def test_function_map_is_cached(self, user_dir, empty_buildin_dir):
        """The merged map is cached after the first call."""
        (user_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)

        first = func_mod.get_func_name_map()
        second = func_mod.get_func_name_map()

        assert first is second

    def test_list_functions_uses_cached_map(self, user_dir, empty_buildin_dir):
        (user_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)

        functions = func_mod.list_functions()

        assert [func.name for func in functions] == ["test_func"]

    def test_get_function_returns_loaded_tool(self, user_dir, empty_buildin_dir):
        (user_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)

        function = func_mod.get_function("test_func")

        assert function.execute(arg="hi") == "hi"

    def test_get_function_raises_for_unknown_tool(self, user_dir, empty_buildin_dir):
        func_mod.get_func_name_map()

        with pytest.raises(ValueError, match="not found"):
            func_mod.get_function("nope")

    def test_openai_schemas_cached(self, user_dir, empty_buildin_dir):
        """get_openai_schemas returns the cached schema list on the second call."""
        (user_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)

        first = tools_mod.get_openai_schemas()
        second = tools_mod.get_openai_schemas()

        assert first is second
        assert len(first) == 1
        assert first[0]["type"] == "function"
        assert first[0]["function"]["name"] == "test_func"

    def test_anthropic_schemas_cached(self, user_dir, empty_buildin_dir):
        """get_anthropic_schemas returns the cached schema list on the second call."""
        (user_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)

        first = tools_mod.get_anthropic_schemas()
        second = tools_mod.get_anthropic_schemas()

        assert first is second
        assert len(first) == 1
        assert first[0]["name"] == "test_func"
        assert "input_schema" in first[0]

    def test_gemini_format_cached(self, user_dir, empty_buildin_dir):
        """get_functions_gemini_format returns the cached callables on the second call."""
        (user_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)

        first = func_mod.get_functions_gemini_format()
        second = func_mod.get_functions_gemini_format()

        assert first is second
        assert len(first) == 1
        assert first[0].__name__ == "test_func"


class TestStaleCopyWarningIntegration:
    """The loader points out stale copies once, but a stale check can never block loading."""

    def test_loader_checks_for_stale_copies_once(self, user_dir, monkeypatch):
        calls = []
        monkeypatch.setattr(functions_mod, "warn_stale_copies_once", lambda **kwargs: calls.append(kwargs) or [])

        func_mod.get_func_name_map()

        assert len(calls) == 1
        assert calls[0]["functions_dir"] == user_dir
        assert calls[0]["buildin_dir"] == REAL_BUILDIN_DIR

    def test_stale_check_failure_does_not_block_loading(self, user_dir, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("manifest exploded")

        monkeypatch.setattr(functions_mod, "warn_stale_copies_once", boom)

        result = func_mod.get_func_name_map()

        assert set(result) == BUILTIN_NAMES

    def test_no_warning_without_manifest(self, user_dir, error_console):
        """A fresh config dir (no manifest) never produces a stale-copy warning."""
        func_mod.get_func_name_map()

        error_console.print.assert_not_called()
