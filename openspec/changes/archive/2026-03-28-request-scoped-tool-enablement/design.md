## Context

YAICLI currently controls tool availability through a mix of shared config mutation and cached provider state.

- `CLI.set_role()` mutates `cfg["ENABLE_FUNCTIONS"]` when switching to shell or coder roles
- `LLMClient` copies `ENABLE_FUNCTIONS` and `ENABLE_MCP` from config at initialization time
- Many providers also cache those flags at initialization, while a few read config on each request

This creates an inconsistent state model. In interactive `exec` mode, the shell prompt is active, but the outbound request may still advertise function or MCP tools if the client or provider cached the old values. The problem is cross-cutting because request behavior is split across `cli.py`, `llms/client.py`, and multiple provider implementations.

There is also a secondary correctness issue in the current client flow: tool calls are attached to the assistant history before tool enablement is checked. If a provider returns tool calls for a request that should not use tools, YAICLI can retain an unexecuted tool trace in conversation history.

## Goals / Non-Goals

**Goals:**
- Make tool availability an explicit per-request decision instead of a side effect of mutating global config
- Ensure `exec` mode requests never send built-in function tools or MCP tools
- Ensure tool execution recursion follows the same per-request policy as outbound request construction
- Preserve configured tool defaults for non-`exec` requests so mode switching does not permanently alter later requests
- Prevent disabled or unexpected tool calls from polluting assistant history
- Keep the change compatible with the current provider architecture and existing config model

**Non-Goals:**
- Redesign the function or MCP tool schema formats
- Add fine-grained per-tool allowlists or policy rules beyond on/off toggles for functions and MCP
- Change chat history storage format on disk
- Introduce new dependencies or a provider capability registry

## Decisions

### D1: Introduce an explicit request-scoped tool policy object

**Choice:** Add a small shared data object, for example `ToolPolicy`, with:

- `enable_functions: bool`
- `enable_mcp: bool`

This object is passed with each request instead of relying on `cfg` mutation to communicate runtime intent.

**Alternative considered:** Continue mutating `cfg`, `LLMClient`, and provider instance flags during mode switches.

**Rationale:** Shared mutable state is the root problem. It is easy for one layer to miss an update, and provider behavior already differs depending on whether flags are cached or read dynamically. An explicit per-request policy makes the active behavior visible at the call site and keeps request semantics local to the request being processed.

### D2: Resolve tool policy at the CLI request boundary

**Choice:** The CLI computes the effective tool policy immediately before calling `LLMClient`.

Planned behavior:
- `exec` mode: `enable_functions=False`, `enable_mcp=False`
- all other modes: use configured defaults from `cfg["ENABLE_FUNCTIONS"]` and `cfg["ENABLE_MCP"]`

`CLI.set_role()` remains responsible for prompt and display behavior, but no longer acts as the primary mechanism for mutating tool configuration.

**Alternative considered:** Infer the policy later from role name or current provider behavior.

**Rationale:** `CLI` already owns mode state (`chat`, `exec`, `temp`) and is the narrowest point where request intent is known. Resolving policy there keeps mode semantics separate from provider transport logic. This also intentionally removes the hidden coupling where non-`exec` behavior can change because a previous mode switch modified global config.

### D3: Thread the policy through `LLMClient` and providers

**Choice:** Extend request APIs to accept the effective tool policy.

Likely shape:
- `LLMClient.completion_with_tools(..., tool_policy: ToolPolicy | None = None)`
- `Provider.completion(..., tool_policy: ToolPolicy | None = None)`

Provider code resolves tools from the passed policy when present, otherwise from config defaults. This keeps direct provider usage backward compatible while making the interactive path explicit.

Implementation guidance:
- Keep existing `enable_function` / `enable_mcp` instance attributes as cached defaults if needed for compatibility
- Add a shared helper to resolve the effective policy so provider families do not duplicate fallback logic
- Update provider-specific tool assembly points:
  - OpenAI-like providers: `get_tools(...)`
  - Anthropic/Mistral providers: request parameter assembly inside `completion(...)`
  - Gemini: `get_chat_config(...)` / `gen_gemini_functions(...)`
  - Cohere and any dynamic providers: override config defaults when a request policy is supplied

**Alternative considered:** Store the request policy temporarily on the client/provider instance and restore it after the call.

**Rationale:** Temporary instance mutation is safer than mutating global config, but it still leaves shared mutable state in the critical path. Passing the policy as an argument keeps recursion, provider calls, and tests straightforward.

### D4: Filter tool calls before persisting assistant history

**Choice:** `LLMClient` should treat the resolved request policy as the source of truth for both execution and history.

Behavior:
- collect raw tool calls from the provider response as today
- filter them against the effective request policy
- only attach allowed tool calls to the assistant message stored in `messages`
- only emit `RefreshLive`, execute tools, and recurse when at least one allowed tool call remains

If the provider returns tool calls even though tools were disabled, YAICLI should ignore them for execution and omit them from saved assistant history. A verbose log message is sufficient for debugging.

**Alternative considered:** Keep raw tool calls in history even when execution is disabled.

**Rationale:** Persisting a tool call without a matching tool response produces an invalid conversation trace. Dropping disabled tool calls keeps the history coherent and prevents later turns from replaying an incomplete tool interaction back to the model.

### D5: Non-`exec` requests become config-driven rather than role-driven

**Choice:** Outside `exec` mode, tool availability follows config defaults instead of implicit role side effects.

This means the request policy is determined by request mode and config, not by whether the active prompt happens to be `DEFAULT`, `CODER`, or another role.

**Alternative considered:** Preserve the current special case where the coder role implicitly disables functions.

**Rationale:** Role names describe prompting behavior, not transport capabilities. Keeping tool policy tied to roles would reintroduce hidden state rules and weaken the design goal of request-scoped behavior. If users want coder-mode requests without tools, config remains the explicit control.

## Risks / Trade-offs

**[Broad provider API touch surface]** → Adding an optional request policy parameter affects many provider classes and related tests. → Mitigation: keep the new parameter optional, add a shared resolution helper, and update providers family-by-family with focused tests.

**[Behavioral change for coder or other non-`exec` requests]** → Requests that previously lost tool access because of role switching may now honor configured defaults. → Mitigation: document the new config-driven rule in change notes and cover it with CLI tests so the behavior is intentional rather than accidental.

**[Unexpected provider tool calls become silent drops]** → Some proxy providers may still emit tool calls when none were advertised. → Mitigation: drop them from execution/history but log the skip in verbose mode for debugging.

**[Missed provider override]** → A provider that still reads cached flags internally could continue sending tools incorrectly. → Mitigation: add request-construction tests for representative provider families and use the shared helper at every tool assembly point.

## Migration Plan

No data migration is required.

Implementation sequence:
1. Add the shared request-scoped tool policy type and default-resolution helper
2. Update CLI request handling to compute policy from mode instead of mutating config for tool control
3. Update `LLMClient` to use the effective policy for provider calls, tool filtering, and recursion
4. Update provider request builders to honor the passed policy
5. Add regression tests for mode switches, request construction, and disabled-tool history handling

Rollback strategy:
- Revert the code change set; there is no persisted state or user data to migrate back

## Open Questions

None at this stage. The main semantics are now decided:
- `exec` mode disables both function and MCP tools
- non-`exec` requests use configured defaults
- disabled tool calls are dropped rather than persisted
