from typing import Any, Dict

from ...const import DEFAULT_TEMPERATURE
from .openai_provider import OpenAIProvider


class SambanovaProvider(OpenAIProvider):
    """Sambanova provider implementation based on OpenAI API"""

    DEFAULT_BASE_URL = "https://api.sambanova.ai/v1"
    SUPPORT_FUNCTION_CALL_MOELS = (
        "Meta-Llama-3.1-8B-Instruct",
        "Meta-Llama-3.1-405B-Instruct",
        "Meta-Llama-3.3-70B-Instruct",
        "Llama-4-Scout-17B-16E-Instruct",
        "DeepSeek-V3-0324",
    )

    def get_completion_params(self) -> Dict[str, Any]:
        params = super().get_completion_params()
        params.pop("presence_penalty", None)
        params.pop("frequency_penalty", None)
        if params.get("temperature") < 0 or params.get("temperature") > 1:
            self.console.print("Sambanova temperature must be between 0 and 1, setting to 0.4", style="yellow")
            params["temperature"] = DEFAULT_TEMPERATURE
        if self.enable_function and self.config["MODEL"] not in self.SUPPORT_FUNCTION_CALL_MOELS:
            self.console.print(
                f"Sambanova supports function call models: {', '.join(self.SUPPORT_FUNCTION_CALL_MOELS)}",
                style="yellow",
            )
