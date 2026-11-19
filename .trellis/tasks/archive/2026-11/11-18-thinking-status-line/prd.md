# Thinking status line with collapsed reasoning

## Goal

Make YAICLI's thinking display match Claude Code's default: once the model actually starts reasoning,
show one animated status line in the Live region (`✻ Thinking… Ns`, timer starts at the first
reasoning chunk); when the answer starts, erase that line and leave one dim collapsed line
(`∴ Thought for Ns`) in scrollback. Models that emit no reasoning get no status line and no summary.
The full reasoning text is **not printed by default** (`SHOW_REASONING=false`), but it is still
stored in the conversation/history exactly as today; `SHOW_REASONING=true` restores the current full
text streaming.

## Background (verified in this repository)

- Every provider already streams reasoning as `LLMResponse.reasoning` (DeepSeek `reasoning_content`,
  OpenRouter `reasoning`, Anthropic thinking blocks, Gemini thoughts, Ollama `think`, and
  `<think>` tags inside content handled by `Printer._check_and_update_think_tags`). This is a
  **display-only** change: no provider/SDK work.
- Today `SHOW_REASONING` defaults to `true` (`yaicli/const.py:152`, `:322`) so the full chain of
  thought is printed dim under a `Thinking:` header (`yaicli/printer.py:775` `_emit_reasoning`,
  `:813` `display_stream`). With `SHOW_REASONING=false` the screen is completely silent while the
  model thinks — the "frozen screen" gap this task fixes.
- Reasoning is already persisted independently of display: `LLMClient` collects
  `assistant_reasoning_content` and stores it on the assistant `ChatMessage`
  (`yaicli/llms/client.py:575-576`, `:618`); `ChatMessage.reasoning` (`yaicli/schemas.py:28`) is
  written to and restored from session JSON (`yaicli/chat.py:73-74`, `:124`) and documented in
  `docs/advanced/history.md` ("restoring a session preserves tool calls, images, and reasoning
  content"). This task must not regress that.
- Interactive TTY streaming is polled every 50 ms through `ThreadedStream.poll_next` because of the
  generation-time Ctrl+O watcher (`yaicli/printer.py:71`, `yaicli/cli.py:2055-2073`,
  `yaicli/stream_bridge.py`), which is what makes a live spinner possible without enabling
  `Live(auto_refresh=True)` (auto-refresh was intentionally disabled — see
  `Printer._create_and_start_live`).
- `machine_output` (pipes, `-p/--print`, `--quiet`, `--output-format json|stream-json`) uses
  `Printer(machine=True)`, which bypasses the Live region entirely
  (`yaicli/printer.py:241` `_display_stream_machine`, `yaicli/cli.py:265`, `:433-435`). That output
  contract must not change.
- `RefreshLive` is yielded by the client before executing a round's tool calls
  (`yaicli/llms/client.py:896`), so a thinking summary finalized on `RefreshLive` prints **before**
  the `@Tool call:` announce — the correct chronological order.
- The display switches (`SHOW_REASONING`, new `SHOW_THINKING_STATUS`) are TTY-only presentation
  state; nothing about them is written to session files.

## Requirements

- **R1 Active status line.** In interactive TTY streaming (`display_stream`, not machine output),
  show one animated live line in the Live region **only after the first reasoning chunk actually
  arrives**: `✻ Thinking… 0s`, then `Ns` ticking. The stopwatch starts at that first reasoning
  chunk (never at submission), so the pre-thinking request wait stays silent. `✻` cycles through
  `· ✢ ✳ ✶ ✻ ✽` (100 ms/frame). Style: `dim cyan`.
- **R2 Collapsed summary.** Once the answer starts (first content token) — or when the round ends
  (`RefreshLive`) / the stream ends — erase the live status and print exactly one dim line
  `∴ Thought for Ns` (style `dim`) **if** thinking was observed in that round and the measured
  thinking time is ≥ 1.0 s. The duration is measured from the first reasoning chunk to the first
  content token (or to the round end when the round produced no content). Formatting: `12s`,
  `1m 12s` for ≥ 60 s. No summary when thinking < 1 s.
- **R3 Collapsed default.** `SHOW_REASONING` default changes from `true` to `false`: reasoning text
  is not printed at all by default (not during, not after). This is the Claude-Code-like default.
- **R4 Opt-in full text.** `SHOW_REASONING=true` keeps today's behavior exactly: dim `> ` lines
  under one `Thinking:` header, streamed append-only. In that mode the active status line is still
  shown (with elapsed time) but **no** `∴ Thought for` summary is printed (the text itself is the
  record).
- **R5 New switch.** New config `SHOW_THINKING_STATUS` (default `true`, env
  `YAI_SHOW_THINKING_STATUS`) plus CLI `--thinking-status/--no-thinking-status`; when false, no
  active status line and no summary line (the old silent behavior when `SHOW_REASONING=false`).
- **R6 Round semantics.** Timer and status are per assistant round: each tool round that starts
  reasoning gets its own `✻ Thinking…`/`∴ Thought for Ns` pair. There is no waiting/pre-thinking
  line in any round; after a tool call the printed tool output is the progress signal.
- **R7 Non-TTY/headless untouched.** No status and no summary in machine output (`-p`, `-q`, JSON,
  stream-json, piped stdout) and in `STREAM=false` (non-streaming) runs. stdout bytes, JSON keys,
  NDJSON events, stderr diagnostics and exit codes are unchanged.
- **R8 History preserved.** The full reasoning must still be returned by `display_stream` and stored
  in `ChatMessage.reasoning`/session JSON when display is collapsed. No data-model or serialization
  changes.
- **R9 Clean interrupts/errors.** Ctrl+C, `KeyboardInterrupt`, provider errors mid-thinking: the
  Live region is stopped and erased, no `Thought for` line is printed, no stale spinner remains.
- **R10 Docs + config template.** `const.DEFAULT_CONFIG_MAP`, `DEFAULT_CONFIG_INI`, README config
  table, `docs/usage/configuration.md` snippet+table (drift-guarded by `tests/test_docs_config.py`),
  and the reasoning/thinking prose in README, `docs/providers/deepseek.md`,
  `docs/providers/minimax.md` must describe the new default.
- **R11 No new machine contract.** No thinking event is added to `stream-json` in this change.
- **R12 Unicode fallback.** If the console encoding cannot encode the glyphs, fall back to ASCII
  frames `- \ | /`, `...`, and `*` so legacy Windows/codepage terminals still render.

## Feature examples

### Example 1 — primary success path: reasoning model, default collapsed (interactive REPL)

Input:

```bash
$ ai --chat
$ ... 💬 > compare the two release strategies
```

Rendered UI over time (each block replaces the previous live line; only the last block stays in
scrollback):

```text
Assistant:                            ← request in flight: no status line yet
```

```text
Assistant:
✻ Thinking… 0s                        ← appears with the first reasoning chunk (dim cyan)
```

```text
Assistant:
✻ Thinking… 5s                        ← dim cyan, ✻ spins · ✢ ✳ ✶ ✻ ✽
```

```text
Assistant:
∴ Thought for 13s                    ← dim; live status erased, one collapsed line
Nov 18 is a Tuesday. Let me compare the two strategies:
...
```

Final scrollback after the turn (dim usage line is the existing `SHOW_USAGE` line):

```text
Assistant:
∴ Thought for 13s
Nov 18 is a Tuesday. Let me compare the two strategies: ...
deepseek-reasoner · context 8% · tokens 1,231 in / 96 out · 14.1s · stop
```

### Example 2 — thinking shorter than 1 s

```text
Assistant:
The capital of France is Paris.       ← no status persisted, no Thought line
```

### Example 3 — model without exposed reasoning

```text
Assistant:                            ← no status line at any point
Paris is the capital of France.       ← no ∴ Thought line
```

### Example 4 — tool round (summary before the tool announcement)

```text
Assistant:
✻ Thinking… 3s
∴ Thought for 3s
@Tool call: get_weather({"city": "Tokyo"})
╭──────────── Tool output ────────────╮
│ {"temp": 21, "condition": "sunny"}  │
╰─────────────────────────────────────╯
✻ Thinking… 2s
∴ Thought for 2s
Tokyo is sunny today, 21°C.
```

### Example 5 — `SHOW_REASONING=true` (opt-in full text, no summary)

```text
Assistant:
Thinking:
> The user asks about Tokyo weather.
> I should call get_weather with city=Tokyo.
✻ Thinking… 6s                        ← live status at the bottom while text streams
The weather in Tokyo is sunny, 21°C.
```

### Example 6 — `SHOW_THINKING_STATUS=false` + default collapsed

```text
Assistant:
The weather in Tokyo is sunny, 21°C.  ← silent while thinking (explicit user choice)
```

### Example 7 — non-TTY / machine output (unchanged)

```bash
$ ai -p "say hi" > out.txt
$ cat out.txt
hi
$ ai -p "say hi" --output-format json
{"content":"hi","tool_calls":[],"usage":{...},"finish_reason":"stop","model":"...","provider":"...","error":null,"exit_code":0}
```

No `✻` / `∴` text, no status, no summary — the machine contract stays byte-identical.

### Presentation form

- Channel: stdout only, and only when the console is a TTY and `machine_output` is false. Nothing
  is written to stderr. No escape sequences in machine/pipe output.
- The active line lives in the existing Rich `Live` region and is erased when content starts; it
  never enters scrollback. Only `∴ Thought for Ns` (dim) is permanent.
- ANSI cursor movement is only emitted on a TTY; `NO_COLOR` keeps the text but drops styling.
- Line width is bounded (~35 chars max); no wrapping/truncation interaction.
- `Assistant:` header appears once per user turn (except CODER role, which has no header); status
  lines appear under it, per round.

### Logic

- Triggers: `SHOW_THINKING_STATUS=true` (CLI `--thinking-status` > env `YAI_SHOW_THINKING_STATUS` >
  config file > default `true`) AND console is a TTY AND not `machine_output` AND
  `Printer.display_stream` (streaming). `show_reasoning` only decides whether the text is printed.
- Timer: one stopwatch per reasoning segment. It starts when `full_reasoning` first becomes
  non-empty (covers separate reasoning fields and `<think>` tags), not when the request is sent.
  Elapsed = time until the first content token, `RefreshLive`, or stream end; integer seconds,
  rounded; ≥60 s renders `Nm SSs`.
- Status line appears only once reasoning has started; no waiting/pre-thinking line. Summary is
  suppressed when `show_reasoning=true`, when < 1.0 s elapsed, when no reasoning was seen, and on
  aborted/error streams.
- Tool rounds: client yields `RefreshLive` before executing tool calls (`client.py:896`), so the
  summary is printed before the `@Tool call:` announce and tool output panels.
- Interleaved thinking (MiniMax): reasoning that arrives after content has started in the same
  round is still stored in history but is not surfaced in collapsed mode (no second live status
  can be shown while the content Live region is rendering). This is an accepted limitation.
- Non-streaming (`STREAM=false`): no active line and no summary; reasoning is hidden (default) or
  printed at completion (`SHOW_REASONING=true`, unchanged `display_normal` path).
- Ctrl+C/provider error: live stopped, no summary, next prompt clean (no residual frames).
- Exit codes and error messages unchanged.

## Out of scope

- Ctrl+O / `/show-output` expansion of the last thinking text (scheme C in the design discussion).
- `stream-json` thinking events (`thinking_start`/`thinking_delta`), JSON thinking fields.
- Live status in non-streaming (`STREAM=false`) runs.
- Random spinner verbs / "esc to interrupt" hint (Claude Code cosmetic extras).
- Displaying reasoning in `/his`, replay or session-load output.
- Reworking `Thinking:` full-text rendering (kept as-is behind `SHOW_REASONING=true`).
- Changing tool-output panel defaults: `TOOL_DISPLAY_MAX_LINES` stays `15` (the user tunes it via
  config/env themselves).

## Acceptance criteria

- **AC1** Default config is `SHOW_REASONING=false`, `SHOW_THINKING_STATUS=true` (const map, template,
  docs tables all in sync — `tests/test_docs_config.py` passes; `ai --template` shows both).
- **AC2** In interactive TTY streaming with reasoning, output contains the animated
  `✻ Thinking… Ns`, the full reasoning text does not appear in the rendered output, and a stream
  whose first chunk is content (no reasoning) renders **no** status/summary at all. (printer tests
  with `force_terminal=True` + fake clock)
- **AC3** When the answer starts after ≥1.0 s of thinking (measured from the first reasoning
  chunk), exactly one `∴ Thought for Ns` line is printed before the content; with <1.0 s no summary
  is printed. (fake-clock printer tests)
- **AC4** `SHOW_REASONING=true` still streams dim `> ` reasoning under one `Thinking:` header and
  prints no `∴ Thought for` summary.
- **AC5** `SHOW_THINKING_STATUS=false` (CLI override) renders no status/summary; the same stream
  with a non-TTY console and with `Printer(machine=True)` also renders none.
- **AC6** Each tool round prints its own summary; on a `RefreshLive` round boundary the summary is
  emitted before the tool announce (ordering assertion at printer level).
- **AC7** `display_stream` still returns the full reasoning string, and the full reasoning is still
  serializable/restorable in session JSON (`tests/test_chat_manage.py` reasoning round-trip tests
  pass; new assertion that collapsed display keeps the returned reasoning full).
- **AC8** Exception / interrupt path: Live stopped, no summary, no residual status print; error
  propagates as before.
- **AC9** Headless/machine contract unchanged: `tests/test_headless_contract.py` passes; captured
  stdout for `-p` text/JSON/stream-json contains no `✻`/`∴`/`Thinking`.
- **AC10** `ruff check --no-fix yaicli tests`, targeted `pytest`, full `pytest`, and
  `mkdocs build --strict` (docs changed) pass; manual demo with a fake reasoning stream matches
  Examples 1–5.
- **AC11** Timer formatting: `_format_elapsed` renders `0s`, `12s`, `60s`→`1m 00s`, `72s`→`1m 12s`.

## Open questions

None — the following decisions were confirmed with the user: scheme A (collapsed, no full text by
default), reasoning still persisted in history, no Ctrl+O expansion in this change, English
`Thinking…`/`Thought for` wording, TTY-only, the status line + stopwatch start at the first reasoning
chunk (no pre-thinking "waiting" line), no status/summary for non-reasoning models, and tool-output
display defaults stay untouched.
