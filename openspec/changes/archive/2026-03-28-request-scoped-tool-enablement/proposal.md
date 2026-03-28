## Why

Interactive `exec` mode is supposed to generate a plain shell command, but the current implementation disables tools by mutating shared configuration when the mode changes. Because the LLM client and several providers cache tool flags at initialization time, `exec` requests can still advertise function or MCP tools depending on provider behavior, which makes command generation inconsistent and undermines the mode boundary.

## What Changes

- Define tool enablement for interactive requests at request time instead of relying on mutable global config set during mode switches
- Require interactive `exec` mode requests to disable all tools, including built-in function tools and MCP tools
- Preserve configured tool availability for interactive `chat` mode and other non-`exec` requests so switching modes does not permanently alter later requests
- Align client-side tool execution rules with request-scoped tool availability so disabled tools are neither sent to the model nor executed if a provider returns tool calls anyway
- Add tests covering interactive mode switching and provider request construction to ensure `exec` requests are tool-free

## Capabilities

### New Capabilities

- `interactive-tool-policy`: Defines how YAICLI decides tool availability for each interactive request, including the requirement that `exec` mode generates commands without exposing function or MCP tools while `chat` mode continues to honor configured tool support.

### Modified Capabilities

(none -- no existing specs)

## Impact

- **CLI orchestration** (`yaicli/cli.py`): interactive mode handling must pass request-scoped tool policy into LLM requests instead of mutating shared config as the primary control path
- **LLM client flow** (`yaicli/llms/client.py`): request handling must honor per-request tool flags for both outbound provider calls and recursive tool execution
- **Provider integrations** (`yaicli/llms/providers/*.py`): providers that currently cache `ENABLE_FUNCTIONS` or `ENABLE_MCP` at initialization must support per-request tool enablement
- **Mode-switch behavior** (`yaicli/cmd_handler.py` and interactive keybinding flow): switching between `chat` and `exec` must affect only the current request policy, not global tool state
- **Tests** (`tests/test_cli.py`, `tests/test_command_handler.py`, `tests/llms/*`): add or update coverage for mode switching, request-scoped tool suppression, and `exec` mode behavior across provider request builders
