# Tool-output viewer and compact display (v0.19.1)

## Goal

Tool results can be multiple screens long and a single turn may call several tools. The REPL
already previews each result head-only (v0.19.1 compact display), but the old expansion printed
the whole result into the scrollback where it cannot be collapsed. Replace that with a
full-screen, alt-screen viewer that lists every tool output of the current turn and can be closed
to restore the REPL.

## Background

- `a0db5eb` added compact display: head-only preview (`TOOL_DISPLAY_MAX_LINES=15`,
  `TOOL_DISPLAY_MAX_CHARS=4000`), summarized `@Function call:` arguments
  (`TOOL_CALL_PREVIEW_MAX_CHARS=300`), plus Ctrl+O / `/show-output` that printed the last full
  result inline.
- Terminal scrollback cannot be collapsed. Only an alternate-screen application can show long
  content and then restore the previous screen on close.
- A turn may run N tool calls (function or MCP), so the viewer must group outputs by turn.

## Requirements

- **R1 Viewer entry**: `Ctrl+O` at the REPL prompt opens a full-screen (alt-screen) viewer;
  `q`, `Esc` or `Ctrl+O` closes it and returns to the prompt with the screen unchanged.
  `/show-output` opens the same viewer.
- **R2 Scope**: show every tool output of the current turn (both `function` and MCP tools). When
  the current turn has no tool outputs yet, fall back to the most recent turn that has some and
  label it; an empty history prints a dim notice instead of opening.
- **R3 Layout**: two panes — left list of entries (index, tool name, original char count, selection
  marker), right scrollable content of the selected entry.
- **R4 Keys**: `↑/↓` move the list selection (list focused) or scroll the content (content
  focused); `Tab`/`Shift+Tab` or `←`/`→` switch pane; `PgUp/PgDn/Home/End` scroll content;
  `f` toggles between the model-visible result and the spilled full file (load capped at 1 MB,
  toggle back); `q`/`Esc`/`Ctrl+O` close.
- **R5 Content**: default is the model-visible result (already capped by `TOOL_OUTPUT_MAX_CHARS`);
  the entry header shows the original size and truncation state, and the right pane shows the
  spill path when one exists. The viewer is display-only and never changes what the model receives.
- **R6 Recording**: record per tool call: kind, name, summarized arguments, model-visible text,
  original character count, spill path, truncated flag; grouped by turn; in-memory ring buffer
  (100 entries max).
- **R7 Preview unchanged**: the inline head-only preview and marker stay exactly as shipped in
  `a0db5eb`; only the expansion path changes (no more inline full print).
- **R8 Fallbacks**: non-TTY/headless or a viewer crash falls back to the existing inline
  last-output panel; machine/headless stdout contract is untouched (`/show-output` is
  REPL/machine-safe).
- **R9 No new config keys**: viewer behavior is fixed; display caps stay configurable as before.
- **R10 Documentation**: README shortcuts, `docs/usage/cli.md`, `interactive.md`, `commands.md`,
  `context-limits.md`, and the py specs (`cli-and-rendering`, `function-tool-guidelines`).

## Non-goals

- No assistant text/reasoning transcript in the viewer — tool outputs only.
- No in-viewer search/filter/export (future work).
- No persistent viewer history on disk; spill files remain the full-output store.
- `Ctrl+O` is prompt-only (not available while a generation is running).

## Acceptance Criteria

- [x] Ctrl+O opens the viewer from the REPL; closing returns to the prompt without traceback or
      screen corruption (manual + prompt_toolkit pipe-input test).
- [x] With 1 output and with 4 outputs the viewer lists all current-turn outputs and switches
      selection/content correctly.
- [x] A tool-free turn falls back to the previous turn's outputs (header says "last turn").
- [x] `f` shows the spilled full file for a truncated entry and toggles back; missing spill shows
      a notice instead of crashing.
- [x] `/show-output` opens the same viewer; non-TTY falls back to the inline panel.
- [x] Model-visible tool results/client behavior unchanged; existing tool tests stay green.
- [x] `pytest` full suite, `ruff check yaicli tests` and `mkdocs build --strict` are green.
- [x] README/docs/spec updated; commits conventional on `feat/tool-output-preview`.
- [ ] Task archived only after the user explicitly asks for the v0.19.1 release (merge + tag +
      PyPI/docs push is a separate, explicit step).

## Constraints

- Python 3.10+; stdlib + existing deps only (prompt_toolkit already a dependency).
- Keep `yaicli/tools/__init__.py` import-time write-free and lazy (viewer imports prompt_toolkit
  layout lazily, only when opened).
- Do not regress the v0.19 headless contract: no stdout pollution in `-p/--output-format`
  runs; viewer is only reachable from the interactive REPL.
