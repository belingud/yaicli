## Context

YAICLI represents model reasoning internally as `ChatMessage.reasoning` and `LLMResponse.reasoning`. OpenAI-compatible providers share the base `Provider._convert_messages()` implementation, which serializes assistant reasoning as `reasoning`.

DeepSeek's thinking mode uses a different wire field: responses return `reasoning_content`, and follow-up requests must replay assistant reasoning as `reasoning_content` when tool calls occurred in the conversation. The current response parsing already extracts `reasoning_content`, but the replay path sends the wrong field name for DeepSeek.

DeepSeek also exposes thinking intensity through the OpenAI-format `reasoning_effort` request parameter. The generic OpenAI provider supports this parameter, but the current DeepSeek provider parameter map does not include it.

## Goals / Non-Goals

**Goals:**

- Allow DeepSeek users to configure thinking mode through existing `EXTRA_BODY` and `REASONING_EFFORT` settings.
- Preserve DeepSeek `reasoning_content` in request replay for assistant messages stored in YAICLI history.
- Keep the fix provider-scoped so other OpenAI-compatible providers continue to use their current message formats.
- Cover normal and tool-call DeepSeek message conversion with unit tests.
- Document the DeepSeek thinking configuration and known ignored sampling parameters.

**Non-Goals:**

- Add a new DeepSeek-specific CLI flag or configuration key for thinking mode.
- Change YAICLI's internal `ChatMessage.reasoning` data model.
- Redesign saved chat persistence for tool calls and reasoning metadata.
- Implement Anthropic-format DeepSeek thinking controls.
- Make real DeepSeek API calls in tests.

## Decisions

### D1: Use existing configuration keys for thinking controls

**Choice:** Keep `EXTRA_BODY` as the way to send `{"thinking": {"type": "enabled"}}` or `{"thinking": {"type": "disabled"}}`, and add `reasoning_effort` to DeepSeek's existing completion parameter map.

**Alternative considered:** Add new config keys such as `DEEPSEEK_THINKING` and `DEEPSEEK_REASONING_EFFORT`.

**Rationale:** YAICLI already has generic config paths for provider-specific request body fields and reasoning effort. Reusing them avoids new config surface area and matches the current provider architecture.

### D2: Do not force-enable thinking in the provider

**Choice:** The provider should not inject a `thinking` object when the user has not configured one.

**Alternative considered:** Automatically add `{"thinking": {"type": "enabled"}}` to every DeepSeek request.

**Rationale:** DeepSeek documents thinking as enabled by default for supported thinking models, and not every DeepSeek-compatible model necessarily accepts the same controls. Preserving explicit user config is safer and keeps non-thinking DeepSeek usage unchanged.

### D3: Override only DeepSeek message conversion

**Choice:** `DeepSeekProvider` should override `_convert_messages()` and serialize assistant reasoning as `reasoning_content`.

**Alternative considered:** Change the base `Provider._convert_messages()` implementation from `reasoning` to `reasoning_content`.

**Rationale:** Other providers already rely on provider-specific reasoning formats. A global field-name change risks breaking OpenRouter, MiniMax, and other OpenAI-compatible endpoints. DeepSeek is the provider with a documented requirement for `reasoning_content` replay.

### D4: Replay all stored assistant reasoning as `reasoning_content`

**Choice:** When a DeepSeek assistant message has `ChatMessage.reasoning`, serialize it as `reasoning_content` whether or not the message also has tool calls.

**Alternative considered:** Only serialize reasoning for assistant messages with tool calls.

**Rationale:** DeepSeek requires reasoning replay when tool calls occurred, and the API ignores unnecessary reasoning content in ordinary multi-turn conversations. Replaying all stored assistant reasoning keeps conversion simple and avoids incorrectly dropping a reasoning segment from a multi-step tool turn.

### D5: Keep response parsing in the base OpenAI provider

**Choice:** Continue using the existing extraction of `reasoning_content` from normal responses and stream deltas.

**Alternative considered:** Duplicate response parsing in `DeepSeekProvider`.

**Rationale:** Existing tests already cover the generic extraction path, and the current behavior maps DeepSeek's response field into `LLMResponse.reasoning`. The missing behavior is outbound replay, not inbound parsing.

## Risks / Trade-offs

**[Saved chat sessions lose reasoning and tool metadata]** -> A persisted chat resumed after a DeepSeek tool-call thinking turn may not contain enough metadata to replay the exact API-required context. Mitigation: keep this change scoped to live request compatibility and call out persistence as a follow-up if needed.

**[Provider-specific parameter support varies by model]** -> Some DeepSeek models may ignore or reject thinking controls differently. Mitigation: do not auto-inject thinking controls; only forward user-configured values.

**[Sampling parameters are ignored in thinking mode]** -> Users may expect `temperature`, `top_p`, or penalties to affect thinking responses. Mitigation: document that DeepSeek ignores these parameters while thinking is enabled.

**[Reasoning replay can add tokens]** -> Replaying reasoning on ordinary non-tool turns may add request payload size, even if DeepSeek ignores it. Mitigation: keep behavior limited to stored assistant reasoning and rely on DeepSeek's documented ignore behavior for non-tool multi-turn contexts.

## Migration Plan

No data migration is required.

Implementation sequence:

1. Update `DeepSeekProvider.COMPLETION_PARAMS_KEYS` to include `reasoning_effort`.
2. Add a DeepSeek-specific `_convert_messages()` implementation that emits `reasoning_content` for assistant reasoning.
3. Add unit tests for completion parameters and message conversion with reasoning plus tool calls.
4. Update DeepSeek provider documentation with thinking mode configuration examples and limitations.

Rollback strategy:

- Revert the DeepSeek provider and documentation changes. No persisted state changes are introduced.

## Open Questions

- Whether saved chat persistence should later store `reasoning`, `tool_calls`, and `tool_call_id` for exact provider replay after reload. This is broader than DeepSeek thinking and remains outside this change.
