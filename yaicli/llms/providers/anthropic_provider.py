import importlib
import json
from os import getenv
from typing import Any, Dict, Generator, List, Optional, Tuple, cast

from anthropic import Anthropic, AnthropicBedrock, AnthropicVertex, Stream
from anthropic.types import InputJSONDelta, Message, TextDelta
from anthropic.types.raw_message_stream_event import RawMessageStreamEvent
from json_repair import repair_json

from ...config import cfg
from ...console import get_console
from ...errors import provider_response_error, wrap_provider_exception
from ...exceptions import ConfigMissingError, MCPToolsError
from ...schemas import ChatMessage, LLMResponse, ToolCall, ToolPolicy
from ...usage import Usage, usage_from_anthropic
from ...utils import str2bool
from ..provider import Provider
from ..tool_calls import ToolCallAccumulator


def _require_optional_dependency(module_name: str, extra: str) -> None:
    """Fail fast when an Anthropic cloud SDK extra is missing (K09).

    ``boto3``/``google.auth`` are only installed through ``yaicli[bedrock]`` /
    ``yaicli[vertex]``; without this check the SDK fails later with a confusing
    request-time error instead of telling the user which extra to install.
    """
    try:
        importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - depends on installed extras
        label = "Bedrock" if extra == "bedrock" else "Vertex"
        raise ImportError(
            f"Anthropic {label} support requires the optional dependency '{module_name}'; "
            f'install it with: pip install "yaicli[{extra}]"'
        ) from exc


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

        # Apply exclude params filtering
        completion_params = Provider.filter_excluded_params(
            completion_params,
            self.config,
            verbose=self.verbose,
            console=self.console,
        )

        return completion_params

    def completion(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
        tool_policy: Optional[ToolPolicy] = None,
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
        effective_tool_policy = self.resolve_tool_policy(tool_policy)

        # Add tools if enabled
        tools = []
        if effective_tool_policy.enable_functions:
            try:
                from ...tools import get_anthropic_schemas

                tools.extend(get_anthropic_schemas())
            except ImportError:
                self.console.print("Function tools not available for Anthropic", style="yellow")

        if effective_tool_policy.enable_mcp:
            try:
                from ...tools import get_anthropic_mcp_tools

                mcp_tools = get_anthropic_mcp_tools()
                tools.extend(mcp_tools)
            except (ValueError, FileNotFoundError, MCPToolsError, ImportError) as e:
                self.console.print(f"Failed to load MCP tools: {e}", style="red")

        if tools:
            params["tools"] = tools
            # Disable parallel tool use by default for better compatibility.
            # The typed config already yields a bool; str2bool keeps a direct dict
            # config (e.g. {"DISABLE_PARALLEL_TOOL_USE": "false"}) from sending a
            # truthy string to the API.
            disable_parallel = str2bool(self.config.get("DISABLE_PARALLEL_TOOL_USE", True))
            params["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": disable_parallel}

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
            # Never let a raw SDK/httpx exception escape unclassified and never
            # turn it into assistant text; the client/CLI can act on the kind.
            if self.verbose:
                self.console.print(f"Anthropic API error: {e}", style="red")
            raise wrap_provider_exception(e, "Anthropic") from e

    def _extract_system_prompt(self, messages: List[ChatMessage]) -> Tuple[Optional[str], Optional[int]]:
        """Extract system prompt from messages"""
        for index, message in enumerate(messages):
            if message.role == "system":
                return message.content, index
        return None, None

    def _handle_normal_response(self, response: Message) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response"""
        if not response.content:
            # An HTTP-200 response without content blocks is an in-band failure
            # (proxy/auth/filter): raise classified instead of faking an answer.
            raise provider_response_error("Anthropic", response.model_dump())

        # Extract content from all blocks in a single pass. A response may contain
        # several ``tool_use`` blocks (parallel tool use); every one is retained.
        text_content = ""
        thinking_content = ""
        tool_calls: List[ToolCall] = []

        for block in response.content:
            if block.type == "text" and hasattr(block, "text"):
                text_content += block.text
            elif block.type == "thinking":
                # Handle thinking blocks
                thinking_content += getattr(block, "thinking", "")
            elif block.type == "tool_use":
                # Handle tool use blocks
                tool_calls.append(
                    ToolCall(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", "") or "",
                        # String input is already valid JSON, no need to convert
                        arguments=block.input if isinstance(block.input, str) else json.dumps(block.input),
                    )
                )

        # Get stop reason
        finish_reason = response.stop_reason or "stop"

        # Yield response with all content types; token usage is attached here (the
        # non-streaming response is a single LLMResponse, so it can not double-count).
        yield LLMResponse(
            reasoning=thinking_content if thinking_content else None,
            content=text_content,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            usage=usage_from_anthropic(response),
        )

    def _handle_stream_response(self, response: Stream[RawMessageStreamEvent]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response from Anthropic API.

        Content blocks are sequential: each ``tool_use`` block is accumulated from
        its ``content_block_delta`` partial-JSON fragments and finalized on
        ``content_block_stop``. Every finalized call is kept (parallel tool use),
        then emitted together on ``message_delta``/``message_stop``. Partial calls
        are never emitted, so the client can not execute truncated arguments.
        """
        accumulator = ToolCallAccumulator()
        tool_call_id = ""
        tool_call_name = ""
        tool_call_input = ""
        # Streaming usage: ``message_start`` reports input tokens while the final
        # ``message_delta`` reports cumulative output tokens. Keep both halves and
        # combine them into one Usage attached to the closing response only.
        start_usage: Optional[Usage] = None
        output_usage: Optional[Usage] = None
        usage_sent = False

        def _combined_usage() -> Optional[Usage]:
            if start_usage is None and output_usage is None:
                return None
            prompt = start_usage.prompt_tokens if start_usage is not None else 0
            completion = output_usage.completion_tokens if output_usage is not None else 0
            if output_usage is not None and output_usage.prompt_tokens:
                prompt = output_usage.prompt_tokens
            cached = start_usage.cached_tokens if start_usage is not None else 0
            return Usage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
                cached_tokens=cached,
            )

        # Process each chunk in the response stream
        for chunk in response:
            # Handle different event types
            if chunk.type == "message_start":
                # The message payload (and its usage) is nested under ``message``.
                start_usage = usage_from_anthropic(chunk)
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
                # Content block stop - finalize this tool call if one is open
                if tool_call_id or tool_call_name:
                    accumulator.add_complete(
                        ToolCall(
                            id=tool_call_id,
                            name=tool_call_name,
                            arguments=repair_json(tool_call_input),
                        )
                    )
                    # Reset tool call data
                    tool_call_id = ""
                    tool_call_name = ""
                    tool_call_input = ""

            elif chunk.type == "message_delta":
                # Message delta update - contains stop reason (and the final output
                # token count). Re-yield the full call list; the client dedupes by id,
                # so this is safe. Usage is attached to the closing message_stop.
                output_usage = usage_from_anthropic(chunk)
                if hasattr(chunk, "delta") and hasattr(chunk.delta, "stop_reason"):
                    finish_reason = chunk.delta.stop_reason
                    if finish_reason:
                        yield LLMResponse(content="", finish_reason=finish_reason, tool_calls=accumulator.finalize())

            elif chunk.type == "message_stop":
                # Message stop - final response; the only response carrying usage.
                final_usage = _combined_usage()
                usage_sent = final_usage is not None
                yield LLMResponse(
                    content="", finish_reason="stop", tool_calls=accumulator.finalize(), usage=final_usage
                )

        if not usage_sent:
            # A proxy may omit message_stop; never lose the captured usage.
            final_usage = _combined_usage()
            if final_usage is not None:
                yield LLMResponse(
                    content="", finish_reason="stop", tool_calls=accumulator.finalize(), usage=final_usage
                )

    def detect_tool_role(self) -> str:
        """Return the role that should be used for tool responses"""
        return "tool"

    def _convert_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Convert ChatMessage list to Anthropic format with proper tool result handling"""
        converted_messages = []
        i = 0

        while i < len(messages):
            msg = messages[i]

            # Handle regular messages
            if msg.role != "tool":
                message: Dict[str, Any] = {"role": msg.role, "content": msg.content or ""}

                # Handle tool calls in assistant messages
                if msg.role == "assistant" and msg.tool_calls:
                    content = []
                    if msg.content:
                        content.append({"type": "text", "text": msg.content})

                    for tool_call in msg.tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tool_call.id,
                                "name": tool_call.name,
                                "input": json.loads(tool_call.arguments),
                            }
                        )

                    message["content"] = content

                # Handle images in user messages
                elif msg.images:
                    content = []
                    # Image blocks before text (Anthropic best practice)
                    for img in msg.images:
                        if img.is_url:
                            content.append({"type": "image", "source": {"type": "url", "url": img.data}})
                        else:
                            content.append(
                                {
                                    "type": "image",
                                    "source": {"type": "base64", "media_type": img.media_type, "data": img.data},
                                }
                            )
                    # Text block after images
                    text = msg.content or ""
                    if text:
                        content.append({"type": "text", "text": text})
                    message["content"] = content

                converted_messages.append(message)
                i += 1
            else:
                # Handle tool results - collect consecutive tool messages
                tool_results = []
                while i < len(messages) and messages[i].role == "tool":
                    tool_msg = messages[i]
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": tool_msg.tool_call_id, "content": tool_msg.content or ""}
                    )
                    i += 1

                # Add tool results as a user message
                if tool_results:
                    converted_messages.append({"role": "user", "content": tool_results})

        return converted_messages


class AnthropicBedrockProvider(AnthropicProvider):
    """Anthropic Bedrock provider implementation based on anthropic library"""

    CLIENT_CLS = AnthropicBedrock

    def __init__(self, *args, **kwargs):
        _require_optional_dependency("boto3", "bedrock")
        super().__init__(*args, **kwargs)
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
        # The Bedrock client authenticates with AWS credentials and rejects an Anthropic
        # api_key alongside them, so drop the shared API provider key.
        client_params.pop("api_key", None)
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

    def __init__(self, *args, **kwargs):
        _require_optional_dependency("google.auth", "vertex")
        super().__init__(*args, **kwargs)
    CLIENT_PARAMS_KEY_ENV_MAP = {
        "PROJECT_ID": "PROJECT_ID",
        "CLOUD_ML_REGION": "CLOUD_ML_REGION",
    }

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters"""
        client_params = super().get_client_params()
        # The Vertex client authenticates via google-auth project/region, not an api_key.
        client_params.pop("api_key", None)
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
