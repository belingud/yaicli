from .openai_provider import OpenAIProvider


class MinimaxProvider(OpenAIProvider):
    """Minimax provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"

    def get_completion_params_keys(self) -> dict:
        """
        Customize completion parameter keys for Minimax API.
        Maps 'max_completion_tokens' to 'max_tokens' for compatibility.

        Returns:
            dict: Modified parameter mapping dictionary
        """
        keys = super().get_completion_params_keys()
        # Replace max_completion_tokens with max_tokens in the API
        if "max_completion_tokens" in keys:
            keys["max_tokens"] = keys.pop("max_completion_tokens")
        return keys
