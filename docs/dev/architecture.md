# Architecture Overview

This page describes how YAICLI is put together and where to start when changing it. User-facing
behaviour is documented under `docs/usage/`; coding conventions live in `CLAUDE.md` and
`.trellis/spec/`.

## Request flow

```
entry.py (Typer CLI)
  └─ cli.py (CLI: mode dispatch, REPL, tool-confirmation pump)
       ├─ llms/client.py (LLMClient: provider call + tool loop + streaming)
       │    └─ llms/provider.py (ProviderFactory -> Provider)
       │         └─ llms/providers/<name>_provider.py
       ├─ tools/__init__.py (tool schemas, execute_tool_call, output panels)
       │    ├─ tools/function.py (built-in functions from ~/.config/yaicli/functions/)
       │    └─ tools/mcp.py (MCP tools, lazy fastmcp import)
       ├─ chat.py (Chat model + FileChatManager persistence)
       └─ printer.py / render.py (streaming, reasoning, markdown, prompts)
```

`entry.py` parses arguments, merges piped stdin, processes `--image`, then builds a `CLI` and
calls `cli.run(...)`. `CLI` decides between the single-shot path (`_run_once`) and the REPL
(`_run_repl`); both assemble messages and ask `LLMClient.completion_with_tools()` for a
response stream. Tool calls come back through the same generator and are executed after the
confirmation gate, then the loop calls the provider again with the tool results.

## Module map

| Module | Responsibility |
| --- | --- |
| `entry.py` | Typer app/options, stdin/image handling, top-level error → exit-code mapping. |
| `cli.py` | `CLI` orchestrator: temp/chat/exec modes, REPL, chat save/load, role wiring. |
| `cmd_handler.py` | Slash commands (`/add`, `/context`, `/save`, `/mode`, ...) and `!shell`. |
| `config.py` | Layered `cfg` singleton: env > `config.ini` > defaults; type conversion. |
| `const.py` | Defaults (`DEFAULT_CONFIG_MAP`), paths, commands/modes, default roles. |
| `console.py` | `YaiConsole` singleton + untrusted-text helpers (`safe_text`, `print_untrusted`, ...). |
| `context.py` | `/add` persistent context and `@path` temporary references (dirs, binaries, images). |
| `chat.py` | `Chat` message model, JSON serialization, atomic saves, `FileChatManager`. |
| `history.py` | Bounded prompt-toolkit history file (`~/.yaicli_history`). |
| `role.py` | `Role`/`RoleManager`, role JSON files under `~/.config/yaicli/roles/`. |
| `schemas.py` | Shared dataclasses crossing layers: `ChatMessage`, `LLMResponse`, `ToolCall`, `ToolPolicy`. |
| `printer.py` / `render.py` | Streaming output, reasoning, confirmation prompts, markdown rendering. |
| `image.py` | `--image` validation, MIME detection, base64/URL handling. |
| `function_schema.py` | `OpenAISchema`: pydantic model → OpenAI/Anthropic tool schemas. |
| `functions/` | Built-in function templates (`buildin/`) and install/reinstall/list callbacks. |
| `llms/` | `LLMClient`, provider ABC/registry, one module per provider. |
| `tools/` | Tool schema aggregation/caching, function loading, MCP integration, approval store. |
| `utils.py` | Shell/OS detection, `str2bool`, option callbacks, event-loop helper. |

## State on disk

- `~/.config/yaicli/config.ini` — configuration (`ai --template` prints the defaults).
- `~/.config/yaicli/roles/`, `functions/`, `mcp.json`, `tool_permissions.json` — user data.
- `~/.yaicli_history` — prompt history (bounded by `MAX_HISTORY`).
- `CHAT_HISTORY_DIR` (temp directory by default) — saved chat JSON sessions.

## Modes

`TEMP_MODE` (single-shot), `CHAT_MODE` (REPL) and `EXEC_MODE` (generate + confirm a shell
command) are the only runtime modes. `--code` is not a runtime mode: it selects the
`Code Assistant` role and a plain-text printer. `--shell` always uses the
`Shell Command Generator` role.

## Tool-calling loop

1. A per-request `ToolPolicy` decides whether functions/MCP tools are advertised.
2. Provider responses carry zero or more complete `ToolCall`s (streaming providers aggregate
   per tool index).
3. `LLMClient` evaluates the policy, runs each call through the confirmation gate
   (`TOOL_CONFIRM`) and `execute_tool_call()`.
4. Tool results are appended as messages and the provider is called again, up to
   `MAX_TOOL_CALL_DEPTH` rounds.

## Where to read next

- `CLAUDE.md` — commands, conventions, module overview.
- `.trellis/spec/py/index.md` — layer-specific coding guidelines.
- `docs/dev/add-provider.md`, `docs/dev/debug-cli.md` — provider tutorial and debugging.
- `tests/` — the executable contract; `tests/conftest.py` shows the isolated test environment.
