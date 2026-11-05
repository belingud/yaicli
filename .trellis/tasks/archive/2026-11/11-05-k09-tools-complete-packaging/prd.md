# K09 tools-complete packaging

## Goal

A plain `pip install yaicli` must leave every builtin tool and MCP working: `web_search` (ddgs),
`fetch_webpage` (trafilatura extraction), `get_weather`, filesystem/shell tools, and MCP (fastmcp).
Only cloud-provider SDKs move out of the base install.

## Requirements

- `pyproject.toml`: base keeps `ddgs`, `trafilatura`, `fastmcp`, `httpx`, `json-repair`,
  `docstring-parser`, `rich`, `typer`, `click`, `prompt-toolkit`, `openai`, `anthropic`, `distro`,
  `socksio`.
- Base changes `anthropic[bedrock,vertex]>=0.57.1` to plain `anthropic>=0.57.1`.
- New extras: `bedrock = ["anthropic[bedrock]>=0.57.1"]`, `vertex = ["anthropic[vertex]>=0.57.1"]`.
- `[all]` stays complete: include `anthropic[bedrock,vertex]` plus the existing provider extras.
- Provider creation for a missing optional SDK raises the classified `AgentError` with an actionable
  hint (verify existing behaviour; extend the hint text to name the extra when missing).
- Docs install matrix updated (`docs/install.md`, `docs/providers/overview.md`, `README` if it lists
  extras): base = chat + all builtin tools + MCP; `[bedrock]`/`[vertex]` cloud; `[all]` everything.
- Tests: base dependency assertions (tool deps present, cloud extras absent) and a fresh-install smoke
  check in the release verification notes.

## Acceptance Criteria

- [ ] Built wheel `METADATA`: base `Requires-Dist` includes `ddgs`, `trafilatura`, `fastmcp` and plain
      `anthropic`; no `anthropic[bedrock,vertex]`; `Requires-Dist` for `bedrock`/`vertex`/`all` exist.
- [ ] `tests/test_packaging.py` locks the policy so a future slim-down cannot silently break tools.
- [ ] Fresh venv from the built base wheel imports all 12 builtin tool modules + `fastmcp` and
      `ai --list-functions` shows builtin tools.
- [ ] Full pytest + ruff + `mkdocs build --strict` green.

## Non-goals

- Removing `ddgs`/`trafilatura`/`fastmcp` from base (explicitly rejected: tools must work out of the box).
- Replacing the fetch extractor with a lighter one.
