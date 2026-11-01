# Fix Bootstrap-Known Defects

## Goal

The `00-bootstrap-guidelines` task recorded seven real defects while documenting the
repository. They were intentionally left unfixed then ("bootstrap documents reality").
This task fixes all seven so the specs stop describing broken behaviour.

Source of the defect list: `.trellis/tasks/archive/2026-11/00-bootstrap-guidelines/prd.md`
section "Known defects documented (not fixed here — bootstrap documents reality)".

## Defects and required fixes

### D1 — First run crashes: `KeyError: 'PROVIDER'`; `YAI_PROVIDER` ignored

`PROVIDER` exists in `DEFAULT_CONFIG_INI` but not in `DEFAULT_CONFIG_MAP`, so the env-based
loader never reads `YAI_PROVIDER`, and `Config._load_from_file()` returns right after writing
the default ini without parsing it. A first run with no config file therefore leaves
`cfg["PROVIDER"]` unset and `CLI()` raises `KeyError: 'PROVIDER'`.

Fix:
- add `PROVIDER` to `DEFAULT_CONFIG_MAP` (`env_key="YAI_PROVIDER"`, type `str`, default
  `DEFAULT_PROVIDER`);
- when the config file is missing, write `DEFAULT_CONFIG_INI` **and parse it** (do not return
  before the shared parsing path);
- treat empty file/env values as "unset" in the conversion layer, so the parsed template keeps the
  typed map defaults (`EXTRA_HEADERS`/`EXTRA_BODY` → `{}`, `REASONING_EFFORT` → `None`). Without
  this, making the first run parse the template would hand raw `""` to typed consumers — a
  behaviour regression vs. the pre-fix first run, and `gemini_provider.get_chat_config()` merges
  `EXTRA_HEADERS` unguarded (`{**""}` raises `TypeError`);
- keep `DEFAULT_CONFIG_INI` output byte-identical (`--template` test compares it line by line).

Regression tests: first run in a fresh config path does not raise, `config["PROVIDER"] == "openai"`,
the written file contains `PROVIDER=openai`, `YAI_PROVIDER` overrides it, first and later runs agree
on typed defaults, and empty template values fall back to the typed defaults.

### D2 — `const.CODE_MODE` defined but never dispatched

`--code` is the CODER role + plaintext printer; there is no code runtime mode. `/mode` and
`Shift+Tab` only know `chat`/`exec`.

Fix: remove the dead `CODE_MODE` constant (no imports/call sites exist), and update the specs
that mention it.

### D3 — `MAX_HISTORY` / `ROLE_MODIFY_WARNING` declared but never read

Both keys are advertised in `README.md` and `docs/usage/configuration.md`.

Fix:
- `MAX_HISTORY`: `CLI.prepare_chat_loop()` currently passes `self.interactive_round` as
  `LimitedFileHistory`'s `max_entries`; pass `cfg["MAX_HISTORY"]` instead. Documented semantics
  `MAX_HISTORY=0` (disable saving) must be honoured: a zero/negative limit makes
  `LimitedFileHistory` stop writing entries.
- `ROLE_MODIFY_WARNING`: warning toggle for modified built-in roles. `RoleManager.create_role()`
  and `RoleManager.delete_role()` must emit a warning when the target name is a built-in
  (`DEFAULT_ROLES`) role, gated by `cfg["ROLE_MODIFY_WARNING"]` (default true). Custom roles
  never warn.

Regression tests: history file keeps no new entries at limit 0; normal trimming still works;
`prepare_chat_loop` builds history with `max_entries=cfg["MAX_HISTORY"]`; role warning prints for
built-ins when enabled and is silent when disabled / for custom roles.

### D4 — `--image`-only invocation aborts in `CLI.run()`

`entry.py` intentionally allows an image-only invocation but passes `user_input=""`; `CLI.run()`
then sees a falsy prompt and aborts with "No input provided." The archived image-input spec says
an image-only invocation MUST still send the image with an empty or minimal text prompt.

Fix: when images are supplied and no prompt is present, send a minimal prompt instead of `""`
(singular for one image, plural for several). Keep warning/validation behaviour for bad images.

Regression tests: `--image` with no prompt reaches `CLI.run()` with the minimal prompt and the
processed `images`; several `--image` flags still work.

### D5 — `ContextManager` uses a `"[...]"` string sentinel

`_read_file()` returns error/placeholder strings beginning with `[` (`[Binary file omitted]`,
`[File too large: ...]`, `[Error reading file: ...]`), and `parse_at_references()` filters
"unavailable" content with `content.strip().startswith("[")`. Real text files whose content starts
with `[` (JSON arrays, Markdown links, logs) are silently dropped.

Fix: give `_read_file()` a structured result (content vs. placeholder/error) instead of a magic
string; `parse_at_references()` includes any real content and warns only when the read actually
failed. Directory context must not embed binary/error placeholders.

Regression tests: a UTF-8 file starting with `[` is referenced/included; error/binary/big files
are still omitted with a warning; existing traversal/binary tests updated to the new return shape.

### D6 — `RoleManager.print_roles()` is broken dead code

It iterates `list_roles()` (a list of dicts) and uses `role.name` / `role.prompt` /
`role.temperature` / `role.top_p`, which raises `AttributeError`; nothing calls it. The CLI
already exposes `--list-roles` (`print_list_option`) and `--show-role`.

Fix: delete the method and its vacuous test. No user-facing command is lost.

### D7 — `functions/buildin/fs_read_image.py` still advertises `Union[str, List[str]]`

Same schema-shape bug class fixed for `fs_read_file` in `0d2d943`: Gemini derives the declaration
from `execute()`'s signature and produces `type=OBJECT` + `any_of=[STRING, ARRAY]`; OpenAI/Anthropic
get an `anyOf` union. Multi-image calls are unreliable as a result.

Fix: mirror `fs_read_file` — `image_paths: List[str]` with a list example/description,
`execute(cls, image_paths: List[str], ...)` normalizing legacy `str`/`tuple`, an in-band error for
other types, unchanged limits and single-element flat payload. Add schema tests (OpenAI/Anthropic,
Gemini) and e2e tool-call coverage.

## Constraints

- No behaviour change beyond the seven defects; no dependency additions.
- Tests must not make network calls; use existing fixtures (`tests/conftest.py`).
- `DEFAULT_CONFIG_INI` text must not change except if a new key is truly needed (it is not).
- Keep user docs truthful: update `README.md` / `docs/` only where behaviour becomes newly true
  (e.g. image-only minimal prompt note) or where a command disappeared (none).
- Builtin function templates stay standalone (stdlib + pydantic + `yaicli.function_schema` only).
- Existing `fs_read_file` behaviour/tests must not regress.

## Acceptance Criteria

- [x] All seven defects fixed; each has a regression test that would fail on the old code.
- [x] `pytest` full suite green; `ruff check yaicli tests` clean; no new skipped tests.
- [x] First-run path verified in a process with an empty config dir + `HOME` sandbox.
- [x] First run and later runs agree on typed defaults (empty template values do not leak `""`).
- [x] `--image`-only invocation reaches `CLI.run()` with a non-empty minimal prompt.
- [x] `fs_read_image` OpenAI/Anthropic schemas advertise `array` of `string` (no `anyOf`);
      Gemini declaration is `ARRAY`/`STRING` with `any_of is None`.
- [x] `.trellis/spec/` updated: remove the "known defects" claims that no longer hold and record
      the new rules (config first-run, structured file-read result, history/role config wiring,
      image-only prompt, fs_read_image array schema).
- [x] `python3 .trellis/scripts/task.py validate <task>` passes before archive.
- [x] PRD "known defects" record in the bootstrap task gets a fixed-in reference at finish.

## Outcome (2026-11-01)

All seven defects fixed, verified by the Lead and independently re-verified by a read-only
verifier (PASS on D1-D7 plus the typed-defaults hardening).

Commits:

| Commit | Change |
|--------|--------|
| `097b6b4` | fix(config): first-run config parsing, `YAI_PROVIDER`, typed defaults, drop `CODE_MODE` |
| `defdf80` | fix(cli): wire `MAX_HISTORY` / `ROLE_MODIFY_WARNING`, remove `print_roles()` |
| `8703514` | fix(context): `FileReadResult` replaces the `[`-sentinel |
| `c6df177` | fix(cli): minimal prompt for image-only invocations |
| `92a4d05` | fix(functions): array-first `fs_read_image` schema |
| `37d46a7` | docs: image-only prompt + multi-image function docs |

Verification evidence:

- full suite: `1 failed, 1055 passed` — only the pre-existing environmental
  `tests/test_run_smoke.py::TestPromptToolkitIntegration::test_prompt_toolkit_input`
  (`PermissionError` writing `~/.yaicli_history`; passes under a temp `HOME`);
- targeted suite for the touched areas: `250 passed` (config/entry/history/role/cli/context/
  fs_read_image/fs_read_file);
- `ruff check yaicli tests` clean; `task.py validate` passes;
- first run vs later run cfg dicts are identical; `DEFAULT_CONFIG_INI` output unchanged;
- old-code reproduction confirmed the new tests are non-vacuous (D1/D5/D7).

Residual notes (documented, not regressions): `MAX_HISTORY=0` "disable saving" only prevents new
writes (`store_string` no-op; `_trim_history`'s clear-on-non-positive branch is defensive);
empty text files referenced with `@path` are now embedded as an empty fenced block instead of
warned about; `--image` combined with `--chat` is still ignored in the REPL (pre-existing,
documented); Gemini schema tests `importorskip` `google.genai` so a minimal venv skips them.

## Verification Commands

```bash
.venv/bin/python -m pytest tests/test_config.py tests/test_entry.py \
  tests/test_history.py tests/test_role.py tests/test_cli.py \
  tests/test_context.py tests/tools/test_fs_read_image.py tests/tools/test_fs_read_file.py -q
.venv/bin/python -m pytest -q            # full suite
.venv/bin/ruff check yaicli tests
python3 .trellis/scripts/get_context.py --mode packages
```

Note: `uv run` is unavailable in this sandbox (cache dir denied); use `.venv/bin/python`.
The single pre-existing `tests/test_run_smoke.py` history-file failure is environmental
(sandbox denies `~/.yaicli_history`), not related to this task.

## Out of Scope

- Other "document reality" discrepancies from the specs (stale `CLAUDE.md` provider note,
  `docs/changelog.md` v0.7.8, `docs/dev/architecture.md` stub, CI lacking pytest/lint workflow,
  `Justfile` `isort yaicli yaicli` duplicate, `.pdm_build/` spelling). Recorded as follow-ups.
