from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from typing import Generator, List, Optional, Union, overload

from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_chunk import Choice as ChoiceChunk

from ..role import Role
from ..const import EventTypeEnum


@dataclass
class Message:
    """Chat message class"""

    role: str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None


@dataclass
class ToolCall:
    """Function call class"""

    id: str
    name: str
    arguments: str


@dataclass
class LLMContent:
    """Data structure for llm response with reasoning and content"""

    event_type: Optional[EventTypeEnum] = None
    reasoning: Optional[str] = None
    content: str = ""
    finish_reason: Optional[str] = None
    tool_call: Optional[ToolCall] = None


@dataclass
class LLMProvider(ABC):
    """LLM provider abstract base class"""

    api_key: str
    model: str
    base_url: Optional[str] = None
    timeout: int = 60

    @abstractmethod
    def stream_completion(
        self,
        messages: List[Message],
        role: Role,
        stream: bool = True,
    ) -> Generator[LLMContent, None, None]:
        pass

    @abstractmethod
    def completion(
        self,
        messages: List[Message],
        role: Role,
        stream: bool = False,
    ) -> Generator[LLMContent, None, None]:
        """
        Send message to LLM

        Args:
            messages: message list
            role: role configuration
            stream: whether to use streaming output

        Returns:
            LLMContent
        """
        pass

    # @abstractmethod
    # def get_total_tokens(self, prompt: str) -> int:
    #     """Get the number of tokens in the prompt"""
    #     pass

    def _get_reasoning_content(self, delta: dict) -> Optional[str]:
        """Extract reasoning content from delta if available based on specific keys.

        This method checks for various keys that might contain reasoning content
        in different API implementations.

        Args:
            delta: The delta/model_extra from the API response

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
    
    @overload
    def parse_choice_from_content(
        self, content: str, choice_cls: type[Choice]
    ) -> Choice:
        ...

    @overload
    def parse_choice_from_content(
        self, content: str, choice_cls: type[ChoiceChunk]
    ) -> ChoiceChunk:
        ...

    def parse_choice_from_content(
        self, content: str, choice_cls: type[Union[Choice, ChoiceChunk]] = Choice
    ) -> Union[Choice, ChoiceChunk]:
        """
        Parse the choice from the content after <think>...</think> block.
        Args:
            content: The content from the LLM response
            choice_cls: The class to use to parse the choice
        Returns:
            The choice object
        Raises ValueError if the content is not valid JSON
        """
        try:
            content_dict = json.loads(content)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid message from LLM: {content}")
        if "delta" in content_dict:
            content_dict["message"] = content_dict["delta"]
        try:
            return choice_cls.model_validate(content_dict)
        except Exception as e:
            raise ValueError(f"Invalid message from LLM: {content}") from e
