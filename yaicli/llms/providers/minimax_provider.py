from typing import Any, Dict, Generator, List, Optional

from openai._streaming import Stream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ...schemas import ChatMessage, LLMResponse, ToolPolicy
from ..tool_calls import ToolCallAccumulator
from .openai_provider import OpenAIProvider


class MinimaxProvider(OpenAIProvider):
    """Minimax provider implementation with Interleaved Thinking support"""

    DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }

    def get_completion_params(self, tool_policy: Optional[ToolPolicy] = None) -> Dict[str, Any]:
        """Get completion params with reasoning_split enabled by default."""
        params = super().get_completion_params(tool_policy=tool_policy)

        # Ensure extra_body exists and enable reasoning_split
        extra_body = params.get("extra_body", {}) or {}
        if isinstance(extra_body, dict):
            # Only set if not explicitly configured
            if "reasoning_split" not in extra_body:
                reasoning_split = self.config.get("MINIMAX_REASONING_SPLIT", True)
                extra_body["reasoning_split"] = reasoning_split
            params["extra_body"] = extra_body

        return params

    def _convert_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Convert messages with MiniMax-specific reasoning_details format."""
        converted_messages = []
        for msg in messages:
            message: Dict[str, Any] = {"role": msg.role, "content": msg.content or ""}

            if msg.name:
                message["name"] = msg.name

            if msg.role == "assistant" and msg.tool_calls:
                message["tool_calls"] = [
                    {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in msg.tool_calls
                ]

            if msg.role == "tool" and msg.tool_call_id:
                message["tool_call_id"] = msg.tool_call_id

            # MiniMax specific: Convert reasoning to reasoning_details format
            if msg.role == "assistant" and msg.reasoning:
                message["reasoning_details"] = [
                    {
                        "type": "reasoning.text",
                        "text": msg.reasoning,
                    }
                ]

            converted_messages.append(message)

        return converted_messages

    def _get_reasoning_content(self, delta: Any) -> Optional[str]:
        """Extract reasoning content from MiniMax response.

        MiniMax returns reasoning in reasoning_details field when reasoning_split=True.
        """
        if not delta:
            return None
        if not isinstance(delta, dict):
            delta = dict(delta)

        # Check for reasoning_details (MiniMax specific format)
        reasoning_details = delta.get("reasoning_details")
        if reasoning_details and isinstance(reasoning_details, list):
            # Extract text from all reasoning blocks
            texts = []
            for detail in reasoning_details:
                if isinstance(detail, dict) and "text" in detail:
                    texts.append(detail["text"])
            if texts:
                return "".join(texts)

        # Fallback to parent implementation for other formats
        return super()._get_reasoning_content(delta)

    def _handle_stream_response(self, response: Stream[ChatCompletionChunk]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response with MiniMax reasoning_details support.

        Tool-call fragments are accumulated with the shared
        :class:`~yaicli.llms.tool_calls.ToolCallAccumulator` so parallel calls are
        all retained (the old single-slot accumulation dropped every call but one)
        and complete calls are emitted once, at ``finish_reason == "tool_calls"``.
        """
        accumulator = ToolCallAccumulator()
        started = False

        for chunk in response:
            if not chunk.choices and not started:
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

            content = delta.content or ""

            # Extract reasoning from model_extra (where reasoning_details lives)
            model_extra = getattr(delta, "model_extra", None) or {}
            reasoning = self._get_reasoning_content(model_extra)

            for position, tool in enumerate(getattr(delta, "tool_calls", None) or []):
                function = getattr(tool, "function", None)
                if function is None:
                    continue
                index = getattr(tool, "index", None)
                if not isinstance(index, int):
                    index = position if len(delta.tool_calls) > 1 else None
                accumulator.add_fragment(
                    index=index,
                    call_id=getattr(tool, "id", None) or None,
                    name=getattr(function, "name", None) or None,
                    arguments=getattr(function, "arguments", None) or None,
                )

            yield LLMResponse(
                reasoning=reasoning,
                content=content,
                tool_calls=accumulator.finalize() if finish_reason == "tool_calls" else [],
                finish_reason=finish_reason,
            )
