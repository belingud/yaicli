## ADDED Requirements

### Requirement: DeepSeek thinking request parameters
YAICLI SHALL allow DeepSeek requests to include thinking mode controls through existing configuration.

#### Scenario: Forward thinking configuration
- **WHEN** the DeepSeek provider is configured with `EXTRA_BODY={"thinking":{"type":"enabled"}}`
- **THEN** the DeepSeek completion request MUST include that `extra_body` value unchanged

#### Scenario: Forward reasoning effort
- **WHEN** the DeepSeek provider is configured with `REASONING_EFFORT=high`
- **THEN** the DeepSeek completion request MUST include `reasoning_effort` with value `high`

#### Scenario: Preserve disabled thinking configuration
- **WHEN** the DeepSeek provider is configured with `EXTRA_BODY={"thinking":{"type":"disabled"}}`
- **THEN** the DeepSeek completion request MUST preserve `thinking.type` as `disabled`

### Requirement: DeepSeek reasoning response handling
YAICLI SHALL expose DeepSeek `reasoning_content` responses through its internal reasoning stream.

#### Scenario: Non-streaming reasoning content
- **WHEN** a DeepSeek non-streaming response message contains `reasoning_content`
- **THEN** YAICLI MUST emit an `LLMResponse` whose `reasoning` contains that value

#### Scenario: Streaming reasoning content
- **WHEN** a DeepSeek streaming delta contains `reasoning_content`
- **THEN** YAICLI MUST emit an `LLMResponse` chunk whose `reasoning` contains that delta value

### Requirement: DeepSeek reasoning replay
YAICLI SHALL serialize stored assistant reasoning as DeepSeek `reasoning_content` when sending conversation history to DeepSeek.

#### Scenario: Assistant reasoning without tool calls
- **WHEN** a stored assistant message has `reasoning` and no tool calls
- **THEN** the DeepSeek message payload MUST contain `reasoning_content`
- **AND** the DeepSeek message payload MUST NOT contain the generic `reasoning` field

#### Scenario: Assistant reasoning with tool calls
- **WHEN** a stored assistant message has `reasoning` and one or more tool calls
- **THEN** the DeepSeek message payload MUST contain `reasoning_content`
- **AND** the DeepSeek message payload MUST preserve the assistant `tool_calls`
- **AND** the DeepSeek message payload MUST NOT contain the generic `reasoning` field

#### Scenario: Tool response replay
- **WHEN** a stored tool response references a DeepSeek assistant tool call by `tool_call_id`
- **THEN** the DeepSeek message payload MUST preserve that `tool_call_id`

### Requirement: Provider-scoped compatibility
YAICLI SHALL implement DeepSeek thinking replay without changing the message format of unrelated providers.

#### Scenario: Generic OpenAI-compatible providers
- **WHEN** a non-DeepSeek OpenAI-format provider converts an assistant message with `reasoning`
- **THEN** its existing provider-specific reasoning field behavior MUST remain unchanged
