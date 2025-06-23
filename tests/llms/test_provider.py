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


class TestProviderFactory:
    """Test the ProviderFactory class"""

    def test_known_provider_types(self):
        """Test that ProviderFactory has the expected provider types"""
        expected_providers = {
            "openai",
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
