from typing import Any, Dict, Generator, List, Optional

import openai
from openai._streaming import Stream
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ...config import cfg
from ...console import get_console
from ...schemas import ChatMessage, LLMResponse, ToolCall
from ...tools import get_openai_schemas
from ..provider import Provider


class OpenAIProvider(Provider):
    """OpenAI provider implementation based on openai library"""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    CLIENT_CLS = openai.OpenAI

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        self.config = config
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        self.verbose = verbose

        # Initialize client
        self.client_params = self.get_client_params()
        self.client = self.CLIENT_CLS(**self.client_params)
        self.console = get_console()

        # Store completion params
        self.completion_params = self.get_completion_params()

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters"""
        # Initialize client params
        client_params = {
            "api_key": self.config["API_KEY"],
            "base_url": self.config["BASE_URL"] or self.DEFAULT_BASE_URL,
        }

        # Add extra headers if set
        if self.config["EXTRA_HEADERS"]:
            client_params["default_headers"] = {
                **self.config["EXTRA_HEADERS"],
                "X-Title": self.APP_NAME,
                "HTTP-Referer": self.APPA_REFERER,
            }
        return client_params

    def get_completion_params(self) -> Dict[str, Any]:
        """Get the completion parameters"""
        completion_params = {
            "model": self.config["MODEL"],
            "temperature": self.config["TEMPERATURE"],
            "top_p": self.config["TOP_P"],
            "max_completion_tokens": self.config["MAX_TOKENS"],
            "timeout": self.config["TIMEOUT"],
        }
        # Add extra body params if set
        if self.config["EXTRA_BODY"]:
            completion_params["extra_body"] = self.config["EXTRA_BODY"]
        return completion_params

    def _convert_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Convert a list of ChatMessage objects to a list of OpenAI message dicts."""
        converted_messages = []
        for msg in messages:
            message = {"role": msg.role, "content": msg.content or ""}

            if msg.name:
                message["name"] = msg.name

            if msg.role == "assistant" and msg.tool_calls:
                message["tool_calls"] = [
                    {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in msg.tool_calls
                ]

            if msg.role == "tool" and msg.tool_call_id:
                message["tool_call_id"] = msg.tool_call_id

            converted_messages.append(message)

        return converted_messages

    def completion(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
    ) -> Generator[LLMResponse, None, None]:
        """Send completion request to OpenAI and return responses"""
        openai_messages = self._convert_messages(messages)
        if self.verbose:
            self.console.print("Messages:")
            self.console.print(openai_messages)

        params = self.completion_params.copy()
        params["messages"] = openai_messages
        params["stream"] = stream

        if self.enable_function:
            tools = get_openai_schemas()
            if tools:
                params["tools"] = tools

        if stream:
            response = self.client.chat.completions.create(**params)
            yield from self._handle_stream_response(response)
        else:
            response = self.client.chat.completions.create(**params)
            yield from self._handle_normal_response(response)

    def _handle_normal_response(self, response: ChatCompletion) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response"""
        choice = response.choices[0]
        content = choice.message.content or ""  # type: ignore
        reasoning = choice.message.reasoning_content  # type: ignore
        finish_reason = choice.finish_reason
        tool_call: Optional[ToolCall] = None

        # Check if the response contains reasoning content in model_extra
        if hasattr(choice.message, "model_extra") and choice.message.model_extra:
            model_extra = choice.message.model_extra
            reasoning = self._get_reasoning_content(model_extra)

        if finish_reason == "tool_calls" and hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
            tool = choice.message.tool_calls[0]
            tool_call = ToolCall(tool.id, tool.function.name or "", tool.function.arguments)

        yield LLMResponse(reasoning=reasoning, content=content, finish_reason=finish_reason, tool_call=tool_call)

    def _handle_stream_response(self, response: Stream[ChatCompletionChunk]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response from OpenAI API"""
        # Initialize tool call object to accumulate tool call data across chunks
        tool_call: Optional[ToolCall] = None

        # Process each chunk in the response stream
        for chunk in response:
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta
            finish_reason = choice.finish_reason

            # Extract content from current chunk
            content = delta.content or ""

            # Extract reasoning content if available
            reasoning = self._get_reasoning_content(getattr(delta, "model_extra", None) or delta)

            # Process tool call information that may be scattered across chunks
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                tool_call = self._process_tool_call_chunk(delta.tool_calls, tool_call)

            # Generate response object with tool_call only when finish_reason indicates completion
            yield LLMResponse(
                reasoning=reasoning,
                content=content,
                tool_call=tool_call if finish_reason == "tool_calls" else None,
                finish_reason=finish_reason,
            )

    def _process_tool_call_chunk(self, tool_calls, existing_tool_call=None):
        """Process tool call data from a response chunk"""
        # Initialize tool call object if this is the first chunk with tool call data
        if existing_tool_call is None and tool_calls:
            existing_tool_call = ToolCall(tool_calls[0].id or "", tool_calls[0].function.name or "", "")

        # Accumulate arguments from multiple chunks
        if existing_tool_call:
            for tool in tool_calls:
                if not tool.function:
                    continue
                existing_tool_call.arguments += tool.function.arguments or ""

        return existing_tool_call

    def _get_reasoning_content(self, delta: Any) -> Optional[str]:
        """Extract reasoning content from delta if available based on specific keys."""
        if not delta:
            return None
        if not isinstance(delta, dict):
            delta = dict(delta)
        # Reasoning content keys from API:
        # reasoning_content: deepseek/infi-ai
        # reasoning: openrouter
        # <think> block implementation not in here
        for key in ("reasoning_content", "reasoning"):
            if key in delta:
                return delta[key]
        return None

    def detect_tool_role(self) -> str:
        """Return the role that should be used for tool responses"""
        return "tool"
