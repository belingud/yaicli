from .openai_provider import OpenAIProvider


class TargonProvider(OpenAIProvider):
    """Targon provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.targon.com/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
    }
