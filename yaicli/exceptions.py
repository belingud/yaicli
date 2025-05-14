class YaicliError(Exception):
    """Base exception for yaicli"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class ChatSaveError(YaicliError):
    """Error saving chat"""


class ChatLoadError(YaicliError):
    """Error loading chat"""


class ChatDeleteError(YaicliError):
    """Error deleting chat"""
