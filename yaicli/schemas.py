from dataclasses import dataclass, field
from typing import List, Optional

from .const import StrEnum


@dataclass
class ImageData:
    """Image data for multimodal messages"""

    data: str  # base64 string (local) or URL string (remote)
    media_type: str  # MIME type: "image/jpeg", "image/png", etc.
    is_url: bool  # True → data is a URL; False → data is base64


@dataclass
class ChatMessage:
    """Chat message class"""

    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: List["ToolCall"] = field(default_factory=list)
    reasoning: Optional[str] = None  # Save reasoning content for interleaved thinking
    images: List[ImageData] = field(default_factory=list)


@dataclass
class ToolCall:
    """Function call class"""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolPolicy:
    """Per-request tool availability policy."""

    enable_functions: bool
    enable_mcp: bool


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


@dataclass
class ConfirmToolCall:
    """Control signal: ask the user to confirm a tool call before execution.

    Yielded out of the tool-execution loop so the display layer can pause the
    live region, prompt the user, and resume the generator with a
    ToolConfirmDecision via ``generator.send(...)``.
    """

    tool_call: ToolCall


class ToolConfirmDecision(StrEnum):  # type: ignore
    """User decision for a pending tool call confirmation."""

    ONCE = "once"  # Execute this call only
    SESSION = "session"  # Execute and stop asking for this tool this session
    PERSIST = "persist"  # Execute and persist approval across runs
    DENY = "deny"  # Do not execute; return a refusal result to the model
