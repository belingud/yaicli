from typing import Any, Dict

from cerebras.cloud.sdk import Cerebras

from .openai_provider import OpenAIProvider


class CerebrasProvider(OpenAIProvider):
    """Cerebras LLM provider"""

    CLIENT_CLS = Cerebras
    DEFAULT_BASE_URL = "https://api.cerebras.ai"

    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_completion_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }

    def get_client_params(self) -> Dict[str, Any]:
        client_params = super().get_client_params()
        client_params["warm_tcp_connection"] = False
        return client_params
