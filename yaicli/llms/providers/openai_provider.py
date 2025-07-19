import json
import os
from copy import deepcopy
from typing import Any, Dict, Generator, List, Optional, cast

import openai
from openai._streaming import Stream
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ...config import cfg
from ...console import get_console
from ...exceptions import MCPToolsError, ProviderError
from ...schemas import ChatMessage, LLMResponse, ToolCall
from ...tools import get_openai_mcp_tools, get_openai_schemas
from ..provider import Provider


class OpenAIProvider(Provider):
    """OpenAI provider implementation based on openai library"""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    CLIENT_CLS = openai.OpenAI
    # Base mapping between config keys and API parameter names
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_completion_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "reasoning_effort": "REASONING_EFFORT",
        "frequency_penalty": "FREQUENCY_PENALTY",
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

        # Store completion params
        self._completion_params: Optional[Dict[str, Any]] = None

    @property
    def completion_params(self) -> Dict[str, Any]:
        if self._completion_params is None:
            self._completion_params = self.get_completion_params()
        return deepcopy(self._completion_params)

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters"""
        # Initialize client params
        client_params: Dict[str, Any] = {
            "api_key": self.config["API_KEY"],
            "base_url": self.config.get("BASE_URL") or self.DEFAULT_BASE_URL,
            "default_headers": {"X-Title": self.APP_NAME, "HTTP_Referer": self.APP_REFERER},
        }

        # Add extra headers if set
        extra_headers = self.config.get("EXTRA_HEADERS")
        if extra_headers:
            client_params["default_headers"] = {**extra_headers, **client_params["default_headers"]}
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
    
    def get_tools(self) -> List[dict]:
        """
        Get the tools for the completion request.

        Returns:
            List[dict]: List of tool objects to use in the completion request.
        """
        tools = []
        if self.enable_function:
            tools.extend(get_openai_schemas())

        # Add MCP tools if enabled
        if self.enable_mcp:
            try:
                mcp_tools = get_openai_mcp_tools()
            except (ValueError, FileNotFoundError, MCPToolsError) as e:
                self.console.print(f"Failed to load MCP tools: {e}", style="red")
                mcp_tools = []
            tools.extend(mcp_tools)
        return tools

    def completion(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
    ) -> Generator[LLMResponse, None, None]:
        """
            Send completion request to OpenAI and return responses.

        Args:
            messages: List of chat messages to send
            stream: Whether to stream the response

        Yields:
            LLMResponse: Response objects containing content, tool calls, etc.

        Raises:
            ValueError: If messages is empty or invalid
            openai.APIError: If API request fails
        """
        openai_messages = self._convert_messages(messages)

        params = self.completion_params.copy()
        params["messages"] = openai_messages
        tools = self.get_tools()
        if tools:
            params["tools"] = tools
        if self.verbose:
            self.console.print("Messages:")
            self.console.print(openai_messages)
            if params.get("tools"):
                self.console.print("Tools:")
                self.console.print(params["tools"])
        response = self.client.chat.completions.create(**params, stream=stream)
        try:
            if stream:
                yield from self._handle_stream_response(cast(Stream[ChatCompletionChunk], response))
            else:
                yield from self._handle_normal_response(cast(ChatCompletion, response))
        except (openai.APIStatusError, openai.APIResponseValidationError) as e:
            try:
                body = e.response.json()
            except Exception:
                body = e.response.text
            self.console.print(f"Error Response: {body}")

    def _handle_normal_response(self, response: ChatCompletion) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response"""
        if not response.choices:
            yield LLMResponse(
                content=json.dumps(getattr(response, "base_resp", None) or response.to_dict()), finish_reason="stop"
            )
            return
        choice = response.choices[0]
        content = choice.message.content or ""
        reasoning = getattr(choice.message, "reasoning_content", "")
        finish_reason = choice.finish_reason
        tool_call: Optional[ToolCall] = None

        # Check if the response contains reasoning content in model_extra
        if hasattr(choice.message, "model_extra") and choice.message.model_extra:
            model_extra = choice.message.model_extra
            reasoning = self._get_reasoning_content(model_extra)

        if finish_reason == "tool_calls" and hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
            tool = choice.message.tool_calls[0]
            tool_call = ToolCall(tool.id, tool.function.name or "", tool.function.arguments)

        yield LLMResponse(reasoning=reasoning, content=content, finish_reason=finish_reason, tool_call=tool_call)

    def _handle_stream_response(self, response: Stream[ChatCompletionChunk]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response from OpenAI API"""
        # Initialize tool call object to accumulate tool call data across chunks
        tool_call: Optional[ToolCall] = None
        started = False
        # Process each chunk in the response stream
        for chunk in response:
            if not chunk.choices and not started:
                # Some api could return error message in the first chunk, no choices to handle, return raw response to show the message
                yield LLMResponse(
                    content=json.dumps(getattr(chunk, "base_resp", None) or chunk.to_dict()), finish_reason="stop"
                )
                started = True
                continue

            if not chunk.choices:
                continue
            started = True
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            # Extract content from current chunk
            content = delta.content or ""

            # Extract reasoning content if available
            reasoning = self._get_reasoning_content(getattr(delta, "model_extra", None) or delta)

            # Process tool call information that may be scattered across chunks
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                tool_call = self._process_tool_call_chunk(delta.tool_calls, tool_call)

            # Generate response object with tool_call only when finish_reason indicates completion
            yield LLMResponse(
                reasoning=reasoning,
                content=content,
                tool_call=tool_call if finish_reason == "tool_calls" else None,
                finish_reason=finish_reason,
            )

    def _process_tool_call_chunk(self, tool_calls, existing_tool_call=None):
        """Process tool call data from a response chunk"""
        # Initialize tool call object if this is the first chunk with tool call data
        if existing_tool_call is None and tool_calls:
            existing_tool_call = ToolCall(tool_calls[0].id or "", tool_calls[0].function.name or "", "")

        # Accumulate arguments from multiple chunks
        if existing_tool_call:
            for tool in tool_calls:
                if not tool.function:
                    continue
                existing_tool_call.arguments += tool.function.arguments or ""

        return existing_tool_call

    def _get_reasoning_content(self, delta: Any) -> Optional[str]:
        """Extract reasoning content from delta if available based on specific keys."""
        if not delta:
            return None
        if not isinstance(delta, dict):
            delta = dict(delta)
        # Reasoning content keys from API:
        # reasoning_content: deepseek/infi-ai/nvida
        # reasoning: openrouter
        # <think> block implementation not in here
        for key in ("reasoning_content", "reasoning"):
            if key in delta:
                return delta[key]
        return None

    def detect_tool_role(self) -> str:
        """Return the role that should be used for tool responses"""
        return "tool"


class OpenAIAzure(OpenAIProvider):
    CLIENT_CLS = openai.AzureOpenAI

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        self.config = config
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        self.enable_mcp = self.config["ENABLE_MCP"]
        self.verbose = verbose

        # Initialize client
        self.client_params = self.get_client_params()
        self.client = self.CLIENT_CLS(**self.client_params)
        self.console = get_console()

        # Store completion params
        self._completion_params: Optional[Dict[str, Any]] = None

    def get_client_params(self) -> Dict[str, Any]:
        """
        azure_endpoint: Your Azure endpoint, including the resource, e.g. `https://example-resource.azure.openai.com/`

        azure_ad_token: Your Azure Active Directory token, https://www.microsoft.com/en-us/security/business/identity-access/microsoft-entra-id

        azure_ad_token_provider: A function that returns an Azure Active Directory token, will be invoked on every request.

        azure_deployment: A model deployment, if given with `azure_endpoint`, sets the base client URL to include `/deployments/{azure_deployment}`.
            Not supported with Assistants APIs.
        """
        api_key = self.config.get("API_KEY")
        azure_ad_token = self.config.get("AZURE_AD_TOKEN")
        azure_ad_token_provider = self.config.get("AZURE_AD_TOKEN_PROVIDER")
        api_version = self.config.get("API_VERSION")
        if api_key is None:
            api_key = os.environ.get("AZURE_OPENAI_API_KEY")

        if azure_ad_token is None:
            azure_ad_token = os.environ.get("AZURE_OPENAI_AD_TOKEN")

        if api_key is None and azure_ad_token is None:
            raise ProviderError(
                "Missing credentials. Please pass one of `api_key`, `azure_ad_token`, or the `AZURE_OPENAI_API_KEY` or `AZURE_OPENAI_AD_TOKEN` environment variables."
            )

        if api_version is None:
            api_version = os.environ.get("OPENAI_API_VERSION")

        if api_version is None:
            raise ProviderError(
                "Must provide either the `api_version` argument or the `OPENAI_API_VERSION` environment variable"
            )

        default_query = {"api-version": api_version}
        # Merge with custom default query if provided
        custom_default_query = self.config.get("DEFAULT_QUERY")
        if custom_default_query:
            default_query.update(custom_default_query)
        default_headers = self.config.get("DEFAULT_HEADERS") or {}
        default_headers.update({"X-Title": self.APP_NAME, "HTTP_Referer": self.APP_REFERER})
        base_url = self.config.get("BASE_URL") or None  # set to None if base url is empty
        azure_deployment = self.config.get("AZURE_DEPLOYMENT")
        azure_endpoint = self.config.get("AZURE_ENDPOINT")

        if base_url is None:
            if azure_endpoint is None:
                azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")

            if azure_endpoint is None:
                raise ValueError(
                    "Must provide one of the `base_url` or `azure_endpoint` arguments, or the `AZURE_OPENAI_ENDPOINT` environment variable"
                )

            if azure_deployment is not None:
                base_url = f"{azure_endpoint.rstrip('/')}/openai/deployments/{azure_deployment}"
            else:
                base_url = f"{azure_endpoint.rstrip('/')}/openai"
        else:
            if azure_endpoint is not None:
                raise ValueError("base_url and azure_endpoint are mutually exclusive")

        client_params = {
            "api_key": api_key,
            "azure_ad_token": azure_ad_token,
            "default_query": default_query,
            "default_headers": default_headers,
            "azure_endpoint": azure_endpoint,
            "azure_deployment": azure_deployment,
            "base_url": base_url,
        }

        # Add azure_ad_token_provider if provided
        if azure_ad_token_provider:
            client_params["azure_ad_token_provider"] = azure_ad_token_provider

        return client_params
