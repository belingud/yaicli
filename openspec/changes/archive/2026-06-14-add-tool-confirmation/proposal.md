## Why

Today YAICLI executes every model-requested tool call silently and immediately. A model can run shell commands, MCP tools, or other side-effecting functions without the user getting a chance to review or stop them. Users need the same per-call control that tools like Claude Code provide: confirm a call once, stop being asked for a tool this session, or permanently allow a tool — and be able to refuse.

## What Changes

- Add an execution-confirmation gate that runs after tool-availability filtering and before each tool call is executed.
- Present a four-way prompt for any tool that is not already approved:
  - **once** — execute this call only;
  - **session** — execute and stop asking for this tool name for the rest of the process;
  - **always** — execute and persist approval for this tool name across runs;
  - **deny** — do not execute; return a refusal result to the model so the conversation continues.
- Persist "always allow" decisions to a dedicated file `~/.config/yaicli/tool_permissions.json` (a tool-name allowlist), independent of `config.ini`.
- Add a master switch `TOOL_CONFIRM` (env `YAI_TOOL_CONFIRM`), **default `true`**. **BREAKING**: tool calls now require confirmation by default; setting `TOOL_CONFIRM=false` restores the previous silent-execution behavior.
- Define non-interactive behavior (no TTY / piped stdin): tools on the persistent allowlist run; all others are denied with a hint to pre-approve or disable confirmation.
- Key the allowlist by the tool name as seen at the gate (MCP names keep their `_mcp__` prefix) so MCP tools and same-named built-in functions never collide.

## Capabilities

### New Capabilities
- `tool-execution-confirmation`: Per-call confirmation of tool execution with once / session / persistent-allow / deny outcomes, a master enable switch, a persisted per-tool allowlist, and defined non-interactive behavior.

### Modified Capabilities
- `interactive-tool-policy`: An allowed tool call no longer executes unconditionally — it proceeds to execution subject to the execution-confirmation policy. The "allowed tool call continues normal execution" behavior is refined to account for the confirmation gate.

## Impact

- **Behavior**: Tool calls require confirmation by default in interactive sessions; existing users relying on silent function execution must set `TOOL_CONFIRM=false` or pre-approve tools.
- **Code**: `yaicli/schemas.py` (new control signal, decision type), `yaicli/llms/client.py` (confirmation gate in the tool-execution loop), `yaicli/printer.py` (stream pump handles the confirmation signal and pauses the live display), `yaicli/cli.py` (wires the approval manager and non-interactive policy), `yaicli/const.py` (new config key and permissions path), and a new `yaicli/tools/approval.py`.
- **Files/Config**: New `~/.config/yaicli/tool_permissions.json`; new `TOOL_CONFIRM` config key.
- **Providers**: Provider-agnostic — all providers funnel tool execution through a single chokepoint, so no per-provider changes are required.
