# v0.20 lightweight and safety foundation

## Goal

Ship the v0.20 milestone from `var/lightweight-audit/09-roadmap.md`: make YAICLI stay fast and
light while keeping the agent safe to leave on. W1 (this branch) = K08 + K09.

## Scope

- **W1 — K08 startup latency**: lazy entry/cli imports, no prompt_toolkit on one-shot paths, deferred
  LLM client construction, `scripts/bench.py` with a regression gate. No behaviour change.
- **W1 — K09 tools-complete packaging**: every builtin tool (web_search/ddgs, fetch_webpage/trafilatura)
  and MCP (fastmcp) keeps working on a plain `pip install yaicli`; only cloud-provider SDK extras are
  split out of base.
- **W2 (later)**: K10 permission policy modes, K11 workspace write safety + `/undo`, K12 `AGENTS.md`,
  K13 session isolation.
- **W3 (later)**: K14 provider tool-call consistency, benchmark, docs, release v0.20.0.

## Product decisions

- **Tools out of the box wins over minimum install size** (user decision, 2026-11-05): the base install
  keeps `ddgs`, `trafilatura` and `fastmcp` so `pip install yaicli` never leaves a builtin tool broken.
- Because of that, K09 no longer targets 23 MB/29 dist. The revised goal is: remove only the cloud
  provider SDK closure (`anthropic[bedrock,vertex]`) from base; keep `[all]` complete and document
  `[bedrock]`/`[vertex]`.

## Acceptance Criteria

- [x] K08: `--version` unchanged (fast path); `--help` does not import `yaicli.cli`/prompt_toolkit;
      REPL first prompt no longer pays the provider SDK import (lazy client); bench script reports numbers.
      Done in `3d33651` (entry import ~563ms -> ~311ms, REPL readiness proxy ~0.55s, `scripts/bench.py`
      + `bench.yml`; tasks archived).
- [x] K09: base METADATA keeps `ddgs`, `trafilatura`, `fastmcp`; no `anthropic[bedrock,vertex]` in base;
      `[bedrock]`/`[vertex]` exist and `[all]` still pulls them; docs install matrix updated.
      Done in `d874b09` (tools-complete base kept per product decision; cloud SDKs opt-in; wheel +
      fresh-venv verified; tasks archived).
- [ ] Both: full test suite + ruff green; no user-visible behaviour change (docs/changelog note only).
      W1 gate green (1924 passed, ruff, `mkdocs build --strict`); changelog entry ships with v0.20.0.

## Notes

- W1 task subtasks (both done and archived): `11-05-k08-startup-latency`, `11-05-k09-tools-complete-packaging`.
- Release v0.20.0 happens in W3, not here.
- W2 to start next: K10 permission policy modes, K11 workspace write safety + `/undo`, K12 `AGENTS.md`,
  K13 session isolation; then K14 consistency + benchmark + docs + release (W3).
