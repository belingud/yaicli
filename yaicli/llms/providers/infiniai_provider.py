from ...config import cfg
from .openai_provider import OpenAIProvider


class InfiniAIProvider(OpenAIProvider):
    """InfiniAI provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://cloud.infini-ai.com/maas/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }

    def __init__(self, config: dict = cfg, **kwargs):
        super().__init__(config, **kwargs)
        if self.enable_function:
            self.console.print("InfiniAI does not support functions, disabled", style="yellow")
        self.enable_function = False
