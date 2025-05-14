from dataclasses import dataclass
from typing import Optional


@dataclass
class ChatMessage:
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
class LLMResponse:
    """Data structure for llm response with reasoning and content"""

    reasoning: Optional[str] = None
    content: str = ""
    finish_reason: Optional[str] = None
    tool_call: Optional[ToolCall] = None
