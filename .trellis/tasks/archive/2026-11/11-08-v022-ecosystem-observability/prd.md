# v0.22.0 ecosystem & observability (K16-K20)

## Goal

Make the agent measurable, trustworthy at its extension edges (MCP), cheaper to run per request,
and comfortable to drive from the REPL. Source of truth: `var/lightweight-audit/09-roadmap.md`
P2 section; evidence reports `01-agent-loop.md`, `02-cli-ux.md`, `03-tools-safety.md`.

Baseline: master `d142223` (v0.21.2 released). 2141 tests green.

## Scope

- **K17 observability (foundation)**: `LLMResponse` carries provider-reported `usage`; the client
  accumulates per-session/per-model tokens, tool count/duration/size; `finish_reason=length` is
  surfaced (warning + JSON field) instead of silently truncating; `/cost` shows tokens + estimated
  cost; headless `--output-format json` / `stream-json` emits real usage; `SHOW_USAGE` per-turn line.
- **K16 MCP hardening**: a bad `mcp.json` or missing optional dependency can no longer abort the
  turn; tool descriptions are sanitized/capped/source-labelled; `MCP_TIMEOUT` bounds list/call;
  `MCP_MAX_TOOLS` caps injected tools with one stderr notice; results join every content block and
  mark `is_error`.
- **K20 secret redaction**: tool results are redacted before they are spilled to `TOOL_OUTPUT_DIR`
  and before a session is written by `/save`/auto-save; shared secret patterns in a new
  `yaicli/redaction.py`; `REDACT_SECRETS=false` keeps the raw bytes.
- **K19 schema narrowing**: `ENABLED_TOOLS` config + `--tools` flag filter builtin + MCP schemas
  with glob support (`fnmatch`), cached per filter, and disabled tools are rejected at the gate with
  an actionable in-band result; defaults unchanged.
- **K18 REPL agent UX (after K17)**: prompt shows model / role / context %; `/` command completion;
  new `/model`, `/role`, `/cost`, `/retry` commands (`/context`, `/compact`, `/undo` already exist);
  multiline input (Alt+Enter / Ctrl+J).
- **Release v0.22.0**: docs (README table, configuration reference, feature pages), changelog,
  bump/tag, PyPI + docs deploy; bench gate.

## Non-goals

- The roadmap "stretch" openai-compatible lite transport (one-shot ≤0.6s) is NOT part of this
  milestone; no new runtime dependencies (stdlib + existing deps only).
- No renaming of existing config keys; every new key defaults to "today's behaviour" or is inert
  until configured (except redaction, which is on by default and only affects on-disk copies).

## Design decisions

### New config keys (added centrally by the Lead before feature work)

| Key | Type | Default | Owner | Meaning |
|---|---|---|---|---|
| `MCP_TIMEOUT` | int | `30` | K16 | Seconds for one MCP list/call operation (`0` = no timeout) |
| `MCP_MAX_TOOLS` | int | `64` | K16 | Max MCP tools injected per request (`0` = unlimited) |
| `SHOW_USAGE` | bool | `true` | K17 | Print one dim token/cost line after each turn (interactive only) |
| `MODEL_PRICING` | dict | `{}` | K17 | JSON overrides for the built-in price table, `{"model-prefix": {"input": x, "output": y}}` USD per 1M tokens |
| `ENABLED_TOOLS` | str | `""` | K19 | Comma-separated tool-name globs; empty = all tools |
| `REDACT_SECRETS` | bool | `true` | K20 | Redact known secret shapes before writing tool output/sessions to disk |

### Shared module interfaces

`yaicli/usage.py` (K17, owner defines; only imported after the owner's commit):
```python
@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    estimated: bool = False
    def __add__(self, other) -> Usage
    def to_dict(self) -> dict

def usage_from_openai(obj) -> Optional[Usage]
def usage_from_anthropic(obj) -> Optional[Usage]
def usage_from_gemini(obj) -> Optional[Usage]
def usage_from_mistral(obj) -> Optional[Usage]
def usage_from_ollama(obj) -> Optional[Usage]
def estimate_usage(messages, completion_text: str) -> Usage
class UsageTracker:  # record(usage, model), total, by_model, requests, tool metrics
def estimate_cost(model: str, usage: Usage) -> Optional[float]
```

`yaicli/redaction.py` (K20):
```python
def redact_text(text: str) -> str                  # value-shape patterns, keeps ordinary text
def redact_json_value(value: Any) -> Any           # key-name based redaction for structured data
def redact_message_dict(payload: dict) -> dict     # used by chat.Chat.to_dict/save
```

### Write scopes

Lead owns central files: `yaicli/const.py`, `README.md`, `docs/usage/configuration.md`,
`tests/test_docs_config.py`, `pyproject.toml`, `CHANGELOG.md`, `mkdocs.yml` nav additions.
Feature owners own their module + tests + feature doc page; no commits are made by teammates
(the Lead reviews the diff and commits per K item).

## Waves

1. **W0 (Lead)**: milestone task + PRD; central config keys/template + README/configuration tables
   (guarded by `tests/test_docs_config.py`).
2. **W1 (parallel)**: K17 (usage), K16 (MCP), K20 (redaction) — disjoint files. Lead implements K19.
3. **W2**: K18 (REPL UX, depends on K17 `/cost` + usage API); docs pass; integration.
4. **W3 (Lead)**: full gates, changelog, release v0.22.0, archive + journal.

## Acceptance Criteria

- [x] K17: provider-reported usage reaches `LLMResponse`, `/cost` and `--output-format json`
      (`usage` non-zero from at least OpenAI-compatible + Anthropic paths); `finish_reason=length`
      produces a visible warning and is reported in JSON; tests mock each usage shape.
- [x] K16: broken `mcp.json`/missing fastmcp keeps the REPL alive with one actionable stderr line;
      description sanitization + source label covered by tests; `MCP_TIMEOUT` covered by a fake
      slow call; `MCP_MAX_TOOLS` truncation covered; multi-block result + `is_error` covered.
- [x] K20: `/save` + spill files contain `[redacted]` instead of `sk-*`/`AKIA*`/private keys while
      the in-memory/model-visible content is unchanged; `REDACT_SECRETS=false` disables; tests.
- [x] K19: `ENABLED_TOOLS`/`--tools` shrink the request schema set (byte-count assertion), unknown
      names warn once, disabled tool calls are refused in-band; default payload unchanged.
- [x] K18: prompt shows model/role/context; `/` completion lists every command; `/model`, `/role`,
      `/retry` work; Alt+Enter inserts a newline; tests for completion/prompt/commands.
- [x] Full suite + `ruff check yaicli tests` + `uv run mkdocs build --strict` +
      `uv run python scripts/bench.py --gate` green; docs site shows the new keys/pages.

## Release

- v0.22.0 shipped: tag `v0.22.0` (bump `75bc821`), changelog `94cf58b`; PyPI wheel `yaicli-0.22.0-py3-none-any.whl` (316,793 B) + sdist live; docs deployed to the `docs` branch; CI Publish-to-PyPI / Deploy-MkDocs / Startup-benchmark all green.
- Verification: 2435 tests, ruff clean, mkdocs strict pass, bench gate ok (idle machine; the shared sandbox can spike, a controlled A/B against v0.21.2 showed no startup regression).

## Notes

- Shipped commits: K16 `f61da5d`, K20 `4274473`, K17 `64ae9c6`, K19 `98cd3b7`, K18 `c34620c`.
- Release v0.22.0: bump/changelog/docs deploy after the final gates.

- K16/K17/K20 are independent; K18 depends on K17's usage API and `/cost`.
- K19 (Lead) can run in parallel with W1: it touches `tools/__init__.py` + `entry.py` only.
- `var/lightweight-audit/` is gitignored research; the PRD is the durable contract.
