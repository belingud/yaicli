from typing import Any, Dict

from fireworks.client import Fireworks

from .openai_provider import OpenAIProvider


class FireworksProvider(OpenAIProvider):
    """Fireworks AI LLM provider

    Fireworks AI supports the following models:
    - llama-v3p1-405b-instruct
    - llama-v3p1-70b-instruct
    - qwen2p5-72b-instruct
    - mixtral-8x22b-instruct
    - firefunction-v2
    - firefunction-v1

    The function calling API is compatible with OpenAI, but has the following differences:
    - Does not support parallel function calls
    - Does not support nested function calls
    - Simplified tool selection options
    """

    CLIENT_CLS = Fireworks
    DEFAULT_BASE_URL = "https://api.fireworks.ai/inference/v1"

    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "reasoning_effort": "REASONING_EFFORT",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters

        account: The account to use for the client. Defaults to "fireworks".
        """
        client_params = super().get_client_params()
        client_params["extra_headers"] = client_params.pop("default_headers")
        # In Fireworks, account can be set to "fireworks" or "fireworks-dev"
        client_params["account"] = self.config.get("ACCOUNT", "fireworks")
        client_params["timeout"] = self.config["TIMEOUT"]
        return client_params

    def detect_tool_role(self) -> str:
        """Return the role that should be used for tool responses"""
        return "tool"
