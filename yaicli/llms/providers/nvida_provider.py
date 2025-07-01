from copy import deepcopy
from typing import Any, Dict

from .openai_provider import OpenAIProvider


class NvidiaProvider(OpenAIProvider):
    DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
    }

    def get_completion_params(self) -> Dict[str, Any]:
        completion_params = super().get_completion_params()
        if completion_params.get("extra_body") and "chat_template_kwargs" not in completion_params["extra_body"]:
            # Nvidia api accept redundant parameters, leave extra_body as is and add key chat_template_kwargs
            # {"chat_template_kwargs": {"thinking":True}} for Qwen3/granite
            completion_params["extra_body"]["chat_template_kwargs"] = deepcopy(completion_params["extra_body"])
        return completion_params
