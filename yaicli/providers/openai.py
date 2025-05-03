from typing import Any, Dict, Iterator, List, Optional
import json

from openai._client import OpenAI
from openai._exceptions import APIConnectionError, APIStatusError, RateLimitError
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta, ChatCompletionChunk

from json_repair import repair_json

from yaicli.const import EventTypeEnum
from yaicli.providers.base import BaseClient, LLMResponse, ToolCall
from yaicli.function import get_function_manager


class OpenAIClient(BaseClient):
    """OpenAI API client implementation using the official OpenAI Python library."""

    def __init__(self, config: Dict[str, Any], console, verbose: bool):
        """Initialize the OpenAI API client with configuration."""
        super().__init__(config, console, verbose)
        self.api_key = config["API_KEY"]
        self.model = config["MODEL"]
        self.base_url = config["BASE_URL"]

        # Initialize the OpenAI client with our custom configuration
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            default_headers={"X-Title": "Yaicli"},
            max_retries=2,  # Add retry logic for resilience
        )

    def _prepare_request_params(self, messages: List[Dict[str, str]], stream: bool) -> Dict[str, Any]:
        """Prepare the common request parameters for OpenAI API calls."""
        params = {
            "messages": messages,
            "model": self.model,
            "stream": stream,
            "temperature": self.config["TEMPERATURE"],
            "top_p": self.config["TOP_P"],
            # Openai: This value is now deprecated in favor of max_completion_tokens
            "max_tokens": self.config["MAX_TOKENS"],
            "max_completion_tokens": self.config["MAX_TOKENS"],
        }

        # Add tools if available and functions are enabled
        if self.tools and self.config["ENABLE_FUNCTIONS"]:
            # Get function specs from FunctionManager
            function_mgr = get_function_manager()
            params["tools"] = function_mgr.function_specs
            if self.verbose:
                self.console.print("Tools:", style="bold underline")
                for tool in params["tools"]:
                    self.console.print(
                        f"- {tool['function']['name']}: {tool['function']['description'].strip()}", style="yellow"
                    )
        elif self.tools and not self.config["ENABLE_FUNCTIONS"] and self.verbose:
            self.console.print("Functions are disabled in configuration", style="yellow")

        return params

    def _process_completion_response(self, completion: ChatCompletion) -> LLMResponse:
        """Process the response from a non-streamed OpenAI completion request."""
        content = None
        reasoning = None
        # tool_calls = None
        _id = name = arguments = ""
        choice = completion.choices[0]

        # Handle normal response
        content = choice.message.content

        # Check for reasoning in model_extra
        if hasattr(completion.choices[0].message, "model_extra") and completion.choices[0].message.model_extra:
            extra = completion.choices[0].message.model_extra
            if extra and "reasoning" in extra:
                reasoning = extra["reasoning"]

        # If no reasoning in model_extra, try extracting from <think> tags
        if reasoning is None and isinstance(completion.choices[0].message.content, str):
            content = completion.choices[0].message.content.lstrip()
            if content.startswith("<think>"):
                think_end = content.find("</think>")
                if think_end != -1:
                    reasoning = content[7:think_end].strip()  # Start after <think>
                    # Remove the <think> block from the main content
                    content = content[think_end + 8 :].strip()  # Start after </think>

        try:
            parsed_content = json.loads(content or "")
            if isinstance(parsed_content, dict):
                try:
                    choice = Choice.model_validate(parsed_content)
                except Exception:
                    pass
        except json.JSONDecodeError:
            pass
        # Handle tool calls if present
        if isinstance(choice, Choice):
            tool_calls = choice.delta.tool_calls
        else:
            tool_calls = choice.message.tool_calls
        if tool_calls:
            for tool_call in tool_calls:
                if tool_call.function and tool_call.function.name:
                    name = tool_call.function.name
                if tool_call.function and tool_call.function.arguments:
                    arguments += tool_call.function.arguments
                if tool_call.id:
                    _id = tool_call.id
            try:
                arguments = repair_json(arguments, ensure_ascii=False, return_objects=True)
            except json.JSONDecodeError:
                self.console.print(f"Invalid tool call arguments: {arguments}", style="red")
                return LLMResponse(content=None, reasoning=None)
            return LLMResponse(
                content=None,
                reasoning=None,
                tool_calls=[ToolCall(id=_id, name=name, arguments=arguments)],
            )
        return LLMResponse(content=content, reasoning=reasoning)

    def handle_tool_calls_response(
        self, messages: List[Dict[str, Any]], tool_calls: List[ToolCall]
    ) -> Optional[List[Dict[str, Any]]]:
        """Process LLM response containing tool calls

        Args:
            response: Original LLM response containing tool calls
            messages: Message history

        Returns:
            Final LLM response with tool call results
        """
        if not tool_calls:
            return None

        # Process tool calls
        try:
            results = self.process_tool_calls(tool_calls)
        except Exception as e:
            self.console.print(f"Error processing tool calls: {e}", style="red bold")
            if self.verbose:
                import traceback

                self.console.print(traceback.format_exc(), style="red")
            return None

        # Add tool calls and results to message history
        for i, result in enumerate(results):
            tool_call = tool_calls[i]
            # Add tool call message
            # messages.append(
            #     {
            #         "role": "tool",
            #         "content": None,
            #         "tool_calls": [
            #             {
            #                 "id": tool_call.id,
            #                 "function": {"name": tool_call.name, "arguments": json.dumps(tool_call.arguments)},
            #             }
            #         ],
            #     }
            # )

            # Add tool call result message
            result_content = json.dumps(result["result"]) if not isinstance(result["result"], str) else result["result"]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "content": result_content,
                }
            )
        return messages
        # try:
        #     # Get model's response to tool call results
        #     return self.completion(messages)
        # except Exception as e:
        #     self.console.print(f"Feedback function result error: {e}", style="red bold")
        #     if self.verbose:
        #         import traceback

        #         self.console.print(traceback.format_exc(), style="red")
        #     return LLMResponse(content=f"Feedback function result error: {str(e)}", reasoning=None)

    def completion(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """Get a complete non-streamed response from the OpenAI API."""
        params = self._prepare_request_params(messages, stream=False)

        try:
            # Use context manager for proper resource management
            response: ChatCompletion = self.client.chat.completions.create(**params)
            if self.verbose:
                self.console.print(f"Response: {response.to_dict()}")
            llm_response = self._process_completion_response(response)

            # Process tool calls
            if llm_response.tool_calls:
                self.console.print(f"Function calls detected: {llm_response.tool_calls}", style="bold blue")
                result = self.handle_tool_calls_response(messages, llm_response.tool_calls)
                if not result:
                    return LLMResponse(content=None, reasoning=None)
                else:
                    return self.completion(result)

            return llm_response
        except APIConnectionError as e:
            self.console.print(f"OpenAI connection error: {e}", style="red")
            if self.verbose:
                self.console.print(f"Underlying error: {e.__cause__}")
            return LLMResponse(content=None, reasoning=None)
        except RateLimitError as e:
            self.console.print(f"OpenAI rate limit error (429): {e}", style="red")
            return LLMResponse(content=None, reasoning=None)
        except APIStatusError as e:
            self.console.print(f"OpenAI API error (status {e.status_code}): {e}", style="red")
            if self.verbose:
                self.console.print(f"Response: {e.response}")
            return LLMResponse(content=None, reasoning=None)
        except Exception as e:
            self.console.print(f"Unexpected error during OpenAI completion: {e}", style="red")
            if self.verbose:
                import traceback

                traceback.print_exc()
            return LLMResponse(content=None, reasoning=None)

    def stream_completion(self, messages: List[Dict[str, str]]) -> Iterator[Dict[str, Any]]:
        """Connect to the OpenAI API and yield parsed stream events.

        Args:
            messages: The list of message dictionaries to send to the API

        Yields:
            Event dictionaries with the following structure:
                - type: The event type (from EventTypeEnum)
                - chunk/message/reason: The content of the event
                - tool_call: Tool call information if present
        """
        params: Dict[str, Any] = self._prepare_request_params(messages, stream=True)
        in_reasoning: bool = False

        try:
            # Use context manager to ensure proper cleanup
            with self.client.chat.completions.create(**params) as stream:
                for chunk in stream:
                    choices: List[Choice] = chunk.choices
                    if not choices:
                        # Some APIs may return empty choices upon reaching the end of content.
                        continue
                    choice: Choice = choices[0]
                    delta: ChoiceDelta = choice.delta
                    finish_reason: Optional[str] = choice.finish_reason

                    # Handle tool calls
                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        # Collect tool calls from this delta chunk
                        for idx, tool_call in enumerate(delta.tool_calls):
                            if hasattr(tool_call, "function") and tool_call.function:
                                if not tool_call.function.name:
                                    continue
                                tool_call_data = {
                                    "id": tool_call.id or f"tool_{idx}",
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments if tool_call.function.arguments else "{}",
                                }
                                # Store the tool call for later execution
                                # if not hasattr(self, "_pending_tool_calls"):
                                #     self._pending_tool_calls = {}

                                # # Accumulate arguments if they come in chunks
                                # if tool_call.id in self._pending_tool_calls:
                                #     # Update existing entry
                                #     existing_args = self._pending_tool_calls[tool_call.id].get("arguments", "{}")
                                #     if tool_call.function.arguments:
                                #         # Append new arguments if any
                                #         if existing_args == "{}":
                                #             self._pending_tool_calls[tool_call.id]["arguments"] = tool_call.function.arguments
                                #         else:
                                #             self._pending_tool_calls[tool_call.id]["arguments"] += tool_call.function.arguments

                                # Update name if provided
                                #     if tool_call.function.name:
                                #         self._pending_tool_calls[tool_call.id]["name"] = tool_call.function.name
                                # else:
                                #     # Add new entry
                                #     self._pending_tool_calls[tool_call.id] = tool_call_data

                                # Only yield for the first appearance of a tool call
                                yield {
                                    "type": EventTypeEnum.TOOL_CALL_START,
                                    "tool_call": tool_call_data,
                                }
                                # messages.append(delta)
                                result = self.process_tool_call(
                                    ToolCall(
                                        id=tool_call_data["id"],
                                        name=tool_call_data["name"],
                                        arguments=json.loads(tool_call_data["arguments"])
                                        if tool_call_data["arguments"]
                                        else {},
                                    )
                                )
                                yield {
                                    "type": EventTypeEnum.TOOL_RESULT,
                                    "result": result,
                                    "name": tool_call_data["name"],
                                }

                    # Process model_extra for reasoning content
                    if hasattr(delta, "model_extra") and delta.model_extra:
                        reasoning: Optional[str] = self._get_reasoning_content(delta.model_extra)
                        if reasoning:
                            yield {"type": EventTypeEnum.REASONING, "chunk": reasoning}
                            in_reasoning = True
                            continue

                    # Process content delta
                    if hasattr(delta, "content") and delta.content:
                        content_chunk = delta.content
                        if in_reasoning and content_chunk:
                            # Send reasoning end signal before content
                            in_reasoning = False
                            yield {"type": EventTypeEnum.REASONING_END, "chunk": ""}
                            yield {"type": EventTypeEnum.CONTENT, "chunk": content_chunk}
                        elif content_chunk:
                            yield {"type": EventTypeEnum.CONTENT, "chunk": content_chunk}

                    # Process finish reason
                    if finish_reason:
                        # Send reasoning end signal if still in reasoning state
                        if in_reasoning:
                            in_reasoning = False
                            yield {"type": EventTypeEnum.REASONING_END, "chunk": ""}

                        # Process tool call completion event
                        if finish_reason == "tool_calls":
                            if self.verbose:
                                self.console.print("Model requested tool execution", style="blue bold")

                            # Get all accumulated tool calls
                            # tool_calls_to_process = []
                            # if hasattr(self, "_pending_tool_calls"):
                            #     for tool_id, tool_call in self._pending_tool_calls.items():
                            #         tool_calls_to_process.append(tool_call)

                            #     # Clear pending tool calls
                            #     self._pending_tool_calls = {}

                            # if self.verbose and tool_calls_to_process:
                            #     self.console.print(f"Processing {len(tool_calls_to_process)} tool calls", style="blue")

                            # Process each tool call in sequence
                            # if tool_calls_to_process:
                            #     for tool_call in tool_calls_to_process:
                            #         yield from self.handle_streaming_tool_calls(messages, tool_call)
                            else:
                                yield {"type": EventTypeEnum.TOOL_CALLS_FINISH, "reason": finish_reason}
                        else:
                            yield {"type": EventTypeEnum.FINISH, "reason": finish_reason}

        except APIConnectionError as e:
            self.console.print(f"OpenAI connection error during streaming: {e}", style="red")
            if self.verbose:
                self.console.print(f"Underlying error: {e.__cause__}")
            yield {"type": EventTypeEnum.ERROR, "message": str(e)}
        except RateLimitError as e:
            self.console.print(f"OpenAI rate limit error (429) during streaming: {e}", style="red")
            yield {"type": EventTypeEnum.ERROR, "message": str(e)}
        except APIStatusError as e:
            self.console.print(f"OpenAI API error (status {e.status_code}) during streaming: {e}", style="red")
            if self.verbose:
                self.console.print(f"Response: {e.response}")
            yield {"type": EventTypeEnum.ERROR, "message": str(e)}
        except Exception as e:
            self.console.print(f"Unexpected error during OpenAI streaming: {e}", style="red")
            if self.verbose:
                import traceback

                traceback.print_exc()
            yield {"type": EventTypeEnum.ERROR, "message": f"Unexpected stream error: {e}"}

    def handle_streaming_tool_calls(
        self, messages: List[Dict[str, Any]], tool_call_data: Dict[str, str]
    ) -> Iterator[Dict[str, Any]]:
        """Handle streaming tool calls

        Args:
            messages: Message history
            tool_call_data: Tool call data

        Yields:
            Tool call processing progress and result events
        """
        try:
            # Parse tool call data
            tool_call_id = tool_call_data.get("id", "tool_1")
            name = tool_call_data.get("name", "")
            arguments = tool_call_data.get("arguments", "{}")

            # Create tool call object
            try:
                args_dict = json.loads(arguments)
                tool_call = ToolCall(id=tool_call_id, name=name, arguments=args_dict)
            except json.JSONDecodeError:
                yield {"type": EventTypeEnum.ERROR, "message": f"Invalid tool call arguments: {arguments}"}
                return

            # Execute tool call
            try:
                yield {"type": EventTypeEnum.TOOL_RESULT, "message": f"Executing tool call: {name}"}
                result = self.process_tool_call(tool_call)
                result_str = json.dumps(result) if not isinstance(result, str) else result

                # Add to message history
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": tool_call_id, "function": {"name": name, "arguments": arguments}}],
                    }
                )

                messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": result_str})

                # Send result event
                yield {"type": EventTypeEnum.TOOL_RESULT, "result": result_str, "name": name}

                # Continue getting LLM response to tool call results
                yield {"type": EventTypeEnum.CONTENT, "chunk": "\n\n"}
                for event in self.stream_completion(messages):
                    yield event

            except Exception as e:
                error_msg = f"Tool call execution error: {str(e)}"
                yield {"type": EventTypeEnum.ERROR, "message": error_msg}

                # Add error message to history
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": tool_call_id, "function": {"name": name, "arguments": arguments}}],
                    }
                )

                messages.append(
                    {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": f"Error: {str(e)}"}
                )

        except Exception as e:
            yield {"type": EventTypeEnum.ERROR, "message": f"Error processing tool call: {str(e)}"}
