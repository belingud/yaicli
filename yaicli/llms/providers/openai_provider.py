import json
import os
from copy import deepcopy
from typing import Any, Dict, Generator, List, Optional, cast
from uuid import uuid4

import openai
from openai._streaming import Stream
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from ...config import cfg
from ...console import get_console
from ...exceptions import MCPToolsError, ProviderError
from ...schemas import ChatMessage, LLMResponse, ToolCall, ToolPolicy
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

    def get_completion_params(self, tool_policy: Optional[ToolPolicy] = None) -> Dict[str, Any]:
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

    def get_tools(self, tool_policy: Optional[ToolPolicy] = None) -> List[dict]:
        """
        Get the tools for the completion request.

        Returns:
            List[dict]: List of tool objects to use in the completion request.
        """
        effective_tool_policy = self.resolve_tool_policy(tool_policy)
        tools = []
        if effective_tool_policy.enable_functions:
            tools.extend(get_openai_schemas())

        # Add MCP tools if enabled
        if effective_tool_policy.enable_mcp:
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
        tool_policy: Optional[ToolPolicy] = None,
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

        params = self.get_completion_params(tool_policy=tool_policy)
        params["messages"] = openai_messages
        tools = self.get_tools(tool_policy=tool_policy)
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

    @staticmethod
    def _generate_tool_call_id() -> str:
        """Generate a unique id for a tool call that arrived without one."""
        return f"call_{uuid4().hex[:24]}"

    def _handle_normal_response(self, response: ChatCompletion) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response.

        A response may contain several parallel tool calls; each one needs its own
        ``LLMResponse`` so ``LLMClient`` can collect and execute all of them. The
        assistant text/reasoning is attached to the first response only so it is not
        accumulated multiple times.
        """
        if not response.choices:
            yield LLMResponse(
                content=json.dumps(getattr(response, "base_resp", None) or response.to_dict()), finish_reason="stop"
            )
            return
        choice = response.choices[0]
        content = choice.message.content or ""
        reasoning = getattr(choice.message, "reasoning_content", "")
        finish_reason = choice.finish_reason

        # Check if the response contains reasoning content in model_extra
        if not reasoning and hasattr(choice.message, "model_extra") and choice.message.model_extra:
            model_extra = choice.message.model_extra
            reasoning = self._get_reasoning_content(model_extra)

        if finish_reason == "tool_calls" and hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
            for tool_call_index, tool in enumerate(choice.message.tool_calls):
                function = getattr(tool, "function", None)
                tool_call = ToolCall(
                    getattr(tool, "id", None) or self._generate_tool_call_id(),
                    (getattr(function, "name", None) if function else None) or "",
                    (getattr(function, "arguments", None) if function else None) or "",
                )
                yield LLMResponse(
                    reasoning=reasoning if tool_call_index == 0 else None,
                    content=content if tool_call_index == 0 else "",
                    finish_reason=finish_reason,
                    tool_call=tool_call,
                )
            return

        yield LLMResponse(reasoning=reasoning, content=content, finish_reason=finish_reason)

    def _first_chunk_error(self, chunk) -> Optional[LLMResponse]:
        """
        Return error LLMResponse if first chunk is error message
        """
        # Some api could return error message in the first chunk, no choices to handle, return raw response to show the message
        # TODO: check which provider should do this
        # LLMResponse(
        #     content=json.dumps(getattr(chunk, "base_resp", None) or chunk.to_dict()), finish_reason="stop"
        # )
        return None

    def _handle_stream_response(self, response: Stream[ChatCompletionChunk]) -> Generator[LLMResponse, None, None]:
        """Handle streaming response from OpenAI API.

        Tool calls are accumulated per ``delta.tool_calls[i].index`` (id/position
        fallback) because the id and function name are only sent in the first chunk of
        each call while arguments arrive in later, possibly interleaved, chunks. When
        ``finish_reason == "tool_calls"`` every accumulated call is emitted as its own
        ``LLMResponse`` (in index order) so the client can collect and execute all of
        them. The chunk's text/reasoning is attached to the first emitted response.
        """
        accumulated_tool_calls: Dict[Any, ToolCall] = {}
        started = False
        # Process each chunk in the response stream
        for chunk in response:
            if not chunk.choices and not started:
                # Some api could return error message in the first chunk, no choices to handle, return raw response to show the message
                _first_chunk_llm_resp = self._first_chunk_error(chunk)
                if _first_chunk_llm_resp is not None:
                    yield _first_chunk_llm_resp
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

            # Accumulate tool call information scattered across chunks, keyed by index
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                self._accumulate_tool_call_chunks(delta.tool_calls, accumulated_tool_calls)

            if finish_reason == "tool_calls":
                tool_calls = self._finalize_tool_calls(accumulated_tool_calls)
                accumulated_tool_calls = {}
                if not tool_calls:
                    yield LLMResponse(
                        reasoning=reasoning, content=content, finish_reason=finish_reason, tool_call=None
                    )
                    continue
                for tool_call_index, tool_call in enumerate(tool_calls):
                    yield LLMResponse(
                        reasoning=reasoning if tool_call_index == 0 else None,
                        content=content if tool_call_index == 0 else "",
                        tool_call=tool_call,
                        finish_reason=finish_reason,
                    )
                continue

            yield LLMResponse(
                reasoning=reasoning,
                content=content,
                tool_call=None,
                finish_reason=finish_reason,
            )

    def _accumulate_tool_call_chunks(self, tool_calls, accumulated: Dict[Any, ToolCall]) -> None:
        """Accumulate streamed tool-call chunks into ``accumulated`` keyed by index.

        The OpenAI streaming format only includes ``id``/``function.name`` in the first
        chunk of a tool call and sends argument fragments afterwards; several calls can
        be interleaved in a single chunk, hence the per-``index`` bookkeeping. When
        ``index`` is absent (some OpenAI-compatible servers) the id or the chunk
        position is used as the key.
        """
        for position, tool in enumerate(tool_calls):
            index = getattr(tool, "index", None)
            if index is None:
                index = getattr(tool, "id", None) or position
            tool_call = accumulated.get(index)
            if tool_call is None:
                tool_call = ToolCall(id="", name="", arguments="")
                accumulated[index] = tool_call

            tool_id = getattr(tool, "id", None)
            if tool_id:
                tool_call.id = tool_id

            function = getattr(tool, "function", None)
            if function is None:
                continue
            name = getattr(function, "name", None)
            if name:
                tool_call.name = name
            arguments = getattr(function, "arguments", None)
            if arguments:
                tool_call.arguments += arguments

    def _finalize_tool_calls(self, accumulated: Dict[Any, ToolCall]) -> List[ToolCall]:
        """Return the accumulated tool calls in index order with unique ids."""
        def sort_key(item):
            index = item[0]
            if isinstance(index, int):
                return (0, index)
            return (1, 0)

        tool_calls = [tool_call for _, tool_call in sorted(accumulated.items(), key=sort_key)]
        for tool_call in tool_calls:
            if not tool_call.id:
                tool_call.id = self._generate_tool_call_id()
        return tool_calls

    def _process_tool_call_chunk(self, tool_calls, existing_tool_call=None):
        """Accumulate a single tool call from a response chunk (legacy helper).

        Kept for provider subclasses that override the streaming handler and still
        assume one tool call per response (chatglm/minimax/openai-compatible).
        ``_handle_stream_response`` uses ``_accumulate_tool_call_chunks`` instead and
        supports parallel calls.
        """
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
