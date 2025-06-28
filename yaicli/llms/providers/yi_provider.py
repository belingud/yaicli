from .openai_provider import OpenAIProvider


class YiProvider(OpenAIProvider):
    """Lingyiwanwu provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.lingyiwanwu.com/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
    }
