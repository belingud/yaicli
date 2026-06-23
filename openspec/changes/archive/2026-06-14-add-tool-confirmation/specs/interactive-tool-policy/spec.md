## MODIFIED Requirements

### Requirement: Disabled tool calls are ignored and not persisted
If a provider returns a tool call that is not permitted for the current request, the system SHALL ignore that tool call. The system SHALL NOT execute it, and it SHALL NOT persist the disallowed tool call in assistant history for later turns. A tool call that IS permitted for the current request SHALL proceed to the execution-confirmation policy, which decides whether it executes, rather than executing unconditionally.

#### Scenario: Disallowed function tool call is dropped
- **WHEN** an interactive request is made with built-in function tools disabled and the provider returns a built-in function tool call
- **THEN** the system SHALL not execute the tool call and SHALL store the assistant turn without that tool call in conversation history

#### Scenario: Disallowed MCP tool call is dropped
- **WHEN** an interactive request is made with MCP tools disabled and the provider returns an MCP tool call
- **THEN** the system SHALL not execute the MCP tool call and SHALL store the assistant turn without that tool call in conversation history

#### Scenario: Allowed tool call continues to the confirmation policy
- **WHEN** an interactive request is made with a tool type enabled and the provider returns a tool call of that enabled type
- **THEN** the system SHALL pass the tool call to the execution-confirmation policy, which determines whether it executes, and SHALL continue the conversation with the resulting tool result
