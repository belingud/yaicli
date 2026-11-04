# Function Calling, Built-in Functions & MCP Guidelines

Read this before changing `yaicli/function_schema.py`, `yaicli/tools/`, `yaicli/functions/`,
or the tool-execution path in `yaicli/llms/client.py`.

A built-in tool definition feeds three generators, so schema changes are cross-provider: OpenAI/
Anthropic from the pydantic model (`yaicli/function_schema.py`), Gemini from the `execute`
signature (`get_functions_gemini_format`). MCP declarations convert the server's `inputSchema`
separately (`yaicli/tools/mcp.py`). Behavior is specified by
[tool-execution-confirmation](../../../openspec/specs/tool-execution-confirmation/spec.md) and
[interactive-tool-policy](../../../openspec/specs/interactive-tool-policy/spec.md); update those
specs and tests together.

## Layer Map

| Concern | Where | Contract |
| --- | --- | --- |
| Schema generation | `yaicli/function_schema.py` | `OpenAISchema.openai_schema` / `.anthropic_schema`, cached per class. |
| Loading / dispatch | `yaicli/tools/function.py`, `yaicli/tools/__init__.py` | Package builtins + `FUNCTIONS_DIR` overrides, per-file robustness, `Function` metadata (`source`/`file_path`/`risk`), schema caches, `execute_tool_call()` (arg repair, output truncation). |
| Built-ins | `yaicli/functions/buildin/`, `yaicli/functions/__init__.py` | Builtins load from the installed package (zero setup); `--install-functions` exports editable copies; `functions_manifest.json` version+sha256 drives the stale-copy warning. |
| Risk / limit helpers | `yaicli/tools/risk.py`, `yaicli/tools/limits.py` | Risk classes + shlex shell-danger classifier; per-tool output caps and spill-to-disk. |
| Policy / confirmation | `yaicli/llms/client.py`, `yaicli/tools/approval.py`, `yaicli/schemas.py` | Per-request `ToolPolicy` filter → risk/rule-aware confirmation gate (danger double-confirm, `--yes`/`--allowed-tools`) → execution → audit log. |
| MCP | `yaicli/tools/mcp.py` | Lazy `fastmcp`, `_mcp__` prefix, MCP→provider schema conversion; MCP tools default to `exec` risk. |

## Schema Generation (`OpenAISchema`)

`openai_schema` is derived from `cls.model_json_schema()` in `yaicli/function_schema.py`:

- **Tool name = pydantic model title** (`class Config: title = "fs_read_file"`); class/file names
  are irrelevant, and duplicate titles overwrite each other in `_func_name_map`.
- **Function description = class docstring**; without one the fallback is the generic
  "Correctly extracted ..." string, so always write the docstring.
- **Field descriptions: `Field(description=...)` wins; class-docstring `Args:` fills gaps** only
  where no field description exists (`function_schema.py` lines 55–58; see
  `tests/tools/test_function_schema.py::test_openai_schema_field_description_takes_priority`).
- **`required` = properties with no JSON-schema `default`** (`Field(...)` required,
  `Field(default=...)` optional). Use literal defaults — `default_factory` emits no `default`
  and flips `required`.
- `openai_schema` strips top-level `title`/`description` from `parameters`; `anthropic_schema`
  returns `{name, description, input_schema: model_json_schema()}`. Provider quirks belong here,
  not in built-ins. Both are cached `classproperty` values shared by callers — treat as immutable.

### Schema design rule: advertise one exact JSON type

Never put `Union`/`Optional` in a model-facing field type. This is the bug fixed by commit
`0d2d943`: the old `Union[str, List[str]]` produced `anyOf` in the OpenAI/Anthropic schemas and,
because Gemini derives declarations from the `execute` signature, `type=OBJECT` +
`any_of=[STRING, ARRAY]` for `file_paths`. The fix advertises one narrow type and normalizes
legacy input inside `execute` (`yaicli/functions/buildin/fs_read_file.py`):

```python
file_paths: List[str] = Field(..., examples=[["/path/to/file1.txt", "/path/to/file2.txt"]],
                              description="File paths to read. Pass a list of paths ...")
# execute(): accept a legacy single path string / tuple; error in-band on anything else.
if isinstance(file_paths, str):
    paths_list = [file_paths]
elif isinstance(file_paths, (list, tuple)):
    paths_list = list(file_paths)
else:
    return json.dumps({"error": "file_paths must be a list of file paths ..."}, ensure_ascii=False)
```

Guards: `tests/tools/test_fs_read_file.py::TestFSReadFileSchema` asserts `type == "array"`,
`items == {"type": "string"}`, no `anyOf`; `::TestFSReadFileGeminiSchema` asserts `ARRAY`/`STRING`
and `any_of is None`. `fs_read_image.py` follows the same array-first contract now
(`image_paths: List[str]`, legacy `str`/`tuple` normalized in `execute`) with matching guards in
`tests/tools/test_fs_read_image.py::TestFSReadImageSchema` / `::TestFSReadImageGeminiSchema`.

## Built-in Function Contract (`yaicli/functions/buildin/`)

Each file defines one public `class Function(OpenAISchema)` plus `class Config: title`.

1. `execute` is a `@classmethod` whose parameter names, types and defaults match the model
   fields: OpenAI/Anthropic read the pydantic model, Gemini reads this signature. Keep
   `Field(default="utf-8")` and `execute(..., encoding: str = "utf-8")` in sync (`fs_read_file.py`).
2. Return a `str`. Use JSON (`json.dumps(..., ensure_ascii=False)`) when the result has structure
   (all `fs_*` built-ins); plain text suits single-value results (`execute_shell_command`:
   `"Exit code: N, Output:\n..."`; `get_weather`: one summary line).
3. Report expected failures in-band, never by raising: `fs_write_file` returns
   `{"success": false, "error": ...}`, `fs_read_file` returns `{"error": ...}` for invalid
   `file_paths`, `execute_shell_command` returns `"Error: ..."`. `execute_tool_call` only catches
   unexpected exceptions, and its generic message cannot help the model fix its arguments.
4. Enforce resource limits in `execute` as in-band errors: `fs_read_file` caps 50 files, 10 MB per
   file and 50 MB total; `fs_read_image` caps 20 images and 5 MB each.
5. Guard the side effect: `fs_write_file` refuses `/etc/`, `/sys/`, `/proc/`, `/dev/`. The shell
   tool no longer keeps a substring blacklist (it broke `git add`): `execute_shell_command` enforces
   timeout/cwd/env/output caps, and destructive commands are classified by
   `yaicli/tools/risk.py::classify_shell_command` + confirmed/denied at the approval gate. New
   side-effecting built-ins should declare `risk` metadata in `tools/risk.py` and rely on the gate.
6. Import heavy/optional packages inside `execute`: `web_search` imports `ddgs` lazily,
   `fetch_webpage` imports `trafilatura` lazily. Every builtin + `FUNCTIONS_DIR` file is exec'd when
   the tool map is first built, so top-level imports slow the first tool-advertising request and a
   missing optional extra must degrade to an in-band error, not a load failure.
7. No printing/UI from `execute`; the call line, `SHOW_FUNCTION_OUTPUT` panel and confirmation
   prompt belong to `yaicli/tools/__init__.py` and `yaicli/llms/client.py`. Those render sites use
   the untrusted-text helpers (`safe_text`/`untrusted_text`) so tool arguments/results can never
   act as Rich markup or emit terminal control sequences.
8. Write-backs must be all-or-nothing and atomic: validate every input first, never partially
   apply an edit list, and replace files via temp file + `os.replace`. `fs_edit_file` is the
   reference: any failed edit leaves the file byte-identical (`success=false`), `replace`
   requires a non-empty `old != new`, and a read-only target is rejected before writing.
9. Network-facing built-ins must validate their targets before any request: `fetch_webpage`
   only allows public http(s), rejects loopback/private/link-local/metadata/CGNAT targets, and
   re-validates every redirect hop (no https-to-http downgrade, no cross-host cookie/Referer
   forwarding, 10 MB response cap). Failures are returned in-band as `Failed to fetch ...`
   strings instead of raising.

## Loading & Install Lifecycle

- v0.19 makes built-ins available out of the box: `get_func_name_map()` loads
  `yaicli/functions/buildin/*.py` **from the installed package first**, then `FUNCTIONS_DIR`
  (`<config-dir>/functions/`). A user file whose schema function name equals a builtin replaces it;
  otherwise the builtin wins. This is the customization path — `--install-functions` only exports
  editable copies (idempotent, never overwrites an existing file) and `--reinstall-functions`
  refreshes those copies (removing untouched copies of builtins that no longer exist, keeping
  user-modified ones). Do not assume the file on disk in `buildin/` is the one executing for an
  existing install: an old exported copy overrides it until `--reinstall-functions`.
- `functions_manifest.json` (`const.FUNCTIONS_MANIFEST_PATH`, written by install/reinstall) records
  the package version + sha256 per builtin. An installed copy whose hash matches the recorded
  install hash and now differs from the bundled file is "stale" → one stderr warning, never blocks.
  Copies the user edited are treated as intentional overrides (no nagging). Pre-v0.19 configs have
  no manifest, so no stale warning is possible until the first install/reinstall in v0.19.
- Per-file robustness (K15): a syntax/import error, missing `Function`, missing
  `openai_schema`/`anthropic_schema`/`execute`, or a bad `risk` import skips **that file** with one
  warning; all other tools keep working. `list_functions()` never creates `FUNCTIONS_DIR`.
- Four caches: `_func_name_map`/`_gemini_functions_cache` in `tools/function.py`,
  `_openai_schemas_cache`/`_anthropic_schemas_cache` in `tools/__init__.py`. Production never
  invalidates them; tests patching `FUNCTIONS_DIR` must reset all four (autouse `reset_caches`
  fixture in `tests/tools/test_function_loading.py`).
- `Function` exposes `name`/`description`/`parameters`/`execute`/`func_cls` plus `source`
  (`builtin`/`user`), `file_path` and `risk` (from `tools/risk.py`, `ImportError`-tolerant). Add a
  builtin by adding the `buildin/` file + schema-contract/execute/end-to-end tests; no install step.
- `--list-functions` prints `name (builtin|user)` and a one-line stale hint; it never writes.

## Execution Path (`execute_tool_call`)

`yaicli/tools/__init__.py::execute_tool_call(tool_call, announce=True) -> Tuple[str, bool]`: the
`_mcp__` prefix selects MCP (`SHOW_MCP_OUTPUT`) vs built-in (`SHOW_FUNCTION_OUTPUT`); arguments
are parsed with `json_repair.repair_json(..., return_objects=True)` and must be a `dict` (never
`json.loads`), then the tool runs and its output prints in a `Panel` when the flag is on.

Every result passes through `yaicli/tools/limits.py::truncate_tool_output()` before it is appended
to the model messages (and before the panel is rendered): per-tool caps (shell 32KB, `fs_read_file`
64KB, search/list 48KB, fetch 100KB, MCP/default 32KB; `TOOL_OUTPUT_MAX_CHARS` overrides, `0`
disables), head+tail with a marker pointing at the full text spilled to `TOOL_OUTPUT_DIR`; spill files
are written 0600 (best effort) because they may contain secrets. A spill failure degrades to plain
truncation. Keep this the single truncation point — do not truncate again in `client.py`/`printer.py`.
`fs_read_file` implements the paging the marker promises (`offset`/`limit` characters, `0` = start /
to end) and reports `total_chars`/`returned_chars`/`truncated`; keep marker, docs and signature in
sync. The standalone shell tool reads its guardrails from `YAI_*` env; `execute_tool_call` exports the
effective `cfg` values (TOOL_TIMEOUT/TOOL_ENV_INHERIT/WORKSPACE_ROOT/TOOL_OUTPUT_MAX_CHARS)
unconditionally (empty skipped), so `--cwd`/config.ini win over a stale exported value. Tool announce/output panels use `get_error_console()` when stdout is not
a TTY (headless JSON purity), the Rich console otherwise.

`ok=True` means the call reached the tool, including in-band errors such as
`{"error": "file_paths must be a list ..."}`. `ok=False` covers an unknown tool, bad arguments, or
an exception from `execute`; the returned text is the error report. Do not raise here.

- Pass `announce=False` when the call was already shown: `LLMClient` passes `announce=not prompted`
  after the confirmation prompt. Never print the call line in a tool.
- MCP names are de-prefixed in place (`execute_tool_call` mutates `tool_call.name`); capture the
  gate-time name first (`client.py` comment) and use `gen_mcp_tool_name`/`parse_mcp_tool_name`.
- Do not call `execute_tool_call` from CLI/display code: `ToolPolicy` filter
  (`LLMClient._get_valid_tool_calls`) → confirmation gate (`_execute_tools_and_continue`) →
  `execute_tool_call`.

## Tool Policy, Risk & Confirmation

- `ToolPolicy` (`yaicli/schemas.py`) is a frozen per-request pair of flags; functions and MCP are
  independent. `exec` mode forces `ToolPolicy(False, False)` (`CLI._get_tool_policy`), defaults are
  ANDed in `Provider.resolve_tool_policy`, and disallowed calls are dropped, not persisted.
- Risk classes live in `yaicli/tools/risk.py`: `RiskLevel` (`read`/`write`/`network`/`exec`),
  `BUILTIN_TOOL_RISK` for the 12 builtins and `get_tool_risk(name)` (MCP/unknown → `exec`). The
  classifier `classify_shell_command()` is shlex/argv based (rm -r/-f, mkfs, dd of=/dev, shutdown
  family, recursive chmod/chown on system paths, find -delete, download|shell pipes, fork bombs,
  git clean -f, device redirects, ...); `is_dangerous_shell()` is the convenience wrapper. Never
  reintroduce substring blacklists (they false-positive on `git add` and miss flag permutations).
- `TOOL_CONFIRM` (enabled by default) gates execution; approved rules/names skip the prompt unless
  the call is a **dangerous shell command**, which is always confirmed even when the tool/rule is
  allowed (non-interactive => deny). Interactive sessions get `ConfirmToolCall` →
  `ToolConfirmDecision` (`ONCE`/`SESSION`/`PERSIST`/`DENY`).
- Headless policy: `--yes` auto-allows only `read` risk; `--allowed-tools` grants this run only
  (fnmatch, never persisted); everything else is denied without a TTY. A deny appends a tool message
  with the matching `tool_call_id` and structured JSON content
  `{"error": "tool_denied", "reason": "..."}` and sets `LLMClient.tool_denied` (CLI mirrors it so
  `--fail-on-tool-denied` can exit 3).
- `ToolApprovalManager` (`yaicli/tools/approval.py`) keeps a session set plus
  `TOOL_PERMISSIONS_PATH` (`<config-dir>/tool_permissions.json`). v2 schema:
  `{"version": 2, "always_allow": ["tool", ...],
  "rules": [{"tool": ..., "argv_prefix": [...]}, {"tool": ..., "path_glob": "..."}]}`;
  v1 bare-string files still load. `is_allowed(name, arguments)` = session → persistent name → rules.
  `argv_prefix` matches only a single simple shell command (any pipe/redirect/`;`/`&&` fails the
  rule); `path_glob` requires **every** path-like argument to match (fnmatch, workspace-relative).
  Writes are atomic (temp + `os.replace`, mode 0600); missing/malformed files load empty, and a
  failed persist falls back to session. Keys are exact gate names (`read` ≠ `_mcp__read`).
- Faithful prompt: `Printer._confirm_tool_call()` renders `approval.canonical_arguments()` (the same
  repaired JSON dict `execute_tool_call` receives), plus specialized previews for
  `execute_shell_command` (decoded command + danger reasons), `fs_write_file` (target/mode/content
  head) and `fs_edit_file` (unified diff head 40). Never show raw model JSON that differs from what
  executes (`\u003b`/duplicate-key cases are regression-tested).
- Audit: every gate decision appends one JSON line to `TOOL_AUDIT_PATH` (`<config-dir>/tool_audit.jsonl`,
  `TOOL_AUDIT` config, default on) with `ts/tool/risk/decision/source/args_summary/duration_ms`
  (`args_summary` secret-redacted, <=500 chars; shell => decoded command). Best-effort OSError-tolerant,
  0600, never affects the call. `/permissions` lists session/persistent/rule state and
  `/permissions revoke <tool-or-index>` mutates the persisted file.
- Behavior changes also update the openspec specs, `tests/llms/test_tool_confirmation.py`,
  `tests/tools/test_approval.py` and `tests/test_permissions.py`.

## MCP Boundary (`yaicli/tools/mcp.py`)

- `fastmcp`/`mcp.types` stay lazy: only `TYPE_CHECKING` imports at module top and
  `_import_fastmcp()` at call time; `yaicli/tools/__init__.py` wraps it in lazy
  `get_mcp_manager()`/`get_mcp()` functions. Never add a module-level `from fastmcp ...` import
  (about 1.6s of startup).
- `gen_mcp_tool_name` adds `_mcp__`; `parse_mcp_tool_name` strips it. The constant exists in both
  `yaicli/tools/mcp.py` and `yaicli/tools/__init__.py`; import it from `yaicli.tools.mcp` in new
  code (`client.py` does) and keep both in sync if it changes.
- Conversion: OpenAI/Anthropic pass `tool.inputSchema` through; Gemini builds callable signatures
  from it (`_create_parameter_from_schema`: array→`List[T]`, enum→`Literal`, optional→`Optional`).
  MCP execution errors are in-band strings.

## Tests for This Layer

- Schema contracts are provider contracts: assert exact JSON (`type`, `items`, no `anyOf`,
  `required`) in `tests/tools/test_function_schema.py` and `tests/tools/test_fs_read_file.py`. The
  Gemini regression builds the real declaration with
  `types.FunctionDeclaration.from_callable_with_api_option(..., api_option="GEMINI_API")` under
  `pytest.importorskip("google.genai")`.
- End-to-end call tests patch `yaicli.tools.cfg` with
  `{"SHOW_FUNCTION_OUTPUT": False, "SHOW_MCP_OUTPUT": False}`, patch `get_function`/`get_mcp`, and
  pass a `MagicMock` console (`tests/tools/test_tools_init.py`); `fastmcp` is a core dependency.
  Truncation/spill tests live in `tests/test_context_budget.py`.
- Loader tests (`tests/tools/test_function_loading.py`, `tests/test_functions_init.py`) patch
  `FUNCTIONS_DIR` and reset all caches: builtin direct-load, user override by schema name,
  broken-file skip, install/reinstall/manifest/stale-warning, no writes on fresh dir.
- Shell guardrails: `tests/test_shell_tool.py` (timeout/process-group kill, env allowlist,
  output cap, workspace cwd, danger classification incl. `git add` false-positive guard).
- Permission gate: `tests/llms/test_tool_confirmation.py` (generator + `send()`),
  `tests/tools/test_approval.py` (v1/v2 store, rules, atomic writes) and
  `tests/test_permissions.py` (risk classes, danger double-confirm, `--yes` read-only,
  `--allowed-tools`, structured deny, audit, prompt/gate argument equality).
- Verify with `uv run pytest tests/tools tests/llms/test_tool_confirmation.py tests/test_permissions.py tests/test_shell_tool.py -q`.

## Anti-Patterns

- A `Union`/`Optional` model-facing field, which becomes an `anyOf`/`any_of` declaration.
- Raising on expected tool failures instead of returning an in-band error.
- Top-level third-party imports in a built-in, `yaicli/tools/__init__.py`, or `mcp.py`.
- Adding a substring blacklist for dangerous shell commands instead of `tools/risk.py` argv
  classification (false positives like `git add`, misses like `rm -r -f` flag orders).
- Truncating tool output anywhere except `execute_tool_call`/`tools/limits.py`, or letting a full
  tool result reach the model messages.
- A new `execute_tool_call` caller that skips the `ToolPolicy` filter or confirmation gate; a deny
  path that appends a tool message without a matching `tool_call_id`; a deny without audit
  `decision=denied`.
- Rendering raw model JSON in the confirmation prompt instead of `canonical_arguments()`.
- Using the class/file name as the tool name, duplicating a title, printing from `execute`, or
  mutating a cached schema dict.
