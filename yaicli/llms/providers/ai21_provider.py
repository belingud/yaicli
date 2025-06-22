from typing import Any, Dict, Generator, Optional

from openai._streaming import Stream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ...schemas import LLMResponse, ToolCall
from .openai_provider import OpenAIProvider


class AI21Provider(OpenAIProvider):
    """AI21 provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.ai21.com/studio/v1"

    def get_completion_params(self) -> Dict[str, Any]:
        params = super().get_completion_params()
        params["max_tokens"] = params.pop("max_completion_tokens")
        return params

    def _handle_stream_response(self, response: Stream[ChatCompletionChunk]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response from AI21 models

        Processes chunks from streaming API, extracting content, reasoning and tool calls.
        The tool call response is scattered across multiple chunks.

        Args:
            response: Stream of chat completion chunks from AI21 API

        Yields:
            Generator yielding LLMResponse objects containing:
            - reasoning: The thinking/reasoning content (if any)
            - content: The normal response content
            - tool_call: Tool call information when applicable
        """
        # Initialize tool call object to accumulate tool call data across chunks
        tool_call: Optional[ToolCall] = None

        # Process each chunk in the response stream
        for chunk in response:
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

            # AI21 specific handling: content cannot be empty for tool calls
            if finish_reason == "tool_calls" and not content:
                # tool call assistant message, content can't be empty
                # Error code: 422 - {'detail': {'error': ['Value error, message content must not be an empty string']}}
                content = tool_call.id

            # Generate response object
            yield LLMResponse(
                reasoning=reasoning,
                content=content,
                tool_call=tool_call if finish_reason == "tool_calls" else None,
                finish_reason=finish_reason,
            )
