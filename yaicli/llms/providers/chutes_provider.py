from .openai_provider import OpenAIProvider


class ChutesProvider(OpenAIProvider):
    """Chutes provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://llm.chutes.ai/v1"

    def get_completion_params_keys(self) -> dict:
        """
        Customize completion parameter keys for Chutes API.
        Maps 'max_completion_tokens' to 'max_tokens' and removes 'reasoning_effort'
        which is not supported by this provider.

        Returns:
            dict: Modified parameter mapping dictionary
        """
        keys = super().get_completion_params_keys()
        # Replace max_completion_tokens with max_tokens in the API
        if "max_completion_tokens" in keys:
            keys["max_tokens"] = keys.pop("max_completion_tokens")
        # Remove unsupported parameters
        keys.pop("reasoning_effort", None)
        return keys
