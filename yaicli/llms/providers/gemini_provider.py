import json
from functools import wraps
from typing import Any, Callable, Dict, Generator, List

import google.genai as genai
from google.genai import types

from ...config import cfg
from ...console import get_console
from ...schemas import ChatMessage, LLMResponse
from ...tools import get_func_name_map
from ..provider import Provider


def wrap_function(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


class GeminiProvider(Provider):
    """Gemini provider implementation based on google-genai library"""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        self.config = config
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        self.verbose = verbose

        # Initialize client
        self.client_params = self.get_client_params()
        self.client = genai.Client(**self.client_params)
        self.console = get_console()

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters"""
        # Initialize client params
        return {
            "api_key": self.config["API_KEY"],
        }

    def get_chat_config(self):
        http_options_map = {
            "timeout": self.config["TIMEOUT"] * 1000,  # Timeout for the request in milliseconds.
            "headers": {**self.config["EXTRA_HEADERS"], "X-Client": self.APP_NAME, "Referer": self.APP_REFERER},
        }
        if self.config.get("BASE_URL"):
            http_options_map["base_url"] = self.config["BASE_URL"]
        if self.config.get("API_VERSION"):
            # Specifies the version of the API to use.
            http_options_map["api_version"] = self.config["API_VERSION"]
        http_options = types.HttpOptions(**http_options_map)
        config_map = {
            "max_output_tokens": self.config["MAX_TOKENS"],
            "temperature": self.config["TEMPERATURE"],
            "top_p": self.config["TOP_P"],
            "http_options": http_options,
        }
        if self.config.get("TOP_K"):
            config_map["top_k"] = self.config["TOP_K"]
        if self.config.get("PRESENCE_PENALTY"):
            config_map["presence_penalty"] = self.config["PRESENCE_PENALTY"]
        if self.config.get("FREQUENCY_PENALTY"):
            config_map["frequency_penalty"] = self.config["FREQUENCY_PENALTY"]
        if self.config.get("SEED"):
            config_map["seed"] = self.config["SEED"]
        # Indicates whether to include thoughts in the response. If true, thoughts are returned only if the model supports thought and thoughts are available.
        thinking_config_map = {"include_thoughts": self.config.get("INCLUDE_THOUGHTS", True)}
        if self.config.get("THINKING_BUDGET"):
            thinking_config_map["thinking_budget"] = int(self.config["THINKING_BUDGET"])
        config_map["thinking_config"] = types.ThinkingConfig(**thinking_config_map)
        config = types.GenerateContentConfig(**config_map)
        if self.enable_function:
            # TODO: support disable automatic function calling
            # config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=False)
            config.tools = self.gen_gemini_functions()
        return config

    def _convert_messages(self, messages: List[ChatMessage]) -> List[types.Content]:
        """Convert a list of ChatMessage objects to a list of Gemini Content objects."""
        converted_messages = []
        for msg in messages:
            if msg.role == "system":
                continue
            content = types.Content(role=self._map_role(msg.role), parts=[types.Part(text=msg.content)])
            if msg.role == "tool":
                content.role = "user"
                content.parts = [
                    types.Part.from_function_response(name=msg.name or "", response={"result": msg.content})
                ]
            converted_messages.append(content)
        return converted_messages

    def _map_role(self, role: str) -> str:
        """Map OpenAI roles to Gemini roles"""
        # Gemini uses "user", "model" instead of "user", "assistant"
        if role == "assistant":
            return "model"
        return role

    def gen_gemini_functions(self) -> List[Callable[..., Any]]:
        """Wrap Gemini functions from OpenAI functions for automatic function calling"""
        func_name_map = get_func_name_map()
        if not func_name_map:
            return []
        funcs = []
        for func_name, func in func_name_map.items():
            wrapped_func = wrap_function(func.execute)
            wrapped_func.__name__ = func_name
            wrapped_func.__doc__ = func.__doc__
            funcs.append(wrapped_func)
        return funcs

    def completion(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
    ) -> Generator[LLMResponse, None, None]:
        """
        Send completion request to Gemini and return responses.

        Args:
            messages: List of chat messages to send
            stream: Whether to stream the response

        Yields:
            LLMResponse: Response objects containing content, tool calls, etc.

        Raises:
            ValueError: If messages is empty or invalid
            APIError: If API request fails
        """
        gemini_messages = self._convert_messages(messages)
        if self.verbose:
            self.console.print("Messages:")
            self.console.print(gemini_messages)
        chat_config = self.get_chat_config()
        chat_config.system_instruction = messages[0].content
        chat = self.client.chats.create(model=self.config["MODEL"], history=gemini_messages, config=chat_config)  # type: ignore
        message = messages[-1].content

        if stream:
            response = chat.send_message_stream(message=message)  # type: ignore
            yield from self._handle_stream_response(response)
        else:
            response = chat.send_message(message=message)  # type: ignore
            yield from self._handle_normal_response(response)

    def _handle_normal_response(self, response) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response"""
        # TODO: support disable automatic function calling
        if not response or not response.candidates:
            yield LLMResponse(
                content=json.dumps(response.to_json_dict()),
                finish_reason="stop",
            )
            return
        for part in response.candidates[0].content.parts:
            if part.thought:
                yield LLMResponse(reasoning=part.text, finish_reason="stop")
            else:
                yield LLMResponse(reasoning=None, content=part.text, finish_reason="stop")

    def _handle_stream_response(self, response) -> Generator[LLMResponse, None, None]:
        """Handle streaming response from Gemini API"""
        # Initialize tool call object to accumulate tool call data across chunks
        # TODO: support disable automatic function calling
        tool_call = None
        for chunk in response:
            if not chunk.candidates:
                continue
            candidate = chunk.candidates[0]
            finish_reason = candidate.finish_reason
            for part in chunk.candidates[0].content.parts:
                if part.thought:
                    reasoning = part.text
                    content = None
                else:
                    content = part.text
                    reasoning = None
                yield LLMResponse(
                    reasoning=reasoning,
                    content=content or "",
                    tool_call=tool_call if finish_reason == "tool_calls" else None,
                    finish_reason=finish_reason or None,
                )

    def detect_tool_role(self) -> str:
        """Return the role that should be used for tool responses"""
        return "user"
