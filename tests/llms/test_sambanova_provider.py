from unittest.mock import MagicMock, patch

import pytest

from yaicli.const import DEFAULT_TEMPERATURE
from yaicli.llms.providers.sambanova_provider import SambanovaProvider
from yaicli.schemas import ToolPolicy


class TestSambanovaProvider:
    """Tests for Sambanova provider implementation"""

    @pytest.fixture
    def mock_config(self):
        """Fixture to create a mock configuration with a function-call-capable model"""
        return {
            "API_KEY": "fake_api_key",
            "BASE_URL": None,  # Will use DEFAULT_BASE_URL
            "MODEL": "Meta-Llama-3.3-70B-Instruct",
            "TEMPERATURE": 0.7,
            "TOP_P": 0.9,
            "MAX_TOKENS": 1024,
            "TIMEOUT": 10,
            "FREQUENCY_PENALTY": 0.0,
            "EXTRA_HEADERS": None,
            "EXTRA_BODY": None,
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
        }

    def test_init(self, mock_config):
        """Test initialization of SambanovaProvider"""
        with patch("yaicli.llms.providers.openai_provider.openai.OpenAI"):
            provider = SambanovaProvider(config=mock_config)

            assert provider.client_params["base_url"] == SambanovaProvider.DEFAULT_BASE_URL
            assert provider.client_params["base_url"] == "https://api.sambanova.ai/v1"
            assert provider.client_params["api_key"] == mock_config["API_KEY"]

    def test_temperature_in_range_unchanged(self, mock_config):
        """Temperature within [0, 1] should be left untouched and emit no warning"""
        mock_console = MagicMock()
        with (
            patch("yaicli.llms.providers.openai_provider.openai.OpenAI"),
            patch("yaicli.llms.providers.openai_provider.get_console", return_value=mock_console),
        ):
            provider = SambanovaProvider(config=mock_config)
            params = provider.get_completion_params(tool_policy=ToolPolicy(True, False))

            assert params["temperature"] == 0.7
            # Supported model + in-range temperature => no warnings printed
            mock_console.print.assert_not_called()

    @pytest.mark.parametrize("bad_temp", [1.5, -0.5, 2.0])
    def test_temperature_out_of_range_reset(self, mock_config, bad_temp):
        """Temperature outside [0, 1] should be reset to DEFAULT_TEMPERATURE with a warning"""
        mock_config["TEMPERATURE"] = bad_temp
        mock_console = MagicMock()
        with (
            patch("yaicli.llms.providers.openai_provider.openai.OpenAI"),
            patch("yaicli.llms.providers.openai_provider.get_console", return_value=mock_console),
        ):
            provider = SambanovaProvider(config=mock_config)
            params = provider.get_completion_params(tool_policy=ToolPolicy(True, False))

            assert params["temperature"] == DEFAULT_TEMPERATURE
            mock_console.print.assert_any_call(
                "Sambanova temperature must be between 0 and 1, setting to 0.4", style="yellow"
            )

    def test_unsupported_model_with_functions_warns(self, mock_config):
        """An unsupported model with functions enabled should warn about function-call support"""
        mock_config["MODEL"] = "some-unsupported-model"
        mock_console = MagicMock()
        with (
            patch("yaicli.llms.providers.openai_provider.openai.OpenAI"),
            patch("yaicli.llms.providers.openai_provider.get_console", return_value=mock_console),
        ):
            provider = SambanovaProvider(config=mock_config)
            provider.get_completion_params(tool_policy=ToolPolicy(True, False))

            printed = " ".join(str(call.args[0]) for call in mock_console.print.call_args_list)
            assert "Sambanova supports function call models" in printed

    def test_unsupported_model_without_functions_no_warn(self, mock_config):
        """An unsupported model with functions disabled should not warn about function-call support"""
        mock_config["MODEL"] = "some-unsupported-model"
        mock_console = MagicMock()
        with (
            patch("yaicli.llms.providers.openai_provider.openai.OpenAI"),
            patch("yaicli.llms.providers.openai_provider.get_console", return_value=mock_console),
        ):
            provider = SambanovaProvider(config=mock_config)
            provider.get_completion_params(tool_policy=ToolPolicy(False, False))

            printed = " ".join(str(call.args[0]) for call in mock_console.print.call_args_list)
            assert "Sambanova supports function call models" not in printed

    def test_supported_model_with_functions_no_warn(self, mock_config):
        """A supported model with functions enabled should not emit the function-call warning"""
        mock_console = MagicMock()
        with (
            patch("yaicli.llms.providers.openai_provider.openai.OpenAI"),
            patch("yaicli.llms.providers.openai_provider.get_console", return_value=mock_console),
        ):
            provider = SambanovaProvider(config=mock_config)
            provider.get_completion_params(tool_policy=ToolPolicy(True, False))

            printed = " ".join(str(call.args[0]) for call in mock_console.print.call_args_list)
            assert "Sambanova supports function call models" not in printed
