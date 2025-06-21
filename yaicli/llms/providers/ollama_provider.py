import json
import time
from typing import Any, Dict, Generator, List

import ollama

from ...config import cfg
from ...console import get_console
from ...schemas import ChatMessage, LLMResponse, ToolCall
from ...tools import get_openai_schemas
from ...utils import str2bool
from ..provider import Provider


class OllamaProvider(Provider):
    """Ollama provider implementation based on ollama Python library"""

    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        self.config = config
        self.enable_function = self.config.get("ENABLE_FUNCTIONS", False)
        self.verbose = verbose
        self.think = str2bool(self.config.get("THINK", False))

        # Initialize client params - Ollama host support
        self.host = self.config.get("BASE_URL") or self.DEFAULT_BASE_URL

        # Initialize console
        self.console = get_console()

        # Store completion params
        self.completion_params = {
            "model": self.config.get("MODEL", "llama3"),
            "temperature": self.config.get("TEMPERATURE", 0.7),
            "top_p": self.config.get("TOP_P", 1.0),
            "num_predict": self.config.get("MAX_TOKENS", 1024),
            "timeout": self.config.get("TIMEOUT", 10),
        }

        # Add extra body params if set
        if self.config.get("EXTRA_BODY"):
            self.completion_params.update(self.config["EXTRA_BODY"])

    def _convert_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Convert a list of ChatMessage objects to a list of Ollama message dicts."""
        converted_messages = []
        for msg in messages:
            message = {"role": msg.role, "content": msg.content or ""}

            if msg.name:
                message["name"] = msg.name

            # Handle tool calls - Ollama now supports the OpenAI format directly
            if msg.role == "assistant" and msg.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.loads(tc.arguments)},
                    }
                    for tc in msg.tool_calls
                ]

            # Handle tool responses - Ollama supports tool_call_id directly
            if msg.role == "tool" and msg.tool_call_id:
                message["tool_call_id"] = msg.tool_call_id

            converted_messages.append(message)

        return converted_messages

    def completion(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
    ) -> Generator[LLMResponse, None, None]:
        """Send messages to Ollama and get response"""
        # Convert message format
        ollama_messages = self._convert_messages(messages)
        if self.verbose:
            self.console.print("Messages:")
            self.console.print(ollama_messages)

        # Prepare parameters
        params = {
            "model": self.completion_params["model"],
            "messages": ollama_messages,
            "stream": stream,
            "think": self.think,
            "options": {
                "temperature": self.completion_params["temperature"],
                "top_p": self.completion_params["top_p"],
                "num_predict": self.completion_params["num_predict"],
                "timeout": self.completion_params["timeout"],
            },
        }

        # Add tools if enabled
        if self.enable_function:
            params["tools"] = get_openai_schemas()

        client = ollama.Client(host=self.host)
        if self.verbose:
            self.console.print("Ollama API params:")
            self.console.print(params)
        try:
            if stream:
                response_generator = client.chat(**params)
                yield from self._handle_stream_response(response_generator)
            else:
                response = client.chat(**params)
                yield from self._handle_normal_response(response)

        except Exception as e:
            self.console.print(f"Ollama API error: {e}", style="red")
            yield LLMResponse(content=f"Error calling Ollama API: {str(e)}")

    def _handle_normal_response(self, response: Dict[str, Any]) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response"""
        content = response.message.content or ""
        reasoning = response.message.thinking or ""

        # Check for tool calls in the response
        tool_call = None
        tool_calls = response.message.tool_calls or []

        if tool_calls and self.enable_function:
            # Get the first tool call
            tc = tool_calls[0]
            function_data = tc.get("function", {})

            # Create tool call with appropriate data type handling
            arguments = function_data.get("arguments", "")
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments)

            tool_call = ToolCall(
                id=tc.get("id", f"tc_{hash(function_data.get('name', ''))}_{int(time.time())}"),
                name=function_data.get("name", ""),
                arguments=arguments,
            )

        yield LLMResponse(content=content, reasoning=reasoning, tool_call=tool_call)

    def _handle_stream_response(self, response_generator) -> Generator[LLMResponse, None, None]:
        """Handle streaming response"""
        accumulated_content = ""
        tool_call = None

        for chunk in response_generator:
            # Extract content from the current chunk
            message = chunk.message
            content = message.content or ""
            reasoning = message.thinking or ""

            if content or reasoning:
                accumulated_content += content
                yield LLMResponse(content=content, reasoning=reasoning)

            # Check for tool calls in the chunk
            tool_calls = message.tool_calls or []
            if tool_calls and self.enable_function:
                # Only handle the first tool call for now
                tc = tool_calls[0]
                function_data = tc.get("function", {})

                # Create tool call with appropriate data type handling
                arguments = function_data.get("arguments", "")
                if isinstance(arguments, dict):
                    arguments = json.dumps(arguments)

                tool_call = ToolCall(
                    id=tc.get("id", None) or f"tc_{hash(function_data.get('name', ''))}_{int(time.time())}",
                    name=function_data.get("name", ""),
                    arguments=arguments,
                )

        # After streaming is complete, if we found a tool call, yield it
        if tool_call:
            yield LLMResponse(tool_call=tool_call)

    def detect_tool_role(self) -> str:
        """Return the role to be used for tool responses"""
        return "tool"
