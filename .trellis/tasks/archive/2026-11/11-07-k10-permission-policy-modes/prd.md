# K10 permission policy modes

Parent: `11-07-v021-safety-foundation`. Source: `var/lightweight-audit/09-roadmap.md` P1 K10.

## Semantics (exact)

`TOOL_POLICY` = `readonly|standard|trusted` (`YAI_TOOL_POLICY` env > config.ini > default `standard`;
invalid → `standard` + one stderr warning).

| mode | auto-allowed, no prompt/rule | hard-denied | interactive prompt |
| --- | --- | --- | --- |
| readonly | read + network risk | write + exec risk (rules / `--yes` / `--allowed-tools` / `TOOL_CONFIRM=false` cannot override) | only danger-classified shell |
| standard | today's flow unchanged | danger shell when non-interactive (unchanged) | everything not otherwise allowed (unchanged) |
| trusted | every non-dangerous tool | danger shell when non-interactive (unchanged) | danger-classified shell only |

Precedence per call: (1) danger-classified shell keeps its existing interactive-confirm / non-interactive-deny
branch; (2) readonly deny write/exec with an actionable reason naming `TOOL_POLICY`; (3) trusted allow;
(4) standard existing approval flow. Denies keep the structured `{"error": "tool_denied", "reason": ...}`
result, set `tool_denied`, print one stderr diagnostic. Audit JSONL gains `"policy": <effective mode>` on
allowed/denied/error lines; other fields unchanged.

## Files (write scope)

`yaicli/const.py` (DEFAULT_TOOL_POLICY, TOOL_POLICY in DEFAULT_CONFIG_MAP + DEFAULT_CONFIG_INI),
`yaicli/llms/client.py` (gate enforcement + audit field), `tests/test_tool_policy.py` (new),
`tests/test_permissions.py` (only if needed).

## DO NOT touch

`yaicli/tools/**`, `yaicli/cmd_handler.py`, `yaicli/cli.py`, `yaicli/entry.py`, builtins, `docs/`,
`openspec/`, `.trellis/spec/` (another teammate + Lead own those). No new dependencies, Python 3.10,
ruff F, 120 cols. No git state commands.

## Acceptance

- [ ] readonly non-interactive denies write/exec (structured deny) and runs read/network without prompt;
      persisted rules/`--yes`/`--allowed-tools`/`TOOL_CONFIRM=false` cannot override.
- [ ] trusted runs write/exec without prompt; danger shell still prompts interactively / denied non-interactively.
- [ ] standard: existing permission suite unchanged; invalid mode → standard + one warning.
- [ ] audit lines carry `policy`; new tests + `tests/test_permissions.py` + `tests/llms/test_tool_confirmation.py`
      pass; `ruff check` clean.
