"""Test fs_read_file function."""

import json
from unittest.mock import MagicMock, patch

import pytest

from yaicli.functions.buildin.fs_read_file import Function
from yaicli.schemas import ToolCall
from yaicli.tools import execute_tool_call
from yaicli.tools.function import Function as ToolFunction, wrap_gemini_function

FAKE_CFG = {"SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False}


class TestFSReadFile:
    def test_execute_single_file(self, tmp_path):
        """Test reading a single file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["path"] == str(test_file)
        assert result_dict["content"] == "Hello World"
        assert result_dict["size"] == 11

    def test_execute_multiple_files(self, tmp_path):
        """Test reading multiple files."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("Content 1")
        file2 = tmp_path / "file2.txt"
        file2.write_text("Content 2")

        result = Function.execute([str(file1), str(file2)])
        result_dict = json.loads(result)

        assert result_dict["total_files"] == 2
        assert result_dict["success_count"] == 2
        assert result_dict["error_count"] == 0
        assert len(result_dict["files"]) == 2
        assert result_dict["files"][0]["content"] == "Content 1"
        assert result_dict["files"][1]["content"] == "Content 2"

    def test_execute_file_not_exists(self):
        """Test reading a non-existent file."""
        result = Function.execute("/nonexistent/file.txt")
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "File does not exist" in result_dict["error"]

    def test_execute_path_is_directory(self, tmp_path):
        """Test reading when path is a directory."""
        result = Function.execute(str(tmp_path))
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Not a file" in result_dict["error"]

    def test_execute_with_custom_encoding(self, tmp_path):
        """Test reading with custom encoding."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World", encoding="utf-8")

        result = Function.execute(str(test_file), encoding="utf-8")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == "Hello World"

    def test_execute_empty_file(self, tmp_path):
        """Test reading an empty file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == ""
        assert result_dict["size"] == 0

    def test_execute_large_file(self, tmp_path):
        """Test reading a large file."""
        test_file = tmp_path / "test.txt"
        content = "Line\n" * 10000
        test_file.write_text(content)

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == content
        assert result_dict["size"] == len(content)

    def test_execute_multiline_content(self, tmp_path):
        """Test reading multiline content."""
        test_file = tmp_path / "test.txt"
        content = "Line 1\nLine 2\nLine 3"
        test_file.write_text(content)

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == content

    def test_execute_special_characters(self, tmp_path):
        """Test reading special characters."""
        test_file = tmp_path / "test.txt"
        content = "Hello 世界! 🌍\nTest\tTabbed"
        test_file.write_text(content, encoding="utf-8")

        result = Function.execute(str(test_file), encoding="utf-8")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == content

    def test_execute_binary_file(self, tmp_path):
        """Test reading a binary file."""
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"\x00\x01\x02\x03")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == "\u0000\u0001\u0002\u0003"

    def test_execute_file_with_bom(self, tmp_path):
        """Test reading a file with BOM."""
        test_file = tmp_path / "test.txt"
        content = "Hello World"
        test_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

        result = Function.execute(str(test_file), encoding="utf-8-sig")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == content

    def test_execute_multiple_files_one_error(self, tmp_path):
        """Test reading multiple files where one fails."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("Content 1")

        result = Function.execute([str(file1), "/nonexistent/file.txt"])
        result_dict = json.loads(result)

        assert result_dict["total_files"] == 2
        assert result_dict["success_count"] == 1
        assert result_dict["error_count"] == 1
        assert len(result_dict["files"]) == 2
        assert result_dict["files"][0]["success"] is True
        assert result_dict["files"][1]["success"] is False

    def test_execute_file_structure(self, tmp_path):
        """Test that file info has correct structure."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "path" in result_dict
        assert "content" in result_dict
        assert "size" in result_dict
        assert "error" in result_dict

    def test_execute_file_size_accuracy(self, tmp_path):
        """Test that file size is accurate."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["size"] == 11

    def test_execute_with_different_encodings(self, tmp_path):
        """Test reading with different encodings."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World", encoding="utf-8")

        result = Function.execute(str(test_file), encoding="utf-8")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == "Hello World"

    def test_execute_file_with_newlines(self, tmp_path):
        """Test reading a file with newlines."""
        test_file = tmp_path / "test.txt"
        content = "Line 1\nLine 2\nLine 3\n"
        test_file.write_text(content)

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == content

    def test_execute_file_with_tabs(self, tmp_path):
        """Test reading a file with tabs."""
        test_file = tmp_path / "test.txt"
        content = "Column1\tColumn2\tColumn3"
        test_file.write_text(content)

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == content

    def test_execute_file_with_unicode(self, tmp_path):
        """Test reading a file with unicode content."""
        test_file = tmp_path / "test.txt"
        content = "Hello 世界! Привет! مرحبا! こんにちは!"
        test_file.write_text(content, encoding="utf-8")

        result = Function.execute(str(test_file), encoding="utf-8")
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == content

    def test_execute_returns_json_string(self, tmp_path):
        """Test that execute returns a valid JSON string."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = Function.execute(str(test_file))

        assert isinstance(result, str)

        result_dict = json.loads(result)
        assert isinstance(result_dict, dict)

    def test_execute_too_many_files(self, tmp_path):
        """Test reading too many files."""
        file_paths = [str(tmp_path / f"file{i}.txt") for i in range(51)]

        result = Function.execute(file_paths)
        result_dict = json.loads(result)

        assert "error" in result_dict
        assert "Too many files" in result_dict["error"]

    def test_execute_file_too_large(self, tmp_path):
        """Test reading a file that's too large."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"X" * (11 * 1024 * 1024))

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "File too large" in result_dict["error"]

    def test_execute_total_size_limit(self, tmp_path):
        """Test that total size limit is enforced."""
        file1 = tmp_path / "file1.txt"
        file1.write_bytes(b"X" * (30 * 1024 * 1024))
        file2 = tmp_path / "file2.txt"
        file2.write_bytes(b"X" * (30 * 1024 * 1024))

        result = Function.execute([str(file1), str(file2)])
        result_dict = json.loads(result)

        assert result_dict["files"][0]["success"] is False
        assert "File too large" in result_dict["files"][0]["error"]
        assert result_dict["files"][1]["success"] is False
        assert "File too large" in result_dict["files"][1]["error"]

    def test_execute_permission_denied(self, tmp_path):
        """Test reading a file with permission denied."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        test_file.chmod(0o000)

        try:
            result = Function.execute(str(test_file))
            result_dict = json.loads(result)

            assert result_dict["success"] is False
            assert "Permission denied" in result_dict["error"]
        finally:
            test_file.chmod(0o644)

    def test_execute_error_field_none_on_success(self, tmp_path):
        """Test that error field is None on success."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["error"] is None

    def test_execute_error_field_set_on_failure(self):
        """Test that error field is set on failure."""
        result = Function.execute("/nonexistent/file.txt")
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert result_dict["error"] is not None

    def test_execute_empty_file_list(self):
        """Test reading with empty file list."""
        result = Function.execute([])
        result_dict = json.loads(result)

        assert "error" in result_dict
        assert "No file paths provided" in result_dict["error"]

    def test_execute_single_file_in_list(self, tmp_path):
        """Test reading a single file provided as a list."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = Function.execute([str(test_file)])
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == "Hello World"

    def test_execute_total_size_in_result(self, tmp_path):
        """Test that total_size is included in result."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("Content 1")
        file2 = tmp_path / "file2.txt"
        file2.write_text("Content 2")

        result = Function.execute([str(file1), str(file2)])
        result_dict = json.loads(result)

        assert result_dict["total_size"] == 18


class TestFSReadFileSchema:
    """The model-facing schema must advertise a list of paths, not a union."""

    def test_openai_schema_file_paths_is_string_array(self):
        """file_paths is an array of strings with no anyOf union."""
        parameters = Function.openai_schema["parameters"]
        file_paths = parameters["properties"]["file_paths"]

        assert file_paths["type"] == "array"
        assert file_paths["items"] == {"type": "string"}
        assert "anyOf" not in file_paths
        assert "file_paths" in parameters["required"]

        description = file_paths["description"]
        assert "list" in description
        assert "several files" in description or "multiple files" in description

    def test_anthropic_schema_file_paths_is_string_array(self):
        """Anthropic input schema advertises the same array contract."""
        input_schema = Function.anthropic_schema["input_schema"]
        file_paths = input_schema["properties"]["file_paths"]

        assert file_paths["type"] == "array"
        assert file_paths["items"] == {"type": "string"}
        assert "anyOf" not in file_paths
        assert "file_paths" in input_schema["required"]

        description = file_paths["description"]
        assert "list" in description
        assert "several files" in description or "multiple files" in description

    def test_openai_schema_description_mentions_single_call(self):
        """The function description tells the model several files can be read at once."""
        description = Function.openai_schema["description"].lower()

        assert "one or more files" in description
        assert "single call" in description


class TestFSReadFileToolCall:
    """End-to-end coverage through the runtime tool-call executor."""

    def test_tool_call_reads_multiple_files_in_one_call(self, tmp_path):
        """One tool call with a file_paths array returns every file's content."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("Content 1")
        file2 = tmp_path / "file2.txt"
        file2.write_text("Content 2")

        tool = ToolFunction(function=Function)
        tool_call = ToolCall(
            id="1",
            name="fs_read_file",
            arguments=json.dumps({"file_paths": [str(file1), str(file2)]}),
        )
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", MagicMock()),
        ):
            result, ok = execute_tool_call(tool_call)

        assert ok is True
        result_dict = json.loads(result)
        assert result_dict["total_files"] == 2
        assert result_dict["success_count"] == 2
        assert result_dict["error_count"] == 0
        assert [item["path"] for item in result_dict["files"]] == [str(file1), str(file2)]
        assert [item["content"] for item in result_dict["files"]] == ["Content 1", "Content 2"]

    def test_tool_call_accepts_legacy_single_path_string(self, tmp_path):
        """A legacy tool call passing one path string still succeeds."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        tool = ToolFunction(function=Function)
        tool_call = ToolCall(
            id="1",
            name="fs_read_file",
            arguments=json.dumps({"file_paths": str(test_file)}),
        )
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", MagicMock()),
        ):
            result, ok = execute_tool_call(tool_call)

        assert ok is True
        result_dict = json.loads(result)
        assert result_dict["success"] is True
        assert result_dict["content"] == "Hello World"

    def test_tool_call_invalid_type_returns_error_json(self):
        """A wrong file_paths type yields an error JSON payload instead of raising."""
        tool = ToolFunction(function=Function)
        tool_call = ToolCall(id="1", name="fs_read_file", arguments=json.dumps({"file_paths": 42}))
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", MagicMock()),
        ):
            result, ok = execute_tool_call(tool_call)

        # The tool call itself does not crash the loop; the failure is reported in-band.
        assert ok is True
        result_dict = json.loads(result)
        assert "error" in result_dict
        assert "file_paths must be a list" in result_dict["error"]


class TestFSReadFileInputCompatibility:
    """Backward compatibility and robustness for the accepted file_paths forms."""

    def test_execute_single_path_string_backward_compatible(self, tmp_path):
        """A single path string keeps returning the flat single-file payload."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["content"] == "Hello World"
        assert result_dict["error"] is None
        assert "files" not in result_dict
        assert "success_count" not in result_dict

    def test_execute_accepts_tuple_of_paths(self, tmp_path):
        """A tuple of paths is normalized to the aggregate multi-file payload."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("Content 1")
        file2 = tmp_path / "file2.txt"
        file2.write_text("Content 2")

        result = Function.execute((str(file1), str(file2)))
        result_dict = json.loads(result)

        assert result_dict["success_count"] == 2
        assert [item["content"] for item in result_dict["files"]] == ["Content 1", "Content 2"]

    @pytest.mark.parametrize(
        "invalid_value",
        [{"a": 1}, 42, 3.14, None],
        ids=["dict", "int", "float", "none"],
    )
    def test_execute_invalid_type_returns_error_json(self, invalid_value):
        """Non-list, non-string file_paths values produce an error JSON payload."""
        result = Function.execute(invalid_value)
        result_dict = json.loads(result)

        assert "error" in result_dict
        assert "file_paths must be a list" in result_dict["error"]
        assert type(invalid_value).__name__ in result_dict["error"]

    def test_execute_multiple_files_partial_failure_keeps_successful_content(self, tmp_path):
        """Missing paths are reported per file while successful contents are kept."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("Content 1")
        file2 = tmp_path / "file2.txt"
        file2.write_text("Content 2")

        result = Function.execute(
            [str(file1), str(tmp_path / "missing.txt"), str(file2)],
        )
        result_dict = json.loads(result)

        assert result_dict["total_files"] == 3
        assert result_dict["success_count"] == 2
        assert result_dict["error_count"] == 1
        assert result_dict["files"][0]["success"] is True
        assert result_dict["files"][0]["content"] == "Content 1"
        assert result_dict["files"][1]["success"] is False
        assert result_dict["files"][1]["error"] == "File does not exist"
        assert result_dict["files"][2]["success"] is True
        assert result_dict["files"][2]["content"] == "Content 2"


class TestFSReadFileGeminiSchema:
    """Regression guard for the Gemini tool declaration built from execute()."""

    @staticmethod
    def _type_name(value):
        """Normalize a google-genai Type enum (or plain string) to its name."""
        if value is None:
            return None
        return getattr(value, "name", None) or str(value).rsplit(".", 1)[-1]

    @pytest.fixture(scope="class")
    def declaration(self):
        """Build the declaration the same way yaicli's Gemini provider does."""
        pytest.importorskip("google.genai")
        from google.genai import types

        wrapped = wrap_gemini_function(Function.execute)
        wrapped.__name__ = "fs_read_file"
        wrapped.__doc__ = Function.openai_schema["description"]
        return types.FunctionDeclaration.from_callable_with_api_option(
            callable=wrapped,
            api_option="GEMINI_API",
        )

    def test_gemini_declaration_file_paths_is_string_array(self, declaration):
        """Gemini must receive an array of strings, not an OBJECT with any_of."""
        assert declaration.name == "fs_read_file"
        assert self._type_name(declaration.parameters.type) == "OBJECT"

        file_paths = declaration.parameters.properties["file_paths"]
        assert self._type_name(file_paths.type) == "ARRAY"
        assert file_paths.items is not None
        assert self._type_name(file_paths.items.type) == "STRING"
        # The pre-fix Union signature generated type=OBJECT + any_of=[STRING, ARRAY].
        assert file_paths.any_of is None
        assert "file_paths" in declaration.parameters.required

    def test_gemini_declaration_keeps_encoding_optional_string(self, declaration):
        """The array fix leaves the remaining parameter untouched."""
        properties = declaration.parameters.properties

        assert set(properties) == {"file_paths", "encoding"}
        assert self._type_name(properties["encoding"].type) == "STRING"
        assert properties["encoding"].default == "utf-8"
        assert "encoding" not in declaration.parameters.required
