from typing import Any, Dict

from huggingface_hub import InferenceClient

from .chatglm_provider import ChatglmProvider


class HuggingFaceProvider(ChatglmProvider):
    """
    HuggingFaceProvider is a provider for the HuggingFace API.
    """

    CLIENT_CLS = InferenceClient
    DEFAULT_PROVIDER = "auto"

    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "extra_body": "EXTRA_BODY",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }

    def get_client_params(self) -> Dict[str, Any]:
        client_params = {
            "api_key": self.config["API_KEY"],
            "timeout": self.config["TIMEOUT"],
            "provider": self.config.get("HF_PROVIDER") or self.DEFAULT_PROVIDER,
        }
        if self.config["BASE_URL"]:
            client_params["base_url"] = self.config["BASE_URL"]
        if self.config["EXTRA_HEADERS"]:
            client_params["headers"] = {
                **self.config["EXTRA_HEADERS"],
                "X-Title": self.APP_NAME,
                "HTTP-Referer": self.APP_REFERER,
            }
        if self.config.get("BILL_TO"):
            client_params["bill_to"] = self.config["BILL_TO"]
        return client_params
