class YAICLIException(Exception):
    """Base exception for YAICLI"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


###################################
# Role exceptions
class RoleNotFoundError(YAICLIException):
    """Exception raised when a role is not found"""

    pass


class RoleAlreadyExistsError(YAICLIException):
    """Exception raised when a role already exists"""

    pass


class RoleCreationError(YAICLIException):
    """Exception raised when a role creation fails"""

    pass


###################################
# Chat exceptions
class ChatNotFoundError(YAICLIException):
    """Exception raised when a chat is not found"""

    pass


class ChatSaveError(YAICLIException):
    """Exception raised when a chat save fails"""

    pass


class ChatDeleteError(YAICLIException):
    """Exception raised when a chat delete fails"""

    pass
