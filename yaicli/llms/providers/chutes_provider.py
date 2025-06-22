from typing import Any, Dict

from .openai_provider import OpenAIProvider


class ChutesProvider(OpenAIProvider):
    """Chutes provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://llm.chutes.ai/v1"

    def get_completion_params(self) -> Dict[str, Any]:
        params = super().get_completion_params()
        params["max_tokens"] = params.pop("max_completion_tokens")
        return params
