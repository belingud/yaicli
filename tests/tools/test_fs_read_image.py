"""Test fs_read_image function."""
import base64
import json

from yaicli.functions.buildin.fs_read_image import Function


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
        return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde" + b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x00\x00\x00IEND\xaeB`\x82"

    def _create_jpeg_header(self):
        """Create a minimal JPEG file header."""
        return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x03\x02\x02\x03\x02\x02\x03\x03\x03\x03\x04\x03\x03\x04\x05\x08\x05\x05\x04\x04\x05\n\x07\x07\x06\x08\x0c\n\x0c\x0c\x0b\n\x0b\x0b\r\x0e\x12\x10\r\x0e\x11\x0e\x0b\x0b\x10\x16\x10\x11\x13\x14\x15\x15\x15\x0c\x0f\x17\x18\x16\x14\x18\x12\x14\x15\x14\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\x9f\xff\xd9"
