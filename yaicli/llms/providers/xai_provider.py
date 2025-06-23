from .openai_provider import OpenAIProvider


class XaiProvider(OpenAIProvider):
    """Xai provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.xai.com/v1"
