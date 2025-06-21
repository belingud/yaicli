import json
from typing import Generator, Optional

from openai._streaming import Stream
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ...schemas import LLMResponse, ToolCall
from .openai_provider import OpenAIProvider


class ChatglmProvider(OpenAIProvider):
    """Chatglm provider support"""

    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"

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
        reasoning = choice.message.reasoning_content  # type: ignore
        finish_reason = choice.finish_reason
        tool_call: Optional[ToolCall] = None

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
        if finish_reason == "tool_calls":
            if '{"index":' in content or '"tool_calls":' in content:
                # Tool call data may in content after the <think> block
                # >/n{"index": 0, "tool_call_id": "call_1", "function": {"name": "name", "arguments": "{}"}, "output": null}
                tool_index = content.find('{"index":')
                if tool_index != -1:
                    tmp_content = content[tool_index:]
                    # Tool call data may in content after the <think> block
                    try:
                        choice = self.parse_choice_from_content(tmp_content)
                    except ValueError:
                        pass
            if hasattr(choice, "message") and hasattr(choice.message, "tool_calls") and choice.message.tool_calls:  # type: ignore
                tool = choice.message.tool_calls[0]  # type: ignore
                tool_call = ToolCall(tool.id, tool.function.name or "", tool.function.arguments)

        yield LLMResponse(reasoning=reasoning, content=content, finish_reason=finish_reason, tool_call=tool_call)

    def _handle_stream_response(self, response: Stream[ChatCompletionChunk]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response
        Support both openai capabilities and chatglm

        Returns:
            Generator yielding LLMContent objects with:
            - reasoning: The thinking/reasoning content (if any)
            - content: The normal response content
        """
        full_reasoning = ""
        full_content = ""
        content = ""
        reasoning = ""
        tool_id = ""
        tool_call_name = ""
        arguments = ""
        tool_call: Optional[ToolCall] = None
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
            full_reasoning += reasoning or ""

            if finish_reason:
                pass
            if finish_reason == "tool_calls" or ('{"index":' in content or '"tool_calls":' in content):
                # Tool call data may in content after the <think> block
                # >/n{"index": 0, "tool_call_id": "call_1", "function": {"name": "name", "arguments": "{}"}, "output": null}
                tool_index = full_content.find('{"index":')
                if tool_index != -1:
                    tmp_content = full_content[tool_index:]
                    try:
                        choice = self.parse_choice_from_content(tmp_content)
                    except ValueError:
                        pass
            if hasattr(choice.delta, "tool_calls") and choice.delta.tool_calls:  # type: ignore
                # Handle tool calls
                tool_id = choice.delta.tool_calls[0].id or ""  # type: ignore
                for tool in choice.delta.tool_calls:  # type: ignore
                    if not tool.function:
                        continue
                    tool_call_name = tool.function.name or ""
                    arguments += tool.function.arguments or ""
                tool_call = ToolCall(tool_id, tool_call_name, arguments)
            yield LLMResponse(reasoning=reasoning, content=content, tool_call=tool_call, finish_reason=finish_reason)

    def parse_choice_from_content(self, content: str) -> "Choice":
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
            return Choice.model_validate(content_dict)
        except Exception as e:
            raise ValueError(f"Invalid message from LLM: {content}") from e
