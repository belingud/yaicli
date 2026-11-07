# Config, Context & Session Guidelines

> Scope: before touching `yaicli/config.py`, `const.py`, `role.py`, `context.py`, `history.py`, `schemas.py`,
> `console.py`, `utils.py`, or their tests. CLI/rendering wiring is in
> [cli-and-rendering.md](./cli-and-rendering.md); cross-layer data flow in the
> [cross-layer guide](../guides/cross-layer-thinking-guide.md).

Configuration is a single global dict `cfg` (`yaicli/config.py`) built at import time from three layers:
defaults in `const.DEFAULT_CONFIG_MAP` → the config file (`CONFIG_PATH`) → environment variables. Everything
else (roles, context, chat sessions, printer, CLI) imports `cfg` and reads uppercase keys. Importing config
never writes: a missing config file is parsed from `DEFAULT_CONFIG_INI` in memory, and the file is created
on demand by `ensure_config_file()` (first real run, never for `--version`/`--help`/`--template`/`--list-*`).

## Configuration Model (`config.py`)

- `Config(dict)` subclasses `dict`: `reload()` clears, loads defaults, parses the INI, applies env overrides,
  then type-converts. `cfg = get_config()` is a `@lru_cache(1)` singleton (`get_config()` calls `sys.exit()` on
  `ConfigError`): **import `cfg`**, never construct `Config()` in feature code.
- `DEFAULT_CONFIG_MAP` (`const.py`) entries have exactly `value`, `env_key` (`YAI_<KEY>`), `type`
  (`bool`/`int`/`float`/`str`/`dict`). The env layer only iterates this map, so a key absent from the map has
  **no env override** (the historical `YAI_PROVIDER` bug — `PROVIDER` now lives in the map).
- Config file: `CONFIG_PATH` is resolved by `const.get_config_dir()` (`YAI_CONFIG_DIR` > `XDG_CONFIG_HOME/yaicli`
  > `%APPDATA%/yaicli` on Windows > `~/.config/yaicli`; an empty/unset `HOME` falls back to a temp dir, never
  `/.config`), single `[core]`, keys **case-sensitive uppercase** (`CasePreservingConfigParser.optionxform` is
  identity). A file without `[core]` is ignored; keys not in `DEFAULT_CONFIG_MAP` pass through unchanged.
- Missing config file: `_load_from_file()` parses `DEFAULT_CONFIG_INI` **in memory** (no `mkdir`/write at import;
  read-only HOME works). `ensure_config_file()` (idempotent, never raises, returns `Optional[Path]`) is the only
  creation path: dir `0700`, file `0600`, best-effort (OSError → one deduped stderr warning, defaults continue).
  `entry.main()` calls it after meta-flag handling, before building `CLI`; `--version/--help/--template/--list-*`
  return before that call and therefore perform zero writes.
- Every config-directory write must tolerate `OSError` (container/read-only HOME): warn once on stderr and
  continue with defaults; never let a config/state write crash the CLI.
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
  `env_key=YAI_PROVIDER`, type `str`), and `_load_from_file()` parses the in-memory template for a missing file.
  A fresh `HOME` therefore has `cfg["PROVIDER"]` without raising `KeyError: 'PROVIDER'`, and `YAI_PROVIDER`
  overrides file/default values. `tests/test_config.py` asserts no file exists until `ensure_config_file()` is
  called (then 0600 file / 0700 dir, never overwriting an existing file).
- `TOOL_POLICY` (v0.21 K10; `YAI_TOOL_POLICY`, type `str`, default `standard`) exists in both the map and
  the INI template. It is **normalized at the consumption site** (`LLMClient._resolve_tool_policy_mode`),
  not in the config layer: empty = unset → `standard`; unrecognized → `standard` + one stderr warning;
  case/whitespace-insensitive `readonly|standard|trusted`. Do not add a config-layer validator for it.
- `WORKSPACE_ROOT` (empty = cwd) is used by the standalone shell tool's cwd guard and, since v0.21 K11,
  by the filesystem write guard; `execute_tool_call` exports it (and the other `TOOL_*` guardrails) via
  environment variables right before a shell call or fs mutation, so config.ini / `--cwd` win over a
  stale user-exported env value.
- `MAX_HISTORY` bounds the prompt history file (see Prompt History below) and `ROLE_MODIFY_WARNING` gates
  the built-in-role warning in `role.py`; both are real consumers now, not dead keys.

## Adding or Changing a Config Key

1. Add a `DEFAULT_CONFIG_MAP` entry (`value`/`env_key`/`type`) in `const.py`; this is what enables env loading and
   type conversion.
2. Add the line + comment to `DEFAULT_CONFIG_INI` — config files are written from that template by
   `ensure_config_file()` only.
3. Read it as `cfg["KEY"]` at the use site; only `Config._load_from_env` may read the env var for a key.
4. Update `_pending_version_updated_config_keys()` (`config.py`) if installed config files need the key
   appended (today hardcoded for `CHAT_HISTORY_DIR`). Detection is read-only at import: lines are queued
   per `CONFIG_PATH` and appended only by `ensure_config_file()` on a real run, deduped and skipped when
   the key already exists (a freshly created template already contains every default key); OSError only
   warns and keeps them pending.
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

- Paths are resolved in `const.py` at import from the environment and must not be hardcoded elsewhere:
  `CONFIG_DIR`/`CONFIG_PATH` (`get_config_dir()`), `ROLES_DIR`, `FUNCTIONS_DIR`, `FUNCTIONS_MANIFEST_PATH`,
  `MCP_JSON_PATH`, `TOOL_PERMISSIONS_PATH`, `TOOL_AUDIT_PATH` all live under `CONFIG_DIR`; chat sessions are
  **per project** (v0.21 K13) under `get_sessions_dir() = ~/.yaicli/sessions/<sha256(resolved cwd)[:16]>/`
  (`get_project_sessions_dir()`), while `DEFAULT_CHAT_HISTORY_DIR = <tempdir>/yaicli/chats` is only the legacy
  flat directory and the anchor for `TOOL_OUTPUT_DIR = DEFAULT_CHAT_HISTORY_DIR/tool-outputs`
  (tool spills still go to the temp dir); an explicit `CHAT_HISTORY_DIR` env/config value different from that
  built-in default keeps the flat directory (`chat.resolve_default_chat_dir()`); `HISTORY_FILE = get_history_file()`
  (`XDG_STATE_HOME/yaicli/history` when set, else `~/.yaicli_history`; empty HOME falls back to a temp dir).
  Session dirs are 0700 and session files 0600 (best effort, atomic write); `HISTORY_FILE` is created 0600.
  Tests patch `yaicli.config.CONFIG_PATH` (the reading module) and `yaicli.cli.HISTORY_FILE` (the consuming module).
  v0.21 K11 backup files are the exception: `<workspace>/.yaicli-backups/<UTC stamp>/<relative path>` is
  resolved by `yaicli/tools/workspace.py` from the workspace root (not the config dir), always 0600/0700,
  and has no retention/cleanup yet.
- `StrEnum` has a Python 3.10 fallback (`class StrEnum(str, Enum)`); use it for new enums, never import `enum.StrEnum`.
- `DEFAULT_ROLES` seeds role state in memory (not on disk at import); `DEFAULT_CONFIG_INI` must stay in sync with
  `DEFAULT_CONFIG_MAP` (template-only keys are invisible to env/type conversion; map-only keys are not written for
  new users). Add new keys to **both** and update `docs/usage/configuration.md`.
- Provider/mode/command constants (`CMD_*`, `EXEC_MODE`/`CHAT_MODE`/`TEMP_MODE`, `NO_VISION_PROVIDERS`) are
  string-or-tuple values shared with `cmd_handler.py`/`completer.py`/tests (most are strings; `CMD_HELP` and
  `CMD_CONTEXT` are tuples and `cmd_handler` branches on the type) — change them together.

## Roles (`role.py`)

- `Role(name, prompt, variables={})` validates both fields then runs `self.prompt.format(**self.variables)`; default
  variables are `_os`/`_shell` from `detect_os`/`detect_shell`. Literal braces must be doubled (`{{`/`}}`) or it raises.
- `RoleManager` builds `DEFAULT_ROLES` in memory and loads `*.json` user files overriding by `role.name`
  (not filename); corrupt JSON prints one red error and continues (`tests/test_role.py::test_load_user_roles`).
  **Importing `role.py` (or `role_mgr = RoleManager()`) must not create files** — this keeps read-only HOME /
  `--help` side-effect free. Writes happen only in `create_role()`/`delete_role()`: mkdir parents lazily, mode
  best-effort, `OSError` → yellow warning and memory unchanged. `--list-roles` merges the in-memory built-ins with
  role files, so a fresh/read-only config dir still lists the three built-in roles.
- CLI-facing role options are `@classmethod`s decorated with `@option_callback` (`--create-role`,
  `--delete-role`, `--list-roles`, `--show-role`); `RoleManager.check_id_ok` is a plain `@classmethod`
  used as the `--role` validator callback. The `@option_callback` methods run before `CLI` exists and exit
  via `typer.Exit`; they use the class-level `console`/`roles_dir`, which tests monkeypatch.
- `role_mgr = RoleManager()` is a module-level singleton imported by `cli.py`; there is no `print_roles()` —
  listing/readout goes through `--list-roles` (`print_list_option`) and `--show-role`. Add a built-in role by
  extending `DEFAULT_ROLES` with `{"name": ..., "prompt": ...}`; it is available immediately (no disk seed).
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

## Project Context (`project_context.py`, v0.21 K12)

- `yaicli/project_context.py` is stdlib-only and side-effect free: `find_git_root()`,
  `iter_project_context_files()` and `collect_project_context()` walk from the current working directory
  up to the nearest `.git` (directory **or** worktree file, inclusive; no git root → filesystem root),
  emitting directories outermost→innermost so the most specific instructions come last; within one
  directory the order is `.yaicli.md` → `AGENTS.md` → `CLAUDE.md`, and files resolving to the same real
  path are loaded once.
- `load_project_context()` is the CLI entry: it reads the config keys, returns an empty result **before any
  filesystem access** when disabled, bounds the whole emitted block to `PROJECT_CONTEXT_MAX_CHARS`
  (default 20000, `0` = no cap), prints exactly one stderr warning when content is truncated/omitted, and
  skips unreadable files with a single warning. It never raises.
- Config keys `ENABLE_PROJECT_CONTEXT` (`YAI_ENABLE_PROJECT_CONTEXT`, bool, default true) and
  `PROJECT_CONTEXT_MAX_CHARS` (`YAI_PROJECT_CONTEXT_MAX_CHARS`, int, default 20000) live in both
  `DEFAULT_CONFIG_MAP` and `DEFAULT_CONFIG_INI`. Existing config files without the keys keep working via
  the map default (no materialization).
- The block is inserted by `cli.py::_build_messages` into the first system message, after the role prompt
  (see [cli-and-rendering.md](./cli-and-rendering.md)); the CLI caches it once and toggles nothing else.

## Prompt History (`history.py`)

`LimitedFileHistory(FileHistory)` writes to `HISTORY_FILE` (`get_history_file()`: `XDG_STATE_HOME/yaicli/history`
when set, else `~/.yaicli_history`) and trims every `trim_every`
appends (default 2) to the newest `max_entries` prompt-toolkit records (`# timestamp` header + `+line` lines).
`history.prepare_history_file()` (v0.21 K13) creates the file 0600 and created dirs 0700, raises `OSError` for the
caller to degrade, and returns `None` for non-`str`/`Path` inputs; `store_string`/`_trim_history` best-effort
re-apply 0600 so legacy 0644 files are repaired on the next append/trim.
`CLI.prepare_chat_loop()` makes the history setup OSError-tolerant (read-only HOME must not crash: warn once,
continue without history) and passes `max_entries=cfg["MAX_HISTORY"]`; a non-positive limit disables saving
(`store_string` no-ops; the `_trim_history()` guard also clears the file if trimming is forced directly).
The documented `MAX_HISTORY=0` semantics live in `docs/advanced/history.md` (the configuration table only
lists the key). `INTERACTIVE_ROUND` does not bound this file — it only bounds the in-conversation chat
messages (and since v0.19 it is a group-aligned max-message cap; token budget trimming lives in
`yaicli/tokens.py` + `LLMClient`). `tests/test_history.py` asserts record counting, reverse-chronological load,
multi-line trimming and the zero-limit behaviour — keep the `# ` / `+` file format if you change trimming.

## Schemas (`schemas.py`) — Cross-Layer Contracts

- `ChatMessage(role, content=None, name=None, tool_call_id=None, tool_calls=[], reasoning=None, images=[])`,
  `ToolCall(id, name, arguments)`, `LLMResponse(reasoning, content, finish_reason, tool_call, tool_calls)`,
  `ImageData(data,
  media_type, is_url)`, `ToolPolicy(enable_functions, enable_mcp)` (frozen, per request). Control signals: `RefreshLive`,
  `StopLive` (unused), `ConfirmToolCall(tool_call)`, `ToolConfirmDecision` (`once|session|persist|deny`).
- Adding a `ChatMessage` field is cross-layer: update provider conversion
  (`Provider._convert_messages` and overrides in `providers/anthropic_provider.py`, `gemini_provider.py`, ...),
  the printer, and chat serialization. `Chat.to_dict()`/`from_dict()` now persist every field through
  `_message_to_dict()`/`_message_from_dict()` (`role`/`content` plus optional `name`, `tool_call_id`,
  `tool_calls`, `reasoning`, `images`), saves are atomic (temp file + `os.replace` around `fsync`), and
  the loader still accepts legacy `{role, content}` files (`tests/test_chat_manage.py`).
- Keep `ToolPolicy` resolved once per request (CLI → client → provider); don't read `cfg` inside provider loops.

## Console & Utils

`get_console()` (`console.py`) returns the `YaiConsole` singleton whose `print()` defaults `justify` to `cfg["JUSTIFY"]`;
feature code must use it instead of `rich.console.Console()`. `get_error_console()` is the stderr twin: use it for
warnings/errors/progress whenever stdout must stay clean (headless/`machine_output`); `YaiConsole.on_broken_pipe`
exits 0 so `ai --help | head` is not a failure. `utils.py` provides
`option_callback` (callback → `typer.Exit`), `detect_os`/`detect_shell` (`auto` resolution), `str2bool`
(config bool parsing), `filter_command` (markdown fences from shell output), `get_or_create_event_loop`
(async/MCP callers) and `gen_tool_call_id`. Tests patch these at consumption sites
(`yaicli.role.get_console`, `yaicli.context.console`, `yaicli.cli.subprocess.call`).

## Tests & Verification

```bash
uv run pytest tests/test_config.py tests/test_context.py tests/test_role.py tests/test_history.py \
  tests/test_filter_command.py tests/test_chat_manage.py -q
```

`tests/conftest.py` is session-scoped/autouse: `patched_config_path` patches
`yaicli.config.CONFIG_PATH`, `patched_history_file` patches `yaicli.cli.HISTORY_FILE` (and `const.HISTORY_FILE`)
to a temp file so REPL/history tests never write the real HOME, `setup_test_environment` sets
`YAI_API_KEY`/`YAI_MODEL` (and `YAI_PROVIDER`, which the map now reads), `mock_console` is a `MagicMock`.
Caveat: the module-level `cfg` singleton is created at import, **before** the `CONFIG_PATH` patch applies, so
tests needing a provider patch `yaicli.cli.cfg` explicitly (`tests/test_cli.py:347`, `tests/test_image.py:420`);
the `cli_with_mocks` helper in `tests/test_cli.py` instead injects a mock client.

## Rules

- One default location: values in `const.py`, conversion in `config.py`, no literals at read sites. Never mutate `cfg`
  from feature code except CLI-flag override and `auto` OS/shell detection (tests share the singleton).
- Never build paths from `~` inline; import the `const.py` constant so tests can patch one place. Keep secrets out of
  logs/verbose output (`API_KEY` masked as `****`).
- Import paths must stay write-free (config/role/chat/providers/tools); all state writes are explicit, best-effort
  (OSError → warning + continue) and use the resolved config dir with 0600/0700 for files containing secrets.
