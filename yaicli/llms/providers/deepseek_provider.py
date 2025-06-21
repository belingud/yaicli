from .openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"

    def __init__(self, config: dict = ..., **kwargs):
        super().__init__(config, **kwargs)
        self.completion_params["max_tokens"] = self.completion_params.pop("max_completion_tokens")
