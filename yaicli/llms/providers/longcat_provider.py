import json
import re
import uuid
from typing import Any, Dict, Generator, Optional

from ...schemas import LLMResponse, ToolCall
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider


def _clean_longcat_reasoning(reasoning: str) -> str:
    """
    Remove LongCat tool call tags from reasoning/content.

    Args:
        reasoning: The reasoning/content that may contain a tool call

    Returns:
        Cleaned reasoning/content without tool call tags
    """
    if not reasoning:
        return reasoning

    # Pattern to match and remove the LongCat tool call format
    pattern = r"<longcat_tool_call>.*?</longcat_tool_call>"
    return re.sub(pattern, "", reasoning, flags=re.DOTALL).strip()


def _parse_and_clean_longcat_content(
    content: str, response_id: Optional[str] = None, verbose: bool = False, console=None
) -> tuple[Optional[ToolCall], str]:
    """
    Parse LongCat-specific tool call format and return both the tool call and cleaned content.

    The format is:
    <longcat_tool_call>function_name
    <longcat_arg_key>key1</longcat_arg_key>
    <longcat_arg_value>value1</longcat_arg_value>
    <longcat_arg_key>key2</longcat_arg_key>
    <longcat_arg_value>value2</longcat_arg_value>
    ...
    </longcat_tool_call>

    Args:
        content: The reasoning/content that may contain a tool call
        response_id: Optional response ID to use for tool call ID
        verbose: Whether to print verbose logging
        console: Console object for verbose output

    Returns:
        Tuple of (ToolCall or None, cleaned_content)
    """
    if not content:
        return None, content

    # Pattern to match the LongCat tool call format with multiple arguments
    pattern = r"<longcat_tool_call>(\w+)(.*?)</longcat_tool_call>"

    match = re.search(pattern, content, re.DOTALL)
    if match:
        function_name = match.group(1)
        args_section = match.group(2)

        # Parse all key-value pairs
        args_pattern = r"<longcat_arg_key>(\w+)</longcat_arg_key>\s*<longcat_arg_value>(.*?)</longcat_arg_value>"
        args_matches = re.findall(args_pattern, args_section, re.DOTALL)

        if args_matches:
            # Build arguments dictionary
            arguments_dict = {}
            for arg_key, arg_value in args_matches:
                arguments_dict[arg_key] = arg_value.strip()

            # Print verbose message
            if verbose and console:
                console.print(f"[LongCat] Extracted tool call: {function_name}")

            # Build JSON arguments string
            arguments = json.dumps(arguments_dict)

            # Use response.id if available, otherwise generate UUID
            tool_call_id = response_id if response_id else f"longcat_{uuid.uuid4().hex[:8]}"

            tool_call = ToolCall(id=tool_call_id, name=function_name, arguments=arguments)
            cleaned_content = _clean_longcat_reasoning(content)

            return tool_call, cleaned_content

    return None, content


class LongCatProvider(OpenAIProvider):
    """LongCat provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.longcat.chat/openai"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }

    def _handle_normal_response(self, response) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response with LongCat tool call parsing"""
        # First get the standard response handling
        for std_response in super()._handle_normal_response(response):
            # Check if there's a tool call hidden in reasoning when finish_reason is "stop"
            if std_response.finish_reason == "stop" and std_response.reasoning:
                # Get response.id if available
                response_id = getattr(response, "id", None)
                tool_call, cleaned_reasoning = _parse_and_clean_longcat_content(
                    std_response.reasoning, response_id, self.verbose, self.console
                )
                if tool_call:
                    yield LLMResponse(
                        reasoning=cleaned_reasoning,
                        content=std_response.content,
                        finish_reason="tool_calls",
                        tool_call=tool_call,
                    )
                else:
                    yield std_response
            else:
                yield std_response

    def _handle_stream_response(self, response) -> Generator[LLMResponse, None, None]:
        """Handle streaming response with LongCat tool call parsing"""
        # Accumulate reasoning content to check for tool calls
        accumulated_reasoning = ""
        tool_call = None
        cleaned_reasoning = ""
        response_id = getattr(response, "id", None)

        for chunk_response in super()._handle_stream_response(response):
            # Accumulate reasoning content
            if chunk_response.reasoning:
                accumulated_reasoning += chunk_response.reasoning

            # If we haven't found a tool call yet and we're accumulating reasoning
            if tool_call is None and accumulated_reasoning:
                tool_call, cleaned_reasoning = _parse_and_clean_longcat_content(
                    accumulated_reasoning, response_id, self.verbose, self.console
                )

            # If finish_reason is "stop" and we found a tool call in reasoning
            if chunk_response.finish_reason == "stop" and tool_call:
                yield LLMResponse(
                    reasoning=cleaned_reasoning,
                    content=chunk_response.content,
                    finish_reason="tool_calls",
                    tool_call=tool_call,
                )
            # If finish_reason is "tool_calls" from standard handling
            elif chunk_response.finish_reason == "tool_calls":
                yield chunk_response
            # Otherwise yield as-is
            else:
                yield LLMResponse(
                    reasoning=chunk_response.reasoning,
                    content=chunk_response.content,
                    finish_reason=chunk_response.finish_reason,
                    tool_call=None,
                )


class LongCatAnthropicProvider(AnthropicProvider):
    """LongCat provider implementation based on Anthropic-compatible API"""

    DEFAULT_BASE_URL = "https://api.longcat.chat/anthropic"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "top_k": "TOP_K",
        "stop_sequences": "STOP_SEQUENCES",
        "metadata": "METADATA",
        "extra_body": "EXTRA_BODY",
    }

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters with Bearer token in Authorization header"""
        client_params = {
            "api_key": self.config["API_KEY"],
            "base_url": self.config.get("BASE_URL") or self.DEFAULT_BASE_URL,
            "default_headers": {
                "Authorization": f"Bearer {self.config['API_KEY']}",
                "X-Title": self.APP_NAME,
                "HTTP_Referer": self.APP_REFERER,
            },
        }

        # Add extra headers if set
        if self.config.get("EXTRA_HEADERS"):
            client_params["default_headers"] = {
                **self.config["EXTRA_HEADERS"],
                **client_params["default_headers"],
            }

        # Add timeout if set
        if self.config.get("TIMEOUT"):
            client_params["timeout"] = self.config["TIMEOUT"]

        return client_params

    def _handle_normal_response(self, response) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response with LongCat tool call parsing"""
        # First get the standard response handling
        for std_response in super()._handle_normal_response(response):
            # If parent already found tool_calls, yield as-is
            if std_response.finish_reason == "tool_use" and std_response.tool_call:
                yield std_response
            # Check if there's a tool call hidden in reasoning when finish_reason is "end_turn"
            elif std_response.finish_reason == "end_turn":
                # Get response.id if available
                response_id = getattr(response, "id", None)

                # Check reasoning field first (for OpenAI-compatible)
                if std_response.reasoning:
                    tool_call, cleaned_reasoning = _parse_and_clean_longcat_content(
                        std_response.reasoning, response_id, self.verbose, self.console
                    )
                    if tool_call:
                        yield LLMResponse(
                            reasoning=cleaned_reasoning,
                            content=std_response.content,
                            finish_reason="tool_use",
                            tool_call=tool_call,
                        )
                        return

                # Check content field (for Anthropic-compatible)
                if std_response.content:
                    tool_call, cleaned_content = _parse_and_clean_longcat_content(
                        std_response.content, response_id, self.verbose, self.console
                    )
                    if tool_call:
                        yield LLMResponse(
                            reasoning=std_response.reasoning,
                            content=cleaned_content,
                            finish_reason="tool_use",
                            tool_call=tool_call,
                        )
                        return

                # No tool call found, yield original response
                yield std_response
            else:
                yield std_response

    def _handle_stream_response(self, response) -> Generator[LLMResponse, None, None]:
        """Handle streaming response with LongCat tool call parsing"""
        # Accumulate content to check for tool calls
        accumulated_content = ""
        tool_call = None
        cleaned_content = ""
        response_id = getattr(response, "id", None)

        for chunk_response in super()._handle_stream_response(response):
            # Accumulate content
            if chunk_response.content:
                accumulated_content += chunk_response.content

            # If we haven't found a tool call yet and we're accumulating content
            if tool_call is None and accumulated_content:
                tool_call, cleaned_content = _parse_and_clean_longcat_content(
                    accumulated_content, response_id, self.verbose, self.console
                )

            # If finish_reason is "stop" and we found a tool call in content
            if chunk_response.finish_reason == "stop" and tool_call:
                yield LLMResponse(
                    content=cleaned_content,
                    finish_reason="tool_use",
                    tool_call=tool_call,
                )
            # If finish_reason is "tool_calls" from standard handling
            elif chunk_response.finish_reason == "tool_use":
                yield chunk_response
            # Otherwise yield as-is
            else:
                yield LLMResponse(
                    content=chunk_response.content,
                    finish_reason=chunk_response.finish_reason,
                    tool_call=None,
                )
