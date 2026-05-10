## Why

DeepSeek's thinking mode returns and requires `reasoning_content`, but YAICLI currently serializes stored assistant reasoning as `reasoning` for OpenAI-format messages. This can break DeepSeek thinking conversations with tool calls because the API requires `reasoning_content` to be replayed in later turns.

## What Changes

- Add DeepSeek-specific request support for `REASONING_EFFORT` so users can set thinking intensity through existing configuration.
- Preserve user-provided `EXTRA_BODY` while allowing `{"thinking": {"type": "enabled"}}` to be sent to DeepSeek through the existing config path.
- Convert stored assistant reasoning back to `reasoning_content` for DeepSeek messages, especially assistant messages that include tool calls.
- Keep existing response parsing and reasoning display behavior, which already maps `reasoning_content` into YAICLI's internal reasoning field.
- Add tests covering DeepSeek completion params, message conversion, and tool-call reasoning replay.
- Document how to configure DeepSeek thinking mode and note parameters that DeepSeek ignores while thinking is enabled.

## Capabilities

### New Capabilities

- `deepseek-thinking-mode`: Defines how YAICLI enables DeepSeek thinking mode, forwards thinking intensity, and preserves DeepSeek `reasoning_content` across normal and tool-call turns.

### Modified Capabilities

(none -- existing specs do not cover provider-specific thinking behavior)

## Impact

- **DeepSeek provider** (`yaicli/llms/providers/deepseek_provider.py`): add provider-specific parameter mapping and message conversion.
- **Message conversion contract** (`ChatMessage.reasoning` to provider payload): ensure DeepSeek receives `reasoning_content` rather than the generic `reasoning` field.
- **Tests** (`tests/llms/`): add focused DeepSeek provider coverage without real API calls.
- **Documentation** (`docs/providers/deepseek.md`, README provider examples if needed): describe thinking configuration and limitations.
