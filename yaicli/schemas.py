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
    """Data structure for llm response with reasoning and content.

    Tool calls are exposed through two synchronised views:

    * ``tool_call`` — the legacy single-call field. Existing code that reads or
      constructs ``LLMResponse(tool_call=...)`` keeps working unchanged.
    * ``tool_calls`` — the full list of calls carried by this response. Providers
      that can return parallel/multiple calls in one response (stream or not)
      should emit ``LLMResponse(tool_calls=[...])``; ``LLMClient`` collects every
      entry.

    The two fields are kept in sync by :meth:`__post_init__` (a dual-set, not a
    property): constructing with either form fills the other, with ``tool_call``
    always pointing at ``tool_calls[0]``. Replace a response object rather than
    mutating one field in place, so the views never diverge.
    """

    reasoning: Optional[str] = None
    content: str = ""
    finish_reason: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    tool_calls: List[ToolCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Keep the legacy ``tool_call`` and plural ``tool_calls`` views in sync."""
        if self.tool_calls is None:  # defensive: callers may pass an explicit None
            self.tool_calls = []
        if self.tool_calls:
            if self.tool_call is None or self.tool_call not in self.tool_calls:
                if self.tool_call is not None:
                    self.tool_calls.insert(0, self.tool_call)
            self.tool_call = self.tool_calls[0]
        elif self.tool_call is not None:
            self.tool_calls = [self.tool_call]


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
