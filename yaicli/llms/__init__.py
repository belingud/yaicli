from ..config import cfg
from .client import LLMClient
from .provider import Provider, ProviderFactory

__all__ = ["LLMClient", "Provider", "ProviderFactory"]


class BaseProvider:
    def __init__(self) -> None:
        self.api_key = cfg["API_KEY"]
        self.model = cfg["MODEL"]
        self.base_url = cfg["BASE_URL"]
        self.timeout = cfg["TIMEOUT"]
