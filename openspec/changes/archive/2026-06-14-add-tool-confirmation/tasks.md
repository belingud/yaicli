## 1. Config & constants

- [x] 1.1 Register `TOOL_CONFIRM` in `DEFAULT_CONFIG_MAP` (`yaicli/const.py`): default `"true"`, env `YAI_TOOL_CONFIRM`, type `bool`; add a `DEFAULT_TOOL_CONFIRM` default constant alongside the others.
- [x] 1.2 Add `TOOL_PERMISSIONS_PATH = CONFIG_PATH.parent / "tool_permissions.json"` to `yaicli/const.py`.
- [x] 1.3 Add the `TOOL_CONFIRM` line (with an explanatory comment) to `DEFAULT_CONFIG_INI` so new config files document it.

## 2. Schemas (control signal & decision type)

- [x] 2.1 In `yaicli/schemas.py`, add a `ToolConfirmDecision` type covering `once`, `session`, `persist`, `deny` (StrEnum or constants).
- [x] 2.2 Add `@dataclass ConfirmToolCall` carrying the `ToolCall` to be confirmed.
- [x] 2.3 Confirm `StopLive` is used by the printer pump (it is currently defined but unused); keep or wire it in step 5. (Kept as-is: the pump stops the live region directly via `_safe_stop_live`, so a routed StopLive signal is unnecessary.)

## 3. Approval manager (new module)

- [x] 3.1 Create `yaicli/tools/approval.py` with `ToolApprovalManager` holding `session_allow: set[str]` and `persistent_allow: set[str]`.
- [x] 3.2 Load `persistent_allow` from `TOOL_PERMISSIONS_PATH` on init; tolerate a missing or malformed file (treat as empty).
- [x] 3.3 Implement `is_allowed(name)` returning membership in the union of session and persistent sets.
- [x] 3.4 Implement `allow_session(name)` (in-memory only) and `allow_persist(name)` (update set + write file).
- [x] 3.5 Persist with a temp-file + atomic `os.replace` write so a partial write cannot corrupt the allowlist; create parent dir if needed. (Write happens before the in-memory set is updated, so a failed write leaves both intact.)

## 4. Confirmation gate in the client

- [x] 4.1 Extend `LLMClient.__init__` to accept and store an `approval` manager and an `interactive: bool` flag.
- [x] 4.2 In `_execute_tools_and_continue`, before each `execute_tool_call`, capture the gate-time tool name (MCP names keep the `_mcp__` prefix) and resolve a decision: execute when `TOOL_CONFIRM` is off or `approval.is_allowed(name)`; deny (no prompt) when not interactive; otherwise `decision = yield ConfirmToolCall(tc)`.
- [x] 4.3 After an interactive decision, record `session`/`persist` outcomes via the approval manager keyed by the gate-time name. (Persist failure degrades gracefully to session approval with a warning.)
- [x] 4.4 On deny, skip execution and append a `tool`-role message whose `tool_call_id` matches the denied call, stating the user declined; ensure every tool call in the turn still produces a matching result message.
- [x] 4.5 On non-interactive deny, print a hint to pre-approve the tool or set `TOOL_CONFIRM=false`.

## 5. Printer prompt & stream pump

- [x] 5.1 Rework `Printer.display_stream` to drive the generator with `next`/`send` instead of a plain `for`, preserving existing `RefreshLive` and `LLMResponse` handling.
- [x] 5.2 On receiving `ConfirmToolCall`, stop the active `Live` (`_safe_stop_live`), render the pending call (name + arguments), and prompt with `[y]once / [a]session / [A]persist / [n]deny`.
- [x] 5.3 Map the keypress to a `ToolConfirmDecision` and resume the generator via `gen.send(decision)`; restart/realign the `Live` so subsequent streaming renders correctly.
- [x] 5.4 Catch `KeyboardInterrupt`/`EOFError` at the prompt and send a `deny` decision (mirroring `exec` mode's EOF handling) so it never propagates as an unhandled error.

## 6. CLI wiring & non-interactive policy

- [x] 6.1 In `yaicli/cli.py`, construct a `ToolApprovalManager` and pass it (plus `interactive=sys.stdin.isatty()`) into the `LLMClient` at `_create_client`.

## 7. Display de-duplication

- [x] 7.1 Avoid double-printing the call: `execute_tool_call` takes an `announce` flag, and the client passes `announce=False` when the gate already showed the call via the prompt.

## 8. Tests

- [x] 8.1 `once`: approving once executes; the tool is not remembered (`is_allowed` stays False).
- [x] 8.2 `session`: after session approval, a later call to the same tool executes without prompting.
- [x] 8.3 `persist`: persistent approval writes the tool to `tool_permissions.json`; a fresh `ToolApprovalManager` loaded from that file executes without prompting.
- [x] 8.4 `deny`: a denied call appends a `tool` result with the matching `tool_call_id` and the conversation continues; multi-call turns leave no tool call without a result.
- [x] 8.5 Non-interactive: with no TTY, an allowlisted tool runs and a non-allowlisted tool is denied.
- [x] 8.6 Master switch: `TOOL_CONFIRM=false` executes all tool calls without prompting.
- [x] 8.7 MCP keying: an MCP tool (prefixed name) and a same-named built-in function are tracked as distinct approvals.
- [x] 8.8 Atomic write: a simulated write failure leaves the prior `tool_permissions.json` intact.

## 9. Docs

- [x] 9.1 Update `CHANGELOG` noting the **BREAKING** default-on confirmation and the `TOOL_CONFIRM=false` opt-out. (Added an Unreleased section; the breaking marker should also ride the commit message for the changelog generator.)
- [x] 9.2 Document `TOOL_CONFIRM` and `tool_permissions.json` in the README/config reference.
