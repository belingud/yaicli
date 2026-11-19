# Implement — thinking status line with collapsed reasoning

## Preconditions (done / to confirm)

- [x] Trellis task created: `.trellis/tasks/11-18-thinking-status-line/` (branch/base recorded).
- [x] Branch created from latest `master`: `feat/thinking-status-line`.
- [x] `README`/`docs`/spec conventions inspected (`feature-spec-writing.md`,
  `cli-and-rendering.md`, `quality-guidelines.md`, `config-and-context.md` index).
- [ ] Final planning summary approved by the user, then `python3 ./.trellis/scripts/task.py start
  11-18-thinking-status-line` before touching product code.
- [ ] `trellis-before-dev` context loaded for `yaicli/printer.py` (printer/CLI layer spec + the
  cross-layer guide).

## Ordered checklist

1. **Config defaults / map / template** — `yaicli/const.py`
   - `DEFAULT_SHOW_REASONING = "false"`; add `DEFAULT_SHOW_THINKING_STATUS = "true"`.
   - Add `SHOW_THINKING_STATUS` entry (env `YAI_SHOW_THINKING_STATUS`, `type` bool) in the UI/UX
     block of `DEFAULT_CONFIG_MAP`.
   - Update `DEFAULT_CONFIG_INI`: `SHOW_REASONING=false` with a comment pointing at the collapsed
     status, plus `SHOW_THINKING_STATUS=true` with a comment.
   - Follow the "New config value" checklist: `const.py` → `config.py` wiring (none needed: generic
     map) → docs.
2. **CLI flag** — `yaicli/entry.py`
   - `OtherOptions.show_thinking_status = typer.Option(cfg["SHOW_THINKING_STATUS"],
     "--thinking-status/--no-thinking-status", help=..., show_default=False, callback=override_config)`.
   - Add `show_thinking_status: bool = OtherOptions.show_thinking_status  # noqa: F841` in `main()`.
3. **Printer implementation** — `yaicli/printer.py`
   - Module constants (`_THINKING_STATUS_FRAMES`, ASCII frames, `_STATUS_FRAME_SECONDS`,
     `_THOUGHT_SUMMARY_MIN_SECONDS`, `_THINKING_LABEL`, `_THOUGHT_MARKER`).
   - `Printer` dataclass: `clock: Callable[[], float] = time.monotonic`; `__post_init__` caches
     `show_thinking_status`.
   - Helpers: `_status_enabled`, `_status_glyphs`, `_format_elapsed`, `_status_text`,
     `_update_thinking_status`, `_finish_thinking`, `_RoundState`.
   - Rewire `display_stream` per `design.md`: timer starts at the first reasoning chunk, poll-timeout
     re-renders the status, first-content transition flushes the summary before content,
     `RefreshLive` reset + summary-before-tool-round, `finally` summary only on normal end, no
     summary on exception. No status line before reasoning (non-reasoning models stay clean).
   - Do not touch `_emit_reasoning`/`display_normal`/machine paths beyond the two-line state resets.
4. **Printer tests** — `tests/test_printer.py` (new `TestThinkingStatus` class; keep existing tests
   green)
   - Fake clock helper; `force_terminal=True` console helper.
   - Cases 1–7 + timer format + ASCII fallback + gating from `design.md` "Test matrix".
   - Extend the error-propagation test to assert no summary printed.
5. **Config/docs drift** — nothing code-wise: `tests/test_docs_config.py` guards the table/template
   sync; update the files in step 6 until it passes.
6. **Docs** (ship in the same change)
   - `README.md`: config table rows (`SHOW_REASONING` default `false` + description,
     `SHOW_THINKING_STATUS` row); "Enhanced Terminal Experience" bullet for the collapsed thinking
     status; Code Generation paragraph (`:1273`) rewrite; DeepSeek paragraph (`:592`) and MiniMax
     paragraph (`:706`) mention the new default; chat-mode bullet (`:1042`).
   - `docs/usage/configuration.md`: config-file snippet (`:85-86`) and reference table (`:248`).
   - `docs/providers/deepseek.md` (`:60`) and `docs/providers/minimax.md` (`:88`): reasoning is
     collapsed into the status line by default, full text with `SHOW_REASONING=true`.
   - `docs/advanced/history.md`: one sentence that reasoning remains stored even though the default
     display is collapsed (ties R8 to the docs).
   - No new doc page → no `mkdocs.yml` nav change.
7. **Verification**
   - `.venv/bin/ruff format yaicli tests` then isort (repo `just format` order).
   - `.venv/bin/ruff check --no-fix yaicli tests` (must be clean; watch that `fix = true` would
     rewrite — use `--no-fix`).
   - `.venv/bin/python -m pytest tests/test_printer.py tests/test_docs_config.py tests/test_entry.py
     tests/test_cli.py tests/test_headless_contract.py -q`
   - `.venv/bin/python -m pytest -q` (full suite; 60 test modules).
   - `.venv/bin/mkdocs build --strict`.
   - Manual demo: script a fake reasoning/content stream through `Printer(console=TTY-ish console)`
     and diff against PRD Examples 1–5; run `ai -p "say hi" | cat` (or the fake machine printer) to
     confirm no glyphs in machine output.
8. **Commit + PR** (only after the gates above pass)
   - `git add -A` on `feat/thinking-status-line`; one conventional commit
     `feat(printer)!: collapse reasoning into a thinking status line` with a body listing the
     `SHOW_REASONING` default flip, new `SHOW_THINKING_STATUS`, and test evidence.
   - `git push -u origin feat/thinking-status-line`.
   - `gh pr create --base master --title "..." --body "..."` with the Feature-examples blocks and
     test evidence; PR body calls out the breaking default change.
   - `gh pr checks <n>` until green. **Ask the user for explicit merge approval** (never merge on
     my own); after approval `gh pr merge <n> --merge --delete-branch`, then sync local master.
   - Trellis follow-up: `task.py archive 11-18-thinking-status-line` after the merge (bookkeeping
     commit allowed on master).

## Change boundary (before code)

- **Gap**: today reasoning is either printed in full (`SHOW_REASONING=true`) or silent; the target is
  one collapsed `✻ Thinking… Ns` status line that only appears when reasoning actually starts, then
  one permanent `∴ Thought for Ns`, with the full text hidden by default but preserved in history.
- **Where it lives**: rendering only — `Printer.display_stream` and private helpers in
  `yaicli/printer.py`; defaults/map/template in `yaicli/const.py`; the CLI switch in
  `yaicli/entry.py`. `LLMClient`, providers, `ChatMessage.reasoning` and session serialization are
  untouched, which is what keeps history intact.
- **Files expected to change**: `yaicli/const.py`, `yaicli/entry.py`, `yaicli/printer.py`,
  `tests/test_printer.py`, `README.md`, `docs/usage/configuration.md`,
  `docs/providers/deepseek.md`, `docs/providers/minimax.md`, `docs/advanced/history.md`.
- **Explicitly not doing**: tool-output display defaults (`TOOL_DISPLAY_MAX_LINES` stays 15),
  Ctrl+O thinking expansion, `stream-json` thinking events, non-streaming status, random spinner
  verbs, any pre-thinking "waiting" line.

## Validation commands (copy/paste)

```bash
cd /Users/vic/Documents/codes/git/yaicli
.venv/bin/ruff format yaicli tests
.venv/bin/ruff check --no-fix yaicli tests
.venv/bin/python -m pytest tests/test_printer.py tests/test_docs_config.py -q
.venv/bin/python -m pytest -q
.venv/bin/mkdocs build --strict
```

(If `uv run` works in the environment, the canonical commands remain `uv run pytest`,
`ruff check --no-fix yaicli tests`, `uv run mkdocs build --strict` per `CLAUDE.md`; the venv paths
above are the sandbox-friendly equivalents. `isort` is run by `just format` — if it is unavailable,
at least run `ruff format` and keep import order matching the surrounding file.)

## Risky files / rollback points

- `yaicli/printer.py` — the only behaviorally risky file (Rich Live lifecycle). Rollback: revert the
  commit; no persisted state, no migration.
- `yaicli/const.py` default flip — rollback also restores the previous display default.
- Docs drift guard (`tests/test_docs_config.py`) fails loudly if a table/template key is missed;
  treat it as the gate for step 6.

## Follow-up checks before PR

- [ ] Default run (reasoning model): no status until reasoning starts, then `✻ Thinking… Ns`,
      then `∴ Thought for Ns`; reasoning text absent; history JSON still contains `"reasoning"`.
- [ ] Non-reasoning model: no status line at all (no `Thinking… 0s` flash).
- [ ] `--show-reasoning`: old `Thinking:` block restored, no `Thought for`.
- [ ] `--no-thinking-status`: silent, no glyphs.
- [ ] `-p`/pipe/JSON: byte-identical stdout, no glyphs.
- [ ] Ctrl+C mid-thinking: no leftover spinner/summary; next prompt clean.
- [ ] Tool round: summary appears before `@Tool call:`; each round one summary.
- [ ] `ai --template` shows both keys; README + docs tables in sync.
- [ ] `TOOL_DISPLAY_MAX_LINES` is deliberately **not** changed in this task (the user tunes it
      themselves: default stays 15).
