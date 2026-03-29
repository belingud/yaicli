## ADDED Requirements

### Requirement: Interactive requests resolve tool availability from the current request context
The system SHALL determine built-in function tool availability and MCP tool availability for each interactive LLM request from the current request context rather than from stale state captured before a mode switch. Function tools and MCP tools MUST be evaluated independently.

#### Scenario: Exec request overrides configured tool defaults
- **WHEN** interactive chat starts with `ENABLE_FUNCTIONS=true` and `ENABLE_MCP=true`, the user switches to `exec` mode, and submits a prompt
- **THEN** the resulting LLM request SHALL treat both function tools and MCP tools as disabled for that request

#### Scenario: Chat request uses configured defaults
- **WHEN** an interactive request is made outside `exec` mode with `ENABLE_FUNCTIONS=false` and `ENABLE_MCP=true`
- **THEN** the resulting LLM request SHALL disable built-in function tools and enable MCP tools for that request

### Requirement: Exec mode requests do not advertise tools
When an interactive request is made in `exec` mode, the system SHALL generate the request without advertising any callable tools to the model. The request MUST omit both built-in function tool definitions and MCP tool definitions, and it MUST omit any provider-specific automatic tool selection parameters that depend on those tool definitions.

#### Scenario: OpenAI-family exec request omits tools
- **WHEN** the active provider uses OpenAI-style request parameters and the user submits a prompt in interactive `exec` mode
- **THEN** the provider request SHALL be sent without a `tools` payload for that turn

#### Scenario: Anthropic-family exec request omits tool configuration
- **WHEN** the active provider uses Anthropic-style request parameters and the user submits a prompt in interactive `exec` mode
- **THEN** the provider request SHALL be sent without tool definitions and without automatic tool choice configuration for that turn

### Requirement: Mode switching does not permanently alter non-exec tool behavior
Switching between interactive modes SHALL affect only the effective tool availability of the current request. It MUST NOT permanently change the configured tool behavior used by later non-`exec` requests.

#### Scenario: Returning to chat restores configured tools
- **WHEN** interactive chat starts with `ENABLE_FUNCTIONS=true` and `ENABLE_MCP=true`, the user switches to `exec` mode for one request, then switches back to `chat` mode and submits another prompt
- **THEN** the `chat` mode request SHALL again advertise both built-in function tools and MCP tools

#### Scenario: Returning to chat preserves configured disablement
- **WHEN** interactive chat starts with `ENABLE_FUNCTIONS=false` and `ENABLE_MCP=false`, the user switches to `exec` mode and then back to `chat` mode
- **THEN** the later `chat` mode request SHALL continue to advertise no tools

### Requirement: Disabled tool calls are ignored and not persisted
If a provider returns a tool call that is not permitted for the current request, the system SHALL ignore that tool call. The system SHALL NOT execute it, and it SHALL NOT persist the disallowed tool call in assistant history for later turns.

#### Scenario: Disallowed function tool call is dropped
- **WHEN** an interactive request is made with built-in function tools disabled and the provider returns a built-in function tool call
- **THEN** the system SHALL not execute the tool call and SHALL store the assistant turn without that tool call in conversation history

#### Scenario: Disallowed MCP tool call is dropped
- **WHEN** an interactive request is made with MCP tools disabled and the provider returns an MCP tool call
- **THEN** the system SHALL not execute the MCP tool call and SHALL store the assistant turn without that tool call in conversation history

#### Scenario: Allowed tool call continues normal execution
- **WHEN** an interactive request is made with a tool type enabled and the provider returns a tool call of that enabled type
- **THEN** the system SHALL execute the tool call and continue the conversation with the tool result
