from typing import Any, Dict, List

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
    }

    def get_client_params(self) -> Dict[str, Any]:
        client_params = super().get_client_params()
        client_params["warm_tcp_connection"] = False
        return client_params

    def get_tools(self) -> List[dict]:
        tools = super().get_tools()
        for i in tools:
            if "function" not in i:
                continue
            if "parameters" not in i["function"]:
                continue
            if "properties" not in i["function"]["parameters"]:
                continue
            if not isinstance(i["function"]["parameters"]["properties"], dict):
                continue
            for v in i["function"]["parameters"]["properties"].values():
                v.pop("example", None)
        return tools
