"""Small shared run options, independent of provider and terminal implementations."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RunState:
    interactive: bool = False
    print_mode: bool = False
    output_format: str = "text"
    quiet: bool = False
    machine_output: bool = True
    yes: bool = False
    allowed_tools: List[str] = field(default_factory=list)
    fail_on_tool_denied: bool = False
    max_turns: Optional[int] = None
    cwd: Optional[str] = None
    resume: bool = False
    init_role: str = "default"
    role_name: str = "default"
    current_mode: str = "temp"
    plan_requested: bool = False
    context_percent: Optional[float] = None
