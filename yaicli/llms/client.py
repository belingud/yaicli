from typing import Generator, List, Optional, Union

from ..config import cfg
from ..console import get_console
from ..schemas import ChatMessage, LLMResponse, RefreshLive, ToolCall
from ..tools import execute_tool_call
from .provider import Provider, ProviderFactory


class LLMClient:
    """
    LLM Client that coordinates provider interactions and tool calling

    This class handles the higher level logic of:
    1. Getting responses from LLM providers
    2. Managing tool calls and their execution
    3. Handling conversation flow with tools
    """

    def __init__(
        self,
        provider: Optional[Provider] = None,
        provider_name: str = "",
        config: dict = cfg,
        verbose: bool = False,
        **kwargs,
    ):
        """
        Initialize LLM client

        Args:
            provider: Optional pre-initialized Provider instance
            provider_name: Name of the provider to use if provider not provided
            config: Configuration dictionary
            verbose: Whether to enable verbose logging
        """
        self.config = config
        self.verbose = verbose
        self.console = get_console()

        # Use provided provider or create one
        if provider:
            self.provider = provider
        elif provider_name:
            self.provider = ProviderFactory.create_provider(provider_name, config=config, verbose=verbose, **kwargs)
        else:
            provider_name = config.get("PROVIDER", "openai").lower()
            self.provider = ProviderFactory.create_provider(provider_name, config=config, verbose=verbose, **kwargs)

        self.max_recursion_depth = config.get("MAX_RECURSION_DEPTH", 5)

    def completion_with_tools(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
        recursion_depth: int = 0,
    ) -> Generator[Union[LLMResponse, RefreshLive], None, None]:
        """
        Get completion from provider with tool calling support

        Args:
            messages: List of messages for the conversation
            stream: Whether to stream the response
            recursion_depth: Current recursion depth for tool calls

        Yields:
            LLMResponse objects and control signals
        """
        if recursion_depth >= self.max_recursion_depth:
            self.console.print(
                f"Maximum recursion depth ({self.max_recursion_depth}) reached, stopping further tool calls",
                style="yellow",
            )
            return

        # Get completion from provider
        llm_response_generator = self.provider.completion(messages, stream=stream)

        # To hold the full response
        assistant_response_content = ""
        tool_calls: List[ToolCall] = []

        # Process all responses from the provider
        for llm_response in llm_response_generator:
            # Forward the response to the caller
            yield llm_response

            # Collect content and tool calls
            if llm_response.content:
                assistant_response_content += llm_response.content
            if llm_response.tool_call and llm_response.tool_call not in tool_calls:
                tool_calls.append(llm_response.tool_call)

        # If we have tool calls, execute them and make recursive call
        if tool_calls and self.config["ENABLE_FUNCTIONS"]:
            # Yield a refresh signal to indicate new content is coming
            yield RefreshLive()

            # Append the assistant message with tool calls to history
            messages.append(ChatMessage(role="assistant", content=assistant_response_content, tool_calls=tool_calls))

            # Execute each tool call and append the results
            for tool_call in tool_calls:
                function_result, _ = execute_tool_call(tool_call)

                # Use provider's tool role detection
                tool_role = self.provider.detect_tool_role()

                # Append the tool result to history
                messages.append(
                    ChatMessage(
                        role=tool_role,
                        content=function_result,
                        name=tool_call.name,
                        tool_call_id=tool_call.id,
                    )
                )

            # Make a recursive call with the updated history
            yield from self.completion_with_tools(messages, stream=stream, recursion_depth=recursion_depth + 1)
