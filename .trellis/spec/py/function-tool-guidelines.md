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
| Loading / dispatch | `yaicli/tools/function.py`, `yaicli/tools/__init__.py` | Executes `FUNCTIONS_DIR` files, validates `Function`, caches schemas, runs `execute_tool_call()`. |
| Built-ins | `yaicli/functions/buildin/`, `yaicli/functions/__init__.py` | Templates copied to `~/.config/yaicli/functions/`; install/reinstall/list lifecycle. |
| Policy / confirmation | `yaicli/llms/client.py`, `yaicli/tools/approval.py`, `yaicli/schemas.py` | Per-request `ToolPolicy` filter → four-outcome confirmation gate → execution. |
| MCP | `yaicli/tools/mcp.py` | Lazy `fastmcp`, `_mcp__` prefix, MCP→provider schema conversion. |

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
and `any_of is None`. `fs_read_image.py` still advertises a Union — migrate it, do not copy it.

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
5. Guard the side effect: `fs_write_file` refuses `/etc/`, `/sys/`, `/proc/`, `/dev/`;
   `execute_shell_command` blocks `rm -rf`, `mkfs`, `dd`. New side-effecting built-ins need an
   equivalent check.
6. Import heavy/optional packages inside `execute`: `web_search` imports `ddgs` lazily,
   `fetch_webpage` imports `trafilatura` lazily. Every file in `FUNCTIONS_DIR` is exec'd when the
   tool map is first built, so top-level imports slow the first tool-advertising request and a
   missing optional extra must degrade to an in-band error, not a load failure.
7. No printing/UI from `execute`; the call line, `SHOW_FUNCTION_OUTPUT` panel and confirmation
   prompt belong to `yaicli/tools/__init__.py` and `yaicli/llms/client.py`.

## Loading & Install Lifecycle

- The runtime reads only `FUNCTIONS_DIR` = `~/.config/yaicli/functions/` (`yaicli/const.py`);
  `yaicli/functions/buildin/*.py` are templates. `--install-functions` copies missing files and
  skips existing ones; `--reinstall-functions` overwrites built-in names and preserves custom files.
  Built-in edits reach an install only after reinstall; buildin imports in tests bypass this.
- `get_func_name_map()` globs `*.py` (skipping `_`-prefixed files), execs each module, raises
  `TypeError` unless `Function` has `openai_schema`, `anthropic_schema` and `execute`, then caches
  a `tools.function.Function` wrapper (`name`/`description`/`parameters`/`execute`/`func_cls`) in
  `_func_name_map`. Files using `from instructor import` warn once per file; never reintroduce it.
- Four caches: `_func_name_map`/`_gemini_functions_cache` in `tools/function.py`,
  `_openai_schemas_cache`/`_anthropic_schemas_cache` in `tools/__init__.py`. Production never
  invalidates them; tests patching `FUNCTIONS_DIR` must reset all four (autouse `reset_caches`
  fixture in `tests/tools/test_function_loading.py`).
- Adding a built-in requires the `buildin/` file, schema-contract + `execute` + end-to-end
  `execute_tool_call` tests, and a note in [docs/usage/advanced.md](../../../docs/usage/advanced.md).

## Execution Path (`execute_tool_call`)

`yaicli/tools/__init__.py::execute_tool_call(tool_call, announce=True) -> Tuple[str, bool]`: the
`_mcp__` prefix selects MCP (`SHOW_MCP_OUTPUT`) vs built-in (`SHOW_FUNCTION_OUTPUT`); arguments
are parsed with `json_repair.repair_json(..., return_objects=True)` and must be a `dict` (never
`json.loads`), then the tool runs and its output prints in a `Panel` when the flag is on.

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

## Tool Policy & Confirmation

- `ToolPolicy` (`yaicli/schemas.py`) is a frozen per-request pair of flags; functions and MCP are
  independent. `exec` mode forces `ToolPolicy(False, False)` (`CLI._get_tool_policy`), defaults are
  ANDed in `Provider.resolve_tool_policy`, and disallowed calls are dropped, not persisted.
- `TOOL_CONFIRM` (enabled by default) gates execution: approved names skip the prompt,
  non-interactive sessions deny unapproved tools with a hint, and interactive sessions get
  `ConfirmToolCall` → `ToolConfirmDecision` (`ONCE`/`SESSION`/`PERSIST`/`DENY`). A deny appends a
  tool message with the matching `tool_call_id` and `"The user declined to execute this tool."`.
- `ToolApprovalManager` (`yaicli/tools/approval.py`) keeps a session set and a persistent allowlist
  at `TOOL_PERMISSIONS_PATH` (`~/.config/yaicli/tool_permissions.json`, key `always_allow`).
  Writes are atomic (temp file + `os.replace`); missing/malformed files load empty, and a failed
  persist falls back to session. Keys are exact gate names (`read` ≠ `_mcp__read`); behavior
  changes also update the openspec specs, `tests/llms/test_tool_confirmation.py` and
  `tests/tools/test_approval.py`.

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
- Loader tests patch `FUNCTIONS_DIR` and reset caches; confirmation tests drive the generator
  with a scripted `FakeProvider` + `drive()` helper (`tests/llms/test_tool_confirmation.py`).
- Verify with `uv run pytest tests/tools tests/llms/test_tool_confirmation.py -q`.

## Anti-Patterns

- A `Union`/`Optional` model-facing field, which becomes an `anyOf`/`any_of` declaration.
- Raising on expected tool failures instead of returning an in-band error.
- Top-level third-party imports in a built-in, `yaicli/tools/__init__.py`, or `mcp.py`.
- Editing installed `~/.config/yaicli/functions/` copies instead of `buildin/` + reinstall.
- A new `execute_tool_call` caller that skips the `ToolPolicy` filter or confirmation gate.
- Using the class/file name as the tool name, duplicating a title, printing from `execute`, or
  mutating a cached schema dict.
