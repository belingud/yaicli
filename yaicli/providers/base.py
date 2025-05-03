from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional, Union
from dataclasses import dataclass
import json

from rich.console import Console

from yaicli.function import get_function_manager


@dataclass
class ToolCall:
    """Tool call data class."""

    id: str
    name: str
    arguments: Union[Dict[str, Any], Any]


@dataclass
class LLMResponse:
    """LLM response data class."""

    content: Optional[str]
    reasoning: Optional[str]
    tool_calls: Optional[List[ToolCall]] = None


class BaseClient(ABC):
    """Base abstract class for LLM API clients."""

    def __init__(self, config: Dict[str, Any], console: Console, verbose: bool):
        """Initialize the API client with configuration."""
        self.config = config
        self.console = console
        self.verbose = verbose
        self.timeout = self.config["TIMEOUT"]
        self.tools = self._load_tools()

    def _load_tools(self) -> Dict[str, Any]:
        """Load available tools using FunctionManager"""
        function_mgr = get_function_manager()

        # Return all function classes
        return function_mgr.functions

    def _enable_functions(self) -> None:
        """Enable function calling in API requests"""
        self.config["ENABLE_FUNCTIONS"] = True

    def _disable_functions(self) -> None:
        """Disable function calling in API requests"""
        self.config["ENABLE_FUNCTIONS"] = False

    @abstractmethod
    def completion(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """Get a complete non-streamed response from the API.

        Returns either:
        - LLMResponse object (for new implementations)
        - Tuple(content, reasoning) (for backward compatibility)
        """
        pass

    @abstractmethod
    def stream_completion(self, messages: List[Dict[str, str]]) -> Iterator[Dict[str, Any]]:
        """Connect to the API and yield parsed stream events."""
        pass

    def _execute_tool(self, tool_call: ToolCall) -> Dict[str, Any]:
        """Execute a tool call and return the result"""
        if tool_call.name not in self.tools:
            raise ValueError(f"Tool {tool_call.name} not found")

        try:
            # Get function class and instantiate with arguments
            function_cls = self.tools[tool_call.name]
            return function_cls.execute(**tool_call.arguments)
        except Exception as e:
            raise ValueError(f"Error executing tool {tool_call.name}: {str(e)}")

    def _process_tool_calls(self, messages: List[Dict[str, Any]], tool_calls: List[ToolCall]) -> Optional[LLMResponse]:
        """Process tool calls and get final response"""
        if not self.tools:
            return LLMResponse(content="Function calling is not supported (no tools installed)", reasoning=None)
        
        for tool_call in tool_calls:
            try:
                # Print tool call information
                if self.verbose:
                    joined_args = ", ".join(f'{k}="{v}"' for k, v in tool_call.arguments.items())
                    self.console.print(f"> @FunctionCall `{tool_call.name}({joined_args})`", style="blue bold")
                
                # Execute tool call
                result = self._execute_tool(tool_call)
                
                # Add tool call to message history
                messages.append({
                    "role": "tool", 
                    # "tool_call_id": tool_call.id,
                    "content": None, 
                    "tool_calls": [{
                        "id": tool_call.id,
                        "function": {
                            "name": tool_call.name,
                            "arguments": json.dumps(tool_call.arguments)
                        }
                    }]
                })
                
                # Add tool call result to message history
                result_str = json.dumps(result) if not isinstance(result, str) else result
                messages.append({
                    "role": "tool", 
                    "name": tool_call.name, 
                    "content": result_str
                })
                
                # Print tool call result
                if self.verbose and self.config.get("SHOW_FUNCTIONS_OUTPUT", True):
                    self.console.print(f"```\n{result_str}\n```", style="green")
                
            except Exception as e:
                error_msg = f"Tool call error: {str(e)}"
                self.console.print(error_msg, style="red")
                if self.verbose:
                    import traceback
                    self.console.print(traceback.format_exc(), style="red")
                return LLMResponse(content=error_msg, reasoning=None)

        # Continue with the conversation with the LLM, get the final response
        return self.completion(messages)

    def process_tool_call(self, tool_call: ToolCall) -> Dict[str, Any]:
        """Process a single tool call and return the result
        
        This method only handles the tool call logic, not message processing
        
        Args:
            tool_call: The tool call object to process
            
        Returns:
            The tool call execution result
            
        Raises:
            ValueError: When the tool is not found or execution fails
        """
        if not self.tools:
            raise ValueError("Tool calling not available (no tools installed)")
            
        # Print tool call information
        if self.verbose:
            args_display = ", ".join(f"{k}={v!r}" for k, v in tool_call.arguments.items())
            self.console.print(f"⚙️ Executing tool: {tool_call.name}({args_display})", style="cyan bold")
            
        # Execute tool call and get result
        try:
            result = self._execute_tool(tool_call)
            
            # Print execution result
            if self.verbose and self.config.get("SHOW_FUNCTIONS_OUTPUT", True):
                result_str = json.dumps(result, ensure_ascii=False, indent=2) if not isinstance(result, str) else result
                self.console.print("✅ Execution result:", style="green bold")
                self.console.print(result_str, style="green")
                
            return result
            
        except Exception as e:
            # Print error information
            error_msg = f"❌ Tool call failed: {str(e)}"
            self.console.print(error_msg, style="red bold")
            if self.verbose:
                import traceback
                self.console.print(traceback.format_exc(), style="red")
            raise ValueError(error_msg)
            
    def process_tool_calls(self, tool_calls: List[ToolCall]) -> List[Dict[str, Any]]:
        """Process multiple tool calls in batch and return results list
        
        Args:
            tool_calls: List of tool calls to process
            
        Returns:
            List of tool call results, in the same order as input
        """
        results = []
        
        for tool_call in tool_calls:
            try:
                result = self.process_tool_call(tool_call)
                results.append({
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "result": result,
                    "status": "success"
                })
            except ValueError as e:
                results.append({
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "error": f"Function call error: {str(e)}",
                    "status": "error"
                })
                
        return results

    def _get_reasoning_content(self, delta: dict) -> Optional[str]:
        """Extract reasoning content from delta if available based on specific keys.

        This method checks for various keys that might contain reasoning content
        in different API implementations.

        Args:
            delta: The delta dictionary from the API response

        Returns:
            The reasoning content string if found, None otherwise
        """
        if not delta:
            return None
        # Reasoning content keys from API:
        # reasoning_content: deepseek/infi-ai
        # reasoning: openrouter
        # <think> block implementation not in here
        for key in ("reasoning_content", "reasoning"):
            # Check if the key exists and its value is a non-empty string
            value = delta.get(key)
            if isinstance(value, str) and value:
                return value

        return None  # Return None if no relevant key with a string value is found
