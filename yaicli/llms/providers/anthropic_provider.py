import json
from os import getenv
from typing import Any, Dict, Generator, List, Optional, Tuple, cast

from anthropic import Anthropic, AnthropicBedrock, AnthropicVertex, Stream
from anthropic.types import InputJSONDelta, Message, TextDelta
from anthropic.types.raw_message_stream_event import RawMessageStreamEvent
from json_repair import repair_json

from ...config import cfg
from ...console import get_console
from ...exceptions import ConfigMissingError, MCPToolsError
from ...schemas import ChatMessage, LLMResponse, ToolCall
from ..provider import Provider


class AnthropicProvider(Provider):
    """Anthropic provider implementation based on anthropic library"""

    DEFAULT_BASE_URL = "https://api.anthropic.com"
    CLIENT_CLS = Anthropic
    # Base mapping between config keys and API parameter names
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

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        self.config = config
        if not self.config.get("API_KEY"):
            raise ValueError("API_KEY is required")
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        self.enable_mcp = self.config["ENABLE_MCP"]
        self.verbose = verbose

        # Initialize client
        self.client_params = self.get_client_params()
        self.client = self.CLIENT_CLS(**self.client_params)
        self.console = get_console()

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters"""
        # Initialize client params
        client_params = {
            "api_key": self.config["API_KEY"],
            "default_headers": {"X-Title": self.APP_NAME, "HTTP_Referer": self.APP_REFERER},
        }

        # Add base URL if configured
        if self.config.get("BASE_URL"):
            client_params["base_url"] = self.config["BASE_URL"]

        # Add extra headers if set
        if self.config.get("EXTRA_HEADERS"):
            client_params["default_headers"] = {**self.config["EXTRA_HEADERS"], **client_params["default_headers"]}

        # Add timeout if set
        if self.config.get("TIMEOUT"):
            client_params["timeout"] = self.config["TIMEOUT"]

        return client_params

    def get_completion_params_keys(self) -> Dict[str, str]:
        """
        Get the mapping between completion parameter keys and config keys.
        Subclasses can override this method to customize parameter mapping.

        Returns:
            Dict[str, str]: Mapping from API parameter names to config keys
        """
        return self.COMPLETION_PARAMS_KEYS.copy()

    def get_completion_params(self) -> Dict[str, Any]:
        """
        Get the completion parameters based on config and parameter mapping.

        Returns:
            Dict[str, Any]: Parameters for completion API call
        """
        completion_params = {}
        params_keys = self.get_completion_params_keys()
        for api_key, config_key in params_keys.items():
            if self.config.get(config_key, None) is not None and self.config[config_key] != "":
                completion_params[api_key] = self.config[config_key]
        return completion_params

    def completion(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
    ) -> Generator[LLMResponse, None, None]:
        """
        Send completion request to Anthropic and return responses.

        Args:
            messages: List of chat messages to send
            stream: Whether to stream the response

        Yields:
            LLMResponse: Response objects containing content, tool calls, etc.

        Raises:
            ValueError: If messages is empty or invalid
            anthropic.APIError: If API request fails
        """
        anthropic_messages = self._convert_messages(messages)

        params = self.get_completion_params()
        system_prompt, system_prompt_index = self._extract_system_prompt(messages)
        if system_prompt and system_prompt_index is not None:
            anthropic_messages.pop(system_prompt_index)
            params["system"] = system_prompt
        params["messages"] = anthropic_messages
        params["stream"] = stream

        # Add tools if enabled
        tools = []
        if self.enable_function:
            try:
                from ...tools import get_anthropic_schemas

                tools.extend(get_anthropic_schemas())
            except ImportError:
                self.console.print("Function tools not available for Anthropic", style="yellow")

        if self.enable_mcp:
            try:
                from ...tools import get_anthropic_mcp_tools

                mcp_tools = get_anthropic_mcp_tools()
                tools.extend(mcp_tools)
            except (ValueError, FileNotFoundError, MCPToolsError, ImportError) as e:
                self.console.print(f"Failed to load MCP tools: {e}", style="red")

        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        if self.verbose:
            self.console.print("System prompt:", params["system"])
            self.console.print("Messages:")
            self.console.print(params["messages"])
            if params.get("tools"):
                self.console.print("Tools:")
                self.console.print(params["tools"])
            self.console.print("Tool choice:", params["tool_choice"])
            if params.get("extra_body"):
                self.console.print("Extra body:")
                self.console.print(params["extra_body"])

        try:
            if stream:
                response = self.client.messages.create(**params)
                yield from self._handle_stream_response(response)
            else:
                response = self.client.messages.create(**params)
                yield from self._handle_normal_response(response)
        except Exception as e:
            self.console.print(f"Error: {e}", style="red")
            raise

    def _extract_system_prompt(self, messages: List[ChatMessage]) -> Tuple[Optional[str], Optional[int]]:
        """Extract system prompt from messages"""
        for index, message in enumerate(messages):
            if message.role == "system":
                return message.content, index
        return None, None

    def _handle_normal_response(self, response: Message) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response"""
        if not response.content:
            yield LLMResponse(content=json.dumps(response.model_dump()), finish_reason="stop")
            return

        # Extract text from content blocks
        text_content = ""
        for block in response.content:
            if block.type == "text" and hasattr(block, "text"):
                text_content += block.text

        # Get stop reason
        finish_reason = response.stop_reason or "stop"

        # Handle tool use
        tool_call: Optional[ToolCall] = None
        for block in response.content:
            if block.type == "tool_use":
                tool_call = ToolCall(id=getattr(block, "id", ""), name=block.name, arguments=json.dumps(block.input))
                break

        yield LLMResponse(content=text_content, finish_reason=finish_reason, tool_call=tool_call)

    def _handle_stream_response(self, response: Stream[RawMessageStreamEvent]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response from Anthropic API"""
        tool_call: Optional[ToolCall] = None
        tool_call_id = ""
        tool_call_name = ""
        tool_call_input = ""

        # Process each chunk in the response stream
        for chunk in response:
            # Handle different event types
            if chunk.type == "message_start":
                # Message start, no need to handle
                continue

            elif chunk.type == "content_block_start":
                # Content block start
                if hasattr(chunk, "content_block") and getattr(chunk.content_block, "type", "") == "tool_use":
                    # Tool call block - initialize tool call data
                    tool_data = chunk.content_block
                    tool_call_id = getattr(tool_data, "id", "")
                    tool_call_name = getattr(tool_data, "name", "")
                    tool_call_input = ""  # Will be built incrementally

            elif chunk.type == "content_block_delta":
                # Content delta update
                if hasattr(chunk, "delta"):
                    delta = chunk.delta

                    # Handle text delta
                    if hasattr(delta, "text"):
                        delta = cast(TextDelta, delta)
                        content = delta.text or ""
                        if content:
                            yield LLMResponse(content=content, tool_call=None)

                    # Handle tool call input delta
                    elif hasattr(delta, "partial_json"):
                        delta = cast(InputJSONDelta, delta)
                        tool_call_input += delta.partial_json or ""

            elif chunk.type == "content_block_stop":
                # Content block stop - finalize tool call if it exists
                if tool_call_id and tool_call_name:
                    tool_call = ToolCall(
                        id=tool_call_id,
                        name=tool_call_name,
                        arguments=repair_json(tool_call_input),
                    )
                    # Reset tool call data
                    tool_call_id = ""
                    tool_call_name = ""
                    tool_call_input = ""

            elif chunk.type == "message_delta":
                # Message delta update - contains stop reason
                if hasattr(chunk, "delta") and hasattr(chunk.delta, "stop_reason"):
                    finish_reason = chunk.delta.stop_reason
                    if finish_reason:
                        yield LLMResponse(content="", finish_reason=finish_reason, tool_call=tool_call)

            elif chunk.type == "message_stop":
                # Message stop - final response
                yield LLMResponse(content="", finish_reason="stop", tool_call=tool_call)

    def detect_tool_role(self) -> str:
        """Return the role that should be used for tool responses"""
        return "tool"


class AnthropicBedrockProvider(AnthropicProvider):
    """Anthropic Bedrock provider implementation based on anthropic library"""

    CLIENT_CLS = AnthropicBedrock
    CLIENT_PARAMS_KEY_ENV_MAP = {
        "AWS_SECRET_ACCESS_KEY": "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID": "AWS_ACCESS_KEY_ID",
        "AWS_SESSION_TOKEN": "AWS_SESSION_TOKEN",
        "AWS_REGION": "AWS_REGION",
    }

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters
        client = AnthropicBedrock(
            # Authenticate by either providing the keys below or use the default AWS credential providers, such as
            # using ~/.aws/credentials or the "AWS_SECRET_ACCESS_KEY" and "AWS_ACCESS_KEY_ID" environment variables.
            aws_access_key="<access key>",
            aws_secret_key="<secret key>",
            # Temporary credentials can be used with aws_session_token.
            # Read more at https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp.html.
            aws_session_token="<session_token>",
            # aws_region changes the aws region to which the request is made. By default, we read AWS_REGION,
            # and if that's not present, we default to us-east-1. Note that we do not read ~/.aws/config for the region.
            aws_region="us-west-2",
        )
        """
        client_params = super().get_client_params()
        for config_key, env_key in self.CLIENT_PARAMS_KEY_ENV_MAP.items():
            if not self.config.get(config_key):
                v = getenv(env_key)
                if not v:
                    raise ConfigMissingError(
                        f"{env_key} is required. Please set `{config_key}` in config or environment variable `{env_key}`"
                    )
                self.config[config_key] = v

        client_params["aws_access_key"] = self.config["AWS_ACCESS_KEY_ID"]
        client_params["aws_secret_key"] = self.config["AWS_SECRET_ACCESS_KEY"]
        client_params["aws_session_token"] = self.config["AWS_SESSION_TOKEN"]
        client_params["aws_region"] = self.config["AWS_REGION"]
        return client_params


class AnthropicVertexProvider(AnthropicProvider):
    """Anthropic Vertex provider implementation based on anthropic library"""

    CLIENT_CLS = AnthropicVertex
    CLIENT_PARAMS_KEY_ENV_MAP = {
        "PROJECT_ID": "PROJECT_ID",
        "CLOUD_ML_REGION": "CLOUD_ML_REGION",
    }

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters"""
        client_params = super().get_client_params()
        for config_key, env_key in self.CLIENT_PARAMS_KEY_ENV_MAP.items():
            if not self.config.get(config_key):
                v = getenv(env_key)
                if not v:
                    raise ConfigMissingError(
                        f"{env_key} is required. Please set `{config_key}` in config or environment variable `{env_key}`"
                    )
                self.config[config_key] = v
        client_params["project_id"] = self.config["PROJECT_ID"]
        client_params["region"] = self.config["CLOUD_ML_REGION"]
        return client_params
