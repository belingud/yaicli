# K08 implementation plan

## Change boundary

- Behaviour gap: cold start pays for imports/client construction that only the REPL or the provider
  needs. The smallest fix is to import at the use site and construct the client lazily.
- Where it lives: `yaicli/entry.py` (module-level imports for callbacks), `yaicli/cli.py` (prompt_toolkit
  top-level imports, eager `PromptSession`, eager `LLMClient` construction), new `scripts/bench.py`.
- Not doing: entry's `cfg` import (option defaults need it at decoration time), typer/rich removal.

## Steps

- [x] `yaicli/cli.py`: lazy module-level helpers `_prompt_session_class()` / `_llm_client_class()` that
      keep `PromptSession` / `LLMClient` module attributes patchable; move `AutoSuggestFromHistory`,
      `KeyBindings`/`KeyPressEvent`, `prompt()` imports into their functions.
- [x] `yaicli/cli.py`: drop the eager `PromptSession` block from `__init__` (REPL builds one in
      `prepare_chat_loop`); `self.bindings` starts `None` and `_setup_key_bindings()` creates it.
- [x] `yaicli/cli.py`: replace eager client construction with `client` property + `_client` slot;
      setter keeps `cli.client = mock`; creation re-points consoles via `_sync_client_console`.
- [x] `yaicli/entry.py`: move `FileChatManager`, `RoleManager`, `ProviderFactory` and the four
      `functions` callbacks behind module-level lazy wrapper callables (same single-value signature).
- [x] `scripts/bench.py`: stdlib bench for `--version`, `--help`, `--template`, `import yaicli.entry`,
      a REPL-construction proxy, one-shot-to-first-request via a local mock OpenAI server; `--json`,
      repeat count, optional max-ms thresholds, `--gate` defaults; `.github/workflows/bench.yml` gate.
- [x] Tests: subprocess import-boundary test (no prompt_toolkit/yaicli.cli after importing entry);
      lazy-client test (client not created in `__init__`, created on first access); update
      `tests/test_headless_contract.py` plain-TTY test to expect REPL-time session creation.
- [x] Verify: targeted tests, full pytest (1913 passed), ruff, mkdocs strict; bench numbers recorded.

## Verification results (macOS sandbox, P50 of 3 runs)

| metric | before | after |
| --- | --- | --- |
| `import yaicli.entry` (importtime cumulative) | ~563 ms | ~311 ms |
| `--version` | ~38 ms | ~42 ms |
| `--help` | ~430–520 ms | ~451 ms |
| `--template` | ~420–470 ms | ~449 ms |
| REPL readiness proxy (entry+cli+session) | roadmap baseline ~1.55 s | ~0.55 s |
| one-shot local overhead (spawn → first request) | ~1.5–1.6 s | ~1.56 s (openai SDK import dominates; entry/prompt_toolkit ~0.4 s removed, sandbox import costs are 2–3× bare metal per roadmap §7.1) |
| prompt_toolkit imported by one-shot/`--help` | yes | no |
