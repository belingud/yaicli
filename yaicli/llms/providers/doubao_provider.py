from typing import Any, Dict

from volcenginesdkarkruntime import Ark

from ...config import cfg
from ...console import get_console
from .openai_provider import OpenAIProvider


class DoubaoProvider(OpenAIProvider):
    """Doubao provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
    CLIENT_CLS = Ark

    def __init__(self, config: dict = cfg, **kwargs):
        self.config = config
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        self.client_params = self.get_client_params()

        # Initialize client
        self.client = self.CLIENT_CLS(**self.client_params)
        self.console = get_console()

        # Store completion params
        self.completion_params = self.get_completion_params()

    def get_client_params(self) -> Dict[str, Any]:
        # Initialize client params
        client_params = {"base_url": self.DEFAULT_BASE_URL}
        if self.config.get("API_KEY", None):
            client_params["api_key"] = self.config["API_KEY"]
        if self.config.get("BASE_URL", None):
            client_params["base_url"] = self.config["BASE_URL"]
        if self.config.get("AK", None):
            client_params["ak"] = self.config["AK"]
        if self.config.get("SK", None):
            client_params["sk"] = self.config["SK"]
        if self.config.get("REGION", None):
            client_params["region"] = self.config["REGION"]
        return client_params

    def get_completion_params(self) -> Dict[str, Any]:
        params = {
            "model": self.config["MODEL"],
            "temperature": self.config["TEMPERATURE"],
            "top_p": self.config["TOP_P"],
            "max_tokens": self.config["MAX_TOKENS"],
            "timeout": self.config["TIMEOUT"],
        }
        if self.config.get("EXTRA_BODY", None):
            params["extra_body"] = self.config["EXTRA_BODY"]
        return params
