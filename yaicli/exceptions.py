class YaicliError(Exception):
    """Base exception for yaicli"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class ConfigError(YaicliError):
    """Error in configuration"""


class ConfigMissingError(ConfigError):
    """Missing required key in config"""


class ProviderError(YaicliError):
    """Error in provider

    Providers should attach a ``kind`` (see ``yaicli.errors.ErrorKind``) and the
    HTTP status when known so the client can classify the failure, decide on
    retries and render an actionable message. All attributes keep v0.18
    defaults, so existing ``ProviderError("message")`` call sites stay valid.
    """

    def __init__(
        self,
        message: str,
        kind=None,
        status_code: int | None = None,
        retryable: bool | None = None,
    ):
        self.kind = kind
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message)


class ChatSaveError(YaicliError):
    """Error saving chat"""


class ChatLoadError(YaicliError):
    """Error loading chat"""


class ChatDeleteError(YaicliError):
    """Error deleting chat"""


class MCPToolsError(YaicliError):
    """Error getting MCP tools"""
