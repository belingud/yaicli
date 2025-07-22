import json
from typing import Generator, Optional

from openai._streaming import Stream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ...schemas import LLMResponse, ToolCall
from .openai_provider import OpenAIProvider


class OpenAICampatibleProvider(OpenAIProvider):
    def _handle_stream_response(self, response: Stream[ChatCompletionChunk]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response from OpenAI API"""
        # Initialize tool call object to accumulate tool call data across chunks
        tool_call: Optional[ToolCall] = None
        started = False
        complete_json_detected = False  # Flag to track if we've detected complete JSON

        # Process each chunk in the response stream
        for chunk in response:
            if not chunk.choices and not started:
                # Some api could return error message in the first chunk, no choices to handle, return raw response to show the message
                _first_chunk_llm_resp = self._first_chunk_error(chunk)
                if _first_chunk_llm_resp is not None:
                    yield _first_chunk_llm_resp
                started = True
                continue

            if not chunk.choices:
                continue
            started = True
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            # Extract content from current chunk
            content = delta.content or ""

            # Extract reasoning content if available
            reasoning = self._get_reasoning_content(getattr(delta, "model_extra", None) or delta)

            # Process tool call information that may be scattered across chunks
            tool_call_updated = False
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                old_args = tool_call.arguments if tool_call else ""
                tool_call = self._process_tool_call_chunk(delta.tool_calls, tool_call)
                tool_call_updated = old_args != tool_call.arguments if tool_call else False

                # Try to detect if we have complete JSON for tool call args
                if tool_call and tool_call_updated:
                    # Check if arguments appear to be complete valid JSON
                    try:
                        json.loads(tool_call.arguments)
                        complete_json_detected = True
                    except (json.JSONDecodeError, ValueError):
                        complete_json_detected = False
            # Determine if we should return the tool call
            # Return tool call if:
            # 1. finish_reason is explicitly "tool_calls", OR
            # 2. We have a complete JSON in the arguments and we're not getting new argument data
            should_return_tool = finish_reason == "tool_calls" or (complete_json_detected and tool_call)

            # Generate response object with tool_call
            yield LLMResponse(
                reasoning=reasoning,
                content=content,
                tool_call=tool_call if should_return_tool else None,
                finish_reason=finish_reason or ("tool_calls" if should_return_tool else None),
            )
