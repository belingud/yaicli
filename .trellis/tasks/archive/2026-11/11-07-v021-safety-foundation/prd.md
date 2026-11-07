# v0.21 safety foundation (K10-K14)

## Goal

Make the agent safe to leave running and project-aware. This milestone picks up the K10-K14 scope that
was descoped from v0.20.0 (user decision at the v0.20.0 release), using
`var/lightweight-audit/09-roadmap.md` as the source of truth.

## Scope

- **K10 permission policy modes**: `TOOL_POLICY=readonly|standard|trusted` (readonly denies write/exec,
  standard keeps today's confirm-plus-rules behaviour, trusted only asks for dangerous exec), on top of
  the existing risk classes / `tool_permissions.json` v2 rules / audit log / `--yes` / `--allowed-tools`.
- **K11 workspace write safety**: confine `fs_write_file`/`fs_edit_file`/`fs_file_operations` writes to
  `WORKSPACE_ROOT`, protect `.git`/`.ssh`/`.env`/`*.pem`/etc., write-backup to `.yaicli-backups/` and
  add `/undo` for the last write of the session.
- **K12 project context**: auto-load `AGENTS.md` / `CLAUDE.md` / `.yaicli.md` from cwd→git root
  (bounded size, truncation notice, config to disable), no extra request when absent.
- **K13 session isolation & resume**: sessions under `~/.yaicli/sessions/<cwd-hash>/` with 0700/0600,
  model/provider/role/cwd metadata, `--resume` and no silent new-session on a missed `--chat` title.
- **K14 multi-provider tool-call consistency**: Anthropic multiple `tool_use` blocks, Gemini streamed
  same-name calls, Ollama multiple calls and the single-call streaming providers share one helper +
  per-provider tests.
- **Release v0.21.0**: changelog, docs, benchmark gate, bump/tag/PyPI/docs.

## Constraints

- Keep v0.20.0 guarantees: tools-complete base install (ddgs/trafilatura/fastmcp stay), lazy startup,
  headless stdout/stderr contract, no new runtime dependencies (stdlib + existing deps only).
- Backwards compatibility: old `tool_permissions.json` v1/v2 files keep working; new config keys default
  to today's behaviour (opt-in policy modes).
- Each K item is its own commit/subtask with tests; full suite + ruff + mkdocs --strict green.

## Acceptance Criteria

- [x] K10: policy modes selectable and enforced by the tool gate; readonly denies write/exec in
      non-interactive runs; audit log records the effective policy. (commit `09a41ad`)
- [x] K11: writes outside `WORKSPACE_ROOT` are refused with an actionable error; protected paths are
      denied; a write can be reverted with `/undo`; backup files are 0600. (commit `d305e92`)
- [x] K12: `AGENTS.md` content reaches the system prompt with a size cap and a stderr notice;
      `AGENTS_NONE`/config disables it; no file → no extra request cost. (commit `001258f`; config keys
      are `ENABLE_PROJECT_CONTEXT`/`PROJECT_CONTEXT_MAX_CHARS`, not `AGENTS_NONE`)
- [x] K13: sessions are per-project, 0600/0700, metadata-stamped; `--resume` works; a missed title
      does not silently start a new session. (commit `7def9ad`)
- [x] K14: multi-tool-call turns keep every call on Anthropic/Gemini/Ollama; provider tests cover it.
      (commit `7d5fa88`; shared accumulator `yaicli/llms/tool_calls.py`, plural `LLMResponse.tool_calls`)
- [x] v0.21.0 shipped to PyPI + docs; `scripts/bench.py --gate` green; task archived + journal recorded.
      (tag `v0.21.0` / changelog commit `dc52fa1`; PyPI wheel+sdist live, docs deployed)

## Notes

- W1 (K08/K09) shipped as v0.20.0 on 2026-11-07; see the archived `11-05-v020-lightweight-safety`.
- Suggested waves: W2a = K10+K11 (security core), W2b = K12+K13, W3 = K14 + release.
