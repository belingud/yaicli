"""Test fs_read_image function."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from yaicli.functions.buildin.fs_read_image import Function
from yaicli.schemas import ToolCall
from yaicli.tools import execute_tool_call
from yaicli.tools.function import Function as ToolFunction, wrap_gemini_function

FAKE_CFG = {"SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False}
# fs_read_image only inspects the extension and file bytes, so the PNG magic is enough
# for the multi-image fixtures; the existing single-image tests keep their full header.
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class TestFSReadImage:
    def test_execute_png_image(self, tmp_path):
        """Test reading a PNG image."""
        test_file = tmp_path / "test.png"
        test_file.write_bytes(self._create_png_header())

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["path"] == str(test_file)
        assert "base64" in result_dict
        assert "size" in result_dict
        assert "format" in result_dict
        assert result_dict["format"] == ".PNG"

    def test_execute_jpeg_image(self, tmp_path):
        """Test reading a JPEG image."""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(self._create_jpeg_header())

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["format"] == ".JPG"

    def test_execute_gif_image(self, tmp_path):
        """Test reading a GIF image."""
        test_file = tmp_path / "test.gif"
        test_file.write_bytes(b"GIF89a")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["format"] == ".GIF"

    def test_execute_bmp_image(self, tmp_path):
        """Test reading a BMP image."""
        test_file = tmp_path / "test.bmp"
        test_file.write_bytes(b"BM")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["format"] == ".BMP"

    def test_execute_webp_image(self, tmp_path):
        """Test reading a WebP image."""
        test_file = tmp_path / "test.webp"
        test_file.write_bytes(b"RIFF....WEBP")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["format"] == ".WEBP"

    def test_execute_file_not_exists(self):
        """Test reading a non-existent image file."""
        result = Function.execute("/nonexistent/image.png")
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Image file does not exist" in result_dict["error"]

    def test_execute_path_is_directory(self, tmp_path):
        """Test reading when path is a directory."""
        result = Function.execute(str(tmp_path))
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Not a file" in result_dict["error"]

    def test_execute_non_image_file(self, tmp_path):
        """Test reading a non-image file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Not an image")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Unsupported format '.txt'" in result_dict["error"]

    def test_execute_empty_file(self, tmp_path):
        """Test reading an empty file."""
        test_file = tmp_path / "empty.png"
        test_file.write_bytes(b"")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["base64"] == ""
        assert result_dict["size"] == 0

    def test_execute_base64_encoding(self, tmp_path):
        """Test that image data is base64 encoded."""
        test_file = tmp_path / "test.png"
        original_data = self._create_png_header()
        test_file.write_bytes(original_data)

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True

        decoded_data = base64.b64decode(result_dict["base64"])
        assert decoded_data == original_data

    def test_execute_file_size(self, tmp_path):
        """Test that file size is correct."""
        test_file = tmp_path / "test.png"
        data = self._create_png_header()
        test_file.write_bytes(data)

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["size"] == len(data)

    def test_execute_result_structure(self, tmp_path):
        """Test that result has correct structure."""
        test_file = tmp_path / "test.png"
        test_file.write_bytes(self._create_png_header())

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "path" in result_dict
        assert "base64" in result_dict
        assert "size" in result_dict
        assert "format" in result_dict
        assert "mime_type" in result_dict

    def test_execute_mime_type_field(self, tmp_path):
        """Test that mime_type field is set correctly."""
        test_file = tmp_path / "test.png"
        test_file.write_bytes(self._create_png_header())

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["mime_type"] == "image/png"

    def test_execute_large_image(self, tmp_path):
        """Test reading a larger image."""
        test_file = tmp_path / "large.png"
        data = self._create_png_header() + b"\x00" * 10000
        test_file.write_bytes(data)

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["size"] == len(data)

    def test_execute_returns_json_string(self, tmp_path):
        """Test that execute returns a valid JSON string."""
        test_file = tmp_path / "test.png"
        test_file.write_bytes(self._create_png_header())

        result = Function.execute(str(test_file))

        assert isinstance(result, str)

        result_dict = json.loads(result)
        assert isinstance(result_dict, dict)

    def test_execute_tiff_image(self, tmp_path):
        """Test reading a TIFF image (not supported)."""
        test_file = tmp_path / "test.tif"
        test_file.write_bytes(b"II")

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Unsupported format '.tif'" in result_dict["error"]

    def test_execute_corrupted_image(self, tmp_path):
        """Test reading a corrupted image file."""
        test_file = tmp_path / "corrupted.png"
        test_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert result_dict["format"] == ".PNG"

    def test_execute_image_with_extension_mismatch(self, tmp_path):
        """Test reading an image with wrong extension (should fail)."""
        test_file = tmp_path / "image.txt"
        test_file.write_bytes(self._create_png_header())

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is False
        assert "Unsupported format '.txt'" in result_dict["error"]

    def test_execute_base64_data_is_string(self, tmp_path):
        """Test that base64 data is a string."""
        test_file = tmp_path / "test.png"
        test_file.write_bytes(self._create_png_header())

        result = Function.execute(str(test_file))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert isinstance(result_dict["base64"], str)

    def _create_png_header(self):
        """Create a minimal PNG file header."""
        return (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            + b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    def _create_jpeg_header(self):
        """Create a minimal JPEG file header."""
        return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x03\x02\x02\x03\x02\x02\x03\x03\x03\x03\x04\x03\x03\x04\x05\x08\x05\x05\x04\x04\x05\n\x07\x07\x06\x08\x0c\n\x0c\x0c\x0b\n\x0b\x0b\r\x0e\x12\x10\r\x0e\x11\x0e\x0b\x0b\x10\x16\x10\x11\x13\x14\x15\x15\x15\x0c\x0f\x17\x18\x16\x14\x18\x12\x14\x15\x14\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\x9f\xff\xd9"


class TestFSReadImageSchema:
    """The model-facing schema must advertise a list of paths, not a union."""

    def test_openai_schema_image_paths_is_string_array(self):
        """image_paths is an array of strings with no anyOf union."""
        parameters = Function.openai_schema["parameters"]
        image_paths = parameters["properties"]["image_paths"]

        assert image_paths["type"] == "array"
        assert image_paths["items"] == {"type": "string"}
        assert "anyOf" not in image_paths
        assert "image_paths" in parameters["required"]

        description = image_paths["description"]
        assert "list" in description
        assert "several images" in description or "multiple images" in description

    def test_anthropic_schema_image_paths_is_string_array(self):
        """Anthropic input schema advertises the same array contract."""
        input_schema = Function.anthropic_schema["input_schema"]
        image_paths = input_schema["properties"]["image_paths"]

        assert image_paths["type"] == "array"
        assert image_paths["items"] == {"type": "string"}
        assert "anyOf" not in image_paths
        assert "image_paths" in input_schema["required"]

        description = image_paths["description"]
        assert "list" in description
        assert "several images" in description or "multiple images" in description

    def test_openai_schema_description_mentions_single_call(self):
        """The function description tells the model several images can be read at once."""
        description = Function.openai_schema["description"].lower()

        assert "image files" in description
        assert "single call" in description


class TestFSReadImageToolCall:
    """End-to-end coverage through the runtime tool-call executor."""

    def test_tool_call_reads_multiple_images_in_one_call(self, tmp_path):
        """One tool call with an image_paths array returns every image's base64 data."""
        image1 = tmp_path / "first.png"
        image1.write_bytes(PNG_HEADER)
        image2 = tmp_path / "second.jpg"
        image2.write_bytes(b"\xff\xd8\xff\xe0")

        tool = ToolFunction(function=Function)
        tool_call = ToolCall(
            id="1",
            name="fs_read_image",
            arguments=json.dumps({"image_paths": [str(image1), str(image2)]}),
        )
        with (
            patch("yaicli.tools.cfg", FAKE_CFG),
            patch("yaicli.tools.get_function", return_value=tool),
            patch("yaicli.tools.console", MagicMock()),
        ):
            result, ok = execute_tool_call(tool_call)

        assert ok is True
        result_dict = json.loads(result)
        assert result_dict["total_images"] == 2
        assert result_dict["success_count"] == 2
        assert result_dict["error_count"] == 0
        assert [item["path"] for item in result_dict["images"]] == [str(image1), str(image2)]
        assert [base64.b64decode(item["base64"]) for item in result_dict["images"]] == [
            PNG_HEADER,
            b"\xff\xd8\xff\xe0",
        ]
        assert [item["mime_type"] for item in result_dict["images"]] == ["image/png", "image/jpeg"]

    def test_tool_call_accepts_legacy_single_path_string(self, tmp_path):
        """A legacy tool call passing one path string still succeeds."""
        image = tmp_path / "legacy.png"
        image.write_bytes(PNG_HEADER)

        tool = ToolFunction(function=Function)
        tool_call = ToolCall(
            id="1",
            name="fs_read_image",
            arguments=json.dumps({"image_paths": str(image)}),
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
        assert base64.b64decode(result_dict["base64"]) == PNG_HEADER
        assert "total_images" not in result_dict

    def test_tool_call_invalid_type_returns_error_json(self):
        """A wrong image_paths type yields an error JSON payload instead of raising."""
        tool = ToolFunction(function=Function)
        tool_call = ToolCall(id="1", name="fs_read_image", arguments=json.dumps({"image_paths": 123}))
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
        assert "image_paths must be a list" in result_dict["error"]


class TestFSReadImageInputCompatibility:
    """Backward compatibility and robustness for the accepted image_paths forms."""

    def test_execute_single_path_string_backward_compatible(self, tmp_path):
        """A single path string keeps returning the flat single-image payload."""
        image = tmp_path / "test.png"
        image.write_bytes(PNG_HEADER)

        result = Function.execute(str(image))
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert base64.b64decode(result_dict["base64"]) == PNG_HEADER
        assert result_dict["error"] is None
        assert "images" not in result_dict
        assert "total_images" not in result_dict

    def test_execute_single_element_list_returns_flat_payload(self, tmp_path):
        """A one-element list still takes the flat single-image branch."""
        image = tmp_path / "test.png"
        image.write_bytes(PNG_HEADER)

        result = Function.execute([str(image)])
        result_dict = json.loads(result)

        assert result_dict["success"] is True
        assert "images" not in result_dict
        assert "success_count" not in result_dict

    def test_execute_accepts_tuple_of_paths(self, tmp_path):
        """A tuple of paths is normalized to the aggregate multi-image payload."""
        image1 = tmp_path / "first.png"
        image1.write_bytes(PNG_HEADER)
        image2 = tmp_path / "second.png"
        image2.write_bytes(PNG_HEADER + b"\x00")

        result = Function.execute((str(image1), str(image2)))
        result_dict = json.loads(result)

        assert result_dict["total_images"] == 2
        assert result_dict["success_count"] == 2
        assert result_dict["error_count"] == 0
        assert [item["success"] for item in result_dict["images"]] == [True, True]

    @pytest.mark.parametrize(
        "invalid_value",
        [{"a": 1}, 123, 3.14, None],
        ids=["dict", "int", "float", "none"],
    )
    def test_execute_invalid_type_returns_error_json(self, invalid_value):
        """Non-list, non-string image_paths values produce an error JSON payload."""
        result = Function.execute(invalid_value)
        result_dict = json.loads(result)

        assert "error" in result_dict
        assert "image_paths must be a list" in result_dict["error"]
        assert type(invalid_value).__name__ in result_dict["error"]

    def test_execute_multiple_images_partial_failure_keeps_successful_data(self, tmp_path):
        """Missing paths are reported per image while successful base64 data is kept."""
        image1 = tmp_path / "first.png"
        image1.write_bytes(PNG_HEADER)
        image2 = tmp_path / "second.png"
        image2.write_bytes(PNG_HEADER)

        result = Function.execute(
            [str(image1), str(tmp_path / "missing.png"), str(image2)],
        )
        result_dict = json.loads(result)

        assert result_dict["total_images"] == 3
        assert result_dict["success_count"] == 2
        assert result_dict["error_count"] == 1
        assert result_dict["images"][0]["success"] is True
        assert base64.b64decode(result_dict["images"][0]["base64"]) == PNG_HEADER
        assert result_dict["images"][1]["success"] is False
        assert result_dict["images"][1]["error"] == "Image file does not exist"
        assert result_dict["images"][2]["success"] is True
        assert base64.b64decode(result_dict["images"][2]["base64"]) == PNG_HEADER


class TestFSReadImageGeminiSchema:
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
        wrapped.__name__ = "fs_read_image"
        wrapped.__doc__ = Function.openai_schema["description"]
        return types.FunctionDeclaration.from_callable_with_api_option(
            callable=wrapped,
            api_option="GEMINI_API",
        )

    def test_gemini_declaration_image_paths_is_string_array(self, declaration):
        """Gemini must receive an array of strings, not an OBJECT with any_of."""
        assert declaration.name == "fs_read_image"
        assert self._type_name(declaration.parameters.type) == "OBJECT"

        image_paths = declaration.parameters.properties["image_paths"]
        assert self._type_name(image_paths.type) == "ARRAY"
        assert image_paths.items is not None
        assert self._type_name(image_paths.items.type) == "STRING"
        # The pre-fix Union signature generated type=OBJECT + any_of=[STRING, ARRAY].
        assert image_paths.any_of is None
        assert "image_paths" in declaration.parameters.required

    def test_gemini_declaration_keeps_max_bytes_optional_integer(self, declaration):
        """The array fix leaves the remaining parameter untouched."""
        properties = declaration.parameters.properties

        assert set(properties) == {"image_paths", "max_bytes"}
        assert self._type_name(properties["max_bytes"].type) == "INTEGER"
        assert properties["max_bytes"].default == 5 * 1024 * 1024
        assert "max_bytes" not in declaration.parameters.required
