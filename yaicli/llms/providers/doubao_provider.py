from volcenginesdkarkruntime import Ark

from ...config import cfg
from ...console import get_console
from .openai_provider import OpenAIProvider


class DoubaoProvider(OpenAIProvider):
    """Doubao provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

    def __init__(self, config: dict = cfg, **kwargs):
        self.config = config
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        # Initialize client params
        self.client_params = {"base_url": self.DEFAULT_BASE_URL}
        if self.config.get("API_KEY", None):
            self.client_params["api_key"] = self.config["API_KEY"]
        if self.config.get("BASE_URL", None):
            self.client_params["base_url"] = self.config["BASE_URL"]
        if self.config.get("AK", None):
            self.client_params["ak"] = self.config["AK"]
        if self.config.get("SK", None):
            self.client_params["sk"] = self.config["SK"]
        if self.config.get("REGION", None):
            self.client_params["region"] = self.config["REGION"]

        # Initialize client
        self.client = Ark(**self.client_params)
        self.console = get_console()

        # Store completion params
        self.completion_params = {
            "model": self.config["MODEL"],
            "temperature": self.config["TEMPERATURE"],
            "top_p": self.config["TOP_P"],
            "max_tokens": self.config["MAX_TOKENS"],
            "timeout": self.config["TIMEOUT"],
        }
        # Add extra headers if set
        if self.config.get("EXTRA_HEADERS", None):
            self.completion_params["extra_headers"] = {
                **self.config["EXTRA_HEADERS"],
                "X-Title": self.APP_NAME,
                "HTTP-Referer": self.APPA_REFERER,
            }

        # Add extra body params if set
        if self.config.get("EXTRA_BODY", None):
            self.completion_params["extra_body"] = self.config["EXTRA_BODY"]
