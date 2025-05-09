from dataclasses import dataclass
import time
from typing import Optional

from ..config import cfg
from ..providers.base import LLMProvider


# Provider map
# PROVIDER_MAP: Dict[str, Type[LLMProvider]] = {
#     "openai": OpenAIProvider,
#     "cohere": CohereProvider,
# }


@dataclass
class ProviderFactory:
    """Provider factory class"""

    @staticmethod
    def create_provider(provider_name: Optional[str] = None) -> LLMProvider:
        """
        Create a provider instance based on the provider name

        Args:
            provider_name: provider name, if None, use the default value from config

        Returns:
            LLMProvider: provider instance
        """
        # Get provider name, if not specified, use the default value from config
        if provider_name is None:
            provider_name = cfg.get("PROVIDER", "openai")

        # Ensure provider_name is a string type
        provider_name_str = str(provider_name).lower()

        # if provider_name_str not in PROVIDER_MAP:
        # raise ValueError(f"Unsupported provider: {provider_name_str}")
        if provider_name_str == "openai":
            s = time.time()
            from yaicli.providers.openai import OpenAIProvider
            e = time.time()
            print(f"Load OpenAIProvider in {e - s}s")

            provider_cls = OpenAIProvider
        elif provider_name_str == "cohere":
            from yaicli.providers.cohere import CohereProvider

            provider_cls = CohereProvider
        else:
            from yaicli.providers.openai import OpenAIProvider

            provider_cls = OpenAIProvider
        # Get the specific configuration for this provider
        api_key = cfg.get("API_KEY", "")
        model = cfg.get("MODEL", "")
        base_url = cfg.get("BASE_URL", None)
        timeout = cfg.get("TIMEOUT", 60)

        # Create provider instance
        return provider_cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
        )
