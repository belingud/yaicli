from typing import Any, Dict

from .openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    """Groq provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

    def get_completion_params(self) -> Dict[str, Any]:
        params = super().get_completion_params()
        if self.config["EXTRA_BODY"] and "N" in self.config["EXTRA_BODY"] and self.config["EXTRA_BODY"]["N"] != 1:
            self.console.print("Groq does not support N parameter, setting N to 1 as Groq default", style="yellow")
            params["extra_body"]["N"] = 1
        return params
