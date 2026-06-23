from typing import Generator, List, Optional, Union

from ..config import cfg
from ..console import get_console
from ..schemas import ChatMessage, ConfirmToolCall, LLMResponse, RefreshLive, ToolCall, ToolConfirmDecision, ToolPolicy
from ..tools import execute_tool_call
from ..tools.approval import ToolApprovalManager
from ..tools.mcp import MCP_TOOL_NAME_PREFIX
from .provider import ProviderFactory


class LLMClient:
    """
    LLM Client that coordinates provider interactions and tool calling

    This class handles the higher level logic of:
    1. Getting responses from LLM providers
    2. Managing tool calls and their execution
    3. Handling conversation flow with tools
    """

    __slots__ = (
        "config",
        "verbose",
        "console",
        "enable_function",
        "enable_mcp",
        "max_tool_call_depth",
        "provider",
        "approval",
        "interactive",
    )

    def __init__(
        self,
        provider_name: str,
        config: dict = cfg,
        verbose: bool = False,
        approval: Optional[ToolApprovalManager] = None,
        interactive: bool = True,
        **kwargs,
    ):
        """
        Initialize LLM client

        Args:
            provider_name: Name of the provider to use, default to openai if not known
            config: Configuration dictionary
            verbose: Whether to enable verbose logging
            approval: Tool approval manager (created if not provided)
            interactive: Whether the session can prompt the user (TTY available)
        """
        self.config = config
        self.verbose = verbose
        self.console = get_console()
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        self.enable_mcp = self.config["ENABLE_MCP"]
        self.approval = approval or ToolApprovalManager()
        self.interactive = interactive

        # Use provided provider or create one
        if provider_name not in ProviderFactory.providers_map:
            self.console.print(f"Provider {provider_name} not found, using openai as default", style="yellow")
            provider_name = "openai"
        self.provider = ProviderFactory.create_provider(provider_name, config=config, verbose=verbose, **kwargs)

        self.max_tool_call_depth = self.config["MAX_TOOL_CALL_DEPTH"]

    def completion_with_tools(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
        recursion_depth: int = 0,
        tool_policy: Optional[ToolPolicy] = None,
    ) -> Generator[Union[LLMResponse, RefreshLive, ConfirmToolCall], Optional[ToolConfirmDecision], None]:
        """
        Get completion from provider with tool calling support

        Args:
            messages: List of messages for the conversation
            stream: Whether to stream the response
            recursion_depth: Current recursion depth for tool calls

        Yields:
            LLMResponse objects and control signals
        """
        if recursion_depth >= self.max_tool_call_depth:
            self.console.print(
                f"Maximum tool call depth ({self.max_tool_call_depth}) reached. Stopping further tool calls...",
                style="bold yellow",
            )
            return

        effective_tool_policy = self.provider.resolve_tool_policy(tool_policy)

        # Get completion from provider and collect response data
        assistant_response_content = ""
        assistant_reasoning_content = ""  # Collect reasoning content
        # Providers may return identical tool calls with the same ID in a single response during streaming
        tool_calls: dict[str, ToolCall] = {}

        # Stream responses and collect data
        for llm_response in self.provider.completion(messages, stream=stream, tool_policy=effective_tool_policy):
            yield llm_response  # Forward response to caller

            # Collect content and tool calls for potential tool execution
            if llm_response.content:
                assistant_response_content += llm_response.content
            if llm_response.reasoning:  # Collect reasoning content
                assistant_reasoning_content += llm_response.reasoning
            if llm_response.tool_call and llm_response.tool_call.id not in tool_calls:
                tool_calls[llm_response.tool_call.id] = llm_response.tool_call

        # Always add assistant response to messages first
        valid_tool_calls = self._get_valid_tool_calls(tool_calls, effective_tool_policy)
        if self.verbose and tool_calls and len(valid_tool_calls) != len(tool_calls):
            skipped_tools = [tool_call.name for tool_call in tool_calls.values() if tool_call not in valid_tool_calls]
            self.console.print(f"Skipping disallowed tool calls: {', '.join(skipped_tools)}", style="dim yellow")

        assistant_message = ChatMessage(
            role="assistant",
            content=assistant_response_content,
            tool_calls=valid_tool_calls,
            reasoning=assistant_reasoning_content if assistant_reasoning_content else None,  # Save reasoning
        )
        messages.append(assistant_message)

        if not valid_tool_calls:
            return

        # Execute tools and continue conversation
        yield from self._execute_tools_and_continue(
            messages,
            valid_tool_calls,
            stream,
            recursion_depth,
            effective_tool_policy,
        )

    def _get_valid_tool_calls(self, tool_calls: dict[str, ToolCall], tool_policy: ToolPolicy) -> List[ToolCall]:
        """Filter tool calls based on enabled features"""
        valid_tool_calls = []

        for tool_call in tool_calls.values():
            if self.verbose:
                self.console.print(f"Raw tool call name: {tool_call.name}")
            is_mcp = tool_call.name.startswith(MCP_TOOL_NAME_PREFIX)

            if is_mcp and tool_policy.enable_mcp:
                valid_tool_calls.append(tool_call)
            elif not is_mcp and tool_policy.enable_functions:
                valid_tool_calls.append(tool_call)

        return valid_tool_calls

    def _execute_tools_and_continue(
        self,
        messages: List[ChatMessage],
        tool_calls: List[ToolCall],
        stream: bool,
        recursion_depth: int,
        tool_policy: ToolPolicy,
    ) -> Generator[Union[LLMResponse, RefreshLive, ConfirmToolCall], Optional[ToolConfirmDecision], None]:
        """Execute tool calls and continue the conversation.

        Each tool call passes through the execution-confirmation gate before it runs
        (unless TOOL_CONFIRM is disabled or the tool is already approved). Denied calls
        still receive a matching tool result so the provider request stays valid.
        """
        # Signal that new content is coming
        yield RefreshLive()

        # Assistant message has already been added to messages in completion_with_tools

        # Execute each tool call and add results to messages
        tool_role = self.provider.detect_tool_role()
        confirm_enabled = self.config["TOOL_CONFIRM"]

        for tool_call in tool_calls:
            # Capture the gate-time name: MCP names keep the _mcp__ prefix here,
            # but execute_tool_call strips it in place at execution time.
            gate_name = tool_call.name
            decision = ToolConfirmDecision.ONCE
            prompted = False

            if confirm_enabled and not self.approval.is_allowed(gate_name):
                if not self.interactive:
                    # No TTY to prompt on: deny and tell the user how to proceed.
                    self.console.print(
                        f"Tool '{gate_name}' requires confirmation but the session is non-interactive; denying. "
                        f"Pre-approve it in {self.approval.permissions_path} or set TOOL_CONFIRM=false.",
                        style="yellow",
                    )
                    decision = ToolConfirmDecision.DENY
                else:
                    decision = (yield ConfirmToolCall(tool_call)) or ToolConfirmDecision.DENY
                    prompted = True
                    if decision == ToolConfirmDecision.SESSION:
                        self.approval.allow_session(gate_name)
                    elif decision == ToolConfirmDecision.PERSIST:
                        try:
                            self.approval.allow_persist(gate_name)
                        except OSError:
                            # Persisting failed (e.g., disk/permission); keep it for the session.
                            self.approval.allow_session(gate_name)
                            self.console.print(
                                f"Could not persist approval for '{gate_name}'; allowed for this session only.",
                                style="yellow",
                            )

            if decision == ToolConfirmDecision.DENY:
                messages.append(
                    ChatMessage(
                        role=tool_role,
                        content="The user declined to execute this tool.",
                        # De-prefix MCP names to match the executed path (execute_tool_call
                        # strips the prefix), so the result name is consistent either way.
                        name=gate_name.removeprefix(MCP_TOOL_NAME_PREFIX),
                        tool_call_id=tool_call.id,
                    )
                )
                continue

            # Avoid double-printing the call: the prompt already showed it when we prompted.
            function_result, _ = execute_tool_call(tool_call, announce=not prompted)

            messages.append(
                ChatMessage(
                    role=tool_role,
                    content=function_result,
                    name=tool_call.name,
                    tool_call_id=tool_call.id,
                )
            )

        # Continue the conversation with updated history
        yield from self.completion_with_tools(
            messages,
            stream=stream,
            recursion_depth=recursion_depth + 1,
            tool_policy=tool_policy,
        )
