from typing import Dict, Generator, Optional

from openai._streaming import Stream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ...schemas import LLMResponse, ToolCall
from .openai_provider import OpenAIProvider


class AI21Provider(OpenAIProvider):
    """AI21 provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.ai21.com/studio/v1"

    def get_completion_params_keys(self) -> Dict[str, str]:
        """
        Customize completion parameter keys for AI21 API.
        Maps 'max_completion_tokens' to 'max_tokens' for compatibility.

        Returns:
            Dict[str, str]: Modified parameter mapping dictionary
        """
        keys = super().get_completion_params_keys()
        if "max_completion_tokens" in keys:
            keys["max_tokens"] = keys.pop("max_completion_tokens")
        return keys

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
                content = tool_call.id if tool_call else ""

            # Generate response object
            yield LLMResponse(
                reasoning=reasoning,
                content=content,
                tool_call=tool_call if finish_reason == "tool_calls" else None,
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
            return ToolCall(
                id=call.id,
                name=call.function.name,
                arguments="{}"
            )
        else:
            # Update existing tool call with new arguments data
            # Keep existing data and update with new information
            existing_arguments = existing_tool_call.arguments
            new_arguments = call.function.arguments if hasattr(call.function, "arguments") else "{}"
            
            # Combine arguments (new arguments should override if available)
            combined_arguments = new_arguments if new_arguments else existing_arguments
            
            return ToolCall(
                id=existing_tool_call.id,
                name=existing_tool_call.name,
                arguments=combined_arguments
            )