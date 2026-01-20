# type: ignore
from unittest.mock import MagicMock, patch

import pytest

from yaicli.llms.provider import Provider, ProviderFactory
from yaicli.schemas import ChatMessage, LLMResponse


class TestProvider:
    """Test the Provider abstract base class"""

    def test_cannot_instantiate_abstract_class(self):
        """Test that Provider cannot be instantiated as an abstract class"""
        with pytest.raises(TypeError):
            Provider()

    def test_abstract_methods(self):
        """Test that Provider requires the implementation of abstract methods"""

        # Define a concrete subclass that doesn't implement the abstract methods
        class IncompleteProvider(Provider):
            pass

        # Trying to instantiate should fail
        with pytest.raises(TypeError):
            IncompleteProvider()

        # Define a concrete subclass that implements the abstract methods
        class CompleteProvider(Provider):
            def completion(self, messages, stream=False):
                yield LLMResponse(content="test")

            def detect_tool_role(self):
                return "tool"

        # Should be able to instantiate
        provider = CompleteProvider()
        assert isinstance(provider, Provider)


class TestFilterExcludedParams:
    """Test the filter_excluded_params static method"""

    def test_empty_exclude_params_returns_original(self):
        """Test that empty EXCLUDE_PARAMS returns original params"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": ""}

        result = Provider.filter_excluded_params(params, config)

        assert result == params

    def test_none_exclude_params_returns_original(self):
        """Test that None EXCLUDE_PARAMS returns original params"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4"}
        config = {}

        result = Provider.filter_excluded_params(params, config)

        assert result == params

    def test_whitespace_only_exclude_params_returns_original(self):
        """Test that whitespace-only EXCLUDE_PARAMS returns original params"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": "   "}

        result = Provider.filter_excluded_params(params, config)

        assert result == params

    def test_single_param_exclusion(self):
        """Test excluding a single parameter"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": "temperature"}

        result = Provider.filter_excluded_params(params, config)

        assert result == {"top_p": 1.0, "model": "gpt-4"}
        assert "temperature" not in result

    def test_multiple_params_exclusion(self):
        """Test excluding multiple parameters"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4", "max_tokens": 1024}
        config = {"EXCLUDE_PARAMS": "temperature,top_p"}

        result = Provider.filter_excluded_params(params, config)

        assert result == {"model": "gpt-4", "max_tokens": 1024}
        assert "temperature" not in result
        assert "top_p" not in result

    def test_case_insensitive_matching(self):
        """Test that parameter matching is case-insensitive"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": "Temperature,TOP_P"}

        result = Provider.filter_excluded_params(params, config)

        assert result == {"model": "gpt-4"}
        assert "temperature" not in result
        assert "top_p" not in result

    def test_whitespace_handling(self):
        """Test that whitespace in EXCLUDE_PARAMS is handled correctly"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": " temperature , top_p , "}

        result = Provider.filter_excluded_params(params, config)

        assert result == {"model": "gpt-4"}
        assert "temperature" not in result
        assert "top_p" not in result

    def test_nonexistent_params_silently_ignored(self):
        """Test that excluding non-existent parameters doesn't cause errors"""
        params = {"temperature": 0.5, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": "nonexistent,temperature"}

        result = Provider.filter_excluded_params(params, config)

        assert result == {"model": "gpt-4"}
        assert "temperature" not in result

    def test_all_params_excluded(self):
        """Test excluding all parameters returns empty dict"""
        params = {"temperature": 0.5, "top_p": 1.0}
        config = {"EXCLUDE_PARAMS": "temperature,top_p"}

        result = Provider.filter_excluded_params(params, config)

        assert result == {}

    def test_empty_params_dict(self):
        """Test with empty params dict"""
        params = {}
        config = {"EXCLUDE_PARAMS": "temperature"}

        result = Provider.filter_excluded_params(params, config)

        assert result == {}

    def test_verbose_logging_enabled(self):
        """Test that verbose logging prints excluded parameters"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": "temperature,top_p"}
        mock_console = MagicMock()

        result = Provider.filter_excluded_params(params, config, verbose=True, console=mock_console)

        assert result == {"model": "gpt-4"}
        mock_console.print.assert_called_once()
        call_args = mock_console.print.call_args
        assert "temperature" in call_args[0][0]
        assert "top_p" in call_args[0][0]

    def test_verbose_logging_disabled(self):
        """Test that verbose=False does not log"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": "temperature"}
        mock_console = MagicMock()

        result = Provider.filter_excluded_params(params, config, verbose=False, console=mock_console)

        assert result == {"top_p": 1.0, "model": "gpt-4"}
        mock_console.print.assert_not_called()

    def test_no_console_no_error(self):
        """Test that not providing console doesn't cause errors"""
        params = {"temperature": 0.5, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": "temperature"}

        result = Provider.filter_excluded_params(params, config, verbose=True, console=None)

        assert result == {"model": "gpt-4"}

    def test_no_params_excluded_no_logging(self):
        """Test that no logging when nothing is excluded"""
        params = {"model": "gpt-4", "max_tokens": 1024}
        config = {"EXCLUDE_PARAMS": "temperature,top_p"}
        mock_console = MagicMock()

        result = Provider.filter_excluded_params(params, config, verbose=True, console=mock_console)

        assert result == {"model": "gpt-4", "max_tokens": 1024}
        # Should not log if nothing was actually excluded
        mock_console.print.assert_not_called()

    def test_special_characters_in_param_names(self):
        """Test handling of special characters in parameter names"""
        params = {"temperature": 0.5, "max_tokens": 1024, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": "max_tokens"}

        result = Provider.filter_excluded_params(params, config)

        assert result == {"temperature": 0.5, "model": "gpt-4"}
        assert "max_tokens" not in result

    def test_comma_separated_with_empty_elements(self):
        """Test that empty elements from comma separation are ignored"""
        params = {"temperature": 0.5, "top_p": 1.0, "model": "gpt-4"}
        config = {"EXCLUDE_PARAMS": "temperature,,top_p,"}

        result = Provider.filter_excluded_params(params, config)

        assert result == {"model": "gpt-4"}


class TestProviderFactory:
    """Test the ProviderFactory class"""

    def test_known_provider_types(self):
        """Test that ProviderFactory has the expected provider types"""
        expected_providers = {
            "openai",
            "openai-azure",
            "modelscope",
            "chatglm",
            "openrouter",
            "siliconflow",
            "chutes",
            "infini-ai",
            "yi",
            "deepseek",
            "doubao",
            "groq",
            "ai21",
            "ollama",
            "cohere",
            "sambanova",
            "minimax",
            "targon",
            "xai",
            "gemini",
            "vertexai",
            "huggingface",
            "cohere-bedrock",
            "cohere-sagemaker",
            "mistral",
            "nvida",
            "bailian",
            "bailian-intl",
            "spark",
            "longcat",
            "longcat-anthropic",
            "together",
            "anthropic",
            "anthropic-bedrock",
            "anthropic-vertex",
            "cerebras",
            "moonshot",
            "fireworks",
            "openai-compatible",
        }

        assert set(ProviderFactory.providers_map.keys()) == expected_providers

    def test_create_provider_unknown_type(self):
        """Test that creating an unknown provider type raises ValueError"""
        with pytest.raises(ValueError, match=r"Unknown provider: nonexistent"):
            ProviderFactory.create_provider("nonexistent")

    @patch("importlib.import_module")
    def test_create_provider_basic(self, mock_import_module):
        """Test basic provider creation with mocked import"""
        # Setup mock
        mock_provider = MagicMock()
        mock_module = MagicMock()
        mock_module.OpenAIProvider = mock_provider
        mock_import_module.return_value = mock_module

        # Call the method
        ProviderFactory.create_provider("openai", verbose=True)

        # Assertions
        mock_import_module.assert_called_once_with(".providers.openai_provider", package="yaicli.llms")
        mock_provider.assert_called_once_with(verbose=True)

    @patch("importlib.import_module")
    def test_create_provider_case_insensitive(self, mock_import_module):
        """Test that provider type is case insensitive"""
        # Setup mock
        mock_provider = MagicMock()
        mock_module = MagicMock()
        mock_module.OpenAIProvider = mock_provider
        mock_import_module.return_value = mock_module

        # Call the method with mixed case
        ProviderFactory.create_provider("OpEnAi")

        # Assertions
        mock_import_module.assert_called_once_with(".providers.openai_provider", package="yaicli.llms")

    @patch("importlib.import_module")
    def test_create_provider_with_kwargs(self, mock_import_module):
        """Test provider creation with additional keyword arguments"""
        # Setup mock
        mock_provider = MagicMock()
        mock_module = MagicMock()
        mock_module.OpenAIProvider = mock_provider
        mock_import_module.return_value = mock_module

        # Call the method with additional kwargs
        kwargs = {"api_key": "test_key", "base_url": "https://test.com"}
        ProviderFactory.create_provider("openai", verbose=True, **kwargs)

        # Assertions
        mock_provider.assert_called_once_with(verbose=True, api_key="test_key", base_url="https://test.com")


class TestProviderImplementation:
    """Test for a mock Provider implementation to validate contract"""

    class MockProvider(Provider):
        """Mock implementation of Provider for testing"""

        def __init__(self):
            self.completion_called = False

        def completion(self, messages, stream=False):
            """Implement completion method"""
            self.completion_called = True
            yield LLMResponse(content="test response")

        def detect_tool_role(self):
            """Implement detect_tool_role method"""
            return "tool"

    def test_provider_implementation_contract(self):
        """Test a concrete implementation of Provider adheres to the contract"""
        provider = self.MockProvider()

        # Test completion method
        messages = [ChatMessage(role="user", content="test")]
        responses = list(provider.completion(messages))

        assert provider.completion_called
        assert len(responses) == 1
        assert responses[0].content == "test response"

        # Test detect_tool_role method
        assert provider.detect_tool_role() == "tool"
