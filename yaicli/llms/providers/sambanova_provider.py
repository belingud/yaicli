from typing import Any, Dict

from ...const import DEFAULT_TEMPERATURE
from .openai_provider import OpenAIProvider


class SambanovaProvider(OpenAIProvider):
    """Sambanova provider implementation based on OpenAI API"""

    DEFAULT_BASE_URL = "https://api.sambanova.ai/v1"
    SUPPORT_FUNCTION_CALL_MOELS = (
        "Meta-Llama-3.1-8B-Instruct",
        "Meta-Llama-3.1-405B-Instruct",
        "Meta-Llama-3.3-70B-Instruct",
        "Llama-4-Scout-17B-16E-Instruct",
        "DeepSeek-V3-0324",
    )

    def get_completion_params_keys(self) -> Dict[str, str]:
        """
        Customize completion parameter keys for Sambanova API.
        Maps 'max_completion_tokens' to 'max_tokens' for compatibility
        and removes parameters not supported by Sambanova.

        Returns:
            Dict[str, str]: Modified parameter mapping dictionary
        """
        keys = super().get_completion_params_keys()
        # Replace max_completion_tokens with max_tokens
        if "max_completion_tokens" in keys:
            keys["max_tokens"] = keys.pop("max_completion_tokens")
        # Remove unsupported parameters
        keys.pop("presence_penalty", None)
        keys.pop("frequency_penalty", None)
        return keys

    def get_completion_params(self) -> Dict[str, Any]:
        """
        Get completion parameters with Sambanova-specific adjustments.
        Validate temperature range and check for function call compatibility.

        Returns:
            Dict[str, Any]: Parameters for completion API call
        """
        params = super().get_completion_params()

        # Validate temperature
        if params.get("temperature") is not None and (params["temperature"] < 0 or params["temperature"] > 1):
            self.console.print("Sambanova temperature must be between 0 and 1, setting to 0.4", style="yellow")
            params["temperature"] = DEFAULT_TEMPERATURE

        # Check function call compatibility
        if self.enable_function and self.config["MODEL"] not in self.SUPPORT_FUNCTION_CALL_MOELS:
            self.console.print(
                f"Sambanova supports function call models: {', '.join(self.SUPPORT_FUNCTION_CALL_MOELS)}",
                style="yellow",
            )

        return params
