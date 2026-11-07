# Headless & Scripting

YAICLI is designed to be scriptable: a one-shot run can be piped, redirected, parsed by `jq`, and
its exit code can be trusted by CI. This page documents that contract.

The rule is simple:

- **stdout** carries the result only (in `text`, `json` or `stream-json` form);
- **stderr** carries everything else — labels, tool previews, warnings, errors, retry/trim notices;
- the **exit code** describes the outcome.

## Quick examples

```bash
# One explicit one-shot run
ai -p "What is the capital of France?"

# Answer only, safe for shell substitution
summary=$(ai -q -p "Summarize README.md in one sentence")

# Machine-readable result
ai -p "List the files changed in the last commit" --output-format json | jq -r .content
# --json is a shorthand for --output-format json
ai -p "Summarize this repository" --json | jq -r .content

# Streaming events (one JSON object per line)
ai -p "Find and fix the failing test" --output-format stream-json | jq -c 'select(.type=="tool_call")'

# Pipe input into the agent
cat error.log | ai -p "Explain these errors and suggest a fix"

# CI: allow the shell tool for this run and fail the step when a tool is denied
ai -p "Run the test suite and summarize failures" \
  --allowed-tools "execute_shell_command" -y --fail-on-tool-denied
```

## Input

| Method | Example | Behaviour |
| --- | --- | --- |
| Prompt argument | `ai "explain this repo"` | One-shot with the given prompt |
| Stdin | `echo hi \| ai` | Stdin content becomes the prompt |
| Both | `cat app.py \| ai "review this"` | Stdin content is prepended to the prompt argument |
| `-p/--print` | `ai -p "..."` | Explicit one-shot mode; never starts the REPL |

- When stdin is not a TTY, `--chat` is ignored (a warning is printed to stderr) because a REPL
  cannot read from a pipe.
- `-p/--print` is the explicit form of a one-shot run. Use it in scripts for clarity: it forces the
  headless contract (plain output, no prompts/REPL) even on a terminal. `--output-format` other
  than `text` and `-q` also imply one-shot; `--chat` is then ignored with a stderr warning.
- The REPL is only started by `--chat` (or by an interactive `ai` with no prompt).

## Output

### `--output-format text` (default)

Human-readable text. In a non-TTY (pipe/redirect) this is plain text: no banner, no Rich Live
animation, no ANSI/box drawing. The output ends with exactly one newline.

### `--output-format json`

One JSON object on stdout. All diagnostics go to stderr.

```json
{
  "content": "The final assistant answer as markdown text.",
  "tool_calls": [
    {"name": "fs_read_file", "arguments": {"file_paths": ["README.md"]}, "result": "..."}
  ],
  "usage": {"prompt_tokens": 1234, "completion_tokens": 456},
  "model": "gpt-5.2",
  "provider": "openai",
  "error": null,
  "exit_code": 0
}
```

| Field | Meaning |
| --- | --- |
| `content` | Final assistant answer text |
| `tool_calls` | Ordered list of tool calls made during the run |
| `usage` | Token usage (`{"prompt_tokens": ..., "completion_tokens": ...}`). v0.19 reports zeros here because usage is not yet propagated from providers |
| `model`, `provider` | Effective model/provider for this run |
| `error` | Exactly `null` on success, otherwise `{"kind": "<error kind>", "message": "<detail>"}`. Possible kinds: `auth`, `rate_limit`, `context_length`, `network`, `timeout`, `bad_request`, `provider`, `tool`, `config`, `depth_limit`, `interrupted`, `unknown` |
| `exit_code` | Exit code the process will return (see below) |

In v0.19 `usage` is intentionally reported as zeros — token usage from providers is not yet
propagated to the payload (token accounting lands in a later v0.19 change). One limitation:
failures that happen *before* a result exists (for example an invalid provider configuration, a
missing API key during client creation, or a usage error such as exit `2`) print a diagnostic to
stderr and exit non-zero **without** emitting the JSON object; every run that reaches a result
emits exactly one object. An interrupted one-shot run is reported both ways: exit `130` and, if
JSON output was active, `error.kind = "interrupted"`.

### `--output-format stream-json`

Newline-delimited JSON (NDJSON): one event object per line, in order. This is the format to use for
progress UIs, cancellation and tool-trace collection.

| Event | When | Fields |
| --- | --- | --- |
| `turn_start` | A model request starts | `type`, `turn` (0-based round index) |
| `text_delta` | The model streams answer text | `type`, `delta` (new text since the previous chunk) |
| `tool_call` | The model requests a tool | `type`, `name`, `arguments` (parsed JSON when possible) |
| `tool_result` | A tool has finished | `type`, `name`, `result` (the tool result text as seen by the model, truncated as in context) |
| `usage` | Token usage is reported | `type`, `prompt_tokens`, `completion_tokens` (zeros in v0.19) |
| `done` | The run finished | `type`, `exit_code`, `error` (`null` or `{kind, message}`) |

Events are flushed per line. `text_delta` events stream during generation; `tool_call` /
`tool_result` pairs are emitted at round boundaries (after the tools have executed), and `usage` /
`done` are emitted at the end. Every event object has a `type` field; unknown event types must be
ignored by consumers so that new event kinds can be added without breaking scripts. Example:

```json
{"type": "turn_start", "turn": 0}
{"type": "text_delta", "delta": "I will check the "}
{"type": "tool_call", "name": "fs_read_file", "arguments": {"file_paths": ["README.md"]}}
{"type": "tool_result", "name": "fs_read_file", "result": "# YAICLI ..."}
{"type": "usage", "prompt_tokens": 0, "completion_tokens": 0}
{"type": "done", "exit_code": 0, "error": null}
```

### `-q/--quiet`

Only the answer on stdout: no labels, no tool preview boxes, no progress. Errors still go to
stderr. Combine with `-p` and either text or JSON output.

## Streaming and the terminal

Streaming stays on by default in a TTY. With a pipe or a redirect, YAICLI disables the Live region
and cursor animation and prints the result plainly, so `ai ... > file.md` produces a clean file.
Without `-p`, `-q` or a non-`text` output format, a TTY keeps the normal rich experience
(labels and panels); the machine contract applies as soon as output is piped.

Use `--no-stream` if you want a single final block instead of streamed chunks.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success: an answer was produced (also informational commands such as `--version` / `--list-*`) |
| `1` | Handled failure: invalid config/provider, auth/API error, network failure, no input, unexpected error |
| `2` | Usage error: invalid option or argument (including an unknown `--output-format` value or an invalid `--cwd`) |
| `3` | A tool was denied and `--fail-on-tool-denied` was set |
| `130` | Interrupted by SIGINT (Ctrl+C) during a one-shot run or generation |
| `141` | Broken pipe (EPIPE): the producer side of a pipeline such as `ai --help \| head -1`. If the write wins the race, the same command may exit `0`; it never exits `1` for a closed pipe. |

Inside the interactive REPL, an error during one turn is printed and the session continues; leaving
the REPL normally exits `0`. Use one-shot (`-p` / prompt argument) when the exit code must reflect
the request outcome.

## Signals

### SIGINT (Ctrl+C)

- **One-shot runs** (including while the answer is generating): interrupts, prints one short line
  to stderr and exits `130` — no traceback.
- **REPL prompt**: a single Ctrl+C clears the current input and stays in the REPL; pressing it a
  second time within ~2 seconds exits normally.
- **REPL generation**: cancels the turn and returns to the prompt (a second Ctrl+C at the prompt exits).
- **Ctrl+D** at the REPL prompt exits normally with `0`.

### EPIPE (`| head`, closed pipes)

Writing to a closed pipe never produces a traceback or a spurious non-zero error message:
`ai --help | head -1` is safe and exits `0`/`141`. The same applies to long streamed answers piped
into tools that stop reading early.

## Non-interactive approvals

In a pipe/CI there is no terminal to ask, so unapproved tool calls are denied by default. Three
flags control this:

| Flag | Effect |
| --- | --- |
| `-y/--yes` | Auto-approve **read-level** tools only (`read` risk class). Write, network and exec tools are still denied unless separately allowed. With `--shell` in a non-TTY it is also the explicit switch that lets the generated command execute. |
| `--allowed-tools "a,b*"` | Per-run allowlist. Comma-separated tool names or glob patterns (`fs_*`, `execute_shell_command`). This is the explicit way to pre-approve write/exec tools. |
| `--fail-on-tool-denied` | Exit with code `3` if any tool call was denied (otherwise the model just receives the refusal and continues). |

Persistent rules live in `tool_permissions.json` and are documented in
[Permissions & Safety](permissions.md). Danger-classified shell commands are always refused
non-interactively, even when the tool itself is allowed.

> **`TOOL_CONFIRM=false`** is still supported for fully unattended runs, but it grants every tool
> call without a prompt (apart from danger classification). Prefer `--allowed-tools` when you only
> need a few tools.

## Run limits

| Option | Effect |
| --- | --- |
| `--max-turns N` | Maximum number of tool-call rounds for this run (`N >= 1`; maps to `MAX_TOOL_CALL_DEPTH`, default `8`). When the limit is reached, the run stops with a `depth_limit` result; with `EXIT_ON_DEPTH_LIMIT=true` (default) a one-shot run exits non-zero. |
| `--cwd DIR` | Working directory for the run; also becomes `WORKSPACE_ROOT` for the shell `cwd` and the guarded file writes. Paths outside the workspace are rejected (see [Workspace Safety](workspace-safety.md)). |
| `--output-format ...`, `-q`, `-p` | Output contract, described above. |

## Non-interactive `--shell`

`--shell` is an interactive convenience by default (it shows the generated command and asks before
executing). When stdin/stdout is not a TTY, `ai --shell "..."` prints the generated command to
stdout and **does not execute it**, exiting `0`. Add `-y`/`--yes` to execute it in a trusted
context; if the command itself then exits non-zero, the run exits `1`.

## CI recipe

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. The agent may read files and run the test command without prompting.
# 2. Any denied tool fails the job instead of silently degrading.
ai -p "Read the failing tests, find the root cause and write a short report to CI_REPORT.md" \
  --output-format json \
  --allowed-tools "fs_*,execute_shell_command" \
  --max-turns 12 \
  --cwd "$PWD" \
  --fail-on-tool-denied > result.json

jq -e '.exit_code == 0' result.json
jq -r '.content' result.json
```

## Troubleshooting

- **No output at all**: errors go to stderr. Re-run and capture both:
  `ai -p "..." >out.txt 2>err.txt`.
- **`jq: parse error`**: make sure you used `-p`/a prompt and `--output-format json`; `text` is the
  default. Warnings always go to stderr, so stdout remains parseable.
- **Tool denied in CI**: add `--allowed-tools` for the tools the task needs; `--yes` alone only
  covers read-level tools.
- **Exit code `130` in CI**: the job sent SIGINT (timeout/cancel) — check the CI timeout settings.
- **Long tasks stop early**: raise `--max-turns`; the run reports a depth-limit message on stderr.

## See Also

- [Permissions & Safety](permissions.md)
- [Context & Limits](context-limits.md)
- [Command Reference](commands.md)
