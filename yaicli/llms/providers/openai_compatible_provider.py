from __future__ import annotations

import json
from typing import TYPE_CHECKING, Generator

from ...schemas import LLMResponse
from ...usage import usage_from_openai
from ..tool_calls import ToolCallAccumulator
from .openai_provider import OpenAIProvider

if TYPE_CHECKING:  # pragma: no cover - typing only; the lite transport avoids the SDK
    from openai._streaming import Stream
    from openai.types.chat.chat_completion_chunk import ChatCompletionChunk


class OpenAICompatibleProvider(OpenAIProvider):
    @staticmethod
    def _arguments_complete(arguments: str) -> bool:
        """True when the accumulated argument text parses as complete JSON."""
        try:
            json.loads(arguments)
        except (json.JSONDecodeError, TypeError, ValueError):
            return False
        return True

    def _handle_stream_response(self, response: Stream[ChatCompletionChunk]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response from a generic OpenAI-compatible endpoint.

        Tool-call fragments are accumulated with the shared
        :class:`~yaicli.llms.tool_calls.ToolCallAccumulator`, which supports
        parallel calls (the previous single-slot code mixed their arguments).
        Every accumulated call is emitted when:

        1. ``finish_reason == "tool_calls"`` (standard protocol), or
        2. its arguments parse as complete JSON — some proxies never send a
           finish reason, so a call must not be held back forever.

        A call is only emitted once (tracked by id); calls already emitted are
        not re-yielded when a later finish reason arrives. Usage from
        ``stream_options={"include_usage": True}`` is captured from the (possibly
        choices-less) final chunk and attached to a terminal response.
        """
        accumulator = ToolCallAccumulator()
        emitted_ids: set = set()
        pending_usage = None
        started = False

        # Process each chunk in the response stream
        for chunk in response:
            chunk_usage = usage_from_openai(chunk)
            if chunk_usage is not None:
                pending_usage = chunk_usage
            if not chunk.choices and not started:
                # Some api could return error message in the first chunk, no choices to handle
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
                    call_id=getattr(tool, "id", None),
                    name=getattr(function, "name", None),
                    arguments=getattr(function, "arguments", None),
                )

            # Decide which calls are complete and not emitted yet.
            calls = accumulator.finalize()
            if finish_reason == "tool_calls":
                pending = [call for call in calls if call.id not in emitted_ids]
            else:
                pending = [
                    call
                    for call in calls
                    if call.id not in emitted_ids and call.name and self._arguments_complete(call.arguments)
                ]

            if pending:
                emitted_ids.update(call.id for call in pending)
                yield LLMResponse(
                    reasoning=reasoning,
                    content=content,
                    tool_calls=pending,
                    finish_reason=finish_reason or "tool_calls",
                )
                continue

            # Generate response object without tool calls
            yield LLMResponse(
                reasoning=reasoning,
                content=content,
                finish_reason=finish_reason,
            )

        if pending_usage is not None:
            # Terminal usage-only response: empty content, no tool call.
            yield LLMResponse(usage=pending_usage)
