from typing import Any, Dict

from .openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    """Groq provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "reasoning_effort": "REASONING_EFFORT",
    }

    def get_completion_params(self) -> Dict[str, Any]:
        """
        Get completion parameters with Groq-specific adjustments.
        Enforce N=1 as Groq doesn't support multiple completions.

        Returns:
            Dict[str, Any]: Parameters for completion API call
        """
        params = super().get_completion_params()
        if self.config["EXTRA_BODY"] and "N" in self.config["EXTRA_BODY"] and self.config["EXTRA_BODY"]["N"] != 1:
            self.console.print("Groq does not support N parameter, setting N to 1 as Groq default", style="yellow")
            params["extra_body"]["N"] = 1

        if params.get("reasoning_effort"):
            if params["reasoning_effort"] not in ("null", "default"):
                self.console.print(
                    "Groq only supports null or default for reasoning_effort, setting to default", style="yellow"
                )
                params["reasoning_effort"] = "default"
            if "qwen3" not in params["model"]:
                self.console.print("Groq only supports reasoning_effort for qwen3, setting to null", style="yellow")
                params["reasoning_effort"] = None
        if params.get("reasoning_effort") == "null":
            params["reasoning_effort"] = None
        return params
