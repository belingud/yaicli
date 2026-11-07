"""Shared accumulation and canonicalization of provider tool calls.

Every provider SDK delivers tool calls a little differently: complete content
blocks (Anthropic/Ollama/Mistral non-stream), per-``index`` streaming deltas
(OpenAI/Mistral/MiniMax), JSON fragments embedded in text (ChatGLM), or complete
function-call parts that may share a name (Gemini). This module is the single
place where those fragments become canonical, ordered
:class:`~yaicli.schemas.ToolCall` objects, so that **every** call in one provider
response/stream is retained and ``LLMClient`` can execute each of them.

The module is standard-library only and never imports a provider SDK.

Design notes / merge rules (the contract providers rely on):

* fragments carrying a streaming ``index`` merge into the call registered for
  that index (first chunk of a call usually carries ``id``/``name``, later
  chunks only argument fragments);
* fragments carrying an ``id`` merge into the call with that id, even when they
  arrive before the index is known;
* a fragment with neither index nor id but a ``name`` always starts a **new**
  call — two same-name calls without ids therefore stay distinct
  (Gemini/proxy streams may emit ``get_weather`` twice in one response);
* a fragment with no index/id/name continues the most recent call (proxies that
  only send the call name in the first fragment);
* insertion order is preserved and every finalized call has a non-empty unique
  id (existing ids are kept; missing ones are generated with
  :func:`yaicli.utils.gen_tool_call_id`).
"""

import json
from typing import Any, Dict, Iterable, List, Mapping, Optional

from ..schemas import ToolCall
from ..utils import gen_tool_call_id

__all__ = [
    "ToolCallAccumulator",
    "dedupe_tool_calls",
    "merge_argument_mapping",
]


def _identity_str(value: Any) -> Optional[str]:
    """Return ``value`` when it is a non-empty string, else ``None``.

    Provider chunks are sometimes ``MagicMock``/dict-shaped in tests and some
    SDKs type id/name/arguments loosely; only real strings identify a call.
    """
    return value if isinstance(value, str) and value else None


def _index_value(value: Any) -> Optional[int]:
    """Return a streaming ``index`` only when it is an int (OpenAI delta protocol)."""
    return value if isinstance(value, int) else None


class ToolCallAccumulator:
    """Collect tool-call fragments from one provider response/stream.

    Add fragments with :meth:`add_fragment` (argument strings, delta style) or
    complete calls with :meth:`add_complete` (block style), then call
    :meth:`finalize` once the response/stream is complete. One accumulator
    instance belongs to exactly one response/stream; do not share it across
    responses (ids only need to be unique inside a response, and the client
    dedupes across responses by id).
    """

    def __init__(self) -> None:
        self._calls: List[ToolCall] = []
        self._by_index: Dict[Any, ToolCall] = {}
        self._by_id: Dict[str, ToolCall] = {}

    def __len__(self) -> int:
        return len(self._calls)

    @property
    def calls(self) -> List[ToolCall]:
        """Calls accumulated so far, in insertion order (live objects, not copies)."""
        return list(self._calls)

    # ------------------- internals -------------------
    def _new_call(self) -> ToolCall:
        call = ToolCall(id="", name="", arguments="")
        self._calls.append(call)
        return call

    def _resolve(self, index: Any, call_id: Optional[str], name: Optional[str]) -> ToolCall:
        """Return the call a fragment belongs to, creating it when needed."""
        by_index = self._by_index.get(index) if index is not None else None
        by_id = self._by_id.get(call_id) if call_id else None

        if by_id is not None and by_index is not None and by_id is not by_index:
            # The same call was first seen by id and later by index (or vice
            # versa): fold the duplicate entry into the index-keyed call.
            target = by_index
            if not target.id:
                target.id = by_id.id
            if not target.name:
                target.name = by_id.name
            target.arguments = (by_id.arguments or "") + (target.arguments or "")
            self._calls = [call for call in self._calls if call is not by_id]
            if call_id:
                self._by_id[call_id] = target
            return target

        if by_index is not None:
            if call_id and not by_index.id:
                by_index.id = call_id
                self._by_id[call_id] = by_index
            return by_index

        if by_id is not None:
            if index is not None:
                self._by_index[index] = by_id
            return by_id

        if index is not None:
            call = self._new_call()
            self._by_index[index] = call
            if call_id:
                call.id = call_id
                self._by_id[call_id] = call
            return call

        if call_id:
            call = self._new_call()
            call.id = call_id
            self._by_id[call_id] = call
            return call

        if name:
            # Same-name calls without ids must stay distinct: each named
            # fragment starts a new call.
            return self._new_call()

        if self._calls:
            # Argument fragment without any identity: continuation of the last call.
            return self._calls[-1]
        return self._new_call()

    # ------------------- public API -------------------
    def add_fragment(
        self,
        *,
        index: Any = None,
        call_id: Optional[str] = None,
        name: Optional[str] = None,
        arguments: Optional[str] = None,
        replace_arguments: bool = False,
    ) -> ToolCall:
        """Add one streamed fragment and return the call it belongs to.

        ``arguments`` is appended to the call's argument text unless
        ``replace_arguments`` is true (APIs like AI21 re-send the complete
        argument JSON on later chunks instead of fragments).
        """
        index = _index_value(index)
        call_id = _identity_str(call_id)
        name = _identity_str(name)
        arguments = arguments if isinstance(arguments, str) else None
        call = self._resolve(index, call_id, name)
        if call_id and not call.id:
            call.id = call_id
            self._by_id[call_id] = call
        if name and not call.name:
            call.name = name
        if arguments:
            if replace_arguments:
                call.arguments = arguments
            else:
                call.arguments += arguments
        return call

    def add_complete(self, tool_call: ToolCall, *, index: Any = None) -> ToolCall:
        """Add an already-complete call (block-style APIs).

        A call whose non-empty id is already known is treated as the same call
        (e.g. a provider re-yields the finalized call): missing fields are
        filled in and complete arguments win over empty ones.
        """
        call_id = _identity_str(getattr(tool_call, "id", "")) or ""
        name = _identity_str(getattr(tool_call, "name", "")) or ""
        arguments = getattr(tool_call, "arguments", "") or ""
        if not isinstance(arguments, str):
            arguments = ""

        existing = self._by_id.get(call_id) if call_id else None
        if existing is not None:
            if name and not existing.name:
                existing.name = name
            if arguments and len(arguments) >= len(existing.arguments or ""):
                existing.arguments = arguments
            if index is not None:
                self._by_index[index] = existing
            return existing

        call = ToolCall(id=call_id, name=name, arguments=arguments)
        self._calls.append(call)
        if call_id:
            self._by_id[call_id] = call
        if index is not None:
            self._by_index[index] = call
        return call

    def finalize(self) -> List[ToolCall]:
        """Return canonical copies of every accumulated call, in insertion order.

        Ids are generated for calls that never received one. Repeated ids are
        deduped defensively (first occurrence wins) so a provider can safely
        re-yield a finalized call without the client executing it twice.
        """
        result: List[ToolCall] = []
        seen_ids: set = set()
        for call in self._calls:
            if not call.id:
                call.id = gen_tool_call_id()
            if call.id in seen_ids:
                continue
            seen_ids.add(call.id)
            result.append(ToolCall(id=call.id, name=call.name or "", arguments=call.arguments or ""))
        return result


def dedupe_tool_calls(calls: Iterable[Optional[ToolCall]]) -> List[ToolCall]:
    """Merge tool calls collected from several responses, preserving order.

    Streaming providers may yield the same accumulated call more than once
    (per-chunk snapshots, ``message_delta`` + ``message_stop``, ...). The client
    executes each call exactly once, keyed by id; calls that arrive without an
    id receive a generated one so assistant/tool history keeps matching ids.
    """
    result: List[ToolCall] = []
    seen_ids: set = set()
    for call in calls:
        if call is None:
            continue
        if not call.id:
            call.id = gen_tool_call_id()
        elif call.id in seen_ids:
            continue
        seen_ids.add(call.id)
        result.append(call)
    return result


def merge_argument_mapping(call: ToolCall, updates: Optional[Mapping[str, Any]]) -> None:
    """Merge a streamed JSON-argument fragment (given as a mapping) into ``call``.

    Gemini-style providers stream ``function_call.args`` mappings instead of
    argument strings. String values for a key already present are concatenated
    (proxies split JSON string values across chunks); other values overwrite.
    """
    if not updates:
        return
    current: Dict[str, Any] = {}
    if call.arguments:
        try:
            parsed = json.loads(call.arguments)
            if isinstance(parsed, dict):
                current = parsed
        except (TypeError, ValueError):
            current = {}
    for key, value in updates.items():
        if key in current and isinstance(value, str) and isinstance(current[key], str):
            current[key] += value
        else:
            current[key] = value
    call.arguments = json.dumps(current)
