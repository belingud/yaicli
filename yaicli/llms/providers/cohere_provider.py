"""
Cohere API provider implementation

This module implements Cohere provider classes for different deployment options:
- CohereProvider: Standard Cohere API
- CohereBadrockProvider: AWS Bedrock integration
- CohereSagemaker: AWS Sagemaker integration
"""

from typing import Any, Dict, Generator, List, Optional

from cohere import BedrockClientV2, ClientV2, SagemakerClientV2
from cohere.types.tool_call_v2 import ToolCallV2
from cohere.types.tool_call_v2function import ToolCallV2Function

from ...config import cfg
from ...console import get_console
from ...schemas import ChatMessage, LLMResponse, ToolCall
from ...tools import get_openai_schemas
from ..provider import Provider


class CohereProvider(Provider):
    """Cohere provider implementation based on cohere library"""

    DEFAULT_BASE_URL = "https://api.cohere.com/v2"
    CLIENT_CLS = ClientV2
    DEFAULT_MODEL = "command-a-03-2025"

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        """
        Initialize the Cohere provider

        Args:
            config: Configuration dictionary
            verbose: Whether to enable verbose logging
            **kwargs: Additional parameters passed to the client
        """
        self.config = config
        self.verbose = verbose
        self.client_params = {
            "api_key": self.config["API_KEY"],
            "timeout": self.config["TIMEOUT"],
        }
        if self.config.get("BASE_URL"):
            self.client_params["base_url"] = self.config["BASE_URL"]
        self.client = self.create_client()
        self.console = get_console()

    def create_client(self):
        """Create and return Cohere client instance"""
        if self.config.get("ENVIRONMENT"):
            self.client_params["environment"] = self.config["ENVIRONMENT"]
        return self.CLIENT_CLS(**self.client_params)

    def detect_tool_role(self) -> str:
        """Return the role name for tool response messages"""
        return "tool"

    def _convert_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """
        Convert a list of ChatMessage objects to a list of Cohere message dicts

        {
            "role": "tool",
            "tool_call_id": tc.id,
            "content": {
                "type": "document",
                "document": {"data": string},
            },
        }

        Args:
            messages: List of ChatMessage objects

        Returns:
            List of message dicts formatted for Cohere API
        """
        converted_messages = []
        for msg in messages:
            # Create base message
            message = {}

            # Set role always
            message["role"] = msg.role

            # Add tool calls for assistant messages
            if msg.role == "assistant" and msg.tool_calls:
                # {
                #     "role": "assistant",
                #     "tool_calls": response.message.tool_calls,
                #     "tool_plan": response.message.tool_plan,
                # }
                message["tool_calls"] = [
                    ToolCallV2(
                        id=tc.id,
                        type="function",
                        function=ToolCallV2Function(name=tc.name, arguments=tc.arguments),
                    )
                    for tc in msg.tool_calls
                ]
            else:
                # Add content for non-tool-call messages
                message["content"] = msg.content or ""

            # Add tool call ID for tool messages
            if msg.role == "tool" and msg.tool_call_id:
                message["tool_call_id"] = msg.tool_call_id

                # For tool messages, convert content to the expected document format
                if msg.content:
                    message["content"] = [{"type": "document", "document": {"data": msg.content}}]

            converted_messages.append(message)

        return converted_messages

    def _prepare_tools(self) -> Optional[List[Dict[str, Any]]]:
        """
        Prepare tools for Cohere API if enabled

        Returns:
            List of tool definitions or None if disabled
        """
        if not self.config.get("ENABLE_FUNCTIONS", False):
            return None

        tools = get_openai_schemas()
        if not tools and self.verbose:
            self.console.print("No tools available", style="yellow")
        return tools

    def _handle_streaming_response(self, response_stream) -> Generator[LLMResponse, None, None]:
        """
        Process streaming response from Cohere API

        doc: https://docs.cohere.com/v2/docs/streaming

        According to Cohere docs, there are multiple event types:
        - message-start: First event with metadata
        - content-start: Start of content block
        - content-delta: Chunk of generated text
        - content-end: End of content block
        - message-end: End of message
        - tool-plan-delta: Part of tool planning
        - tool-call-start: Start of tool call
        - tool-call-delta: Part of tool call
        - tool-call-end: End of tool call
        - citation-start/end: For citations in RAG

        Args:
            response_stream: Stream from Cohere client

        Yields:
            LLMResponse objects with content or tool calls
        """
        tool_call: Optional[ToolCall] = None
        for chunk in response_stream:
            if not chunk:
                continue

            # Handle different event types
            if chunk.type == "content-delta":
                # Text generation chunks
                content = chunk.delta.message.content.text or ""
                yield LLMResponse(content=content)

            elif chunk.type == "tool-plan-delta":
                # Tool planning - when model is deciding which tool to use: cohere.types.chat_tool_plan_delta_event_delta_message.ChatToolPlanDeltaEventDeltaMessage
                content = chunk.delta.message.tool_plan or ""
                yield LLMResponse(content=content)

            elif chunk.type == "tool-call-start":
                # Start of tool call
                tool_call_msg = chunk.delta.message.tool_calls
                tool_call = ToolCall(
                    id=tool_call_msg.id, name=tool_call_msg.function.name, arguments=tool_call_msg.function.arguments
                )
                # Tool call started, waiting for tool-calls-delta events
                continue
            elif chunk.type == "tool-call-delta":
                # Tool call arguments being generated: cohere.types.chat_tool_call_delta_event_delta_message.ChatToolCallDeltaEventDeltaMessage
                if not tool_call:
                    continue
                tool_call.arguments += chunk.delta.message.tool_calls.function.arguments or ""
                # Waiting for tool-call-end event
                continue

            elif chunk.type == "tool-call-end":
                # End of a tool call, empty chunk
                yield LLMResponse(tool_call=tool_call)

    def _handle_normal_response(self, response) -> Generator[LLMResponse, None, None]:
        """
        Process non-streaming response from Cohere API

        Args:
            response: Response from Cohere client

        Yields:
            LLMResponse objects with content or tool calls
        """
        # Handle content
        if response.message.content:
            for content_item in response.message.content:
                if hasattr(content_item, "text") and content_item.text:
                    yield LLMResponse(content=content_item.text)

        # Handle tool calls
        if response.message.tool_calls:
            yield LLMResponse(content=response.message.tool_plan)
            for tool_call in response.message.tool_calls:
                yield LLMResponse(
                    tool_call=ToolCall(
                        id=tool_call.id,
                        name=tool_call.function.name,
                        arguments=tool_call.function.arguments,
                    )
                )

    def completion(
        self, messages: List[ChatMessage], stream: bool = False, **kwargs
    ) -> Generator[LLMResponse, None, None]:
        """
        Get completion from Cohere models

        Args:
            messages: List of messages for the conversation
            stream: Whether to stream the response
            **kwargs: Additional parameters to pass to the Cohere client

        Yields:
            LLMResponse objects with content or tool calls
        """
        # Get configuration values
        model = self.config.get("MODEL", self.DEFAULT_MODEL)
        temperature = float(self.config.get("TEMPERATURE", 0.3))
        frequency_penalty = float(self.config.get("FREQUENCY_PENALTY", 0.0))
        # Prepare messages and tools
        cohere_messages = self._convert_messages(messages)
        if self.verbose:
            self.console.print("Messages:")
            self.console.print(cohere_messages)
        tools = self._prepare_tools()

        # Common request parameters
        request_params = {
            "model": model,
            "messages": cohere_messages,
            "temperature": temperature,
            "frequency_penalty": frequency_penalty,
            **kwargs,
        }

        # Add tools if available
        if tools:
            request_params["tools"] = tools

        # Apply exclude params filtering
        request_params = Provider.filter_excluded_params(
            request_params,
            self.config,
            verbose=self.verbose,
            console=self.console,
        )

        # Call Cohere API
        try:
            if stream:
                # Streaming mode
                response_stream = self.client.chat_stream(**request_params)
                yield from self._handle_streaming_response(response_stream)
            else:
                # Non-streaming mode
                response = self.client.chat(**request_params)
                yield from self._handle_normal_response(response)

        except Exception as e:
            error_msg = f"Error in Cohere API call: {e}"
            if self.verbose:
                import traceback

                self.console.print("Error in Cohere completion:")
                traceback.print_exc()
            yield LLMResponse(content=error_msg)


class CohereBadrockProvider(CohereProvider):
    """Cohere provider for AWS Bedrock integration"""

    CLIENT_CLS = BedrockClientV2
    DOC_URL = "https://docs.cohere.com/v2/docs/text-gen-quickstart"
    CLIENT_KEYS = (
        ("AWS_REGION", "aws_region"),
        ("AWS_ACCESS_KEY_ID", "aws_access_key"),
        ("AWS_SECRET_ACCESS_KEY", "aws_secret_key"),
        ("AWS_SESSION_TOKEN", "aws_session_token"),
    )

    def create_client(self):
        """Create Bedrock client with AWS credentials"""
        for k, p in self.CLIENT_KEYS:
            v = self.config.get(k, None)
            if v is None:
                raise ValueError(
                    f"You have to set key `{k}` to use {self.__class__.__name__}, see cohere doc `{self.DOC_URL}`"
                )
            self.client_params[p] = v
        return self.CLIENT_CLS(**self.client_params)


class CohereSagemakerProvider(CohereBadrockProvider):
    """Cohere provider for AWS Sagemaker integration"""

    CLIENT_CLS = SagemakerClientV2
