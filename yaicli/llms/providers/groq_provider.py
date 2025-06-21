from .openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    """Groq provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, config: dict = ..., **kwargs):
        super().__init__(config, **kwargs)
        if "N" in self.completion_params["EXTRA_BODY"] and self.completion_params["EXTRA_BODY"]["N"] != 1:
            self.console.print("Groq does not support N parameter, setting N to 1", style="yellow")
            self.completion_params["EXTRA_BODY"]["N"] = 1
