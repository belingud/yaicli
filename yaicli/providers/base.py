from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional, Tuple

from rich.console import Console


class BaseClient(ABC):
    """Base abstract class for LLM API clients."""

    def __init__(self, config: Dict[str, Any], console: Console, verbose: bool):
        """Initialize the API client with configuration."""
        self.config = config
        self.console = console
        self.verbose = verbose
        self.timeout = self.config["TIMEOUT"]

    @abstractmethod
    def completion(self, messages: List[Dict[str, str]]) -> Tuple[Optional[str], Optional[str]]:
        """Get a complete non-streamed response from the API."""
        pass

    @abstractmethod
    def stream_completion(self, messages: List[Dict[str, str]]) -> Iterator[Dict[str, Any]]:
        """Connect to the API and yield parsed stream events."""
        pass

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
