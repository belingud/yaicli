# Architecture Overview

This page describes how YAICLI is put together and where to start when changing it. User-facing
behaviour is documented under `docs/usage/`; coding conventions live in `CLAUDE.md` and
`.trellis/spec/`.

## Request flow

```
_faststart.py (thin console entry; -v/--version fast path, EPIPE-safe)
  └─ entry.py (Typer CLI; headless flags -> CLI.configure_headless, exit-code mapping)
       └─ cli.py (CLI: assembly, mode dispatch, REPL, tool-confirmation pump)
       ├─ llms/client.py (LLMClient: provider call + tool loop + streaming)
       │    └─ llms/provider.py (ProviderFactory -> Provider)
       │         └─ llms/providers/<name>_provider.py
       ├─ commands/registry.py (one definition for dispatch, help and completion)
       ├─ cmd_handler.py (bound handlers; named session/planning operations)
       ├─ application/session.py (chat state, persistence and checkpoint coordination)
       ├─ application/output.py (result state, machine events and exit mapping)
       ├─ application/state.py (shared run options)
       ├─ planning/coordinator.py (plan interaction and application coordination)
       │    ├─ planning/model.py / validation.py (session models and input validation)
       │    ├─ planning/service.py / store.py (state transitions and persistence)
       │    └─ planning/prompt.py / editor.py (context text and editor adapter)
       ├─ tools/__init__.py (compatible public schema/execution entry points)
       │    ├─ tools/schemas.py (selection, declarations, mode and caches)
       │    ├─ tools/policy.py (permission decisions; no confirmation IO)
       │    ├─ tools/executor.py (dispatch, guard/capture/undo and result processing)
       │    ├─ tools/display.py (tool announcements, previews and panels)
       │    ├─ tools/function.py (package builtins, overridden by same-name user functions)
       │    └─ tools/mcp.py (MCP tools, lazy fastmcp import)
       ├─ chat.py (Chat model + FileChatManager persistence)
       └─ printer.py / render.py (streaming, reasoning, markdown, prompts)
```

`_faststart.main` answers `-v/--version` without importing the config/role/CLI stack (zero
filesystem writes) and otherwise delegates to `entry.py`. `entry.py` parses arguments (including
the headless flags), merges piped stdin, processes `--image`, then builds a `CLI`, calls
`cli.configure_headless(...)` and `cli.run(...)`. `CLI` decides between the single-shot path
(`_run_once`) and the REPL (`_run_repl`); both assemble messages and ask
`LLMClient.completion_with_tools()` for a response stream. Tool calls come back through the same
generator and are executed after the confirmation gate, then the loop calls the provider again
with the tool results.

## Module map

| Module | Responsibility |
| --- | --- |
| `_faststart.py` | Console entry (`ai`, `yaicli`, `python -m yaicli`); static `--version` fast path, SIGPIPE/EPIPE handling; then delegates to `entry.py`. |
| `entry.py` | Typer app/options, stdin/image handling, headless flags, top-level error → exit-code mapping. |
| `cli.py` | Application assembly, temp/chat/exec dispatch, REPL, role wiring and generation/terminal lifecycle; compatible public properties delegate to the underlying state. |
| `application/session.py` | `SessionController`: one chat state, save/load/resume and checkpoint storage coordination, using the actual injected chat manager's directory. |
| `application/output.py` | `MachineOutput`/`ResultState`: result payloads, tool events, usage, errors and exit mapping; serialization does not eagerly construct a provider. |
| `application/state.py` | `RunState`: shared interaction/mode options, without a reference back to the CLI. |
| `planning/` | Models, validation, persistence, state operations, prompt formatting and editor adapter; `PlanCoordinator` connects them to session/output services and a small set of terminal lifecycle operations. |
| `plan_mode.py` / `plan_store.py` | Explicit compatibility exports for the planning implementation; no duplicate model classes or plan state. Product imports use `planning/`. |
| `errors.py` | `ErrorKind`/`AgentError`, exception classification, retry helpers, `EXIT_*` constants. |
| `commands/registry.py` | Immutable command metadata: handler name, aliases, help and argument policy; generates dispatch metadata and slash completions. |
| `cmd_handler.py` | Binds registry entries to command methods; slash command business logic and `!shell`; preserves existing metadata/constant exports. |
| `commands/session.py` / `planning.py` / `runtime.py` | Session, plan and model/role/retry command groups use named services and operations; their business logic does not reach into CLI private state. |
| `config.py` | Layered `cfg` singleton: env > `config.ini` > defaults; type conversion. |
| `const.py` | Defaults (`DEFAULT_CONFIG_MAP`), paths, commands/modes, default roles. |
| `console.py` | `YaiConsole` singleton, stderr console for machine mode, EPIPE-safe broken-pipe handling, untrusted-text helpers. |
| `context.py` | `/add` persistent context and `@path` temporary references (dirs, binaries, images). |
| `chat.py` | `Chat` message model, JSON serialization, atomic saves, `FileChatManager`; v0.21 K13 per-project session store (`~/.yaicli/sessions/<hash>/`, `0700`/`0600`), session metadata and `--resume`. |
| `history.py` | Bounded prompt-toolkit history file (`$XDG_STATE_HOME/yaicli/history` or `~/.yaicli_history`, mode `0600`). |
| `role.py` | `Role`/`RoleManager`, role JSON files under `~/.config/yaicli/roles/`. |
| `project_context.py` | v0.21 K12: discovers `.yaicli.md`/`AGENTS.md`/`CLAUDE.md` from cwd to the git root and builds the bounded system-prompt block. |
| `schemas.py` | Shared dataclasses crossing layers: `ChatMessage`, `LLMResponse`, `ToolCall`, `ToolPolicy`. |
| `printer.py` / `render.py` | Streaming output, reasoning, confirmation prompts, markdown rendering. |
| `image.py` | `--image` validation, MIME detection, base64/URL handling. |
| `function_schema.py` | `OpenAISchema`: pydantic model → OpenAI/Anthropic tool schemas. |
| `functions/` | Built-in function templates (`buildin/`) and install/reinstall/list callbacks. |
| `llms/` | `LLMClient`, provider ABC/registry, one module per provider. |
| `tools/` | Public entry points delegate to `schemas.py`, `policy.py`, `executor.py` and `display.py`; `function.py` loads functions, `mcp.py` adapts MCP, `approval.py` stores grants/rules, `risk.py` classifies risk. |
| `utils.py` | Shell/OS detection, `str2bool`, option callbacks, event-loop helper. |

## State on disk

The config directory is resolved at import time: `YAI_CONFIG_DIR` > `XDG_CONFIG_HOME/yaicli` >
`%APPDATA%/yaicli` (Windows) > `~/.config/yaicli`.

- `<config-dir>/config.ini` — configuration, created lazily on the first run that needs it and
  written with mode `0600` (`ai --template` prints the defaults).
- `<config-dir>/roles/`, `functions/`, `mcp.json`, `tool_permissions.json` — user data.
  `functions_manifest.json` records the version/hashes used to warn about stale exported copies.
- `<config-dir>/tool_audit.jsonl` — tool audit log; `<tempdir>/yaicli/chats/tool-outputs/` —
  spilled (untruncated) tool outputs (`TOOL_OUTPUT_DIR` overrides; see
  `docs/usage/context-limits.md` and `docs/usage/permissions.md`).
- `$XDG_STATE_HOME/yaicli/history` or `~/.yaicli_history` — prompt history (bounded by
  `MAX_HISTORY`, mode `0600`).
- `~/.yaicli/sessions/<sha256(resolved cwd)[:16]>/` — saved chat JSON sessions per project (dirs
  `0700`, files `0600`); an explicit `CHAT_HISTORY_DIR` override keeps the old flat directory.

## Modes

`TEMP_MODE` (single-shot), `CHAT_MODE` (REPL) and `EXEC_MODE` (generate + confirm a shell
command) are the only runtime modes. `--code` is not a runtime mode: it selects the
`Code Assistant` role and a plain-text printer. `--shell` always uses the
`Shell Command Generator` role.

## Tool-calling loop

1. A per-request `ToolPolicy` decides whether functions/MCP tools are advertised.
2. Provider responses carry zero or more complete `ToolCall`s (streaming providers aggregate
   per tool index).
3. `tools/policy.py` evaluates permission/risk decisions. `LLMClient` keeps the confirmation
   generator (`yield ConfirmToolCall` / `send`), remembered grants and audit, then calls the compatible
   `execute_tool_call()` entry point. `tools/executor.py` owns actual dispatch, workspace mutation
   capture/undo and one result-truncation/history pass; `tools/display.py` renders its preview.
4. Tool results are appended as messages and the provider is called again, up to
   `MAX_TOOL_CALL_DEPTH` rounds.

Command registration and tool execution remain separate boundaries. Add a handler and one
`CommandInfo` entry to extend the slash command set; help and completion derive from that same
entry. Session and planning coordination receive concrete dependencies rather than the CLI;
the CLI retains generation threads, confirmation and terminal lifecycle. Core planning models,
validation and storage do not import the CLI or terminal presentation code. Builtin/user/MCP
loading contracts and public tool entry points are preserved; Gemini retains its existing
callable/MCP declaration path.

## Where to read next

- `CLAUDE.md` — commands, conventions, module overview.
- `.trellis/spec/py/index.md` — layer-specific coding guidelines.
- `docs/dev/add-provider.md`, `docs/dev/debug-cli.md` — provider tutorial and debugging.
- `tests/` — the executable contract; `tests/conftest.py` shows the isolated test environment.
