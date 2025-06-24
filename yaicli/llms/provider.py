import importlib
from abc import ABC, abstractmethod
from typing import Generator, List

from ..schemas import ChatMessage, LLMResponse


class Provider(ABC):
    """Base abstract class for LLM providers"""

    APP_NAME = "yaicli"
    APP_REFERER = "https://github.com/halfrost/yaicli"

    @abstractmethod
    def completion(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
    ) -> Generator[LLMResponse, None, None]:
        """
        Send a completion request to the LLM provider

        Args:
            messages: List of message objects representing the conversation
            stream: Whether to stream the response

        Returns:
            Generator yielding LLMResponse objects
        """
        pass

    @abstractmethod
    def detect_tool_role(self) -> str:
        """Return the role that should be used for tool responses"""
        pass


class ProviderFactory:
    """Factory to create LLM provider instances"""

    providers_map = {
        "ai21": (".providers.ai21_provider", "AI21Provider"),
        "chatglm": (".providers.chatglm_provider", "ChatglmProvider"),
        "chutes": (".providers.chutes_provider", "ChutesProvider"),
        "cohere": (".providers.cohere_provider", "CohereProvider"),
        "cohere-bedrock": (".providers.cohere_provider", "CohereBadrockProvider"),
        "cohere-sagemaker": (".providers.cohere_provider", "CohereSagemakerProvider"),
        "deepseek": (".providers.deepseek_provider", "DeepSeekProvider"),
        "doubao": (".providers.doubao_provider", "DoubaoProvider"),
        "gemini": (".providers.gemini_provider", "GeminiProvider"),
        "groq": (".providers.groq_provider", "GroqProvider"),
        "huggingface": (".providers.huggingface_provider", "HuggingFaceProvider"),
        "infini-ai": (".providers.infiniai_provider", "InfiniAIProvider"),
        "minimax": (".providers.minimax_provider", "MinimaxProvider"),
        "modelscope": (".providers.modelscope_provider", "ModelScopeProvider"),
        "ollama": (".providers.ollama_provider", "OllamaProvider"),
        "openai": (".providers.openai_provider", "OpenAIProvider"),
        "openrouter": (".providers.openrouter_provider", "OpenRouterProvider"),
        "sambanova": (".providers.sambanova_provider", "SambanovaProvider"),
        "siliconflow": (".providers.siliconflow_provider", "SiliconFlowProvider"),
        "targon": (".providers.targon_provider", "TargonProvider"),
        "vertexai": (".providers.vertexai_provider", "VertexAIProvider"),
        "xai": (".providers.xai_provider", "XaiProvider"),
        "yi": (".providers.yi_provider", "YiProvider"),
    }

    @classmethod
    def create_provider(cls, provider_type: str, verbose: bool = False, **kwargs) -> Provider:
        """Create a provider instance based on provider type

        Args:
            provider_type: The type of provider to create
            **kwargs: Additional parameters to pass to the provider

        Returns:
            A Provider instance
        """
        provider_type = provider_type.lower()
        if provider_type not in cls.providers_map:
            raise ValueError(f"Unknown provider: {provider_type}")

        module_path, class_name = cls.providers_map[provider_type]
        module = importlib.import_module(module_path, package="yaicli.llms")
        return getattr(module, class_name)(verbose=verbose, **kwargs)
