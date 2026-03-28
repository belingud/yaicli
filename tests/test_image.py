import base64
from unittest.mock import patch

import pytest
import typer

from yaicli.config import cfg
from yaicli.image import (
    encode_local_image,
    is_image_url,
    parse_image_url,
    process_image_source,
    validate_local_image,
)
from yaicli.schemas import ChatMessage, ImageData


class TestImageData:
    """Test ImageData dataclass creation and defaults."""

    def test_create_base64_image(self):
        img = ImageData(data="abc123", media_type="image/jpeg", is_url=False)
        assert img.data == "abc123"
        assert img.media_type == "image/jpeg"
        assert img.is_url is False

    def test_create_url_image(self):
        img = ImageData(data="https://example.com/img.jpg", media_type="image/jpeg", is_url=True)
        assert img.data == "https://example.com/img.jpg"
        assert img.is_url is True

    def test_chat_message_images_default_empty(self):
        msg = ChatMessage(role="user", content="hello")
        assert msg.images == []

    def test_chat_message_with_images(self):
        img = ImageData(data="abc", media_type="image/png", is_url=False)
        msg = ChatMessage(role="user", content="hello", images=[img])
        assert len(msg.images) == 1
        assert msg.images[0].data == "abc"


class TestIsImageUrl:
    """Test is_image_url() with various inputs."""

    def test_https_url(self):
        assert is_image_url("https://example.com/image.jpg") is True

    def test_http_url(self):
        assert is_image_url("http://example.com/image.jpg") is True

    def test_relative_path(self):
        assert is_image_url("./images/photo.jpg") is False

    def test_absolute_path(self):
        assert is_image_url("/home/user/photo.jpg") is False

    def test_tilde_path(self):
        assert is_image_url("~/photo.jpg") is False

    def test_just_filename(self):
        assert is_image_url("photo.jpg") is False


class TestValidateLocalImage:
    """Test validate_local_image() with various scenarios."""

    def test_valid_jpeg(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        result = validate_local_image(str(img))
        assert result == img

    def test_valid_png(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG")
        result = validate_local_image(str(img))
        assert result == img

    def test_file_not_found(self):
        with pytest.raises(typer.BadParameter, match="not found"):
            validate_local_image("/nonexistent/path/image.jpg")

    def test_unsupported_extension(self, tmp_path):
        img = tmp_path / "test.bmp"
        img.write_bytes(b"BM")
        with pytest.raises(typer.BadParameter, match="Unsupported image format"):
            validate_local_image(str(img))

    def test_unreadable_file(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        # Remove read permission
        img.chmod(0o000)
        try:
            with pytest.raises(typer.BadParameter, match="Cannot read"):
                validate_local_image(str(img))
        finally:
            # Restore permissions for cleanup
            img.chmod(0o644)

    def test_webp_supported(self, tmp_path):
        img = tmp_path / "test.webp"
        img.write_bytes(b"RIFF")
        result = validate_local_image(str(img))
        assert result == img

    def test_gif_supported(self, tmp_path):
        img = tmp_path / "test.gif"
        img.write_bytes(b"GIF89a")
        result = validate_local_image(str(img))
        assert result == img


class TestEncodeLocalImage:
    """Test encode_local_image() produces correct base64 and media type."""

    def test_encode_jpeg(self, tmp_path):
        content = b"\xff\xd8\xff\xe0test_data"
        img = tmp_path / "photo.jpg"
        img.write_bytes(content)

        result = encode_local_image(str(img))
        assert result.is_url is False
        assert result.media_type == "image/jpeg"
        assert result.data == base64.standard_b64encode(content).decode("utf-8")

    def test_encode_png(self, tmp_path):
        content = b"\x89PNG\r\n\x1a\ntest_data"
        img = tmp_path / "photo.png"
        img.write_bytes(content)

        result = encode_local_image(str(img))
        assert result.media_type == "image/png"
        assert result.is_url is False

    def test_encode_jpeg_extension(self, tmp_path):
        content = b"data"
        img = tmp_path / "photo.jpeg"
        img.write_bytes(content)

        result = encode_local_image(str(img))
        assert result.media_type == "image/jpeg"


class TestParseImageUrl:
    """Test parse_image_url() with URL with and without extension."""

    def test_url_with_jpg_extension(self):
        result = parse_image_url("https://example.com/photo.jpg")
        assert result.data == "https://example.com/photo.jpg"
        assert result.media_type == "image/jpeg"
        assert result.is_url is True

    def test_url_with_png_extension(self):
        result = parse_image_url("https://example.com/photo.png")
        assert result.media_type == "image/png"

    def test_url_without_extension(self):
        result = parse_image_url("https://example.com/image?id=123")
        assert result.media_type == "image/jpeg"  # default fallback
        assert result.is_url is True

    def test_url_with_query_params(self):
        result = parse_image_url("https://example.com/photo.webp?w=800")
        assert result.media_type == "image/webp"


class TestProcessImageSource:
    """Test process_image_source() dispatching."""

    def test_dispatches_url(self):
        result = process_image_source("https://example.com/photo.jpg")
        assert result.is_url is True
        assert result.data == "https://example.com/photo.jpg"

    def test_dispatches_local(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8data")
        result = process_image_source(str(img))
        assert result.is_url is False
        assert result.media_type == "image/jpeg"


class TestOpenAIConvertMessages:
    """Test base Provider._convert_messages() with images."""

    def test_message_with_base64_image(self):
        from yaicli.llms.provider import Provider

        # Create a concrete subclass for testing
        class TestProvider(Provider):
            def completion(self, messages, stream=False):
                yield from []

            def detect_tool_role(self):
                return "tool"

        provider = TestProvider()
        img = ImageData(data="abc123", media_type="image/jpeg", is_url=False)
        msg = ChatMessage(role="user", content="What is this?", images=[img])

        result = provider._convert_messages([msg])
        assert len(result) == 1
        content = result[0]["content"]
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "What is this?"}
        assert content[1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc123"}}

    def test_message_with_url_image(self):
        from yaicli.llms.provider import Provider

        class TestProvider(Provider):
            def completion(self, messages, stream=False):
                yield from []

            def detect_tool_role(self):
                return "tool"

        provider = TestProvider()
        img = ImageData(data="https://example.com/img.jpg", media_type="image/jpeg", is_url=True)
        msg = ChatMessage(role="user", content="Describe", images=[img])

        result = provider._convert_messages([msg])
        content = result[0]["content"]
        assert content[1] == {"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}}

    def test_message_without_images_unchanged(self):
        from yaicli.llms.provider import Provider

        class TestProvider(Provider):
            def completion(self, messages, stream=False):
                yield from []

            def detect_tool_role(self):
                return "tool"

        provider = TestProvider()
        msg = ChatMessage(role="user", content="Hello")

        result = provider._convert_messages([msg])
        assert result[0]["content"] == "Hello"
        assert isinstance(result[0]["content"], str)

    def test_message_with_multiple_images(self):
        from yaicli.llms.provider import Provider

        class TestProvider(Provider):
            def completion(self, messages, stream=False):
                yield from []

            def detect_tool_role(self):
                return "tool"

        provider = TestProvider()
        img1 = ImageData(data="abc", media_type="image/jpeg", is_url=False)
        img2 = ImageData(data="def", media_type="image/png", is_url=False)
        msg = ChatMessage(role="user", content="Compare", images=[img1, img2])

        result = provider._convert_messages([msg])
        content = result[0]["content"]
        assert len(content) == 3  # 1 text + 2 images


class TestAnthropicConvertMessages:
    """Test Anthropic _convert_messages() with images."""

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    def test_base64_image(self, mock_anthropic):
        from yaicli.llms.providers.anthropic_provider import AnthropicProvider

        config = {"API_KEY": "test", "ENABLE_FUNCTIONS": False, "ENABLE_MCP": False}
        provider = AnthropicProvider(config=config)

        img = ImageData(data="abc123", media_type="image/png", is_url=False)
        msg = ChatMessage(role="user", content="Describe", images=[img])

        result = provider._convert_messages([msg])
        content = result[0]["content"]
        assert isinstance(content, list)
        # Image block before text block
        assert content[0] == {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "abc123"},
        }
        assert content[1] == {"type": "text", "text": "Describe"}

    @patch("yaicli.llms.providers.anthropic_provider.Anthropic")
    def test_url_image(self, mock_anthropic):
        from yaicli.llms.providers.anthropic_provider import AnthropicProvider

        config = {"API_KEY": "test", "ENABLE_FUNCTIONS": False, "ENABLE_MCP": False}
        provider = AnthropicProvider(config=config)

        img = ImageData(data="https://example.com/img.jpg", media_type="image/jpeg", is_url=True)
        msg = ChatMessage(role="user", content="Describe", images=[img])

        result = provider._convert_messages([msg])
        content = result[0]["content"]
        assert content[0] == {"type": "image", "source": {"type": "url", "url": "https://example.com/img.jpg"}}


class TestGeminiConvertMessages:
    """Test Gemini _convert_messages() with images."""

    @patch("yaicli.llms.providers.gemini_provider.genai")
    def test_base64_image_produces_part(self, mock_genai):

        from yaicli.llms.providers.gemini_provider import GeminiProvider

        config = {
            "API_KEY": "test",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": {},
        }
        provider = GeminiProvider(config=config)

        img = ImageData(data=base64.standard_b64encode(b"imgdata").decode(), media_type="image/jpeg", is_url=False)
        msg = ChatMessage(role="user", content="What is this?", images=[img])

        result = provider._convert_messages([msg])
        assert len(result) == 1
        parts = result[0].parts
        # Should have 2 parts: image + text
        assert len(parts) == 2

    @patch("yaicli.llms.providers.gemini_provider.genai")
    def test_url_image_produces_uri_part(self, mock_genai):
        from yaicli.llms.providers.gemini_provider import GeminiProvider

        config = {
            "API_KEY": "test",
            "ENABLE_FUNCTIONS": False,
            "ENABLE_MCP": False,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": {},
        }
        provider = GeminiProvider(config=config)

        img = ImageData(data="https://example.com/img.jpg", media_type="image/jpeg", is_url=True)
        msg = ChatMessage(role="user", content="Describe", images=[img])

        result = provider._convert_messages([msg])
        parts = result[0].parts
        assert len(parts) == 2


class TestOllamaConvertMessages:
    """Test Ollama _convert_messages() with images."""

    @patch("yaicli.llms.providers.ollama_provider.ollama")
    def test_base64_image_in_images_array(self, mock_ollama):
        from yaicli.llms.providers.ollama_provider import OllamaProvider

        config = {
            "ENABLE_FUNCTIONS": False,
            "THINK": "false",
            "BASE_URL": "http://localhost:11434",
            "TIMEOUT": 60,
        }
        provider = OllamaProvider(config=config)

        img = ImageData(data="abc123", media_type="image/jpeg", is_url=False)
        msg = ChatMessage(role="user", content="What is this?", images=[img])

        result = provider._convert_messages([msg])
        assert result[0]["content"] == "What is this?"
        assert isinstance(result[0]["content"], str)
        assert result[0]["images"] == ["abc123"]

    @patch("yaicli.llms.providers.ollama_provider.ollama")
    def test_multiple_images(self, mock_ollama):
        from yaicli.llms.providers.ollama_provider import OllamaProvider

        config = {
            "ENABLE_FUNCTIONS": False,
            "THINK": "false",
            "BASE_URL": "http://localhost:11434",
            "TIMEOUT": 60,
        }
        provider = OllamaProvider(config=config)

        img1 = ImageData(data="abc", media_type="image/jpeg", is_url=False)
        img2 = ImageData(data="def", media_type="image/png", is_url=False)
        msg = ChatMessage(role="user", content="Compare", images=[img1, img2])

        result = provider._convert_messages([msg])
        assert result[0]["images"] == ["abc", "def"]

    @patch("yaicli.llms.providers.ollama_provider.ollama")
    def test_no_images_key_when_empty(self, mock_ollama):
        from yaicli.llms.providers.ollama_provider import OllamaProvider

        config = {
            "ENABLE_FUNCTIONS": False,
            "THINK": "false",
            "BASE_URL": "http://localhost:11434",
            "TIMEOUT": 60,
        }
        provider = OllamaProvider(config=config)

        msg = ChatMessage(role="user", content="Hello")

        result = provider._convert_messages([msg])
        assert "images" not in result[0]


class TestGracefulDegradation:
    """Test non-vision provider strips images and warns."""

    def test_no_vision_provider_strips_images(self, cli):
        """Images should be stripped for non-vision providers."""
        from yaicli.schemas import ImageData

        img = ImageData(data="abc", media_type="image/jpeg", is_url=False)

        with patch.object(cli, "console"):
            with patch("yaicli.cli.cfg", {**cfg, "PROVIDER": "cohere"}):
                messages = cli._build_messages("test", images=[img])

        # The user message should have no images
        user_msg = [m for m in messages if m.role == "user"][0]
        assert user_msg.images == []

    def test_vision_provider_keeps_images(self, cli):
        """Images should be kept for vision-capable providers."""
        from yaicli.schemas import ImageData

        img = ImageData(data="abc", media_type="image/jpeg", is_url=False)

        with patch("yaicli.cli.cfg", {**cfg, "PROVIDER": "openai"}):
            messages = cli._build_messages("test", images=[img])

        user_msg = [m for m in messages if m.role == "user"][0]
        assert len(user_msg.images) == 1


class TestBuildMessagesImageAttachment:
    """Test _build_messages() attaches images only to user message."""

    def test_images_only_on_user_message(self, cli):
        """Images should only be on the user message, not system."""
        from yaicli.schemas import ImageData

        img = ImageData(data="abc", media_type="image/jpeg", is_url=False)

        with patch("yaicli.cli.cfg", {**cfg, "PROVIDER": "openai"}):
            messages = cli._build_messages("test", images=[img])

        for msg in messages:
            if msg.role == "system":
                assert msg.images == []
            elif msg.role == "user":
                assert len(msg.images) == 1


class TestAtImageReferences:
    """Test @ image references merged with --image flag images in _build_messages()."""

    def test_at_image_merged_with_flag_image(self, cli, tmp_path):
        """Both @ images and --image images should appear on user message."""
        import os

        from yaicli.schemas import ImageData

        # Create a local image file
        img_file = tmp_path / "photo.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\ntest_data")

        # Image from --image flag
        flag_img = ImageData(data="flag_b64", media_type="image/jpeg", is_url=False)

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with patch("yaicli.cli.cfg", {**cfg, "PROVIDER": "openai"}):
                messages = cli._build_messages("Describe @photo.png", images=[flag_img])
        finally:
            os.chdir(original_cwd)

        user_msg = [m for m in messages if m.role == "user"][0]
        # Should have 2 images: 1 from --image flag + 1 from @ reference
        assert len(user_msg.images) == 2
        # First image is from --image flag
        assert user_msg.images[0].data == "flag_b64"
        # Second image is from @ reference (base64 encoded)
        assert user_msg.images[1].media_type == "image/png"
        assert user_msg.images[1].is_url is False
        # @ reference should be cleaned from text
        assert "@photo.png" not in user_msg.content
        assert "'photo.png'" in user_msg.content

    def test_at_image_only(self, cli, tmp_path):
        """@ image reference without --image flag should work."""
        import os

        img_file = tmp_path / "shot.jpg"
        img_file.write_bytes(b"\xff\xd8\xff\xe0test")

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with patch("yaicli.cli.cfg", {**cfg, "PROVIDER": "openai"}):
                messages = cli._build_messages("What is @shot.jpg")
        finally:
            os.chdir(original_cwd)

        user_msg = [m for m in messages if m.role == "user"][0]
        assert len(user_msg.images) == 1
        assert user_msg.images[0].media_type == "image/jpeg"
        assert "'shot.jpg'" in user_msg.content
