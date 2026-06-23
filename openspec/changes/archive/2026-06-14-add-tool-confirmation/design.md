## Context

YAICLI executes every model-requested tool call immediately and silently. All providers (OpenAI, Anthropic, Gemini, etc.) funnel tool execution through a single chokepoint: `execute_tool_call()` in `yaicli/tools/__init__.py`, invoked from the loop in `LLMClient._execute_tools_and_continue()` (`yaicli/llms/client.py`). Gemini does not bypass this — it disables the SDK's automatic function calling and yields `ToolCall` objects like the other providers, so a single gate covers every provider.

The tool-execution loop runs inside a generator that `Printer.display_stream()` drives while a Rich `Live` region is active. Reading stdin for a confirmation prompt while `Live` is refreshing corrupts the terminal, so prompting requires coordinating with the live display. The existing `RefreshLive` control signal already models live-control as a value yielded out of the generator, which this change follows. (A sibling `StopLive` class is defined but unused; it is left as-is, since the pump stops the live region directly via `_safe_stop_live`.)

Tool availability is already filtered upstream by `interactive-tool-policy` (`_get_valid_tool_calls`). Confirmation layers on top: only already-permitted calls reach the gate. `exec` mode disables all tools, so it is unaffected.

Configuration is a flat `config.ini` under `[core]` with env (`YAI_*`) overrides; there is no config write-back API, and `config.ini` carries hand-written comments that `configparser.write()` would strip.

## Goals / Non-Goals

**Goals:**
- Confirm each tool call before execution, with outcomes: once, session, persistent-allow, deny.
- Default to confirmation on, with a master switch (`TOOL_CONFIRM`) to restore silent execution.
- Persist per-tool approvals across runs without disturbing `config.ini`.
- Keep the feature provider-agnostic by gating at the single execution chokepoint.
- Behave safely and non-blocking in non-interactive sessions.

**Non-Goals:**
- Batch "approve all" for a multi-call turn (each call is confirmed independently).
- Argument-level confirmation or editing arguments before execution.
- A permissions management TUI / slash command (the JSON file is hand-editable for now).
- Changing `exec` mode's existing command confirmation.

## Decisions

### Gate location: the tool-execution loop, not `execute_tool_call()`
The confirmation gate lives in `LLMClient._execute_tools_and_continue()`, just before each `execute_tool_call()`. The loop is a method with access to instance state (the approval manager), whereas `execute_tool_call()` is a module-level pure function. This keeps execution mechanism separate from approval policy. There is exactly one call site today, so coverage is complete.

### Signal-based prompt coordination (chosen) over an injected callback
The generator yields a new `ConfirmToolCall(tool_call)` signal; `display_stream()` receives it, stops the live region, renders the call, prompts, and resumes the generator via `gen.send(decision)`. `yield from` transparently forwards the sent value through the delegation chain to `_execute_tools_and_continue()`.

- *Alternative considered*: inject a `confirmer` callback into `LLMClient` and have it reach into the printer to pause the live. Rejected because the callback would run re-entrantly inside `next(gen)` while the printer's loop frame is suspended, and it couples the client to live-display internals.
- *Why signal wins*: `display_normal()` is dead code, so `display_stream()` is the only consumer to update; when the signal surfaces, control is back in the printer's own frame with the generator cleanly suspended at the `yield`, so stopping/restarting `Live` has no re-entrancy. It also matches the existing `RefreshLive` control-signal idiom.

### Persistent approvals in a dedicated JSON file
"Always allow" is written to `~/.config/yaicli/tool_permissions.json` (a tool-name allowlist), not `config.ini`. `configparser.write()` would strip the file's comments, and there is no existing write-back path. A dedicated file matches the project's convention of separate `mcp.json` and `roles/`. Writes use a temp-file + atomic rename so a crash mid-write cannot corrupt the list.

### Per-tool-name granularity, keyed at the gate
Approvals are keyed by tool name. The key is captured at the gate, where MCP names still carry their `_mcp__` prefix — `execute_tool_call()` strips that prefix in place at execution time, so recording later would lose it and could collide an MCP tool with a same-named built-in function. The global escape hatch is `TOOL_CONFIRM=false` rather than a separate "allow all" entry.

### Default on, with a master switch
`TOOL_CONFIRM` (env `YAI_TOOL_CONFIRM`, type bool) defaults to `true`. This is a behavior change for existing users; `TOOL_CONFIRM=false` restores prior silent execution. Registered in `DEFAULT_CONFIG_MAP`, so the default applies even for config files that predate the key.

### Deny returns a matched tool result
Denial does not raise; it appends a tool result message whose `tool_call_id` matches the denied call, stating the user declined. OpenAI-style providers require every `tool_call` in an assistant turn to have a matching tool result, so skipping would 400 the next request. This also lets the model adapt to the refusal.

### Non-interactive policy
When `sys.stdin.isatty()` is false (piped stdin / no TTY), the gate does not block: allowlisted tools execute, all others are denied with a hint to pre-approve or set `TOOL_CONFIRM=false`.

## Risks / Trade-offs

- **Breaking default (silent → confirm)** → Mitigation: `TOOL_CONFIRM=false` master switch; call out in CHANGELOG; the change is marked BREAKING in the proposal.
- **`display_stream` pump rewrite (for-loop → next/send)** → Mitigation: single consumer; cover with tests for the signal round-trip and live stop/restart.
- **`display_normal` is dead code and would not honor confirmation if revived** → Mitigation: note in code; if a non-stream display path is reintroduced it must handle `ConfirmToolCall`.
- **Multiple prompts in one multi-tool turn** → Accepted for v1; batch approval is a v2 non-goal.
- **Concurrent processes writing the allowlist** → Atomic rename prevents corruption; last-writer-wins on the set is acceptable for an allowlist.
- **Prompt interruption (Ctrl-C / EOF)** → Caught and treated as deny, mirroring `exec` mode's `_confirm_and_execute` EOF handling, so it never propagates as an unhandled error.
- **Duplicate call display** → `execute_tool_call()` already prints `@Function call: ...`; the confirmation prompt shows the same call, so one of the two must be suppressed when the gate prompts.

## Migration Plan

- Ship with `TOOL_CONFIRM=true`. Document in CHANGELOG that tool calls now require confirmation and how to opt out.
- `tool_permissions.json` is created lazily (empty allowlist) on first persistent approval; absence means "nothing pre-approved".
- Rollback for a user is `TOOL_CONFIRM=false`; rollback for the project is reverting the change (no persisted state migration needed).

## Open Questions

- Should a later version add a management command (e.g., `/tools` or `--reset-permissions`) to list/revoke persistent approvals? Deferred; the JSON file is hand-editable in v1.
- Should there be an explicit global "allow all tools" allowlist entry in addition to the master switch? Deferred in favor of `TOOL_CONFIRM=false`.
