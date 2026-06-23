from typing import Any, Dict, List

from ...schemas import ChatMessage
from .openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "frequency_penalty": "FREQUENCY_PENALTY",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "reasoning_effort": "REASONING_EFFORT",
    }

    def _convert_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Convert messages using DeepSeek's reasoning_content field."""
        converted_messages = super()._convert_messages(messages)
        for source, message in zip(messages, converted_messages):
            if source.role == "assistant" and source.reasoning:
                message.pop("reasoning", None)
                message["reasoning_content"] = source.reasoning
        return converted_messages
