from typing import Generator

from openai._streaming import Stream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ...schemas import LLMResponse, ToolCall
from ..tool_calls import ToolCallAccumulator
from .openai_provider import OpenAIProvider


class AI21Provider(OpenAIProvider):
    """AI21 provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.ai21.com/studio/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }

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
        # Accumulate every tool call of the stream (parallel calls included), using
        # the shared accumulator. AI21 re-sends the complete argument JSON on later
        # chunks instead of fragments, hence ``replace_arguments=True``.
        accumulator = ToolCallAccumulator()

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
            delta_tool_calls = getattr(delta, "tool_calls", None) or []
            for position, tool in enumerate(delta_tool_calls):
                function = getattr(tool, "function", None)
                if function is None:
                    continue
                index = getattr(tool, "index", None)
                if not isinstance(index, int):
                    index = position if len(delta_tool_calls) > 1 else None
                accumulator.add_fragment(
                    index=index,
                    call_id=getattr(tool, "id", None) or None,
                    name=getattr(function, "name", None) or None,
                    arguments=getattr(function, "arguments", None) or None,
                    replace_arguments=True,
                )

            tool_calls = accumulator.finalize() if finish_reason == "tool_calls" else []

            # AI21 specific handling: content cannot be empty for tool calls
            if finish_reason == "tool_calls" and not content and tool_calls:
                # tool call assistant message, content can't be empty
                # Error code: 422 - {'detail': {'error': ['Value error, message content must not be an empty string']}}
                content = tool_calls[0].id

            # Generate response object
            yield LLMResponse(
                reasoning=reasoning,
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )

    def _process_tool_call_chunk(self, tool_calls, existing_tool_call=None):
        """Process a tool call chunk from AI21 API response

        Tool calls from AI21 are delivered across multiple chunks:
        - First chunk contains function name
        - Subsequent chunks contain arguments data
        - Final chunk (with finish_reason='tool_calls') contains complete arguments

        Args:
            tool_calls: Tool call data from current chunk
            existing_tool_call: Previously accumulated tool call object

        Returns:
            ToolCall: Updated tool call object with accumulated data
        """
        # Get the first (and only) tool call from the chunk
        call = tool_calls[0]

        if existing_tool_call is None:
            # First chunk - create new tool call with function name
            return ToolCall(id=call.id, name=call.function.name, arguments="{}")
        else:
            # Update existing tool call with new arguments data
            # Keep existing data and update with new information
            existing_arguments = existing_tool_call.arguments
            new_arguments = call.function.arguments if hasattr(call.function, "arguments") else "{}"

            # Combine arguments (new arguments should override if available)
            combined_arguments = new_arguments if new_arguments else existing_arguments

            return ToolCall(id=existing_tool_call.id, name=existing_tool_call.name, arguments=combined_arguments)
