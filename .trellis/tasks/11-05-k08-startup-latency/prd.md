# K08 startup latency

## Goal

Cut cold-start work that is not needed for the current mode, with no user-visible behaviour change:

- `ai --help/--template` must not import the CLI stack (`yaicli.cli`, prompt_toolkit, provider SDKs).
- one-shot (`ai -p ...`) must not build a prompt_toolkit `PromptSession` or build a second
  `PromptSession` in `CLI.__init__` (REPL builds its own in `prepare_chat_loop`).
- interactive REPL must not pay the provider SDK import at startup: construct the `LLMClient` on
  first use (first request), keeping machine-mode console re-pointing intact.
- add `scripts/bench.py` to measure `--version`, `--help`, `--template`, `import yaicli.entry` and
  a one-shot local-overhead proxy, with optional threshold failure.

## Constraints

- Keep module-level names `PromptSession`/`LLMClient` patchable in `yaicli.cli` (tests patch
  `yaicli.cli.PromptSession` and `yaicli.cli.LLMClient`); implement lazy imports through small
  module-level helpers instead of direct function-local imports where tests need patch points.
- No new runtime dependencies. Bench script is stdlib only.
- `--version/--help/--template/--list-*` stay write-free (K21 contract) and `--help | head` exits 141.

## Acceptance Criteria

- [ ] `python -c "import yaicli.entry"` does not import `prompt_toolkit` or `yaicli.cli`.
- [ ] `scripts/bench.py` runs locally and prints reproducible numbers; `--json` output; thresholds
      (`--max-version-ms`, `--max-help-ms`, `--max-entry-import-ms`) can fail the process.
- [ ] REPL first-prompt path no longer constructs `LLMClient`; first `cli.client` access does.
      `cli.client = mock` still works (property setter).
- [ ] `CLI.__init__` never constructs a `PromptSession`; `prepare_chat_loop()` does exactly one.
- [ ] Full pytest + `ruff check yaicli tests` green; `mkdocs build --strict` unaffected.

## Non-goals

- Replacing typer/rich (plain-click rewrite is P1-b, out of scope).
- openai-compatible lite transport (v0.21 stretch).
