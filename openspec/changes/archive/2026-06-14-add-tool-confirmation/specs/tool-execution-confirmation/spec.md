## ADDED Requirements

### Requirement: Tool execution requires confirmation by default

When tool-execution confirmation is enabled, the system SHALL prompt the user to approve a tool call before executing it, unless the tool has already been approved for the current session or in the persistent allowlist. Confirmation SHALL be governed by a `TOOL_CONFIRM` setting (environment variable `YAI_TOOL_CONFIRM`) that defaults to enabled. The confirmation gate SHALL run after tool-availability filtering, so only tool calls already permitted for the request can reach it.

#### Scenario: First call to an unapproved tool prompts the user
- **WHEN** confirmation is enabled and the model returns a permitted tool call for a tool that is not in the session or persistent allowlist
- **THEN** the system SHALL prompt the user to approve the call before executing it

#### Scenario: Master switch disables confirmation
- **WHEN** `TOOL_CONFIRM` is disabled and the model returns a permitted tool call
- **THEN** the system SHALL execute the tool call without prompting, matching the prior silent-execution behavior

### Requirement: Confirmation offers once, session, persistent, and deny outcomes

The confirmation prompt SHALL offer four outcomes: execute only the current call (once), execute and stop asking for this tool name for the remainder of the process (session), execute and persist approval for this tool name across runs (persistent), and refuse the call (deny).

#### Scenario: Approve once executes only the current call
- **WHEN** the user approves a tool call for the current call only
- **THEN** the system SHALL execute that call and SHALL prompt again the next time the same tool is called

#### Scenario: Approve for session suppresses later prompts
- **WHEN** the user approves a tool for the session and the same tool is called again later in the same process
- **THEN** the system SHALL execute the later call without prompting

#### Scenario: Deny does not execute the tool
- **WHEN** the user denies a tool call
- **THEN** the system SHALL NOT execute the tool

### Requirement: Persistent approval survives across runs

When the user grants persistent approval for a tool, the system SHALL record the tool name in a persistent allowlist stored at `~/.config/yaicli/tool_permissions.json`, written so a partial write cannot corrupt the existing file. On a later run, a tool present in the persistent allowlist SHALL execute without prompting.

#### Scenario: Persistent approval is recorded
- **WHEN** the user grants persistent approval for a tool
- **THEN** the tool name SHALL be added to the persistent allowlist file

#### Scenario: A new run honors the persistent allowlist
- **WHEN** a new process starts with a tool already present in the persistent allowlist and that tool is called
- **THEN** the system SHALL execute the call without prompting

### Requirement: Denied tool calls return a refusal result to the model

When a tool call is denied, the system SHALL NOT execute the tool and SHALL append a tool result message whose tool-call identifier matches the denied call, indicating the user declined execution, so the conversation can continue and the provider request remains valid.

#### Scenario: Deny appends a matched refusal result
- **WHEN** a tool call is denied
- **THEN** the system SHALL append a tool result for that call's identifier stating the user declined, and SHALL continue the conversation

#### Scenario: Multi-call turn with a denial stays valid
- **WHEN** the model returns multiple tool calls in one turn and at least one is denied
- **THEN** every tool call in the turn SHALL have a corresponding tool result message before the next provider request

### Requirement: Non-interactive sessions do not block on prompts

When confirmation is enabled but the session is non-interactive (no controlling TTY, such as piped stdin), the system SHALL NOT block waiting for input. Tools present in the persistent allowlist SHALL execute; all other tools SHALL be denied, and the system SHALL surface a hint to pre-approve the tool or disable confirmation.

#### Scenario: Allowlisted tool runs without a TTY
- **WHEN** the session is non-interactive and a called tool is in the persistent allowlist
- **THEN** the system SHALL execute the tool without prompting

#### Scenario: Non-allowlisted tool is denied without a TTY
- **WHEN** the session is non-interactive and a called tool is not in the persistent allowlist
- **THEN** the system SHALL deny the call and surface a hint to pre-approve it or disable confirmation

### Requirement: Approval is keyed by tool name with MCP prefix preserved

The system SHALL key session and persistent approvals by the tool name as observed at the confirmation gate. MCP tool names SHALL retain their MCP prefix so that an MCP tool and a built-in function sharing the same base name are tracked as distinct approvals.

#### Scenario: MCP tool and same-named function are distinct
- **WHEN** a built-in function and an MCP tool resolve to the same base name and one of them is approved
- **THEN** approving one SHALL NOT suppress the confirmation prompt for the other

### Requirement: Interrupting the prompt cancels the call

When the user interrupts the confirmation prompt (for example via Ctrl-C or end-of-input), the system SHALL treat the interruption as a denial of the current call rather than allowing an unhandled error to propagate.

#### Scenario: Interrupt at the prompt denies the call
- **WHEN** the user interrupts the confirmation prompt for a tool call
- **THEN** the system SHALL treat the call as denied and continue without executing the tool
