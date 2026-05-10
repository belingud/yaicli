## 1. DeepSeek Provider

- [x] 1.1 Add `reasoning_effort` to `DeepSeekProvider.COMPLETION_PARAMS_KEYS`.
- [x] 1.2 Add DeepSeek-specific message conversion that serializes assistant `reasoning` as `reasoning_content`.
- [x] 1.3 Ensure DeepSeek assistant messages with tool calls preserve `tool_calls` while using `reasoning_content`.
- [x] 1.4 Ensure DeepSeek tool response messages preserve `tool_call_id`.

## 2. Tests

- [x] 2.1 Add DeepSeek provider tests for forwarding `EXTRA_BODY` thinking controls unchanged.
- [x] 2.2 Add DeepSeek provider tests for forwarding `REASONING_EFFORT`.
- [x] 2.3 Add DeepSeek message conversion tests for assistant reasoning without tool calls.
- [x] 2.4 Add DeepSeek message conversion tests for assistant reasoning with tool calls.
- [x] 2.5 Add DeepSeek message conversion tests for tool response replay.
- [x] 2.6 Add or reuse response parsing tests proving DeepSeek `reasoning_content` maps to `LLMResponse.reasoning`.

## 3. Documentation

- [x] 3.1 Update DeepSeek provider docs with thinking mode configuration examples.
- [x] 3.2 Document that DeepSeek thinking mode ignores `temperature`, `top_p`, `presence_penalty`, and `frequency_penalty`.
- [x] 3.3 Document that saved chat replay of reasoning and tool metadata is outside this change if not implemented.
- [x] 3.4 Update README DeepSeek provider section with thinking mode configuration.

## 4. Verification

- [x] 4.1 Run targeted DeepSeek/OpenAI provider tests.
- [x] 4.2 Run formatting or lint checks for touched Python files.
- [x] 4.3 Run OpenSpec status or validation for `support-deepseek-thinking-mode`.
