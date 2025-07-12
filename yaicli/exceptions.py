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
    """Error in provider"""


class ChatSaveError(YaicliError):
    """Error saving chat"""


class ChatLoadError(YaicliError):
    """Error loading chat"""


class ChatDeleteError(YaicliError):
    """Error deleting chat"""


class MCPToolsError(YaicliError):
    """Error getting MCP tools"""
