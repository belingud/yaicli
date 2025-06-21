from .openai_provider import OpenAIProvider


class ChutesProvider(OpenAIProvider):
    """Chutes provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://llm.chutes.ai/v1"
