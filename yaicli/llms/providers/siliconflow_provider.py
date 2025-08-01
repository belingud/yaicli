from .openai_provider import OpenAIProvider


class SiliconFlowProvider(OpenAIProvider):
    """SiliconFlow provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }
