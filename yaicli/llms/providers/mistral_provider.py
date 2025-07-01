import json
from typing import Any, Dict, Generator, List, Optional, Union

from mistralai import Mistral
from mistralai.models import ChatCompletionResponse, CompletionEvent, ContentChunk
from mistralai.models import ToolCall as MistralToolCall
from mistralai.utils.eventstreaming import EventStream

from ...config import cfg
from ...console import get_console
from ...exceptions import MCPToolsError
from ...schemas import ChatMessage, LLMResponse, ToolCall
from ...tools import get_openai_mcp_tools, get_openai_schemas
from ...utils import gen_tool_call_id
from ..provider import Provider


class MistralProvider(Provider):
    """Mistral provider implementation based on mistralai library"""

    CLIENT_CLS = Mistral
    DEFAULT_BASE_URL = "https://api.mistral.ai/v1"

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        """Initialize Mistral provider

        Args:
            config: Configuration dictionary
            verbose: Whether to enable verbose logging
        """
        self.config = config
        self.verbose = verbose
        self.enable_functions = config["ENABLE_FUNCTIONS"]
        self.enable_mcp = config["ENABLE_MCP"]
        self.client = Mistral(**self.get_client_params())
        self.console = get_console()


    def get_client_params(self) -> Dict[str, Any]:
        """Get client parameters for Mistral

        Returns:
            Dict[str, Any]
        """
        client_params = {
            "api_key": self.config["API_KEY"],
            "timeout_ms": self.config["TIMEOUT"] * 1000,  # Mistral uses milliseconds
        }
        if self.config["BASE_URL"]:
            client_params["server_url"] = self.config["BASE_URL"]
        if self.config.get("SERVER"):
            client_params["server"] = self.config["SERVER"]
        return client_params

    def get_completion_params(self) -> Dict[str, Any]:
        """Get completion parameters for Mistral

        Returns:
            Dict[str, Any]
        """
        params = {
            "model": self.config["MODEL"],
            "temperature": self.config["TEMPERATURE"],
            "top_p": self.config["TOP_P"],
            "max_tokens": self.config["MAX_TOKENS"],
            "stream": self.config["STREAM"],
            "http_headers": {
                "X-Title": self.APP_NAME,
                "HTTP_Referer": self.APP_REFERER,
            },
        }
        if self.config["EXTRA_HEADERS"]:
            params["http_headers"] = {**self.config["EXTRA_HEADERS"], **params["http_headers"]}
        tools = []
        if self.enable_functions:
            tools.extend(get_openai_schemas())
        if self.enable_mcp:
            try:
                tools.extend(get_openai_mcp_tools())
            except MCPToolsError as e:
                self.console.print(e, style="red")
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"
            params["parallel_tool_calls"] = False
        return params

    def completion(self, messages: List[ChatMessage], stream: bool = False) -> Generator[LLMResponse, None, None]:
        """Completion method for Mistral

        Args:
            messages: List of ChatMessage
            stream: Whether to stream the response
        """
        # Convert messages to Mistral format
        mistral_messages = self._convert_messages(messages)
        if self.verbose:
            self.console.print("Messages:")
            self.console.print(mistral_messages)

        params = self.get_completion_params()
        params["messages"] = mistral_messages

        if stream:
            response = self.client.chat.stream(**params)
            yield from self._handle_stream_response(response)
        else:
            response = self.client.chat.complete(**params)
            yield from self._handle_normal_response(response)

    def _handle_normal_response(self, response: ChatCompletionResponse) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response"""
        if not response.choices or not response.choices[0].message:
            content = response.model_dump_json()
            yield LLMResponse(content=content, finish_reason="stop")
            return

        choice = response.choices[0]
        finish_reason = choice.finish_reason
        content = self.get_content_from_delta_content(choice.message.content) if choice.message.content else ""
        tool_call: Optional[ToolCall] = None

        # Handle tool calls if present
        if finish_reason == "tool_calls":
            tool_call = self._process_tool_call_chunk(choice.message.tool_calls or [])

        yield LLMResponse(content=content, finish_reason=finish_reason, tool_call=tool_call)

    def _handle_stream_response(self, response: EventStream[CompletionEvent]) -> Generator[LLMResponse, None, None]:
        """Handle stream response"""
        tool_call: Optional[ToolCall] = None

        for chunk in response:
            choice = chunk.data.choices[0]
            finish_reason = choice.finish_reason
            delta_content = choice.delta.content
            delta = choice.delta
            content = ""

            if delta_content:
                content = self.get_content_from_delta_content(delta_content)

            # Process tool call information
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                tool_call = self._process_tool_call_chunk(delta.tool_calls, tool_call)

            yield LLMResponse(
                content=content,
                finish_reason=finish_reason,
                tool_call=tool_call if finish_reason == "tool_calls" else None,
            )

    def _process_tool_call_chunk(
        self, tool_calls: List[MistralToolCall], existing_tool_call: Optional[ToolCall] = None
    ) -> Optional[ToolCall]:
        """Process tool call data from a response chunk"""
        # Initialize tool call object if this is the first chunk with tool call data
        if existing_tool_call is None and tool_calls:
            tool = tool_calls[0]
            existing_tool_call = ToolCall(tool.id or gen_tool_call_id(), tool.function.name, "")

        # Accumulate arguments from multiple chunks
        if existing_tool_call:
            for tool in tool_calls:
                if not tool.function:
                    continue
                # Ensure arguments is a string
                tool_args = tool.function.arguments
                if not isinstance(tool_args, str):
                    tool_args = json.dumps(tool_args)
                existing_tool_call.arguments += tool_args

        return existing_tool_call

    def get_content_from_delta_content(self, delta_content: Union[str, List[ContentChunk]]) -> str:
        """Get content from a delta content

        If the delta content is a string, it will be returned as is.
        If the delta content is a list of ContentChunk, it will be converted to a string.
        Args:
            delta_content: Union[str, List[ContentChunk]]
        Returns:
            str
        """
        if isinstance(delta_content, str):
            return delta_content
        return self.extract_contents_list(delta_content)

    def extract_contents_list(self, delta_content: List[ContentChunk]) -> str:
        """Extract content from a list of ContentChunk

        If the content is a list of ContentChunk, it will be converted to a string.
        Args:
            delta_content: List[ContentChunk]
        Returns:
            str
        """
        content = ""
        for i in delta_content:
            if i.type == "text":
                content += i.text
            elif i.type == "image_url":
                content += i.image_url if isinstance(i.image_url, str) else i.image_url.url
            elif i.type == "document_url":
                content += f"[{i.document_name}]({i.document_url})"
            elif i.type == "reference":
                content += "Reference IDs: " + json.dumps(i.reference_ids)
        return content

    def detect_tool_role(self) -> str:
        return "tool"
