from .openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    """Groq provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, config: dict = ..., **kwargs):
        super().__init__(config, **kwargs)
        if self.config.get("EXTRA_BODY") and "N" in self.config["EXTRA_BODY"] and self.config["EXTRA_BODY"]["N"] != 1:
            self.console.print("Groq does not support N parameter, setting N to 1 as Groq default", style="yellow")
            if "extra_body" in self.completion_params:
                self.completion_params["extra_body"]["N"] = 1
