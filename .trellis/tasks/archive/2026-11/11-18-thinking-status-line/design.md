# Design — thinking status line with collapsed reasoning

## Scope & boundaries

- **Display-only change.** `LLMClient` and every provider already stream the reasoning text as
  `LLMResponse.reasoning`; they are not touched. The only renderer is `yaicli/printer.py`.
- **Config surface only where the user touches it:** `yaicli/const.py` (defaults, map, template) and
  `yaicli/entry.py` (CLI flag). `yaicli/cli.py` needs no change: it already builds
  `Printer(console=self.console, content_markdown=...)` (`cli.py:433-435`) and prints the
  `Assistant:` header before `display_stream` (`cli.py:2027-2028`).
- **No data-model change.** Reasoning keeps flowing through `LLMResponse.reasoning` →
  `LLMClient` (`llms/client.py:575-576`, `:618`) → `ChatMessage.reasoning` (`schemas.py:28`) →
  session JSON (`chat.py:73-74`, `:124`). Hiding it in the terminal must not alter this path.

## Data flow

```text
provider SSE
  → LLMClient.completion_with_tools() yields LLMResponse(reasoning=..., content=...)
  → (interactive TTY only) ThreadedStream / worker console routing
  → Printer.display_stream()
       ├─ reasoning started:         Live line  ✻ Thinking… Ns (timer from first reasoning)
       ├─ first content:              console.print  ∴ Thought for Ns                (permanent, dim)
       └─ content streaming:          Live region renders the Markdown answer       (as today)
  → display_stream returns (full_content, full_reasoning)  ← reasoning stays complete
  → CLI chat.history → ChatMessage.reasoning → session JSON (unchanged)
```

`RefreshLive` is yielded by the client **before** executing a round's tool calls
(`llms/client.py:896`), so finalizing the summary there prints it before the `@Tool call:` announce
and before tool output panels — the chronologically correct order.

## Display state machine (per assistant round)

| State | Entered when | Rendered |
| --- | --- | --- |
| `SILENT` | round starts / request in flight, no reasoning yet | nothing (prefill wait stays silent) |
| `THINKING` | first non-empty `full_reasoning` (covers `<think>` tags via `_process_chunk`) | `✻ Thinking… Ns` |
| `ANSWER` | first non-empty `full_content` | status erased; summary printed once; content Live |
| `DONE` | `RefreshLive` / normal stream end | summary printed once (if not yet), state reset |

- Stopwatch: one per reasoning segment. `state.started_at = clock()` is set when the first reasoning
  chunk makes `full_reasoning` non-empty (never at request start); reset on `RefreshLive`. Elapsed =
  `clock() - started_at`; it ends at the first content token, `RefreshLive`, or normal stream end.
- Summary is printed only when **all** hold: `show_thinking_status`, `not show_reasoning`,
  `thinking_seen`, `not summary_printed`, elapsed ≥ 1.0 s, and the stream was not aborted by an
  exception.
- No status line before reasoning: a non-reasoning model (or the prefill wait) renders nothing, so
  there is no flash and no invented "waiting" UI.
- Active line style: `dim cyan`, built with `rich.text.Text`; text is trusted (no model text is
  interpolated), so no `safe_text` needed. Summary style: `dim`, plain console print.
- Integer seconds, rounded; ≥60 s renders `Nm SSs`.

## `printer.py` changes

```python
# module constants (near _STREAM_POLL_SECONDS)
_THINKING_STATUS_FRAMES = ("·", "✢", "✳", "✶", "✻", "✽")
_THINKING_STATUS_ASCII_FRAMES = ("-", "\\", "|", "/")
_STATUS_FRAME_SECONDS = 0.1
_THOUGHT_SUMMARY_MIN_SECONDS = 1.0
_THINKING_LABEL = "Thinking"
_THOUGHT_MARKER = "∴"
```

- `Printer` dataclass: add `clock: Callable[[], float] = time.monotonic` (last field, defaulted) so
  tests can drive deterministic time. `import time`, `from rich.text import Text`.
- `__post_init__`: cache `self.show_thinking_status = self.config["SHOW_THINKING_STATUS"]` next to
  the existing `show_reasoning` cache (never re-read config per chunk).
- New helpers (private, unit-testable):
  - `_status_enabled() -> bool`: `show_thinking_status and not machine and
    bool(getattr(console, "is_terminal", False))`.
  - `_status_glyphs() -> tuple[str, tuple[str, ...], str, str]`: unicode `(marker, frames, ellipsis)`
    when `console.encoding` can encode them, else ASCII `("*", ("-", "\\", "|", "/"), "...")`.
  - `_format_elapsed(seconds) -> str`: `12s`, `1m 12s` (>=60 s), rounded seconds.
  - `_status_text(elapsed) -> Text`: `f"{frame} Thinking{ellipsis} {elapsed}"`, frame chosen by
    `int(elapsed / _STATUS_FRAME_SECONDS) % len(frames)`, style `dim cyan`.
  - `_update_thinking_status(live, state)`: no-op when `not state.reasoning_seen`, when the summary
    was already printed, or when status is disabled; otherwise
    `live.update(self._status_text(elapsed), refresh=True)`.
  - `_finish_thinking(state)`: idempotent; sets `state.summary_printed`; prints
    `∴ Thought for Ns` dim (markup safe — trusted literal + number) when the R2 conditions hold.
  - Round state: a small private dataclass `_RoundState(started_at, reasoning_seen,
    summary_printed)` or equivalent locals in `display_stream` (implementation detail; keep one
    object for clarity).
- `display_stream` rewiring (all inside the existing TTY branch, after the machine early return):
  1. create an empty state before the loop (no timer yet);
  2. on poll timeout (`chunk is None, continue`) call `_update_thinking_status(live, state)` before
     continuing — this is what re-renders the timer/spinner at the existing 50 ms poll cadence once
     reasoning has started;
  3. after each `_process_chunk` update: if `full_reasoning` and `not state.reasoning_seen`, set
     `state.reasoning_seen = True; state.started_at = self.clock()` (first reasoning chunk starts
     the stopwatch);
  4. content branch: `_finish_thinking(state)` **before** `live.update(content, refresh=True)`;
     reasoning-only branch: after `_emit_reasoning(...)`, `_update_thinking_status(live, state)`;
  5. `RefreshLive` branch: `_finish_thinking(state)` (elapsed to now), flush reasoning as today,
     stop/start live, reset the state (`started_at = 0.0`, `reasoning_seen = summary_printed =
     False`);
  6. `finally`: keep the existing reasoning flush; when the loop ended normally (StopIteration) and
     content never started, `_finish_thinking(state)`; stop live. On exception: no summary (just
     stop live, re-raise as today).
  7. after pause/viewer restart (`_maybe_handle_pause`) and after tool confirmation, the next loop
     iteration re-renders the status; no extra path needed.
- Not touched: `_display_stream_machine`, `_display_normal_machine`, `display_normal`,
  `_emit_reasoning` (full-text mode), `_format_display_text`, confirmation/plan panels.

## Config & CLI changes

- `yaicli/const.py`:
  - `DEFAULT_SHOW_REASONING: BOOL_STR = "false"` (`:152`);
  - new `DEFAULT_SHOW_THINKING_STATUS: BOOL_STR = "true"`;
  - new map entry `"SHOW_THINKING_STATUS": {"value": DEFAULT_SHOW_THINKING_STATUS,
    "env_key": "YAI_SHOW_THINKING_STATUS", "type": bool}` next to `SHOW_REASONING` (`:322`);
  - `DEFAULT_CONFIG_INI` UI/UX block: `SHOW_REASONING=false` + comment, and the new
    `SHOW_THINKING_STATUS` line with comment (`:476-477`).
- `yaicli/entry.py`: `OtherOptions.show_thinking_status` Typer option
  (`--thinking-status/--no-thinking-status`, default `cfg["SHOW_THINKING_STATUS"]`,
  `show_default=False`, help shows effective default, `callback=override_config`) and the matching
  `show_thinking_status: bool = OtherOptions.show_thinking_status  # noqa: F841` parameter in
  `main()`. `override_config` maps the param name to `SHOW_THINKING_STATUS`.
- Precedence (unchanged layering): CLI flag > `YAI_SHOW_THINKING_STATUS` env > config file >
  `const` default. Same for `SHOW_REASONING` (its default value only changes).
- `Printer.__post_init__` caches both booleans at construction (CLI/one-shot build the printer after
  option callbacks run, so overrides are visible).

## Compatibility & migration

- **Default behavior change** (breaking UX): full chain-of-thought is no longer printed by default.
  Restore with `SHOW_REASONING=true` / `--show-reasoning`. Documented in README, configuration docs
  and provider pages; the conventional commit carries `!` so git-cliff marks it in `CHANGELOG.md`.
- No session-file/JSON/NDJSON changes; old sessions load unchanged (reasoning already persisted).
- TTY-only: pipes, `-p`, `-q`, `--output-format json|stream-json` keep byte-identical stdout.
- Encoding: unicode glyphs with an ASCII fallback, so legacy Windows/codepage terminals degrade
  gracefully instead of raising `UnicodeEncodeError`.
- Rollback: revert the single feature commit; no data migration, no state to clean up.

## Testing design

- Deterministic time via injected `clock=` callable (`FakeClock.now` mutated by the test).
- TTY rendering: `Console(file=StringIO(), force_terminal=True, width=80)` collects ANSI frames;
  assertions use substring search for `Thinking…`, `Thought for`, absence of reasoning text.
- Non-TTY: `force_terminal=False` console → status disabled (existing tests unaffected; they set
  `show_reasoning=True` explicitly where needed).
- Existing tests that patch `yaicli.printer.Live` with `MagicMock` stay valid: status code only
  calls `live.update(...)`/`live.stop()`.
- Test matrix:
  1. collapsed default: reasoning text absent, `Thought for Ns` present with ≥1 s (fake clock),
     content rendered, returned reasoning is the full text;
  2. `✻ Thinking…` marker and spinner glyph render, timer value from fake clock (starts at the
     first reasoning chunk; absent during prefill); no status in round 2 until reasoning arrives;
  3. <1 s → no summary; `show_reasoning=True` → old text + no summary;
  4. `show_thinking_status=False` → no markers; machine mode → no markers; non-TTY → none;
  5. `RefreshLive` → one summary per round, printed before next content/tool output;
  6. exception path → no summary, error propagates (extend existing error test);
  7. `_format_elapsed` parametrized; ASCII glyph fallback; `_status_enabled` gating;
  8. history regression: returned reasoning full + existing `tests/test_chat_manage.py`
     serialization/redaction tests pass;
  9. docs drift guard `tests/test_docs_config.py` + `ai --template` contains the new key;
  10. `tests/test_headless_contract.py` and `tests/test_cli.py` streaming tests pass.
- Manual acceptance: run a local fake-stream demo (printer + scripted chunks) to capture the
  Examples 1–5 blocks, plus `ai -p "say hi" | cat` to confirm no glyphs in machine output.

## Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Rich Live + `console.print` above the live region re-render conflicts (previous bug class) | Reuse the existing single Live; status is only another renderable of that Live, never a second Live; summary prints while Live is active exactly like tool panels do today. |
| Animation needs periodic refresh but `auto_refresh=False` | Interactive TTY already polls every 50 ms (`_STREAM_POLL_SECONDS`); update the status on each poll timeout. Bare one-shot TTY also has the watcher/bridge (`cli.py:2134-2146`), so it animates too. |
| Silent pre-thinking wait (no status before reasoning) | Deliberate user decision: the timer starts at the first reasoning chunk, and non-reasoning models never flash a status line. |
| Stale spinner/residual lines after Ctrl+C or provider error | Single `finally` stops the Live (existing); no summary on exception. |
| Tests using MagicMock consoles get `is_terminal` truthy | Status path only calls Live methods; Live is patched in those tests. Tests asserting rendered output use real consoles (status disabled when non-TTY). |
| Encoding errors on odd terminals | ASCII glyph fallback decided from `console.encoding`. |
| Behavior-change surprise | Docs/README/provider pages + `!` commit marker + PR body clearly state `SHOW_REASONING` default flip. |

## Deferred / out of scope

- Ctrl+O (or `/show-output`) expansion of the last thinking text.
- `stream-json` thinking events; JSON field.
- Non-streaming (`STREAM=false`) status.
- Random verb rotation, "esc to interrupt" hint.
- Surfacing interleaved reasoning segments that arrive after content started (MiniMax); still saved
  to history.
