import json
from typing import Generator, Union, overload

from openai._streaming import Stream
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice as ChoiceChunk

from ...schemas import LLMResponse, ToolCall
from ..tool_calls import ToolCallAccumulator
from .openai_provider import OpenAIProvider


class ChatglmProvider(OpenAIProvider):
    """Chatglm provider support"""

    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"

    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "do_sample": "DO_SAMPLE",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }

    def _handle_normal_response(self, response: ChatCompletion) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response
        Support both openai capabilities and chatglm

        Returns:
            LLMContent object with:
            - reasoning: The thinking/reasoning content (if any)
            - content: The normal response content
        """
        choice = response.choices[0]
        content = choice.message.content or ""  # type: ignore
        # HuggingFace's ChatCompletionOutputMessage (and plain OpenAI-schema ChatGLM
        # responses) may not expose reasoning_content at all, so never access it directly.
        reasoning = getattr(choice.message, "reasoning_content", None)
        finish_reason = choice.finish_reason

        # Check if the response contains reasoning content
        if "<think>" in content and "</think>" in content:
            # Extract reasoning content
            content = content.lstrip()
            if content.startswith("<think>"):
                think_end = content.find("</think>")
                if think_end != -1:
                    reasoning = content[7:think_end].strip()  # Start after <think>
                    # Remove the <think> block from the main content
                    content = content[think_end + 8 :].strip()  # Start after </think>
        # Check if the response contains reasoning content in model_extra
        elif hasattr(choice.message, "model_extra") and choice.message.model_extra:  # type: ignore
            model_extra = choice.message.model_extra  # type: ignore
            reasoning = self._get_reasoning_content(model_extra)
        # Collect every tool call (parallel tool use included); the legacy single
        # ``tool_call`` view is filled in by LLMResponse.__post_init__.
        tool_calls = []
        if finish_reason == "tool_calls":
            if '{"index":' in content or '"tool_calls":' in content:
                # Tool call data may in content after the <think> block
                # >/n{"index": 0, "tool_call_id": "call_1", "function": {"name": "name", "arguments": "{}"}, "output": null}
                tool_index = content.find('{"index":')
                if tool_index != -1:
                    tmp_content = content[tool_index:]
                    # Tool call data may in content after the <think> block
                    try:
                        choice = self.parse_choice_from_content(tmp_content, Choice)
                    except ValueError:
                        pass
            if hasattr(choice, "message") and hasattr(choice.message, "tool_calls") and choice.message.tool_calls:  # type: ignore
                for tool in choice.message.tool_calls:  # type: ignore
                    function = getattr(tool, "function", None)
                    tool_calls.append(
                        ToolCall(
                            getattr(tool, "id", "") or "",
                            (getattr(function, "name", None) if function else None) or "",
                            (getattr(function, "arguments", None) if function else None) or "",
                        )
                    )

        yield LLMResponse(reasoning=reasoning, content=content, finish_reason=finish_reason, tool_calls=tool_calls)

    def _handle_stream_response(self, response: Stream[ChatCompletionChunk]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response
        Support both openai capabilities and chatglm

        Tool-call fragments are accumulated per call (index/id/name) with the
        shared :class:`~yaicli.llms.tool_calls.ToolCallAccumulator`; complete calls
        are emitted once at the end of the stream. ChatGLM may also embed the tool
        call JSON in the content after a ``<think>`` block, which is parsed first.

        Returns:
            Generator yielding LLMContent objects with:
            - reasoning: The thinking/reasoning content (if any)
            - content: The normal response content
        """
        accumulator = ToolCallAccumulator()
        full_content = ""
        for chunk in response:
            # Check if the response contains reasoning content
            choice = chunk.choices[0]  # type: ignore
            delta = choice.delta
            finish_reason = choice.finish_reason

            # Concat content
            content = delta.content or ""
            full_content += content

            # Concat reasoning
            reasoning = self._get_reasoning_content(delta)

            if finish_reason == "tool_calls" or ('{"index":' in content or '"tool_calls":' in content):
                # Tool call data may in content after the <think> block
                # >/n{"index": 0, "tool_call_id": "call_1", "function": {"name": "name", "arguments": "{}"}, "output": null}
                tool_index = full_content.find('{"index":')
                if tool_index != -1:
                    tmp_content = full_content[tool_index:]
                    try:
                        choice = self.parse_choice_from_content(tmp_content, ChoiceChunk)
                    except ValueError:
                        pass

            # Accumulate every fragment of the (possibly content-parsed) delta.
            for position, tool in enumerate(getattr(choice.delta, "tool_calls", None) or []):  # type: ignore
                function = getattr(tool, "function", None)
                if function is None:
                    continue
                index = getattr(tool, "index", None)
                if not isinstance(index, int):
                    index = None
                accumulator.add_fragment(
                    index=index if index is not None else None,
                    call_id=getattr(tool, "id", None) or None,
                    name=getattr(function, "name", None) or None,
                    arguments=getattr(function, "arguments", None) or None,
                )
            yield LLMResponse(reasoning=reasoning, content=content, finish_reason=finish_reason)

        # Emit the complete tool calls once the stream is finished (never partial).
        tool_calls = accumulator.finalize()
        if tool_calls:
            yield LLMResponse(tool_calls=tool_calls, finish_reason="tool_calls")

    @overload
    def parse_choice_from_content(self, content: str, choice_class: type[ChoiceChunk] = ChoiceChunk) -> "ChoiceChunk":
        """
        Parse the choice from the content after <think>...</think> block.
        Args:
            content: The content from the LLM response
        Returns:
            The choice object
        Raises ValueError if the content is not valid JSON
        """

    @overload
    def parse_choice_from_content(self, content: str, choice_class: type[Choice] = Choice) -> "Choice":
        """
        Parse the choice from the content after <think>...</think> block.
        Args:
            content: The content from the LLM response
        Returns:
            The choice object
        Raises ValueError if the content is not valid JSON
        """

    def parse_choice_from_content(
        self, content: str, choice_class: type[Union[Choice, ChoiceChunk]] = Choice
    ) -> Union[Choice, ChoiceChunk]:
        """
        Parse the choice from the content after <think>...</think> block.
        Args:
            content: The content from the LLM response
        Returns:
            The choice object
        Raises ValueError if the content is not valid JSON
        """
        try:
            content_dict = json.loads(content)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid message from LLM: {content}")
        try:
            return choice_class.model_validate(content_dict)
        except Exception as e:
            raise ValueError(f"Invalid message from LLM: {content}") from e
