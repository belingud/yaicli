from typing import Dict

from .openai_provider import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

    def get_completion_params_keys(self) -> Dict[str, str]:
        """
        Customize completion parameter keys for OpenRouter API.
        Maps 'max_completion_tokens' to 'max_tokens' for compatibility.

        Returns:
            Dict[str, str]: Modified parameter mapping dictionary
        """
        keys = super().get_completion_params_keys()
        if "max_completion_tokens" in keys:
            keys["max_tokens"] = keys.pop("max_completion_tokens")
        return keys
