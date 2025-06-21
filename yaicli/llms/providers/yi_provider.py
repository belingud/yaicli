from .openai_provider import OpenAIProvider


class YiProvider(OpenAIProvider):
    """Yi provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.lingyiwanwu.com/v1"
