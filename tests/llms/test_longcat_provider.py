from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.providers.longcat_provider import (
    LongCatAnthropicProvider,
    LongCatProvider,
)


class TestLongCatProvider:
    """Test the LongCat provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://api.longcat.chat/v1/openai",
            "MODEL": "longcat-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of LongCatProvider"""
        with patch("openai.OpenAI"):
            provider = LongCatProvider(config=mock_config)

            # Check initialization of client params
            assert provider.client_params == {
                "api_key": mock_config["API_KEY"],
                "base_url": mock_config["BASE_URL"],
                "default_headers": {
                    "X-Title": provider.APP_NAME,
                    "HTTP_Referer": provider.APP_REFERER,
                },
            }

            # Check completion params (should use LongCat-specific mapping)
            expected_params = {
                "model": mock_config["MODEL"],
                "temperature": mock_config["TEMPERATURE"],
                "top_p": mock_config["TOP_P"],
                "max_tokens": mock_config["MAX_TOKENS"],
                "timeout": mock_config["TIMEOUT"],
            }
            assert provider.completion_params == expected_params

    def test_parse_longcat_tool_call(self):
        """Test parsing of LongCat tool call format"""
        from yaicli.llms.providers.longcat_provider import (
            _parse_and_clean_longcat_content,
        )

        content = """I'll help you with this task.
<longcat_tool_call>test_function
<longcat_arg_key>param1</longcat_arg_key>
<longcat_arg_value>value1</longcat_arg_value>
<longcat_arg_key>param2</longcat_arg_key>
<longcat_arg_value>value2</longcat_arg_value>
</longcat_tool_call>"""

        tool_call, cleaned_content = _parse_and_clean_longcat_content(content, "resp_123", False, None)

        # Verify tool call was parsed correctly
        assert tool_call is not None
        assert tool_call.name == "test_function"
        assert "param1" in tool_call.arguments
        assert "param2" in tool_call.arguments

        # Verify content was cleaned
        assert "I'll help you with this task." in cleaned_content
        assert "<longcat_tool_call>" not in cleaned_content

    def test_clean_longcat_reasoning(self):
        """Test cleaning LongCat tool call tags from reasoning"""
        from yaicli.llms.providers.longcat_provider import _clean_longcat_reasoning

        reasoning = """Let me think about this.
<longcat_tool_call>test_func
<longcat_arg_key>test</longcat_arg_key>
<longcat_arg_value>data</longcat_arg_value>
</longcat_tool_call>"""

        cleaned = _clean_longcat_reasoning(reasoning)
        assert "Let me think about this." in cleaned
        assert "<longcat_tool_call>" not in cleaned


class TestLongCatAnthropicProvider:
    """Test the LongCat Anthropic provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": "https://api.longcat.chat/anthropic",
            "MODEL": "longcat-claude-model",
            "TEMPERATURE": 0.7,
            "TOP_P": 1.0,
            "MAX_TOKENS": 1000,
            "TIMEOUT": 60,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of LongCatAnthropicProvider"""
        with patch("yaicli.llms.providers.anthropic_provider.Anthropic"):
            provider = LongCatAnthropicProvider(config=mock_config)

            # Check that it uses the correct base URL and adds Bearer token
            client_params = provider.get_client_params()
            assert client_params["base_url"] == "https://api.longcat.chat/anthropic"
            assert client_params["default_headers"]["Authorization"] == "Bearer fake_api_key"

    def test_handle_normal_response_with_longcat_tool_call(self, mock_config):
        """Test normal response handling with LongCat tool call"""
        with patch("yaicli.llms.providers.anthropic_provider.Anthropic"):
            provider = LongCatAnthropicProvider(config=mock_config)

            # Create a mock response with LongCat tool call in content
            mock_response = MagicMock()
            mock_response.id = "resp_123"

            # Mock the content block with LongCat tool call
            mock_content_block = MagicMock()
            mock_content_block.type = "text"
            mock_content_block.text = """I'll execute the function for you.
<longcat_tool_call>test_function
<longcat_arg_key>input_data</longcat_arg_key>
<longcat_arg_value>sample data</longcat_arg_value>
</longcat_tool_call>"""

            mock_response.content = [mock_content_block]
            mock_response.stop_reason = "end_turn"

            # Mock the _handle_normal_response method to test the logic
            responses = list(provider._handle_normal_response(mock_response))

            # Verify response - should detect tool call and change finish_reason
            assert len(responses) == 1
            assert "I'll execute the function for you." in responses[0].content
            assert responses[0].finish_reason == "tool_use"
            assert responses[0].tool_call is not None
            assert responses[0].tool_call.name == "test_function"
            assert "input_data" in responses[0].tool_call.arguments
