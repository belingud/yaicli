from typing import Any, Dict

from .openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    """Groq provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

    def get_completion_params_keys(self) -> Dict[str, str]:
        """
        Customize completion parameter keys for Groq API.
        Maps 'max_completion_tokens' to 'max_tokens' for compatibility.

        Returns:
            Dict[str, str]: Modified parameter mapping dictionary
        """
        keys = super().get_completion_params_keys()
        if "max_completion_tokens" in keys:
            keys["max_tokens"] = keys.pop("max_completion_tokens")
        return keys

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
        return params
