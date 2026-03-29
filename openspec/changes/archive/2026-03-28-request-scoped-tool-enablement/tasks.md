## 1. Request-Scoped Tool Policy

- [x] 1.1 Add a shared request-scoped tool policy type and helper for resolving effective `enable_functions` and `enable_mcp` values from request overrides or config defaults
- [x] 1.2 Update the provider request interface so completions can receive an optional per-request tool policy without breaking existing non-interactive call sites

## 2. CLI And Client Flow

- [x] 2.1 Update interactive CLI request handling in `yaicli/cli.py` to compute tool policy from the current mode, with `exec` mode forcing both tool types off and non-`exec` requests using configured defaults
- [x] 2.2 Remove mode-switch logic that relies on mutating shared config as the primary way to disable tools for interactive `exec` requests
- [x] 2.3 Update `LLMClient.completion_with_tools()` to pass the effective tool policy into provider calls and to use the same policy for recursive tool execution decisions
- [x] 2.4 Update `LLMClient` assistant message handling so disallowed tool calls are dropped before they are stored in conversation history

## 3. Provider Request Construction

- [x] 3.1 Update OpenAI-family provider tool assembly to honor the per-request tool policy when deciding whether to include `tools`
- [x] 3.2 Update Anthropic-family provider request construction to honor the per-request tool policy for both tool definitions and `tool_choice`
- [x] 3.3 Update Gemini provider request construction to honor the per-request tool policy when building `tools` and automatic function-calling configuration
- [x] 3.4 Update other tool-capable providers that currently cache or derive tool flags from config, including Mistral and config-driven providers such as Cohere or Ollama, so request-scoped policy overrides are applied consistently

## 4. Regression Tests

- [x] 4.1 Add CLI tests covering mode switches so an `exec` request disables both built-in function tools and MCP tools while a later `chat` request restores configured defaults
- [x] 4.2 Add `LLMClient` tests covering per-request tool filtering, including dropping disabled tool calls from execution and assistant history
- [x] 4.3 Add provider request-construction tests for representative families to verify `exec` requests omit tool payloads and provider-specific tool-selection parameters
- [x] 4.4 Add regression coverage for non-`exec` requests to verify configured tool defaults still apply when no `exec` override is active
