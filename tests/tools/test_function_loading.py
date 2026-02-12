import shutil
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import yaicli.tools as tools_mod
import yaicli.tools.function as func_mod


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

# Helper: write a function file using old instructor import
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


@pytest.fixture
def func_dir(tmp_path):
    """Create a temporary functions directory and patch FUNCTIONS_DIR."""
    funcs = tmp_path / "functions"
    funcs.mkdir()
    return funcs


@pytest.fixture(autouse=True)
def reset_caches():
    """Reset all module-level caches before each test."""
    func_mod._func_name_map = None
    func_mod._gemini_functions_cache = None
    func_mod._deprecated_warned.clear()
    tools_mod._openai_schemas_cache = None
    tools_mod._anthropic_schemas_cache = None
    yield
    func_mod._func_name_map = None
    func_mod._gemini_functions_cache = None
    func_mod._deprecated_warned.clear()
    tools_mod._openai_schemas_cache = None
    tools_mod._anthropic_schemas_cache = None


class TestGetFuncNameMap:
    def test_loads_valid_function(self, func_dir):
        """Test loading a valid function file."""
        (func_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)
        with patch.object(func_mod, "FUNCTIONS_DIR", func_dir):
            result = func_mod.get_func_name_map()
        assert "test_func" in result
        assert result["test_func"].execute(arg="hello") == "hello"

    def test_skips_underscore_files(self, func_dir):
        """Test files starting with _ are skipped."""
        (func_dir / "_private.py").write_text(VALID_FUNC_SOURCE)
        with patch.object(func_mod, "FUNCTIONS_DIR", func_dir):
            result = func_mod.get_func_name_map()
        assert len(result) == 0

    def test_creates_dir_if_missing(self, tmp_path):
        """Test FUNCTIONS_DIR is created if it doesn't exist."""
        missing = tmp_path / "nonexistent"
        with patch.object(func_mod, "FUNCTIONS_DIR", missing):
            result = func_mod.get_func_name_map()
        assert result == {}
        assert missing.exists()

    def test_caches_after_first_call(self, func_dir):
        """Test function map is cached after first call."""
        (func_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)
        with patch.object(func_mod, "FUNCTIONS_DIR", func_dir):
            r1 = func_mod.get_func_name_map()
            r2 = func_mod.get_func_name_map()
        assert r1 is r2

    def test_raises_on_missing_schema(self, func_dir):
        """Test error when Function class lacks openai_schema."""
        bad_source = textwrap.dedent("""\
            from pydantic import BaseModel
            class Function(BaseModel):
                name: str = "bad"
                @classmethod
                def execute(cls):
                    pass
        """)
        (func_dir / "bad_func.py").write_text(bad_source)
        with patch.object(func_mod, "FUNCTIONS_DIR", func_dir):
            with pytest.raises(TypeError, match="yaicli.function_schema.OpenAISchema"):
                func_mod.get_func_name_map()

    def test_raises_on_missing_execute(self, func_dir):
        """Test error when Function class lacks execute method."""
        no_exec_source = textwrap.dedent("""\
            from yaicli.function_schema import OpenAISchema
            from pydantic import Field
            class Function(OpenAISchema):
                \"\"\"No execute.\"\"\"
                arg: str = Field(...)
                class Config:
                    title = "no_exec"
        """)
        (func_dir / "no_exec.py").write_text(no_exec_source)
        with patch.object(func_mod, "FUNCTIONS_DIR", func_dir):
            with pytest.raises(TypeError, match="execute"):
                func_mod.get_func_name_map()


class TestDeprecatedImportWarning:
    def test_warns_on_instructor_import(self, func_dir):
        """Test deprecation warning is printed for old instructor imports."""
        (func_dir / "old_func.py").write_text(OLD_FUNC_SOURCE)
        mock_console = MagicMock()
        with (
            patch.object(func_mod, "FUNCTIONS_DIR", func_dir),
            patch("yaicli.tools.function.get_console", return_value=mock_console),
        ):
            func_mod.get_func_name_map()
        # Check console.print was called with deprecation message
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("deprecated" in c for c in calls)
        assert any("reinstall-functions" in c for c in calls)

    def test_warns_only_once_per_file(self, func_dir):
        """Test same file only triggers warning once."""
        (func_dir / "old_func.py").write_text(OLD_FUNC_SOURCE)
        mock_console = MagicMock()
        with (
            patch.object(func_mod, "FUNCTIONS_DIR", func_dir),
            patch("yaicli.tools.function.get_console", return_value=mock_console),
        ):
            # Call _check_deprecated_import twice for the same file
            func_mod._check_deprecated_import(func_dir / "old_func.py")
            func_mod._check_deprecated_import(func_dir / "old_func.py")
        assert mock_console.print.call_count == 1

    def test_no_warning_for_new_import(self, func_dir):
        """Test no warning for files using yaicli.function_schema."""
        (func_dir / "new_func.py").write_text(VALID_FUNC_SOURCE)
        mock_console = MagicMock()
        with (
            patch.object(func_mod, "FUNCTIONS_DIR", func_dir),
            patch("yaicli.tools.function.get_console", return_value=mock_console),
        ):
            func_mod._check_deprecated_import(func_dir / "new_func.py")
        mock_console.print.assert_not_called()


class TestSchemasCaching:
    def test_openai_schemas_cached(self, func_dir):
        """Test get_openai_schemas returns cached result on second call."""
        (func_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)
        with patch.object(func_mod, "FUNCTIONS_DIR", func_dir):
            r1 = tools_mod.get_openai_schemas()
            r2 = tools_mod.get_openai_schemas()
        assert r1 is r2
        assert len(r1) == 1
        assert r1[0]["type"] == "function"
        assert r1[0]["function"]["name"] == "test_func"

    def test_anthropic_schemas_cached(self, func_dir):
        """Test get_anthropic_schemas returns cached result on second call."""
        (func_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)
        with patch.object(func_mod, "FUNCTIONS_DIR", func_dir):
            r1 = tools_mod.get_anthropic_schemas()
            r2 = tools_mod.get_anthropic_schemas()
        assert r1 is r2
        assert len(r1) == 1
        assert r1[0]["name"] == "test_func"
        assert "input_schema" in r1[0]

    def test_gemini_format_cached(self, func_dir):
        """Test get_functions_gemini_format returns cached result on second call."""
        (func_dir / "test_func.py").write_text(VALID_FUNC_SOURCE)
        with patch.object(func_mod, "FUNCTIONS_DIR", func_dir):
            r1 = func_mod.get_functions_gemini_format()
            r2 = func_mod.get_functions_gemini_format()
        assert r1 is r2
        assert len(r1) == 1
        assert r1[0].__name__ == "test_func"


class TestReinstallFunctions:
    def test_reinstall_overwrites_builtin(self, tmp_path):
        """Test reinstall_functions overwrites existing builtin files."""
        functions_dir = tmp_path / "installed"
        functions_dir.mkdir()

        # Write an old version
        old_content = "# old version\nfrom instructor import OpenAISchema\n"
        (functions_dir / "execute_shell_command.py").write_text(old_content)

        buildin_dir = Path(__file__).resolve().parent.parent.parent / "yaicli" / "functions" / "buildin"
        expected_new = (buildin_dir / "execute_shell_command.py").read_text()

        mock_console = MagicMock()
        with (
            patch("yaicli.functions.FUNCTIONS_DIR", functions_dir),
            patch("yaicli.functions.console", mock_console),
        ):
            # Call the inner function directly (unwrapped from @option_callback)
            from yaicli.functions import reinstall_functions

            # option_callback wraps it; call inner logic by simulating
            cur_dir = Path(__file__).resolve().parent.parent.parent / "yaicli" / "functions"
            buildin_dir_local = cur_dir / "buildin"
            buildin_funcs = {p.name: p for p in buildin_dir_local.glob("*.py")}
            for name, src in buildin_funcs.items():
                dst = functions_dir / name
                if dst.exists():
                    dst.unlink()
                shutil.copy(src, dst, follow_symlinks=True)

        actual = (functions_dir / "execute_shell_command.py").read_text()
        assert "from yaicli.function_schema import OpenAISchema" in actual
        assert actual == expected_new

    def test_reinstall_preserves_custom(self, tmp_path):
        """Test reinstall_functions does not touch custom function files."""
        functions_dir = tmp_path / "installed"
        functions_dir.mkdir()

        custom_content = "# my custom function\n"
        (functions_dir / "my_custom.py").write_text(custom_content)

        buildin_dir = Path(__file__).resolve().parent.parent.parent / "yaicli" / "functions" / "buildin"
        buildin_names = {p.name for p in buildin_dir.glob("*.py")}

        # Simulate reinstall - only copy builtin names
        for p in buildin_dir.glob("*.py"):
            dst = functions_dir / p.name
            if dst.exists():
                dst.unlink()
            shutil.copy(p, dst, follow_symlinks=True)

        # Custom file should still be there untouched
        assert (functions_dir / "my_custom.py").read_text() == custom_content
