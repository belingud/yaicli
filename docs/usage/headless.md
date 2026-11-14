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

# One-shot planning: save a plan and exit without executing it
ai -p "Add a --dry-run flag to fs_write_file" --plan --output-format json | jq '{plan_path, revision}'

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
  "usage": {
    "prompt_tokens": 1234,
    "completion_tokens": 456,
    "total_tokens": 1690,
    "cached_tokens": 0,
    "reasoning_tokens": 0,
    "estimated": false,
    "requests": 1,
    "cost_usd": 0.0077,
    "models": {
      "gpt-4o-mini": {
        "prompt_tokens": 1234,
        "completion_tokens": 456,
        "total_tokens": 1690,
        "estimated": false,
        "cost_usd": 0.0077
      }
    },
    "tools": {"count": 1, "duration_ms": 42.0, "result_chars": 1024}
  },
  "finish_reason": "stop",
  "model": "gpt-4o-mini",
  "provider": "openai",
  "error": null,
  "exit_code": 0
}
```

| Field | Meaning |
| --- | --- |
| `content` | Final assistant answer text |
| `tool_calls` | Ordered list of tool calls made during the run |
| `usage` | Real token usage and cost for the run (see below) |
| `finish_reason` | Last provider `finish_reason` (`"stop"`, `"length"`, `"tool_calls"`, `"depth_limit"`, or `null` when unknown) |
| `plan`, `plan_path`, `revision` | **Only added by `--plan` runs**: the submitted plan object, the path of the saved plan file and its revision (see [One-shot planning](#one-shot-planning-plan)) |
| `model`, `provider` | Effective model/provider for this run |
| `error` | Exactly `null` on success, otherwise `{"kind": "<error kind>", "message": "<detail>"}`. Possible kinds: `auth`, `rate_limit`, `context_length`, `network`, `timeout`, `bad_request`, `provider`, `tool`, `config`, `depth_limit`, `interrupted`, `plan_not_submitted`, `unknown` |
| `exit_code` | Exit code the process will return (see below) |

`usage` is no longer zeroed (v0.22 K17):

| `usage` key | Meaning |
| --- | --- |
| `prompt_tokens`, `completion_tokens`, `total_tokens` | Provider-reported token counts. `prompt_tokens`/`completion_tokens` are kept at the top level for backwards compatibility. |
| `cached_tokens` | Prompt-cache hits (provider-dependent; `0` when not reported) |
| `reasoning_tokens` | Reasoning/thinking tokens included in `completion_tokens` (provider-dependent) |
| `estimated` | `true` when the provider reported no usage and the numbers are a heuristic estimate (see [Context & Limits](context-limits.md)) |
| `requests` | Number of provider requests made during the run (tool rounds included) |
| `cost_usd` | Estimated cost in USD from the built-in price table, overridden by `MODEL_PRICING`. `null` when no price is known for the model. |
| `models` | Per-model breakdown (`prompt_tokens`, `completion_tokens`, `total_tokens`, `estimated`, `cost_usd`) |
| `tools` | Executed tool calls: `count`, `duration_ms` (wall clock) and `result_chars` (size of the results the model saw) |

When the model stops because the output token limit was reached, `finish_reason` is `"length"`
and one `Response stopped at MAX_TOKENS; ...` warning is printed to stderr in every output mode
(stdout stays clean/parseable). Increase `MAX_TOKENS` (or shrink the prompt/tool output) to get a
complete answer.

One limitation: failures that happen *before* a result exists (for example an invalid provider
configuration, a missing API key during client creation, or a usage error such as exit `2`) print a
diagnostic to stderr and exit non-zero **without** emitting the JSON object; every run that reaches
a result emits exactly one object. An interrupted one-shot run is reported both ways: exit `130`
and, if JSON output was active, `error.kind = "interrupted"`.

### `--output-format stream-json`

Newline-delimited JSON (NDJSON): one event object per line, in order. This is the format to use for
progress UIs, cancellation and tool-trace collection.

| Event | When | Fields |
| --- | --- | --- |
| `turn_start` | A model request starts | `type`, `turn` (0-based round index) |
| `text_delta` | The model streams answer text | `type`, `delta` (new text since the previous chunk) |
| `tool_call` | The model requests a tool | `type`, `name`, `arguments` (parsed JSON when possible) |
| `tool_result` | A tool has finished | `type`, `name`, `result` (the tool result text as seen by the model, truncated as in context) |
| `plan_start` | A `--plan` run starts | `type` |
| `plan_ready` | The model submitted a plan in a `--plan` run (emitted before the final `usage`/`done` events) | `type`, `steps` (step count), `path`, `revision` |
| `usage` | The run finished collecting usage | `type`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cached_tokens`, `reasoning_tokens`, `estimated`, `requests`, `cost_usd`, `models`, `tools`, and `finish_reason` when known (same values as the JSON `usage` object) |
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
{"type": "usage", "prompt_tokens": 1234, "completion_tokens": 456, "total_tokens": 1690, "cached_tokens": 0, "reasoning_tokens": 0, "estimated": false, "requests": 1, "cost_usd": 0.0077, "models": {"gpt-4o-mini": {"prompt_tokens": 1234, "completion_tokens": 456, "total_tokens": 1690, "estimated": false, "cost_usd": 0.0077}}, "tools": {"count": 1, "duration_ms": 42.0, "result_chars": 1024}, "finish_reason": "stop"}
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
| `1` | Handled failure: invalid config/provider, auth/API error, network failure, no input, unexpected error — with `--plan`, also when the model did not submit a plan (`error.kind = "plan_not_submitted"`) |
| `2` | Usage error: invalid option or argument (including an unknown `--output-format` value, an invalid `--cwd`, or `--plan` combined with `--shell`/`--code`) |
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

## One-shot planning (`--plan`)

`--plan` runs a single **read-only planning turn** and exits: the model works in plan mode (the
read/network tools plus the fixed read-only shell allowlist, see [Plan Mode](plan-mode.md)), must
finish by calling `submit_plan`, and YAICLI saves the submitted plan as a `draft` under
`<config-dir>/plans/<project-key>/`. The plan is **not executed**: there is no approval panel and
no todo execution in headless mode.

```bash
ai -p "Add a --dry-run flag to fs_write_file" --plan --output-format json
```

Rules:

- `--plan` forces one-shot output. `--chat` / `--resume` are ignored with a warning; a prompt or
  piped stdin is still required.
- `--plan` cannot be combined with `--shell` or `--code`: the run fails with
  `Error: --plan cannot be combined with --shell/--code.` on stderr and exits `2`.
- When `PLAN_ENABLED=false`, `--plan` fails with `Error: --plan requires PLAN_ENABLED=true.` and
  exits `2`.
- The plan file is left in `draft` status; open it later from an interactive session with
  `/plan review` (see [Plan Mode](plan-mode.md#approval-panel)).

### `--plan` output

- **text** (default): the submitted plan Markdown (goal, assumptions, steps, risks, ...) is written
  to stdout; progress, warnings and errors stay on stderr.
- **json**: the normal result object gains three top-level keys:

| Field | Meaning |
| --- | --- |
| `plan` | The full plan object: `id`, `goal`, `assumptions`, `steps`, `risks`, `not_doing`, `status`, `revision`, `session_id`, `created`, `updated`, `cwd`, `project_key`, `model`, `base_rev`, `approved_at`, `change_summary`, `path` |
| `plan_path` | Absolute path of the saved plan file |
| `revision` | Plan revision (`1` for a first plan) |

The remaining JSON keys are unchanged from a normal run. Example (Feature example F6):

```bash
$ ai -p "Add a --dry-run flag to fs_write_file" --plan --output-format json | jq '{plan_path, revision, steps: [.plan.steps[].title]}'
{
  "plan_path": "/Users/vic/.config/yaicli/plans/3f9a1c2d…/20261114-004512-fs-dry-run.md",
  "revision": 1,
  "steps": ["Locate the fs_write_file schema and execution path", "Add dry_run and short-circuit in the execution layer", "Add tests"]
}
$ echo $?   # 0
```

- **stream-json**: two additional events describe the planning run before the usual `usage` /
  `done` events:

```json
{"type": "plan_start"}
{"type": "plan_ready", "steps": 3, "path": "/Users/vic/.config/yaicli/plans/3f9a1c2d…/20261114-004512-fs-dry-run.md", "revision": 1}
```

### `--plan` exit codes

| Code | Meaning |
| --- | --- |
| `0` | A plan was submitted and saved; `plan`/`plan_path`/`revision` are in the result |
| `1` | The model did not submit a plan: `error.kind = "plan_not_submitted"`, message `plan mode ended: model did not submit a plan` |
| `2` | Usage error: `--plan` combined with `--shell`/`--code`, or `PLAN_ENABLED=false` |

Without a prompt or piped stdin a `--plan` run falls back to the usual no-input behaviour (the help
screen for `text` output, exit `2` for machine output formats).

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
- **Answers are cut off mid-sentence**: `finish_reason` is `"length"` and a `MAX_TOKENS` warning is
  printed to stderr — raise `MAX_TOKENS` (or lower the amount of context/tool output sent).

## See Also

- [Plan Mode](plan-mode.md) — the interactive plan → approve → todo execution workflow
- [Permissions & Safety](permissions.md)
- [Context & Limits](context-limits.md)
- [Command Reference](commands.md)
