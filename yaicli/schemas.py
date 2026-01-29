from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ChatMessage:
    """Chat message class"""

    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: List["ToolCall"] = field(default_factory=list)
    reasoning: Optional[str] = None  # Save reasoning content for interleaved thinking


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


class RefreshLive:
    """Refresh live display"""


class StopLive:
    """Stop live display"""
