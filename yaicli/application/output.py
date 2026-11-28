"""Result payloads, event serialization and exit mapping for one CLI run."""

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..errors import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_SIGINT,
    EXIT_TOOL_DENIED,
    ErrorKind,
    classify_exception,
)
from ..schemas import ChatMessage, RefreshLive
from ..usage import Usage, estimate_cost
from .state import RunState

TOOL_DENIED_MARKERS = ("declined to execute", "tool_denied")


@dataclass
class ResultState:
    exit_code: int = EXIT_OK
    had_error: bool = False
    interrupted: bool = False
    depth_limit_reached: bool = False
    tool_denied: bool = False
    error_kind: ErrorKind = ErrorKind.UNKNOWN
    error_message: Optional[str] = None
    last_content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


class MachineOutput:
    """Read explicit run/result state; never construct a provider while emitting output."""

    def __init__(self, config, state: RunState, live_client=lambda: None):
        self.config = config
        self.state = state
        self.result = ResultState()
        self.live_client = live_client
        self.plan_output = None

    def emit_event(self, event: Dict[str, Any]) -> None:
        """Write one stream-json event (one JSON object per line) to stdout."""
        if self.state.output_format != "stream-json":
            return
        sys.stdout.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()

    def write_text_result(self, content: Optional[str]) -> None:
        """Write the final text answer to stdout with exactly one trailing newline."""
        if not self.state.machine_output or self.state.output_format != "text" or content is None:
            return
        if content == "":
            return
        sys.stdout.write(content.rstrip("\n") + "\n")
        sys.stdout.flush()

    @staticmethod
    def parse_arguments(arguments: Any) -> Any:
        """Best-effort JSON decoding of tool-call arguments for structured output."""
        if isinstance(arguments, str):
            try:
                return json.loads(arguments)
            except (ValueError, TypeError):
                return arguments
        return arguments

    def record_error(self, exc: BaseException) -> None:
        """Store a classified error for JSON output/stderr rendering."""
        try:
            agent_error = classify_exception(exc)
            self.result.error_kind = agent_error.kind
            self.result.error_message = agent_error.message or str(exc)
        except Exception:  # pragma: no cover - classifier must never break the CLI
            self.result.error_kind = ErrorKind.UNKNOWN
            self.result.error_message = str(exc)

    def error_payload(self) -> Optional[Dict[str, Any]]:
        """The JSON ``error`` field: ``null`` on success, ``{kind, message}``."""
        if not self.result.error_message:
            return None
        kind = (
            self.result.error_kind.value
            if isinstance(self.result.error_kind, ErrorKind)
            else str(self.result.error_kind)
        )
        return {"kind": kind, "message": self.result.error_message}

    @staticmethod
    def usage_dict_int(usage: Optional[Dict[str, Any]], key: str) -> int:
        """Read a non-negative integer field from a usage snapshot (never raises)."""
        if not isinstance(usage, dict):
            return 0
        value = usage.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return max(0, value)

    def client_usage_snapshot(self) -> Optional[Dict[str, Any]]:
        """Return the live client's session usage snapshot, or ``None``.

        The private client slot is used on purpose: emitting a result or a usage
        line must never construct the LLM client as a side effect. Any missing
        client/API degrades to ``None`` instead of breaking output.
        """
        client = self.live_client()
        if client is None:
            return None
        snapshot = getattr(client, "usage_snapshot", None)
        if not callable(snapshot):
            return None
        try:
            data = snapshot()
        except Exception:  # pragma: no cover - usage reporting must never break the CLI
            return None
        return data if isinstance(data, dict) else None

    def usage_payload(self) -> Dict[str, Any]:
        """The JSON ``usage`` object: real session usage or a zeroed fallback."""
        snapshot = self.client_usage_snapshot()
        if snapshot is not None:
            return snapshot
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
            "estimated": False,
            "requests": 0,
            "cost_usd": None,
            "models": {},
            "tools": {"count": 0, "duration_ms": 0.0, "result_chars": 0},
        }

    def turn_finish_reason(self) -> Optional[str]:
        """Last provider ``finish_reason`` (only when the client exposed a string)."""
        client = self.live_client()
        if client is None:
            return None
        try:
            value = getattr(client, "last_finish_reason", None)
        except Exception:  # pragma: no cover
            return None
        return value if isinstance(value, str) else None

    def turn_output_truncated(self) -> bool:
        """True when the last turn stopped at MAX_TOKENS (``finish_reason=length``)."""
        client = self.live_client()
        if client is None:
            return False
        try:
            if getattr(client, "output_truncated", False) is True:
                return True
        except Exception:  # pragma: no cover
            pass
        return self.turn_finish_reason() == "length"

    def show_usage_enabled(self) -> bool:
        """Whether the interactive per-turn usage line is enabled (``SHOW_USAGE``)."""
        try:
            return bool(self.config.get("SHOW_USAGE", True))
        except Exception:  # pragma: no cover - config lookups must never break a turn
            return True

    def format_usage_line(
        self,
        before: Optional[Dict[str, Any]],
        after: Optional[Dict[str, Any]],
        elapsed_seconds: float,
        finish_reason: Optional[str],
    ) -> Optional[str]:
        """Build the dim per-turn status line (``model · context 12% · tokens … · 1.2s``).

        It carries the session status the REPL prompt used to show: current model,
        cached context usage, then this turn's tokens/cost/time/finish reason.
        ``before``/``after`` are session snapshots; the difference is this turn's
        usage. Returns ``None`` when no usage data is available at all (graceful
        degrade); unknown model pricing simply omits the cost segment.
        """
        if not isinstance(after, dict):
            return None
        prompt = max(0, self.usage_dict_int(after, "prompt_tokens") - self.usage_dict_int(before, "prompt_tokens"))
        completion = max(
            0, self.usage_dict_int(after, "completion_tokens") - self.usage_dict_int(before, "completion_tokens")
        )
        parts: List[str] = []
        model = self.prompt_model_name()
        if model:
            parts.append(model)
        percent = self.state.context_percent
        if isinstance(percent, (int, float)) and not isinstance(percent, bool):
            parts.append(f"context {max(0.0, float(percent)):.0f}%")
        if prompt or completion:
            parts.append(f"tokens {prompt:,} in / {completion:,} out")
            try:
                model = str(self.config.get("MODEL") or "")
                cost = estimate_cost(model, Usage(prompt, completion, prompt + completion), self.config)
            except Exception:  # pragma: no cover - cost display must never break a turn
                cost = None
            if cost is not None:
                parts.append(f"${cost:.4f}")
        else:
            parts.append("tokens n/a")
        parts.append(f"{max(0.0, elapsed_seconds):.1f}s")
        if finish_reason:
            parts.append(str(finish_reason))
        return " · ".join(parts)

    def build_result(self) -> Dict[str, Any]:
        """The single JSON object emitted by ``--output-format json``."""
        result: Dict[str, Any] = {
            "content": self.result.last_content or "",
            "tool_calls": [
                {"name": call.get("name", ""), "arguments": call.get("arguments"), "result": call.get("result")}
                for call in self.result.tool_calls
            ],
            "usage": self.usage_payload(),
            "finish_reason": self.turn_finish_reason(),
            "model": self.config.get("MODEL", ""),
            "provider": self.config.get("PROVIDER", ""),
            "error": self.error_payload(),
            "exit_code": self.result.exit_code,
        }
        # v0.24 K23: only ``--plan`` runs add the planning payload, so the normal
        # headless JSON key set stays exactly as documented.
        plan = self.plan_output
        if plan is not None or self.state.plan_requested:
            try:
                result["plan"] = plan.to_dict() if plan is not None else None
            except Exception:  # pragma: no cover - serialization must never break output
                result["plan"] = None
            path = getattr(plan, "path", None) if plan is not None else None
            result["plan_path"] = str(path) if path is not None else None
            result["revision"] = getattr(plan, "revision", None) if plan is not None else None
        return result

    def record_tool_calls(self, messages: Optional[List[ChatMessage]]) -> None:
        """Extract tool calls/results of the last user turn from the client messages.

        The client mutates the message list in place (no client.py changes needed):
        assistant messages carry ``tool_calls`` and the following ``role=tool``
        messages carry the matching results via ``tool_call_id``.
        """
        calls: List[Dict[str, Any]] = []
        if not messages:
            self.result.tool_calls = calls
            return
        last_user = -1
        for index, message in enumerate(messages):
            if getattr(message, "role", None) == "user":
                last_user = index
        pending: Dict[str, Dict[str, Any]] = {}
        for message in messages[last_user + 1 :]:
            role = getattr(message, "role", None)
            if role == "assistant":
                for tool_call in getattr(message, "tool_calls", None) or []:
                    entry: Dict[str, Any] = {
                        "name": getattr(tool_call, "name", ""),
                        "arguments": self.parse_arguments(getattr(tool_call, "arguments", None)),
                        "result": None,
                    }
                    calls.append(entry)
                    call_id = getattr(tool_call, "id", None)
                    if call_id:
                        pending[call_id] = entry
            elif role == "tool":
                content = message.content or ""
                if self.is_denied_result(content):
                    self.result.tool_denied = True
                entry = pending.pop(getattr(message, "tool_call_id", None) or "", None)
                if entry is not None and entry.get("result") is None:
                    entry["result"] = content
                else:
                    calls.append(
                        {
                            "name": getattr(message, "name", None) or "",
                            "arguments": None,
                            "result": content,
                        }
                    )
        self.result.tool_calls = calls

    @staticmethod
    def is_denied_result(content: str) -> bool:
        """True when a tool result represents a denied tool call."""
        lowered = (content or "").lower()
        return any(marker in lowered for marker in TOOL_DENIED_MARKERS)

    def emit_tool_events_from(self, messages: List[ChatMessage], cursor: int) -> int:
        """Emit stream-json tool_call/tool_result events for messages[cursor:]."""
        if self.state.output_format != "stream-json":
            return len(messages)
        for message in messages[cursor:]:
            role = getattr(message, "role", None)
            if role == "assistant":
                for tool_call in getattr(message, "tool_calls", None) or []:
                    self.emit_event(
                        {
                            "type": "tool_call",
                            "name": getattr(tool_call, "name", ""),
                            "arguments": self.parse_arguments(getattr(tool_call, "arguments", None)),
                        }
                    )
            elif role == "tool":
                content = message.content or ""
                if self.is_denied_result(content):
                    self.result.tool_denied = True
                self.emit_event(
                    {
                        "type": "tool_result",
                        "name": getattr(message, "name", None) or "",
                        "result": content,
                    }
                )
        return len(messages)

    def instrument_tool_events(self, stream_iterator, messages: List[ChatMessage]):
        """Tee the LLM stream so stream-json tool events are emitted per round.

        ``RefreshLive`` marks the end of a completion round; the client executes the
        tools when the generator is resumed, so new messages are inspected right
        after the next chunk arrives (or when the stream ends).
        """
        cursor = len(messages)

        def _forward():
            nonlocal cursor
            send_value = None
            boundary_pending = False
            while True:
                try:
                    if send_value is None:
                        chunk = next(stream_iterator)
                    else:
                        chunk = stream_iterator.send(send_value)
                except StopIteration:
                    cursor = self.emit_tool_events_from(messages, cursor)
                    return
                send_value = None
                if boundary_pending:
                    cursor = self.emit_tool_events_from(messages, cursor)
                    boundary_pending = False
                if isinstance(chunk, RefreshLive):
                    boundary_pending = True
                try:
                    send_value = yield chunk
                except GeneratorExit:  # pragma: no cover - consumer stopped early
                    return

        return _forward()

    def finalize_exit_code(self) -> int:
        """Resolve the process exit code from the public state contract."""
        if self.result.interrupted:
            self.result.exit_code = EXIT_SIGINT
        elif self.result.tool_denied and self.state.fail_on_tool_denied:
            self.result.exit_code = EXIT_TOOL_DENIED
        elif self.result.had_error:
            self.result.exit_code = EXIT_ERROR
        elif self.result.depth_limit_reached and self.config.get("EXIT_ON_DEPTH_LIMIT", True):
            self.result.exit_code = EXIT_ERROR
        else:
            self.result.exit_code = EXIT_OK
        return self.result.exit_code

    def finalize_headless(self) -> int:
        """Emit the final structured output (json/stream-json) and resolve the code."""
        self.finalize_exit_code()
        if self.result.exit_code != EXIT_OK and not self.result.error_message:
            # Describe flag-only outcomes (depth limit / denied tool) so JSON and
            # stream-json consumers never see a non-zero code with a null error.
            if self.result.depth_limit_reached:
                self.result.error_kind = ErrorKind.DEPTH_LIMIT
                self.result.error_message = "tool-call depth limit reached"
            elif self.result.tool_denied and self.state.fail_on_tool_denied:
                self.result.error_kind = ErrorKind.TOOL
                self.result.error_message = "a tool call was denied"
        if self.state.output_format == "json":
            payload = json.dumps(self.build_result(), ensure_ascii=False, default=str)
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()
        elif self.state.output_format == "stream-json":
            usage_event: Dict[str, Any] = {"type": "usage", **self.usage_payload()}
            finish_reason = self.turn_finish_reason()
            if finish_reason is not None:
                usage_event["finish_reason"] = finish_reason
            self.emit_event(usage_event)
            self.emit_event(
                {
                    "type": "done",
                    "exit_code": self.result.exit_code,
                    "error": self.error_payload(),
                }
            )
        return self.result.exit_code

    def prompt_model_name(self) -> str:
        """Return the short model name for the REPL status line (``""`` when unknown)."""
        try:
            model = self.config.get("MODEL") if hasattr(self.config, "get") else ""
        except Exception:  # pragma: no cover - config lookups must never break the prompt
            return ""
        if not isinstance(model, str):
            return ""
        # Provider-prefixed ids ("openai/gpt-4o") are shown without the prefix.
        model = model.strip().rsplit("/", 1)[-1]
        return model if len(model) <= 32 else model[:31] + "…"
