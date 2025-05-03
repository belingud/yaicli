from typing import Any, Dict, Iterator, List, Literal, TypeVar
import json

from cohere import ChatResponse, ClientV2, StreamedChatResponseV2
from cohere.core.api_error import ApiError

from yaicli.const import EventTypeEnum
from yaicli.providers.base import BaseClient, LLMResponse, ToolCall
from yaicli.function import get_function_manager

ChunkType = Literal[
    "message-start",
    "content-start",
    "content-delta",
    "content-end",
    "tool-plan-delta",
    "tool-call-start",
    "tool-call-delta",
    "tool-call-end",
    "citation-start",
    "citation-end",
    "message-end",
    "debug",
]

# Type variable for chunks that have delta attribute
T = TypeVar("T", bound=StreamedChatResponseV2)


class CohereClient(BaseClient):
    """Cohere API client implementation using the official Cohere Python library."""

    def __init__(self, config: Dict[str, Any], console, verbose: bool):
        """Initialize the Cohere API client with configuration."""
        super().__init__(config, console, verbose)
        self.api_key = config["API_KEY"]
        self.model = config["MODEL"]
        if not config["BASE_URL"] or "cohere" not in config["BASE_URL"]:
            # BASE_URL can be empty, in which case we use the default base_url
            self.base_url = "https://api.cohere.com"
        else:
            self.base_url = config["BASE_URL"]
        self.base_url = self.base_url.rstrip("/")
        if self.base_url.endswith("v2") or self.base_url.endswith("v1"):
            self.base_url = self.base_url[:-2]

        # Initialize the Cohere client with our custom configuration
        self.client = ClientV2(
            api_key=self.api_key,
            base_url=self.base_url,
            client_name="Yaicli",
            timeout=self.timeout,
        )

    def _prepare_request_params(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Prepare the common request parameters for Cohere API calls."""
        # P value must be between 0.01 and 0.99, default to 0.75 if outside this range, also cohere api default is 0.75
        p = 0.75 if not (0.01 < self.config["TOP_P"] < 0.99) else self.config["TOP_P"]
        params = {
            "messages": messages,
            "model": self.model,
            "temperature": self.config["TEMPERATURE"],
            "max_tokens": self.config["MAX_TOKENS"],
            "p": p,
        }

        # Add tools if available and functions are enabled
        if self.tools and self.config.get("ENABLE_FUNCTIONS", True):
            function_mgr = get_function_manager()
            # Convert to Cohere tools format
            tools = []
            for tool_spec in function_mgr.function_specs:
                if tool_spec["type"] == "function" and "function" in tool_spec:
                    function_info = tool_spec["function"]
                    tool = {
                        "name": function_info["name"],
                        "description": function_info.get("description", ""),
                        "parameter_definitions": function_info.get("parameters", {}),
                    }
                    tools.append(tool)

            if tools:
                params["tools"] = tools

            if self.verbose:
                self.console.print("Tools:", style="bold underline")
                for tool in tools:
                    self.console.print(f"- {tool['name']}: {tool['description'].strip()}", style="yellow")
        elif self.tools and not self.config.get("ENABLE_FUNCTIONS", True) and self.verbose:
            self.console.print("Functions are disabled in configuration", style="yellow")

        return params

    def _process_completion_response(self, response: ChatResponse) -> LLMResponse:
        """Process the response from a non-streamed Cohere completion request."""
        try:
            # Check for tool calls
            if hasattr(response.message, "tool_calls") and response.message.tool_calls:
                tool_calls = []
                for tool_call in response.message.tool_calls:
                    try:
                        # 正确访问function属性
                        if hasattr(tool_call, "function") and tool_call.function:
                            arguments_str = (
                                tool_call.function.arguments if hasattr(tool_call.function, "arguments") else None
                            )
                            if arguments_str:
                                arguments = json.loads(arguments_str)
                            else:
                                arguments = {}
                            tool_calls.append(
                                {
                                    "id": tool_call.id if hasattr(tool_call, "id") else f"tool_{len(tool_calls)}",
                                    "name": tool_call.function.name if hasattr(tool_call.function, "name") else "",
                                    "arguments": arguments,
                                }
                            )
                    except Exception as e:
                        self.console.print(f"Error parsing tool call: {e}", style="red")

                if tool_calls:
                    return LLMResponse(
                        content=None, reasoning=None, tool_calls=[ToolCall(**call) for call in tool_calls]
                    )

            # Process regular content
            content = response.message.content
            if not content:
                return LLMResponse(content=None, reasoning=None)
            text = content[0].text
            if not text:
                return LLMResponse(content=None, reasoning=None)
            return LLMResponse(content=text, reasoning=None)

        except Exception as e:
            self.console.print(f"Error processing Cohere response: {e}", style="red")
            if self.verbose:
                self.console.print(f"Response: {response}")
            return LLMResponse(content=None, reasoning=None)

    def handle_tool_calls_response(self, response: LLMResponse, messages: List[Dict[str, Any]]) -> LLMResponse:
        """Process LLM response containing tool calls

        Args:
            response: Original LLM response containing tool calls
            messages: Message history

        Returns:
            Final LLM response with tool call results
        """
        if not response.tool_calls:
            return response

        # Process tool calls
        try:
            results = self.process_tool_calls(response.tool_calls)

            # Add tool calls and results to message history
            for i, result in enumerate(results):
                tool_call = response.tool_calls[i]
                # Add assistant's tool call message (Cohere format)
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "function": {"name": tool_call.name, "arguments": json.dumps(tool_call.arguments)},
                            }
                        ],
                    }
                )

                # Add tool call result message
                if result["status"] == "success":
                    result_content = (
                        json.dumps(result["result"]) if not isinstance(result["result"], str) else result["result"]
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result_content,
                        }
                    )
                else:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": f"Error: {result['error']}",
                        }
                    )

            # Get model's response to tool call results
            return self.completion(messages)
        except Exception as e:
            self.console.print(f"Error processing tool calls: {e}", style="red bold")
            if self.verbose:
                import traceback

                self.console.print(traceback.format_exc(), style="red")
            return LLMResponse(content=f"Tool call processing failed: {str(e)}", reasoning=None)

    def completion(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """Get a complete non-streamed response from the Cohere API."""
        params = self._prepare_request_params(messages)

        try:
            response: ChatResponse = self.client.chat(**params)
            llm_response = self._process_completion_response(response)

            # 处理工具调用
            if llm_response.tool_calls:
                return self.handle_tool_calls_response(llm_response, messages)

            return llm_response
        except ApiError as e:
            self.console.print(f"Cohere API error: {e}", style="red")
            if self.verbose:
                self.console.print(f"Response: {e.body}")
            return LLMResponse(content=None, reasoning=None)

    def stream_completion(self, messages: List[Dict[str, str]]) -> Iterator[Dict[str, Any]]:
        """Connect to the Cohere API and yield parsed stream events."""
        params = self._prepare_request_params(messages)

        try:
            for chunk in self.client.v2.chat_stream(**params):
                # Handle tool calls
                if chunk.type in ("tool-call-start", "tool-call-delta", "tool-call-end"):  # type: ignore
                    if chunk.type == "tool-call-start" and hasattr(chunk, "tool_call"):  # type: ignore
                        tool_call = getattr(chunk, "tool_call")
                        if hasattr(tool_call, "function"):
                            function = getattr(tool_call, "function")
                            if hasattr(function, "name") and hasattr(function, "arguments"):
                                tool_call_data = {
                                    "id": getattr(tool_call, "id", "tool_1"),
                                    "name": getattr(function, "name", ""),
                                    "arguments": getattr(function, "arguments", ""),
                                }

                                # Store the tool call for later execution
                                if not hasattr(self, "_pending_tool_calls"):
                                    self._pending_tool_calls = {}

                                # Add or update tool call info
                                tool_id = tool_call_data["id"]
                                if tool_id in self._pending_tool_calls:
                                    # Update existing entry with new info
                                    if tool_call_data["name"]:
                                        self._pending_tool_calls[tool_id]["name"] = tool_call_data["name"]
                                    if tool_call_data["arguments"]:
                                        existing_args = self._pending_tool_calls[tool_id].get("arguments", "")
                                        if existing_args:
                                            self._pending_tool_calls[tool_id]["arguments"] += tool_call_data[
                                                "arguments"
                                            ]
                                        else:
                                            self._pending_tool_calls[tool_id]["arguments"] = tool_call_data["arguments"]
                                else:
                                    # Add new entry
                                    self._pending_tool_calls[tool_id] = tool_call_data

                                yield {
                                    "type": EventTypeEnum.TOOL_CALL_START,
                                    "tool_call": tool_call_data,
                                }
                    continue

                # Skip message start/end events
                if chunk.type in ("message-start", "message-end", "content-end"):  # type: ignore
                    continue

                # Safe attribute checking - skip if any required attribute is missing
                if not hasattr(chunk, "delta"):
                    continue

                # At this point we know chunk has delta attribute
                delta = getattr(chunk, "delta")
                if delta is None or not hasattr(delta, "message"):
                    continue

                message = getattr(delta, "message")
                if message is None or not hasattr(message, "content"):
                    continue

                content = getattr(message, "content")
                if content is None or not hasattr(content, "text"):
                    continue

                # Access text safely
                text = getattr(content, "text")
                if text:
                    yield {"type": EventTypeEnum.CONTENT, "chunk": text}

                # Check for tool call completion events
                if hasattr(chunk, "event_type") and getattr(chunk, "event_type") == "tool-call-end":
                    if self.verbose:
                        self.console.print("Model requested tool execution", style="blue")
                    yield {"type": EventTypeEnum.TOOL_CALLS_FINISH, "reason": "tool_calls"}

                    # Get all accumulated tool calls
                    tool_calls_to_process = []
                    if hasattr(self, "_pending_tool_calls"):
                        for tool_id, tool_call in self._pending_tool_calls.items():
                            tool_calls_to_process.append(tool_call)

                        # Clear pending tool calls
                        self._pending_tool_calls = {}

                    if self.verbose and tool_calls_to_process:
                        self.console.print(f"Processing {len(tool_calls_to_process)} tool calls", style="blue")

                    # Process each tool call in sequence
                    if tool_calls_to_process:
                        for tool_call in tool_calls_to_process:
                            yield from self.handle_streaming_tool_calls(messages, tool_call)

        except ApiError as e:
            self.console.print(f"Cohere API error during streaming: {e}", style="red")
            yield {"type": EventTypeEnum.ERROR, "message": str(e)}
        except Exception as e:
            self.console.print(f"Unexpected error during Cohere streaming: {e}", style="red")
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
