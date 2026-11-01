# Config, Context & Session Guidelines

> Scope: before touching `yaicli/config.py`, `const.py`, `role.py`, `context.py`, `history.py`, `schemas.py`,
> `console.py`, `utils.py`, or their tests. CLI/rendering wiring is in
> [cli-and-rendering.md](./cli-and-rendering.md); cross-layer data flow in the
> [cross-layer guide](../guides/cross-layer-thinking-guide.md).

Configuration is a single global dict `cfg` (`yaicli/config.py`) built at import time from three layers:
defaults in `const.DEFAULT_CONFIG_MAP` → `~/.config/yaicli/config.ini` → environment variables. Everything
else (roles, context, chat sessions, printer, CLI) imports `cfg` and reads uppercase keys.

## Configuration Model (`config.py`)

- `Config(dict)` subclasses `dict`: `reload()` clears, loads defaults, parses the INI, applies env overrides,
  then type-converts. `cfg = get_config()` is a `@lru_cache(1)` singleton (`get_config()` calls `sys.exit()` on
  `ConfigError`): **import `cfg`**, never construct `Config()` in feature code.
- `DEFAULT_CONFIG_MAP` (`const.py`) entries have exactly `value`, `env_key` (`YAI_<KEY>`), `type`
  (`bool`/`int`/`float`/`str`/`dict`). The env layer only iterates this map, so a key absent from the map has
  **no env override** (the historical `YAI_PROVIDER` bug — `PROVIDER` now lives in the map).
- Config file: `CONFIG_PATH = ~/.config/yaicli/config.ini`, single `[core]`, keys **case-sensitive uppercase**
  (`CasePreservingConfigParser.optionxform` is identity). A file without `[core]` is ignored; keys not in
  `DEFAULT_CONFIG_MAP` pass through unchanged; a missing file is created from `DEFAULT_CONFIG_INI` **and
  parsed in the same `_load_from_file()` call**.
- Type conversion (`_convert_value`): `bool` via `utils.str2bool` (`y/yes/t/true/on/1` + inverse, else
  `ValueError`), `dict` via `json.loads` (this makes `EXTRA_HEADERS`/`EXTRA_BODY` dicts), numeric via
  `int()`/`float()`. Invalid values warn and fall back to the typed default, never the raw string
  (`tests/test_config.py::test_type_conversion_errors`). Empty file/env values count as "unset" and also
  fall back to the typed default (`EXTRA_HEADERS`/`EXTRA_BODY` → `{}`, `REASONING_EFFORT` → `None`), so
  the parsed `DEFAULT_CONFIG_INI` template does not leak `""` into typed consumers
  (`tests/test_config.py::test_empty_template_values_fall_back_to_typed_defaults`).
- `EXTRA_HEADERS`/`EXTRA_BODY` are consumed by providers, never config: `openai_provider.py:68` /
  `anthropic_provider.py:61-62` merge headers, and provider `COMPLETION_PARAMS_KEYS` maps `"extra_body": "EXTRA_BODY"`
  (`openai_provider.py:31`). Invalid JSON → warning + `{}`; providers guard with `if self.config["EXTRA_HEADERS"]:`.
- First-run contract: `PROVIDER` is in `DEFAULT_CONFIG_MAP` (`value=DEFAULT_PROVIDER`,
  `env_key=YAI_PROVIDER`, type `str`), and `_load_from_file()` parses the template it just wrote for a
  missing file. A fresh `HOME` therefore has `cfg["PROVIDER"]` without raising `KeyError: 'PROVIDER'`,
  and `YAI_PROVIDER` overrides file/default values.
- `MAX_HISTORY` bounds the prompt history file (see Prompt History below) and `ROLE_MODIFY_WARNING` gates
  the built-in-role warning in `role.py`; both are real consumers now, not dead keys.

## Adding or Changing a Config Key

1. Add a `DEFAULT_CONFIG_MAP` entry (`value`/`env_key`/`type`) in `const.py`; this is what enables env loading and
   type conversion.
2. Add the line + comment to `DEFAULT_CONFIG_INI` — new config files are written from that template only.
3. Read it as `cfg["KEY"]` at the use site; only `Config._load_from_env` may read the env var for a key.
4. Update `_ensure_version_updated_config_keys()` (`config.py:81`) if installed config files need the key appended
   (today hardcoded for `CHAT_HISTORY_DIR`).
5. Update `docs/usage/configuration.md` and any `entry.py` option default mirroring it.
6. Test in `tests/test_config.py` with `patch("yaicli.config.getenv")` + `mock_open`/`Path.exists` patch.

## CLI ↔ Config Wiring

- CLI flags override config through `entry.override_config`, which writes `cfg[param.name.upper()] = value` only
  when the value differs from the option default (the default was read from `cfg` at import). This is why
  `--model`, `--temperature`, `--stream/--no-stream`, `--show-reasoning`, `--enable-mcp`, etc. mutate `cfg`
  before `CLI` is built — there is no separate options object for them.
- `CLI.__init__` resolves `auto` values: `OS_NAME`/`SHELL_NAME` are detected via `detect_os`/`detect_shell`
  (`utils.py`) and written back into global `cfg`; `role`, `chat_manager`, `context_manager` and cfg-derived
  state (`interactive_round`, `chat_history_dir`) are captured on the instance.
- `--verbose` prints config with `API_KEY` replaced by `"****"`; any new secret key must be masked there.

## Constants & Paths (`const.py`)

- Paths: `HISTORY_FILE = ~/.yaicli_history`, `CONFIG_PATH = ~/.config/yaicli/config.ini`, while `ROLES_DIR`,
  `FUNCTIONS_DIR`, `MCP_JSON_PATH`, `TOOL_PERMISSIONS_PATH` are `CONFIG_PATH.parent / ...`; chat sessions live under
  `DEFAULT_CHAT_HISTORY_DIR = <tempdir>/yaicli/chats`. Never hardcode them; tests patch `yaicli.config.CONFIG_PATH`
  (the reading module), not `const.CONFIG_PATH`.
- `StrEnum` has a Python 3.10 fallback (`class StrEnum(str, Enum)`); use it for new enums, never import `enum.StrEnum`.
- `DEFAULT_ROLES` seeds role JSON files; `DEFAULT_CONFIG_INI` must stay in sync with `DEFAULT_CONFIG_MAP`
  (template-only keys are invisible to env/type conversion; map-only keys are not written for new users).
- Provider/mode/command constants (`CMD_*`, `EXEC_MODE`/`CHAT_MODE`/`TEMP_MODE`, `NO_VISION_PROVIDERS`) are
  string-or-tuple values shared with `cmd_handler.py`/`completer.py`/tests (most are strings; `CMD_HELP` and
  `CMD_CONTEXT` are tuples and `cmd_handler` branches on the type) — change them together.

## Roles (`role.py`)

- `Role(name, prompt, variables={})` validates both fields then runs `self.prompt.format(**self.variables)`; default
  variables are `_os`/`_shell` from `detect_os`/`detect_shell`. Literal braces must be doubled (`{{`/`}}`) or it raises.
- `RoleManager` seeds `ROLES_DIR` with `DEFAULT_ROLES` JSON, loads defaults, then `*.json` user files overriding by
  `role.name` (not filename); corrupt JSON prints one red error and continues (`tests/test_role.py::test_load_user_roles`).
  Persistence = one JSON file per role, written/removed by `create_role`/`delete_role`.
- CLI-facing role options are `@classmethod`s decorated with `@option_callback` (`--create-role`,
  `--delete-role`, `--list-roles`, `--show-role`); `RoleManager.check_id_ok` is a plain `@classmethod`
  used as the `--role` validator callback. The `@option_callback` methods run before `CLI` exists and exit
  via `typer.Exit`; they use the class-level `console`/`roles_dir`, which tests monkeypatch.
- `role_mgr = RoleManager()` is a module-level singleton imported by `cli.py`; there is no `print_roles()` —
  listing/readout goes through `--list-roles` (`print_list_option`) and `--show-role`. Add a built-in role by
  extending `DEFAULT_ROLES` with `{"name": ..., "prompt": ...}`; existing installs get the JSON on next start
  via `_ensure_roles_dir()`.
- `create_role()`/`delete_role()` warn (yellow) when the target name is a built-in (`DEFAULT_ROLES`) role and
  `cfg.get("ROLE_MODIFY_WARNING", True)` is truthy; custom roles never warn (`tests/test_role.py`).

## Context (`context.py`)

Two mechanisms share one manager (`ctx_mgr` global), and `CLI._build_messages()` wires both:

- **Persistent** (`/add`, `/context add`): `ContextManager.add(path)` stores a resolved `ContextItem`
  (`type="file"|"dir"`); `get_context_messages()` renders all items into **one** system message (`## File: name` +
  `Path:` + fenced content; directories recursed). `/context list|clear|remove` and `remove()` match exact path,
  filename or unique partial name; `add()` prints and returns `bool` for missing/duplicate/unsupported paths.
- **Temporary** (`@path`): `parse_at_references(text)` returns `(system_message, cleaned_text, images)`; the regex
  accepts quoted (`@"my file.txt"`) and unquoted paths, each hit resolved from cwd and **replaced in the prompt** by
  `'<filename>'`. Text files are inlined; image suffixes become `ImageData` via `encode_local_image`; failures warn.
- `_read_file()` returns `FileReadResult(content, error)` (`ok` property): binary suffixes, files >
  `1_000_000` bytes and I/O failures set `error` to the display text (`[Binary file omitted]`,
  `[File too large: ... - omitted]`, `[Error reading file: ...]`) and leave `content=None`; success returns
  the decoded text (`utf-8` with `errors="replace"`). Directory scans (`_read_dir_recursive`) stop at
  depth 2, skip dotfiles and `default_ignores` (`.git`, `__pycache__`, `.venv`, `node_modules`, ...), skip
  error results, and have **no total-size cap**.
- `parse_at_references()` includes any successful content regardless of its first character (files whose
  content starts with `[` are no longer dropped) and warns/replaces the `@ref` only when `error` is set;
  `get_context_messages()` skips unreadable persistent items instead of embedding a placeholder. Do not
  reintroduce string sentinels — `FileReadResult` status is the only source of truth.
- Tests (`tests/test_context.py`) use `tmp_path`, `monkeypatch.chdir` for relative `@` refs, `os.mkfifo` for the
  unsupported-type branch, and patch `yaicli.context.console` for output assertions.

## Prompt History (`history.py`)

`LimitedFileHistory(FileHistory)` writes to `HISTORY_FILE` (`~/.yaicli_history`) and trims every `trim_every`
appends (default 2) to the newest `max_entries` prompt-toolkit records (`# timestamp` header + `+line` lines).
`CLI.prepare_chat_loop()` passes `max_entries=cfg["MAX_HISTORY"]`; a non-positive limit disables saving
(`store_string` no-ops; the `_trim_history()` guard also clears the file if trimming is forced directly).
The documented `MAX_HISTORY=0` semantics live in `docs/advanced/history.md` (the configuration table only
lists the key). `INTERACTIVE_ROUND` does not bound this file — it only bounds the in-conversation chat
messages. `tests/test_history.py` asserts record counting, reverse-chronological load, multi-line trimming
and the zero-limit behaviour — keep the `# ` / `+` file format if you change trimming.

## Schemas (`schemas.py`) — Cross-Layer Contracts

- `ChatMessage(role, content=None, name=None, tool_call_id=None, tool_calls=[], reasoning=None, images=[])`,
  `ToolCall(id, name, arguments)`, `LLMResponse(reasoning, content, finish_reason, tool_call)`, `ImageData(data,
  media_type, is_url)`, `ToolPolicy(enable_functions, enable_mcp)` (frozen, per request). Control signals: `RefreshLive`,
  `StopLive` (unused), `ConfirmToolCall(tool_call)`, `ToolConfirmDecision` (`once|session|persist|deny`).
- Adding a `ChatMessage` field is cross-layer: update provider conversion
  (`Provider._convert_messages` and overrides in `providers/anthropic_provider.py`, `gemini_provider.py`, ...),
  the printer, and — because `Chat.to_dict()`/`from_dict()` persist only `role` and `content` — decide whether
  the field survives chat save/load (today `reasoning`, `tool_calls` and `images` are dropped).
- Keep `ToolPolicy` resolved once per request (CLI → client → provider); don't read `cfg` inside provider loops.

## Console & Utils

`get_console()` (`console.py`) returns the `YaiConsole` singleton whose `print()` defaults `justify` to `cfg["JUSTIFY"]`;
feature code must use it instead of `rich.console.Console()`. `utils.py` provides `option_callback` (callback →
`typer.Exit`), `detect_os`/`detect_shell` (`auto` resolution), `str2bool` (config bool parsing), `filter_command`
(markdown fences from shell output), `get_or_create_event_loop` (async/MCP callers) and `gen_tool_call_id`. Tests patch
these at consumption sites (`yaicli.role.get_console`, `yaicli.context.console`, `yaicli.cli.subprocess.call`).

## Tests & Verification

```bash
uv run pytest tests/test_config.py tests/test_context.py tests/test_role.py tests/test_history.py \
  tests/test_filter_command.py tests/test_chat_manage.py -q
```

`tests/conftest.py` is session-scoped/autouse: `patched_config_path` patches
`yaicli.config.CONFIG_PATH`, `setup_test_environment` sets `YAI_API_KEY`/`YAI_MODEL` (and `YAI_PROVIDER`,
which the map now reads), `mock_console` is a `MagicMock`. Caveat: the module-level `cfg` singleton is
created at import, **before** the `CONFIG_PATH` patch applies, so tests needing a provider patch
`yaicli.cli.cfg` explicitly (`tests/test_cli.py:347`, `tests/test_image.py:420`); the `cli_with_mocks`
helper in `tests/test_cli.py` instead injects a mock client.

## Rules

- One default location: values in `const.py`, conversion in `config.py`, no literals at read sites. Never mutate `cfg`
  from feature code except CLI-flag override and `auto` OS/shell detection (tests share the singleton).
- Never build paths from `~` inline; import the `const.py` constant so tests can patch one place. Keep secrets out of
  logs/verbose output (`API_KEY` masked as `****`).
