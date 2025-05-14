import json
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Union, cast

import litellm
from json_repair import repair_json
from litellm.types.utils import Choices
from litellm.types.utils import Message as ChoiceMessage
from litellm.types.utils import ModelResponse
from rich.panel import Panel

from .config import cfg
from .console import get_console
from .schemas import LLMResponse, ChatMessage, ToolCall
from .tools import (
    Function,
    FunctionName,
    get_function,
    get_openai_schemas,
    list_functions,
)

litellm.drop_params = True
console = get_console()


class RefreshLive:
    """Refresh live display"""


class StopLive:
    """Stop live display"""


@dataclass
class LitellmClient:
    """OpenAI provider implementation"""

    api_key: str = field(default_factory=lambda: cfg["API_KEY"])
    model: str = field(default_factory=lambda: f"{cfg['PROVIDER']}/{cfg['MODEL']}")
    base_url: Optional[str] = field(default_factory=lambda: cfg["BASE_URL"])
    timeout: int = field(default_factory=lambda: cfg["TIMEOUT"])

    verbose: bool = False

    def __post_init__(self) -> None:
        """Initialize OpenAI client"""
        self.pre_tool_call_id = None

    def _convert_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
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

    def _execute_tool_call(self, tool_call: ToolCall) -> tuple[str, bool]:
        """Call function and return result"""
        console.print(f"@Function call: {tool_call.name}({tool_call.arguments})", style="blue")

        # 1. Get function
        try:
            function = get_function(FunctionName(tool_call.name))
        except ValueError as e:
            error_msg = f"Function '{tool_call.name!r}' not exists: {e}"
            console.print(error_msg, style="red")
            return error_msg, False

        # 2. Parse function arguments
        try:
            arguments = repair_json(tool_call.arguments, return_objects=True)
            if not isinstance(arguments, dict):
                error_msg = f"Invalid arguments type: {arguments!r}, should be JSON object"
                console.print(error_msg, style="red")
                return error_msg, False
            arguments = cast(dict, arguments)
        except Exception as e:
            error_msg = f"Invalid arguments from llm: {e}\nRaw arguments: {tool_call.arguments!r}"
            console.print(error_msg, style="red")
            return error_msg, False

        # 3. execute function
        try:
            function_result = function.execute(**arguments)
            if cfg["SHOW_FUNCTION_OUTPUT"]:
                panel = Panel(
                    function_result,
                    title="Function output",
                    title_align="left",
                    expand=False,
                    border_style="blue",
                    style="dim",
                )
                console.print(panel)
            return function_result, True
        except Exception as e:
            error_msg = f"Call function error: {e}\nFunction name: {tool_call.name!r}\nArguments: {arguments!r}"
            console.print(error_msg, style="red")
            return error_msg, False

    def completion(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
        recursion_depth: int = 0,
    ) -> Generator[Union[LLMResponse, RefreshLive], None, None]:
        """Send message to OpenAI with a maximum recursion depth of 5"""
        if self.verbose:
            console.print(messages)
        openai_messages = self._convert_messages(messages)

        # Prepare request parameters
        params: Dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": cfg["TEMPERATURE"],
            "top_p": cfg["TOP_P"],
            "stream": stream,
            # Openai: This value is now deprecated in favor of max_completion_tokens.
            "max_tokens": cfg["MAX_TOKENS"],
            "max_completion_tokens": cfg["MAX_TOKENS"],
            # litellm api params
            "api_key": self.api_key,
            "base_url": self.base_url,
            "reasoning_effort": cfg["REASONING_EFFORT"],
        }

        # Add optional parameters
        if cfg["ENABLE_FUNCTIONS"]:
            params["tools"] = self._convert_functions(list_functions())
            params["tool_choice"] = "auto"
            params["parallel_tool_calls"] = False
        # Send request
        response = litellm.completion(**params)
        if stream:
            response = cast(litellm.CustomStreamWrapper, response)
            llm_content_generator = self._handle_stream_response(response)
        else:
            response = cast(ModelResponse, response)
            llm_content_generator = self._handle_normal_response(response)
        for llm_content in llm_content_generator:
            yield llm_content
            if llm_content.tool_call:
                if not self.pre_tool_call_id:
                    self.pre_tool_call_id = llm_content.tool_call.id
                elif self.pre_tool_call_id == llm_content.tool_call.id:
                    continue
                # Let live display know we are in next run
                yield RefreshLive()

                # execute function call
                function_result, _ = self._execute_tool_call(llm_content.tool_call)

                # add function call result
                messages.append(
                    ChatMessage(
                        role=self.detect_tool_role(cfg["PROVIDER"]),
                        content=function_result,
                        name=llm_content.tool_call.name,
                        tool_call_id=llm_content.tool_call.id,
                    )
                )
                # Check if we've exceeded the maximum recursion depth
                if recursion_depth >= 5:
                    console.print("Maximum recursion depth (5) reached, stopping further tool calls", style="yellow")
                    return

                # Continue with recursion if within limits
                if stream:
                    yield from self.completion(messages, stream=stream, recursion_depth=recursion_depth + 1)
                else:
                    yield from self.completion(messages, stream=stream, recursion_depth=recursion_depth + 1)
                # yield StopLive()

    def stream_completion(self, messages: List[ChatMessage], stream: bool = True) -> Generator[LLMResponse, None, None]:
        openai_messages = self._convert_messages(messages)
        params: Dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": cfg["TEMPERATURE"],
            "top_p": cfg["TOP_P"],
            "stream": stream,
            # Openai: This value is now deprecated in favor of max_completion_tokens.
            "max_tokens": cfg["MAX_TOKENS"],
            "max_completion_tokens": cfg["MAX_TOKENS"],
            # litellm api params
            "api_key": self.api_key,
            "base_url": self.base_url,
        }
        # Add optional parameters
        if cfg["ENABLE_FUNCTIONS"]:
            params["tools"] = self._convert_functions(list_functions())
            params["tool_choice"] = "auto"
            params["parallel_tool_calls"] = False

        # Send request
        response = litellm.completion(**params)
        response = cast(litellm.CustomStreamWrapper, response)
        llm_content_generator = self._handle_stream_response(response)
        for llm_content in llm_content_generator:
            yield llm_content
            if llm_content.tool_call:
                if not self.pre_tool_call_id:
                    self.pre_tool_call_id = llm_content.tool_call.id
                elif self.pre_tool_call_id == llm_content.tool_call.id:
                    continue

                # execute function
                function_result, _ = self._execute_tool_call(llm_content.tool_call)

                # add function call result
                messages.append(
                    ChatMessage(
                        role=self.detect_tool_role(cfg["PROVIDER"]),
                        content=function_result,
                        name=llm_content.tool_call.name,
                        tool_call_id=llm_content.tool_call.id,
                    )
                )

                yield from self.stream_completion(messages)

    def _handle_normal_response(self, response: ModelResponse) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response

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

    def _handle_stream_response(self, response: litellm.CustomStreamWrapper) -> Generator[LLMResponse, None, None]:
        """Handle streaming response

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

    def _get_reasoning_content(self, delta: Any) -> Optional[str]:
        """Extract reasoning content from delta if available based on specific keys.

        This method checks for various keys that might contain reasoning content
        in different API implementations.

        Args:
            delta: The delta/model_extra from the API response

        Returns:
            The reasoning content string if found, None otherwise
        """
        if not delta:
            return None
        # Reasoning content keys from API:
        # reasoning_content: deepseek/infi-ai
        # reasoning: openrouter
        # <think> block implementation not in here
        for key in ("reasoning_content", "reasoning"):
            # Check if the key exists and its value is a non-empty string
            if hasattr(delta, key):
                return getattr(delta, key)

        return None  # Return None if no relevant key with a string value is found

    def parse_choice_from_content(self, content: str) -> Choices:
        """
        Parse the choice from the content after <think>...</think> block.
        Args:
            content: The content from the LLM response
            choice_cls: The class to use to parse the choice
        Returns:
            The choice object
        Raises ValueError if the content is not valid JSON
        """
        try:
            content_dict = json.loads(content)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid message from LLM: {content}")
        if "delta" in content_dict:
            try:
                content_dict["delta"] = ChoiceMessage.model_validate(content_dict["delta"])
            except Exception as e:
                raise ValueError(f"Invalid message from LLM: {content}") from e
        try:
            return Choices.model_validate(content_dict)
        except Exception as e:
            raise ValueError(f"Invalid message from LLM: {content}") from e

    def detect_tool_role(self, provider: str) -> str:
        """Detect the role of the tool call"""
        if provider == "gemini":
            return "user"
        else:
            return "tool"
