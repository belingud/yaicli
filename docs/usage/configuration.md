# Configuration Guide

YAICLI uses a layered configuration system to store your preferences and API keys. This guide explains all available configuration options and how to customize them.

## Configuration Hierarchy

YAICLI follows this priority order for configuration:

1. Command-line arguments (highest priority)
2. Environment variables
3. Configuration file
4. Default values (lowest priority)

## Configuration File

### Location

YAICLI resolves its configuration directory in this order:

1. `YAI_CONFIG_DIR` (explicit override)
2. `XDG_CONFIG_HOME/yaicli`
3. `%APPDATA%/yaicli` on Windows
4. `~/.config/yaicli` (fallback, e.g. Linux/macOS without XDG set)

The configuration file is `config.ini` inside that directory. It may contain an API key, so it is
created with mode `0600` (and the directory with `0700`). On a read-only HOME or container, YAICLI
keeps working with defaults and only warns once when it cannot persist state.

The prompt history file follows XDG state conventions: `$XDG_STATE_HOME/yaicli/history` when
`XDG_STATE_HOME` is set, otherwise `~/.yaicli_history`.

### First-time Setup

1. Run a real model command once (e.g. `ai "hi"`); the default configuration file is created on first use
2. Edit the file to add your API key and customize settings (or export `YAI_API_KEY` instead)

`--version` and `--help` never write state, so they are safe in read-only environments.

### Viewing Default Configuration

To view the default configuration template:

```bash
ai --template
```

## Configuration File Structure

The configuration file uses the INI format with the following sections:

```ini
[core]
PROVIDER=openai
BASE_URL=
API_KEY=
MODEL=gpt-5.2

DEFAULT_ROLE=DEFAULT
# auto detect shell and os (or specify manually, e.g., bash, zsh, powershell.exe)
SHELL_NAME=auto
OS_NAME=auto

# true: streaming response, false: non-streaming
STREAM=true

# LLM parameters
TEMPERATURE=0.3
FREQUENCY_PENALTY=0.0
TOP_P=1.0
MAX_TOKENS=1024
TIMEOUT=60
# JSON strings
EXTRA_HEADERS=
EXTRA_BODY=
REASONING_EFFORT=

# Interactive mode parameters
INTERACTIVE_ROUND=25

# UI/UX
CODE_THEME=monokai
# Max entries kept in history file
MAX_HISTORY=500
AUTO_SUGGEST=true
# Print reasoning content or not
SHOW_REASONING=true
# Text alignment (default, left, center, right, full)
JUSTIFY=default

# Chat history settings (v0.21 K13: sessions are per project by default)
# Explicit override: keep the old flat directory. Leave/remove the line (or keep the
# built-in default value) to use ~/.yaicli/sessions/<hash of the working directory>/.
# CHAT_HISTORY_DIR=/home/me/yaicli-sessions
MAX_SAVED_CHATS=20

# Role settings
# Set to false to disable warnings about modified built-in roles
ROLE_MODIFY_WARNING=true

# Function settings
# Set to false to disable sending functions in API requests
ENABLE_FUNCTIONS=true
# Set to false to disable showing function output in the response
SHOW_FUNCTION_OUTPUT=true
# Comma-separated tool-name globs to offer the model (empty = all tools).
# Builtin and MCP tools are both matched; MCP names carry the _mcp__ prefix.
ENABLED_TOOLS=

# MCP settings
ENABLE_MCP=false
SHOW_MCP_OUTPUT=false
# Seconds one MCP list/call operation may take (0 = no timeout)
MCP_TIMEOUT=30
# Max MCP tools offered to the model per request (0 = unlimited)
MCP_MAX_TOOLS=64

# Observability & cost (v0.22)
# Print one token/cost line after each interactive turn
SHOW_USAGE=true
# json string overriding the built-in price table, e.g.
# {"gpt-4o": {"input": 2.5, "output": 10}}  (USD per 1M tokens)
MODEL_PRICING=

# Provider-specific settings
# MiniMax: request reasoning content separately (interleaved thinking); ignored by others
MINIMAX_REASONING_SPLIT=true
# Anthropic: true = one tool call per response (compatibility default); false = allow parallel calls
DISABLE_PARALLEL_TOOL_USE=true

# Tool confirmation (set to false to restore silent execution)
TOOL_CONFIRM=true

# Session-wide tool permission mode (v0.21): readonly | standard | trusted
# readonly: auto-allow read/network tools only; write/exec tools are always denied
# standard: ask for confirmation / use tool_permissions.json rules (default)
# trusted: auto-allow every non-dangerous tool (dangerous shell commands still ask)
TOOL_POLICY=standard

# Maximum recursive tool-call rounds per request
MAX_TOOL_CALL_DEPTH=8

# Comma-separated API parameters to omit from requests, e.g. temperature,top_p
EXCLUDE_PARAMS=

# Agent context settings (v0.19)
# Max characters of one tool result kept in the context (0 = no truncation);
# the full output is saved to TOOL_OUTPUT_DIR.
TOOL_OUTPUT_MAX_CHARS=32000
# Scratch directory for full (untruncated) tool outputs; independent of the
# per-project session store. Defaults to <tempdir>/yaicli/chats/tool-outputs.
TOOL_OUTPUT_DIR=<tempdir>/yaicli/chats/tool-outputs
# Redact known secret shapes (API keys, tokens, private keys, ...) before tool
# output and saved sessions are written to disk. The model still sees the real
# content; only the on-disk copies are sanitized.
REDACT_SECRETS=true
# Terminal display of tool results (v0.19.1): head-only preview; the model still
# receives TOOL_OUTPUT_MAX_CHARS. 0 = show everything.
TOOL_DISPLAY_MAX_LINES=15
TOOL_DISPLAY_MAX_CHARS=4000
# Max characters of the "@Function call:" argument line (0 = raw arguments).
TOOL_CALL_PREVIEW_MAX_CHARS=300
# Token budget for one request; 0 = derive from the model context window
# (window - MAX_TOKENS - CONTEXT_SAFETY_TOKENS). Set explicitly to override.
CONTEXT_BUDGET_TOKENS=0
# Model context windows (JSON): "model" / "provider:model" / "provider/model"
# keys; values are token counts or {"window": N, "max_output": M}.
# Empty = resolve via learned/metadata/catalog/heuristic layers.
MODEL_CONTEXT_WINDOWS={}
# Probe provider metadata (OpenRouter / Gemini / Ollama) for the model window.
ENABLE_MODEL_METADATA=true
# Safety headroom kept below (window - MAX_TOKENS) when deriving the request budget.
CONTEXT_SAFETY_TOKENS=1024
# Cache resolved windows under <config-dir>/cache/model_limits.json.
ENABLE_MODEL_LIMITS_CACHE=true

# Project context settings (v0.21 K12)
# Auto-load .yaicli.md / AGENTS.md / CLAUDE.md from the working directory up to the
# git root and add them to the system prompt. false = no project-file reads at all.
ENABLE_PROJECT_CONTEXT=true
# Max characters of project instructions added to the system prompt
# (0 = no cap; a truncated block prints one warning naming the files involved).
PROJECT_CONTEXT_MAX_CHARS=20000

# Plan mode (v0.24 K23)
# Persistent read-only planning mode: Shift+Tab / /plan, submit_plan -> approve -> todo execution.
PLAN_ENABLED=true
# Maximum number of steps accepted in one plan.
PLAN_MAX_STEPS=20
# Finished (done/aborted) plan files kept per project; older ones are pruned.
PLAN_KEEP=80
# Allow a fixed read-only shell allowlist while planning (true/false).
PLAN_ALLOW_READONLY_SHELL=true
# Plans root directory (empty = <config-dir>/plans).
PLAN_DIR=

# Shell tool settings (v0.19)
# Max seconds a shell command may run (killed with its process group on timeout).
TOOL_TIMEOUT=120
# true = pass the full parent environment to shell commands (old behaviour);
# false = filtered environment, secrets such as YAI_API_KEY are not passed.
TOOL_ENV_INHERIT=false
# Workspace root for shell cwd and guarded file writes (empty = current directory).
WORKSPACE_ROOT=

# Reliability settings (v0.19)
RETRY_ENABLED=true
RETRY_MAX=2
RETRY_BASE_DELAY=1.0
# Maximum delay between retries in seconds (caps the exponential backoff)
RETRY_MAX_DELAY=8.0
# Exit non-zero in one-shot mode when the tool-call depth limit is reached.
EXIT_ON_DEPTH_LIMIT=true

# Tool audit log (v0.19)
# Write one JSON line per tool decision to tool_audit.jsonl in the config dir.
TOOL_AUDIT=true
```

> Comments in `config.ini` must be on their own line. Inline comments are **not** stripped by
> the INI parser and become part of the value (e.g. `PROVIDER=openai  # note` would make the
> provider name invalid).

## Configuration Options Reference

| Option                 | Description                                 | Default                  | Environment Variable       |
| ---------------------- | ------------------------------------------- | ------------------------ | -------------------------- |
| `PROVIDER`             | LLM provider (openai, anthropic, cohere, etc.) | `openai`              | `YAI_PROVIDER`             |
| `BASE_URL`             | Provider API base URL (OpenAI-compatible ones usually end with `/v1`) | - | `YAI_BASE_URL` |
| `API_KEY`              | Your API key                                | -                        | `YAI_API_KEY`              |
| `MODEL`                | LLM model to use                            | `gpt-5.2`                | `YAI_MODEL`                |
| `DEFAULT_ROLE`         | Default role                                | `DEFAULT`                | `YAI_DEFAULT_ROLE`         |
| `SHELL_NAME`           | Shell type                                  | `auto`                   | `YAI_SHELL_NAME`           |
| `OS_NAME`              | Operating system                            | `auto`                   | `YAI_OS_NAME`              |
| `STREAM`               | Enable streaming                            | `true`                   | `YAI_STREAM`               |
| `TIMEOUT`              | API timeout (seconds)                       | `60`                     | `YAI_TIMEOUT`              |
| `EXTRA_HEADERS`        | Extra headers                               | -                        | `YAI_EXTRA_HEADERS`        |
| `EXTRA_BODY`           | Extra body                                  | -                        | `YAI_EXTRA_BODY`           |
| `REASONING_EFFORT`     | Reasoning effort                            | -                        | `YAI_REASONING_EFFORT`     |
| `DISABLE_PARALLEL_TOOL_USE` | Anthropic: send `disable_parallel_tool_use` (`true` = one tool call per response, the compatibility default; `false` = allow parallel calls) | `true` | `YAI_DISABLE_PARALLEL_TOOL_USE` |
| `INTERACTIVE_ROUND`    | Interactive mode rounds                     | `25`                     | `YAI_INTERACTIVE_ROUND`    |
| `CODE_THEME`           | Syntax highlighting theme                   | `monokai`                | `YAI_CODE_THEME`           |
| `TEMPERATURE`          | Response randomness                         | `0.3`                    | `YAI_TEMPERATURE`          |
| `FREQUENCY_PENALTY`    | Frequency penalty                           | `0.0`                    | `YAI_FREQUENCY_PENALTY`    |
| `TOP_P`                | Top-p sampling                              | `1.0`                    | `YAI_TOP_P`                |
| `MAX_TOKENS`           | Max response tokens (reserved from the context window) | `1024`          | `YAI_MAX_TOKENS`           |
| `MAX_HISTORY`          | Max history entries                         | `500`                    | `YAI_MAX_HISTORY`          |
| `AUTO_SUGGEST`         | Enable history suggestions                  | `true`                   | `YAI_AUTO_SUGGEST`         |
| `SHOW_REASONING`       | Enable reasoning display                    | `true`                   | `YAI_SHOW_REASONING`       |
| `JUSTIFY`              | Text alignment                              | `default`                | `YAI_JUSTIFY`              |
| `CHAT_HISTORY_DIR`     | Explicit session-directory override (old flat layout); a value equal to the built-in default means the per-project store | *unset* (per-project `~/.yaicli/sessions/<hash>/`) | `YAI_CHAT_HISTORY_DIR` |
| `MAX_SAVED_CHATS`      | Max saved sessions per store                | `20`                     | `YAI_MAX_SAVED_CHATS`      |
| `ROLE_MODIFY_WARNING`  | Warn when modifying built-in roles          | `true`                   | `YAI_ROLE_MODIFY_WARNING`  |
| `ENABLE_FUNCTIONS`     | Enable function calling                     | `true`                   | `YAI_ENABLE_FUNCTIONS`     |
| `SHOW_FUNCTION_OUTPUT` | Show function output                        | `true`                   | `YAI_SHOW_FUNCTION_OUTPUT` |
| `ENABLED_TOOLS`        | Comma-separated tool-name globs offered to the model (`fnmatch`; MCP names keep the `_mcp__` prefix; empty = all tools) | - | `YAI_ENABLED_TOOLS` |
| `ENABLE_MCP`           | Enable MCP tools                            | `false`                  | `YAI_ENABLE_MCP`           |
| `SHOW_MCP_OUTPUT`      | Show MCP output                             | `false`                  | `YAI_SHOW_MCP_OUTPUT`      |
| `MCP_TIMEOUT`          | Seconds one MCP list/call operation may take (`0` = no timeout) | `30` | `YAI_MCP_TIMEOUT` |
| `MCP_MAX_TOOLS`        | Max MCP tools offered to the model per request (`0` = unlimited) | `64` | `YAI_MCP_MAX_TOOLS` |
| `SHOW_USAGE`           | Print one token/cost line after each interactive turn | `true`          | `YAI_SHOW_USAGE`           |
| `MODEL_PRICING`        | JSON price overrides: `{"model-prefix": {"input": 2.5, "output": 10}}` (USD per 1M tokens) | - | `YAI_MODEL_PRICING` |
| `MAX_TOOL_CALL_DEPTH`  | Max tool calls in one request               | `8`                      | `YAI_MAX_TOOL_CALL_DEPTH`  |
| `TOOL_CONFIRM`         | Confirm each tool call before running it    | `true`                   | `YAI_TOOL_CONFIRM`         |
| `TOOL_POLICY`          | Session-wide tool permission mode: `readonly`, `standard` or `trusted` (see [Permissions & Safety](permissions.md#permission-modes-tool_policy)) | `standard` | `YAI_TOOL_POLICY` |
| `TOOL_OUTPUT_MAX_CHARS` | Max characters of one tool result kept in context (`0` = unlimited) | `32000` | `YAI_TOOL_OUTPUT_MAX_CHARS` |
| `TOOL_OUTPUT_DIR`      | Where full (untruncated) tool outputs are saved | `<tempdir>/yaicli/chats/tool-outputs` | `YAI_TOOL_OUTPUT_DIR` |
| `REDACT_SECRETS`       | Redact known secret shapes before tool output/sessions are written to disk | `true` | `YAI_REDACT_SECRETS` |
| `TOOL_DISPLAY_MAX_LINES` | Terminal preview: max lines of one tool result shown (`0` = unlimited) | `15` | `YAI_TOOL_DISPLAY_MAX_LINES` |
| `TOOL_DISPLAY_MAX_CHARS` | Terminal preview: max characters shown; the model cap is `TOOL_OUTPUT_MAX_CHARS` | `4000` | `YAI_TOOL_DISPLAY_MAX_CHARS` |
| `TOOL_CALL_PREVIEW_MAX_CHARS` | Max characters of the `@Function call:` argument line (`0` = raw) | `300` | `YAI_TOOL_CALL_PREVIEW_MAX_CHARS` |
| `CONTEXT_BUDGET_TOKENS` | Token budget per request (`0` = derive from the window − `MAX_TOKENS` − `CONTEXT_SAFETY_TOKENS`; `> 0` = verbatim override) | `0` | `YAI_CONTEXT_BUDGET_TOKENS` |
| `MODEL_CONTEXT_WINDOWS` | JSON per-model context windows (empty = resolve via provider metadata/catalog/heuristic); keys may be `model`, `provider:model` or `provider/model`, values an int or `{"window": N, "max_input": M, "max_output": M}` | - | `YAI_MODEL_CONTEXT_WINDOWS` |
| `ENABLE_MODEL_METADATA` | Probe provider metadata (OpenRouter `/models`, Gemini `models.get`, Ollama `/api/show`) for the model context window | `true` | `YAI_ENABLE_MODEL_METADATA` |
| `CONTEXT_SAFETY_TOKENS` | Extra headroom kept below `window - MAX_TOKENS` when deriving the request budget | `1024` | `YAI_CONTEXT_SAFETY_TOKENS` |
| `ENABLE_MODEL_LIMITS_CACHE` | Cache resolved windows in `<config-dir>/cache/model_limits.json` (provider metadata 7 days, learned limits 30 days) | `true` | `YAI_ENABLE_MODEL_LIMITS_CACHE` |
| `ENABLE_PROJECT_CONTEXT` | Auto-load project instruction files into the system prompt (`false` = no project-file reads) | `true` | `YAI_ENABLE_PROJECT_CONTEXT` |
| `PROJECT_CONTEXT_MAX_CHARS` | Max characters of project context added to the system prompt (`0` = no cap) | `20000` | `YAI_PROJECT_CONTEXT_MAX_CHARS` |
| `PLAN_ENABLED`         | Enable persistent plan mode (`Shift+Tab` / `/plan`; `false` hides it and `--plan` exits `2`) | `true` | `YAI_PLAN_ENABLED` |
| `PLAN_MAX_STEPS`       | Maximum number of steps accepted in one submitted plan | `20` | `YAI_PLAN_MAX_STEPS` |
| `PLAN_KEEP`            | Finished (done/aborted) plan files kept per project; older ones are pruned (draft/in-progress plans are never auto-deleted) | `80` | `YAI_PLAN_KEEP` |
| `PLAN_ALLOW_READONLY_SHELL` | Expose the fixed read-only shell allowlist while planning | `true` | `YAI_PLAN_ALLOW_READONLY_SHELL` |
| `PLAN_DIR`             | Plans root directory (empty = `<config-dir>/plans`; plans are isolated per project) | - | `YAI_PLAN_DIR` |
| `TOOL_TIMEOUT`         | Max seconds a shell tool command may run    | `120`                    | `YAI_TOOL_TIMEOUT`         |
| `TOOL_ENV_INHERIT`     | Pass the full parent environment to shell tools (old behaviour) | `false` | `YAI_TOOL_ENV_INHERIT` |
| `WORKSPACE_ROOT`       | Workspace root: shell `cwd` and guarded file writes must stay inside it (empty = current dir; see [Workspace Safety](workspace-safety.md)) | - | `YAI_WORKSPACE_ROOT` |
| `RETRY_ENABLED`        | Retry retryable API failures (429/5xx/network/timeout) | `true`         | `YAI_RETRY_ENABLED`        |
| `RETRY_MAX`            | Maximum retry attempts                      | `2`                      | `YAI_RETRY_MAX`            |
| `RETRY_BASE_DELAY`     | Base backoff delay in seconds               | `1.0`                    | `YAI_RETRY_BASE_DELAY`     |
| `RETRY_MAX_DELAY`      | Maximum backoff delay in seconds (cap)      | `8.0`                    | `YAI_RETRY_MAX_DELAY`      |
| `EXIT_ON_DEPTH_LIMIT`  | Exit non-zero in one-shot mode when the tool-round limit is reached | `true` | `YAI_EXIT_ON_DEPTH_LIMIT` |
| `TOOL_AUDIT`           | Write tool decisions to `tool_audit.jsonl`  | `true`                   | `YAI_TOOL_AUDIT`           |
| `EXCLUDE_PARAMS`       | Comma-separated API parameters to omit      | -                        | `YAI_EXCLUDE_PARAMS`       |
| `MINIMAX_REASONING_SPLIT` | MiniMax interleaved reasoning (reasoning_split) | `true`            | `YAI_MINIMAX_REASONING_SPLIT` |


## Context Management

Conversation context is bounded on three levels; see
[Context & Limits](context-limits.md) for the full behaviour:

- **Per-tool truncation**: `TOOL_OUTPUT_MAX_CHARS` (default 32000 chars) keeps head/tail and
  spills the full output to `TOOL_OUTPUT_DIR`.
- **Token budget**: `CONTEXT_BUDGET_TOKENS` (default `0` = derive from the resolved model window as
  `window - MAX_TOKENS - CONTEXT_SAFETY_TOKENS`; `> 0` = verbatim override) is enforced before each
  request; over-budget history is trimmed by turn group, keeping assistant `tool_calls` and their
  tool results together. The window itself comes from `MODEL_CONTEXT_WINDOWS`, provider metadata,
  the bundled catalog or a family heuristic — see [Context & Limits](context-limits.md).
- **REPL retention**: `INTERACTIVE_ROUND` (default `25`) is the number of chat turns kept in the
  REPL (×2 messages), not a token limit. `MAX_HISTORY` (default `500`) only sizes the prompt
  history file (see [Conversation & History](../advanced/history.md)).
- **Project instructions**: `.yaicli.md` / `AGENTS.md` / `CLAUDE.md` are auto-loaded into the
  system prompt (`ENABLE_PROJECT_CONTEXT`, `PROJECT_CONTEXT_MAX_CHARS`; see
  [Project Context](project-context.md)).

Use `/context` to inspect the estimated usage and `/compact [keep_rounds]` to compact manually
(see [Command Reference](commands.md#interactive-mode-commands)).

## Chat Sessions

Since v0.21, chat sessions are isolated per project. With the default configuration `CHAT_HISTORY_DIR`
is unset, and sessions are stored in `~/.yaicli/sessions/<sha256(resolved cwd)[:16]>/` (directories
`0700`, session files `0600`). Setting an explicit `CHAT_HISTORY_DIR` that differs from the built-in
default (`<tempdir>/yaicli/chats`) restores the old flat directory for all projects; a value equal
to the built-in default counts as unset. `MAX_SAVED_CHATS` applies within the active store.

Each saved session records `model`, `provider`, `role`, `cwd`, `created_at` and `updated_at` in its
JSON, so a resumed session describes how it was produced. Sessions saved by older versions load
normally and are backfilled on their next save. Use `--resume` to continue the newest session of the
current project — see [Chat Sessions & Resume](sessions.md).

## Plan Mode

Plan mode is a read-only planning phase in the REPL, toggled with `Shift+Tab` / `/plan`. Its five
keys are `PLAN_ENABLED`, `PLAN_MAX_STEPS`, `PLAN_KEEP`, `PLAN_ALLOW_READONLY_SHELL` and `PLAN_DIR`.
Plan files are stored per project under `<config-dir>/plans/<project-key>/` and only the CLI writes
them. See [Plan Mode](plan-mode.md) for the full workflow.

## State Files

| Path | Purpose |
| --- | --- |
| `<config-dir>/config.ini` | Main configuration (mode `0600`) |
| `<config-dir>/roles/` | Role definitions |
| `<config-dir>/functions/` | User/exported function definitions |
| `<config-dir>/functions_manifest.json` | Version/hash manifest for stale copied-function detection |
| `<config-dir>/mcp.json` | MCP server configuration |
| `<config-dir>/tool_permissions.json` | Persistent tool allow rules (mode `0600`) |
| `<config-dir>/tool_audit.jsonl` | Tool decision audit log |
| `<tempdir>/yaicli/chats/tool-outputs/` | Spilled full tool outputs (legacy scratch dir; `TOOL_OUTPUT_DIR` overrides) |
| `~/.yaicli/sessions/<hash>/` | Saved chat sessions per project, mode `0700` dirs / `0600` files (or an explicit `CHAT_HISTORY_DIR`) |
| `<config-dir>/plans/<project-key>/` | Plan-mode plan files (`draft`/`in-progress`/`done`/`aborted`), mode `0700` dirs / `0600` files (or a `PLAN_DIR` override) |
| `$XDG_STATE_HOME/yaicli/history` or `~/.yaicli_history` | REPL prompt history (mode `0600`) |


## Syntax Highlighting Themes

YAICLI supports all Pygments syntax highlighting themes. Set your preferred theme with:

```ini
CODE_THEME = monokai
```

Browse available themes at: [https://pygments.org/styles/](https://pygments.org/styles/)

## Extra Headers and Body

You can add extra headers and body parameters to the API request:

```ini
EXTRA_HEADERS={"X-Extra-Header": "value"}
EXTRA_BODY={"extra_key": "extra_value"}
```

Example: Disable Qwen3's thinking behavior:

```ini
EXTRA_BODY={"enable_thinking": false}
```

Or limit thinking tokens:

```ini
EXTRA_BODY={"thinking_budget": 4096}
```

## Environment Variables

Every option in the reference table above can be set with its `YAI_*` environment variable
(these override the config file):

```bash
# Set API key via environment variable
export YAI_API_KEY="your-api-key"

# Use a different model
export YAI_MODEL="gpt-3.5-turbo"

# Disable streaming
export YAI_STREAM="false"
```

Environment variables take precedence over the configuration file settings.

Provider-specific keys that are not in the table (for example `HF_PROVIDER`, `AZURE_ENDPOINT`,
`AWS_*`, `AK`/`SK`) are read by the individual provider implementations from the config file or
their usual environment variables; they do not have a `YAI_` alias.

## Provider-Specific Configuration

See the [Providers section](../providers/overview.md) for detailed configuration options for each supported LLM provider.
