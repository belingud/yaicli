import subprocess

from yaicli.function_schema import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """
    Execute a shell command and return the output (result).
    """

    shell_command: str = Field(
        ...,
        json_schema_extra={
            "example": "ls -la",
        },
        description="Shell command to execute.",
    )

    class Config:
        title = "execute_shell_command"

    @classmethod
    def execute(cls, shell_command: str) -> str:
        """
        Execute a shell command and return the output (result).

        Args:
            shell_command (str): shell command to execute.

        Returns:
            str: exit code and output string.
        """
        # Optional security check
        dangerous_commands = ["rm -rf", "mkfs", "dd"]
        if any(cmd in shell_command for cmd in dangerous_commands):
            return "Error: Dangerous command detected."

        try:
            process = subprocess.Popen(
                shell_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            output, _ = process.communicate()
            exit_code = process.returncode
            return f"Exit code: {exit_code}, Output:\n{output}"
        except Exception as e:
            return f"Error: {str(e)}"
