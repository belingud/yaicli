from typing import Any, Dict

from pydantic import PydanticDeprecationWarning

from ...config import cfg
from .openai_provider import OpenAIProvider


class SparkProvider(OpenAIProvider):
    DEFAULT_BASE_URL = "https://spark-api-open.xf-yun.com/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
    }
    # Identifiers of models that support function call
    FUNCTION_CALL_MODEL_IDENTIFIERS = ("Ultra", "generalv3")

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        # Suppress specific warnings before initialization
        # TODO: Remove this after openai upgraded
        import warnings

        warnings.filterwarnings("ignore", category=PydanticDeprecationWarning)

        api_key = config.get("API_KEY")
        api_secret = config.get("API_SECRET")
        app_id = config.get("APP_ID")

        if not all([api_key, api_secret]):
            raise ValueError("API_KEY and API_SECRET are required for Spark provider")

        # Create a mutable copy of the config to avoid modifying the original
        config_copy = config.copy()
        config_copy["API_KEY"] = f"{api_key}:{api_secret}"

        # Add uid to extra_body
        extra_body = config_copy.get("EXTRA_BODY") or {}
        extra_body["uid"] = app_id
        config_copy["EXTRA_BODY"] = extra_body

        super().__init__(config_copy, verbose, **kwargs)

    def get_completion_params(self) -> Dict[str, Any]:
        completion_params = super().get_completion_params()

        # Only process when function call is enabled
        if self.enable_function:
            # Check if the current model supports function call (by checking the model name)
            model_name = completion_params.get("model", "")
            function_call_supported = any(
                identifier in model_name for identifier in self.FUNCTION_CALL_MODEL_IDENTIFIERS
            )

            if not function_call_supported:
                self.console.print(f"Spark Warning: `{model_name}` model not support function call.", style="yellow")

            # Ensure extra_body exists and add tool_calls_switch
            extra_body = completion_params.get("extra_body", {})
            extra_body["tool_calls_switch"] = True
            completion_params["extra_body"] = extra_body

        return completion_params
