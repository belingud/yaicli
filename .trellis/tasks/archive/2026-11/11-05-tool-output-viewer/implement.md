# Implementation Plan — tool-output viewer (v0.19.1)

Status: complete — viewer, history, docs and tests are implemented and verified (1832 tests,
ruff, mkdocs --strict). Only the explicit v0.19.1 release step remains.

## Step 1 — Display layer (compact previews) — done earlier, commit `a0db5eb`

- `TOOL_DISPLAY_MAX_LINES` (15), `TOOL_DISPLAY_MAX_CHARS` (4000),
  `TOOL_CALL_PREVIEW_MAX_CHARS` (300) config keys + env/template.
- `make_display_preview()` / `build_preview_marker()` / `summarize_arguments()` in
  `yaicli/tools/limits.py`; panel renders head-only with `… +N lines · Ctrl+O to expand`.
- Docs/tests for the preview layer (to be updated in step 5 for the new Ctrl+O semantics).

## Step 2 — Output history + truncation metadata — written, unverified

- `yaicli/tools/output_history.py`: `ToolOutputEntry`, `begin_turn()`, `record_output()`,
  `viewer_outputs()` (current turn → fallback last turn), ring buffer 100, `reset()`.
- `yaicli/tools/limits.py`: `TruncatedOutput` + `truncate_tool_output_meta()`; existing
  `truncate_tool_output()` delegates (no caller/test churn).
- `yaicli/tools/__init__.py`: record every result (kind/name/args/text/total/spill/truncated);
  `get_last_tool_output()`/`show_last_tool_output()` now read the history (inline fallback kept).
- `CLI._process_user_input()` calls `begin_turn()`.

## Step 3 — Full-screen two-pane viewer — written, unverified

- `yaicli/tool_output_viewer.py`:
  - `ToolOutputViewerRequested` signal;
  - `build_viewer_app(entries, label, *, input=None, output=None)` — alt-screen two-pane layout,
    list/content panes, `f` full-spill toggle (1 MB cap), q/Esc/Ctrl+O/Ctrl+C close;
  - `open_tool_output_viewer(console)` — TTY guard, empty-history notice, inline fallback.
- `yaicli/cli.py`: c-o binding raises the signal via `event.app.exit(exception=...)`; `_run_repl`
  catches it, runs the viewer in sync context, continues; `/show-output` help text updated.
- `yaicli/cmd_handler.py`: `/show-output` delegates to `CLI._open_tool_output_viewer()`.

## Step 4 — Tests (in progress)

- [x] Update `tests/tools/test_tool_display.py`: replace `_last_tool_output` fixtures with
      `output_history.reset()`; assert recording metadata (spill path/total chars).
- [x] New `tests/tools/test_output_history.py`: turn grouping, current→last fallback, ring cap,
      reset, `begin_turn`.
- [x] New `tests/test_tool_output_viewer.py`: `_entry_header`/`_body_text`/`_left_fragments`;
      `build_viewer_app` runs with pipe input + `DummyOutput` and exits on `q`/Ctrl+O;
      `open_tool_output_viewer` fallbacks (non-TTY → inline, empty → notice).
- [x] `tests/test_cli.py`: c-o binding exits prompt with `ToolOutputViewerRequested`;
      `_run_repl` catches the signal → viewer called → loop continues; `/show-output` delegates.
- [x] `tests/test_command_handler.py` (or display test): `/show-output` calls
      `_open_tool_output_viewer`, bare-attribute fallback works.
- [x] Truncation metadata test: small cap + patched `TOOL_OUTPUT_DIR` → spill path exists,
      original text round-trips.
- [x] Full `pytest`; fix regressions (expected: old inline `Ctrl+O`/`show_last_tool_output`
      assumptions).

## Step 5 — Docs / specs

- [x] README keyboard shortcuts: Ctrl+O = full-screen tool-output viewer (this turn).
- [x] `docs/usage/cli.md`, `interactive.md`, `commands.md`: Ctrl+O / `/show-output` semantics,
      viewer keys (`↑/↓`, `Tab`, `f`, `q`).
- [x] `docs/usage/context-limits.md`: viewer + model-visible vs spilled full text; `f` cap.
- [x] `.trellis/spec/py/cli-and-rendering.md`: Ctrl+O signal → viewer flow.
- [x] `.trellis/spec/py/function-tool-guidelines.md`: history store, viewer metadata, fallback.
- [ ] CHANGELOG entry deferred to the v0.19.1 release step.

## Step 6 — Verification

- [x] `ruff check yaicli tests`
- [x] `pytest -q` full suite
- [x] `mkdocs build --strict`
- [x] Manual smoke without a TTY: build app with `create_pipe_input()` + `DummyOutput`, send
      `q`; `f` toggle on a truncated entry; verify no traceback.
- [ ] Confirm `--template` config keys and headless JSON mode untouched.

## Step 7 — Commit / review

- [x] Commit the viewer redesign (follow-up to `a0db5eb`, conventional commit).
- [x] `git diff e654434..HEAD` review; branch `feat/tool-output-preview`, no stray files.
- [ ] Update task.json status; do **not** archive until the release step completes.

## Step 8 — Release v0.19.1 (explicit user request required)

- [ ] Version bump 0.19.1 (pyproject + `.bumpversion.cfg` + `__init__`), git-cliff changelog,
      `docs/changelog.md` sync.
- [ ] Merge to `master`, annotated tag `v0.19.1`, push master + tag (PyPI workflow), push docs.
- [ ] Verify PyPI 0.19.1 + docs deploy; archive task; record journal.

## Step 9 — Generation-time Ctrl+O toggle (follow-up)

- [x] `yaicli/generation_keys.py`: `GenerationKeyWatcher` (cbreak stdin watcher, Ctrl+O request,
      pause/resume, pending typed text, termios restore) + tests with a pipe fd.
- [x] `Printer.display_stream(pause_requested=..., on_pause=...)`: stop/restart the live region
      around the pause callback; redraw accumulated content.
- [x] `CLI._handle_llm_response()`: start/stop the watcher around the stream; `_open_viewer_while_generating()`
      helper; store pending text in `_pending_prompt_text`.
- [x] `CLI._run_repl()`: pass pending text as `PromptSession.prompt(default=...)`.
- [x] Tests: watcher state machine, printer pause hook, CLI lifecycle/pending prefill, no-TTY skip.
- [x] Docs/specs: Ctrl+O works while generating (generation pauses while viewing).
- [x] Verification: ruff + pytest + mkdocs --strict; commit.

## Background generation (v0.19.1 follow-up — split into subtasks)

| # | Subtask | Deliverable | Depends on |
| --- | --- | --- | --- |
| T0 | paused viewer baseline | commit `7fcea5f` (watcher + printer hook; generation pauses while viewer open) | — |
| T1 ✅ | `11-05-stream-bridge` | `ThreadedStream` adapter + unit tests; not wired yet | T0 |
| T2 ✅ | `11-05-worker-console-routing` | thread-dispatching console wrapper + tests; not wired yet | T1 |
| T3 ✅ | `11-05-background-generation-cli` | interactive streaming uses the bridge; Ctrl+O viewer while worker continues; close redraws | T1+T2 |
| T4 ✅ | `11-05-background-generation-cancel` | Ctrl+C/abort semantics, watcher lifecycle, message-copy safety, queued confirmations | T3 |
| T5 ✅ | `11-05-background-generation-verify` | regression + docs/spec + commit | T4 |
| T6 | release v0.19.1 | merge/tag/PyPI/docs (explicit user request only) | T5 |

Each subtask must keep the full suite green and be committed separately before the next one starts.

## Post-T5 hotfixes

- `2eaaadf` — `execute_shell_command` argument renamed `shell_command` → `command` (breaking
  schema change; approval/risk/preview/tests updated).
- `cba65ee` — Ctrl+O was only serviced at the next stream chunk; `Printer.display_stream()` now
  polls `ThreadedStream.poll_next(50ms)` and re-checks the viewer request between chunks, with a
  dim hint when the current turn has no tool output yet. Added opt-in `YAI_DEBUG_LOG` breadcrumbs
  (watcher start/skip, Ctrl+O byte, pause/resume ack, printer pause, viewer run begin/end/error)
  documented in `docs/dev/debug-cli.md` for terminal-specific reproduction reports.
