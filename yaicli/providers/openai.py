from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

from json_repair import repair_json

from openai._client import OpenAI
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ..config import cfg
from ..providers.base import ToolCall, LLMContent, LLMProvider, Message
from ..role import Role
from ..tools import Function, FunctionName, get_function, get_openai_schemas, list_functions
from ..console import get_console
from ..const import EventTypeEnum

console = get_console()


@dataclass
class OpenAIProvider(LLMProvider):
    """OpenAI provider implementation"""

    def __post_init__(self) -> None:
        """Initialize OpenAI client"""
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )
        self.pre_tool_call_id = None

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert message format to OpenAI API required format"""
        openai_messages = []
        for msg in messages:
            if msg.tool_call_id:
                openai_messages.append(
                    {"role": msg.role, "content": msg.content, "tool_call_id": msg.tool_call_id, "name": msg.name}
                )
            else:
                openai_messages.append({"role": msg.role, "content": msg.content})
        return openai_messages

    def _convert_functions(self, _: List[Function]) -> List[Dict[str, Any]]:
        """Convert function format to OpenAI API required format"""
        return get_openai_schemas()

    def completion(
        self,
        messages: List[Message],
        role: Role,
        stream: bool = False,
    ) -> Generator[LLMContent, None, None]:
        """Send message to OpenAI"""
        openai_messages = self._convert_messages(messages)

        # Prepare request parameters
        params: Dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": role.temperature,
            "top_p": role.top_p,
            "stream": stream,
            # Openai: This value is now deprecated in favor of max_completion_tokens.
            "max_tokens": cfg["MAX_TOKENS"],
            "max_completion_tokens": cfg["MAX_TOKENS"],
        }

        # Add optional parameters
        if cfg["ENABLE_FUNCTIONS"]:
            params["tools"] = self._convert_functions(list_functions())
            params["tool_choice"] = "auto"
            params["parallel_tool_calls"] = False
        # Send request
        if stream:
            llm_content_generator = self._handle_stream_response(self.client.chat.completions.create(**params))
        else:
            llm_content_generator = self._handle_normal_response(self.client.chat.completions.create(**params))
        # llm_content = self._handle_normal_response(self.client.chat.completions.create(**params))
        for llm_content in llm_content_generator:
            yield llm_content
            if llm_content.tool_call:
                if not self.pre_tool_call_id:
                    self.pre_tool_call_id = llm_content.tool_call.id
                elif self.pre_tool_call_id == llm_content.tool_call.id:
                    continue
                # If the response contains a tool call, execute the function
                function = get_function(FunctionName(llm_content.tool_call.name))
                if function is None:
                    raise ValueError(f"Function {llm_content.tool_call.name} not found")
                arguments = repair_json(llm_content.tool_call.arguments, return_objects=True)
                function_result = function.execute(**dict(arguments))  # type: ignore
                # Add the function result to the messages
                messages.append(
                    Message(
                        role="tool",
                        content=function_result,
                        name=llm_content.tool_call.name,
                        tool_call_id=llm_content.tool_call.id,
                    )
                )
                if stream:
                    yield from self.stream_completion(messages, role, stream=stream)
                else:
                    yield from self.completion(messages, role, stream=stream)

    def stream_completion(
        self, messages: List[Message], role: Role, stream: bool = True
    ) -> Generator[LLMContent, None, None]:
        openai_messages = self._convert_messages(messages)
        params: Dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": role.temperature,
            "top_p": role.top_p,
            "stream": stream,
            # Openai: This value is now deprecated in favor of max_completion_tokens.
            "max_tokens": cfg["MAX_TOKENS"],
            "max_completion_tokens": cfg["MAX_TOKENS"],
        }
        # Add optional parameters
        if cfg["ENABLE_FUNCTIONS"]:
            params["tools"] = self._convert_functions(list_functions())
            params["tool_choice"] = "auto"
            params["parallel_tool_calls"] = False
        llm_content_generator = self._handle_stream_response(self.client.chat.completions.create(**params))
        for llm_content in llm_content_generator:
            yield llm_content
            if llm_content.tool_call:
                if not self.pre_tool_call_id:
                    self.pre_tool_call_id = llm_content.tool_call.id
                elif self.pre_tool_call_id == llm_content.tool_call.id:
                    continue
                # If the response contains a tool call, execute the function
                function = get_function(FunctionName(llm_content.tool_call.name))
                if function is None:
                    raise ValueError(f"Function {llm_content.tool_call.name} not found")
                arguments = repair_json(llm_content.tool_call.arguments, return_objects=True)
                function_result = function.execute(**dict(arguments))  # type: ignore
                # Add the function result to the messages
                messages.append(
                    Message(
                        role="tool",
                        content=function_result,
                        name=llm_content.tool_call.name,
                        tool_call_id=llm_content.tool_call.id,
                    )
                )
                yield from self.stream_completion(messages, role, stream=stream)

    def _handle_normal_response(self, response: ChatCompletion) -> Generator[LLMContent, None, None]:
        """Handle normal (non-streaming) response

        Yields:
            LLMContent objects with event types
        """
        choice = response.choices[0]
        full_content = choice.message.content or ""
        reasoning = None
        content = ""
        finish_reason = choice.finish_reason
        tool_call: Optional[ToolCall] = None

        # Check for reasoning in model_extra first
        if hasattr(choice.message, "model_extra") and choice.message.model_extra:
            model_extra = choice.message.model_extra
            reasoning_from_extra = self._get_reasoning_content(model_extra)
            if reasoning_from_extra:
                yield LLMContent(event_type=EventTypeEnum.REASONING, content=reasoning_from_extra, finish_reason=finish_reason)
                # If reasoning is from extra, the rest of full_content is actual content
                content = full_content
            else: # No reasoning in extra, parse content for think tags
                content = full_content # Process full_content for think tags below
        else: # No model_extra, parse content for think tags
            content = full_content

        # Process content for <think> tags if not already handled by model_extra
        if not reasoning and "<think>" in content and "</think>" in content:
            processed_content = content.lstrip()
            if processed_content.startswith("<think>"):
                think_end = processed_content.find("</think>")
                if think_end != -1:
                    reasoning_text = processed_content[7:think_end].strip()
                    yield LLMContent(event_type=EventTypeEnum.REASONING, content=reasoning_text, finish_reason=finish_reason)
                    yield LLMContent(event_type=EventTypeEnum.REASONING_END, finish_reason=finish_reason)
                    content = processed_content[think_end + 8 :].strip()
                else: # Malformed think tag
                    content = processed_content # Treat as normal content
            else: # Think tags are present but not at the start, treat as normal content for now
                content = processed_content
        elif not reasoning : # No <think> tags and no reasoning from extra
             content = full_content


        if content:
            yield LLMContent(event_type=EventTypeEnum.CONTENT, content=content, finish_reason=finish_reason)

        if hasattr(choice, "message") and hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
            tool = choice.message.tool_calls[0]
            tool_call_obj = ToolCall(tool.id, tool.function.name, tool.function.arguments)
            # Yield a specific event for tool call if needed, or bundle with content
            # For now, it's part of the last content event or a new one if no content
            if content: # If there was preceding content, tool_call is part of that LLMContent
                 # This might override previous yield if content was the last thing.
                 # It's better to yield a new event for tool_call if it's meant to be separate.
                 # Let's assume tool_call is associated with the last yielded content/reasoning event for now.
                 # Or, more cleanly, yield a dedicated event if tool_call exists.
                yield LLMContent(event_type=EventTypeEnum.CONTENT, content="", tool_call=tool_call_obj, finish_reason=finish_reason)
            else: # No preceding content, tool_call is its own event
                yield LLMContent(event_type=EventTypeEnum.CONTENT, content="", tool_call=tool_call_obj, finish_reason=finish_reason)
        elif finish_reason and not content and not reasoning: # Ensure a finish event if nothing else was yielded
            yield LLMContent(event_type=EventTypeEnum.FINISH, finish_reason=finish_reason)


    def _handle_stream_response(
        self, response: Generator[ChatCompletionChunk, None, None]
    ) -> Generator[LLMContent, None, None]:
        """Handle streaming response

        Yields:
            Generator yielding LLMContent objects with event types
        """
        tool_id = ""
        tool_call_name = ""
        arguments = ""
        in_think_block = False # Manage <think> block state

        for chunk in response:
            choice = chunk.choices[0]
            delta_content = choice.delta.content or ""
            finish_reason = choice.finish_reason
            tool_call_chunks = choice.delta.tool_calls

            # Handle reasoning from model_extra (e.g. OpenRouter)
            if hasattr(choice.delta, "model_extra") and choice.delta.model_extra:
                model_extra = choice.delta.model_extra
                reasoning_text = self._get_reasoning_content(model_extra)
                if reasoning_text:
                    yield LLMContent(event_type=EventTypeEnum.REASONING, content=reasoning_text)
                    continue # Move to next chunk

            # Handle <think> tags in delta_content
            # This part needs careful handling for streaming
            temp_content = delta_content
            while temp_content:
                if not in_think_block:
                    think_start_index = temp_content.find("<think>")
                    if think_start_index != -1:
                        # Yield content before <think>
                        if think_start_index > 0:
                            yield LLMContent(event_type=EventTypeEnum.CONTENT, content=temp_content[:think_start_index])
                        # Yield reasoning start and content within <think>
                        temp_content = temp_content[think_start_index + 7:]
                        in_think_block = True
                        # Continue to find </think> or more reasoning content in the same chunk
                    else: # No <think> tag, yield as content
                        yield LLMContent(event_type=EventTypeEnum.CONTENT, content=temp_content)
                        temp_content = "" # Consumed
                else: # Inside a <think> block
                    think_end_index = temp_content.find("</think>")
                    if think_end_index != -1:
                        # Yield reasoning content before </think>
                        if think_end_index > 0:
                            yield LLMContent(event_type=EventTypeEnum.REASONING, content=temp_content[:think_end_index])
                        yield LLMContent(event_type=EventTypeEnum.REASONING_END)
                        temp_content = temp_content[think_end_index + 8:]
                        in_think_block = False
                        # Continue to process rest of temp_content in the same chunk
                    else: # No </think> tag, yield as reasoning
                        yield LLMContent(event_type=EventTypeEnum.REASONING, content=temp_content)
                        temp_content = "" # Consumed

            if tool_call_chunks:
                for tool_call_chunk in tool_call_chunks:
                    if tool_call_chunk.id:
                        tool_id = tool_call_chunk.id
                    if tool_call_chunk.function:
                        if tool_call_chunk.function.name:
                            tool_call_name = tool_call_chunk.function.name
                        if tool_call_chunk.function.arguments:
                            arguments += tool_call_chunk.function.arguments
                # Potentially yield delta tool calls, or accumulate and yield at the end / when finish_reason is tool_calls
                # For simplicity, we accumulate and will yield a single ToolCall object later.
                # However, a more robust solution might yield TOOL_CALL_DELTA events.

            if finish_reason:
                if tool_id and tool_call_name and arguments: # If accumulated tool call parts exist
                    tool_call_obj = ToolCall(tool_id, tool_call_name, arguments)
                    yield LLMContent(event_type=EventTypeEnum.TOOL_CALL_END, tool_call=tool_call_obj, finish_reason=finish_reason)
                    # Reset for next potential tool call
                    tool_id, tool_call_name, arguments = "", "", ""
                else: # General finish reason
                    yield LLMContent(event_type=EventTypeEnum.FINISH, finish_reason=finish_reason)
                if in_think_block: # If stream ends while still in think block
                    yield LLMContent(event_type=EventTypeEnum.REASONING_END)
                    in_think_block = False
