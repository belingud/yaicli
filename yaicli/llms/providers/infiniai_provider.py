from typing import Any, Dict

from .openai_provider import OpenAIProvider


class InfiniAIProvider(OpenAIProvider):
    """InfiniAI provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://cloud.infini-ai.com/maas/v1"

    def __init__(self, config: dict = ..., **kwargs):
        super().__init__(config, **kwargs)
        if self.enable_function:
            self.console.print("InfiniAI does not support functions, disabled", style="yellow")
        self.enable_function = False

    def get_completion_params(self) -> Dict[str, Any]:
        params = super().get_completion_params()
        params["max_tokens"] = params.pop("max_completion_tokens")
        return params
