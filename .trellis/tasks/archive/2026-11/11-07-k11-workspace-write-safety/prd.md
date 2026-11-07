# K11 workspace write safety + /undo

Parent: `11-07-v021-safety-foundation`. Source: `var/lightweight-audit/09-roadmap.md` P1 K11.

## Requirements

1. **Workspace confinement**: `fs_write_file`, `fs_edit_file`, `fs_file_operations` mutations confined to
   effective workspace root (`WORKSPACE_ROOT` cfg; empty = cwd). Outside targets refused with actionable
   in-band JSON error (no raise), filesystem untouched. Symlink-safe (resolve existing parents).
2. **Protected paths**: refuse `.git`/`.ssh`/`.aws`/`.gnupg` path components and `.env`/`.env.*`/`*.pem`/`*.key`
   basenames even inside the workspace.
3. **Backups**: before overwriting/editing/deleting/moving an existing file, copy to
   `<workspace>/.yaicli-backups/<UTC stamp>/<relative path>` (files 0600, dirs 0700). Backup failure =>
   refuse mutation. `fs_edit_file(dry_run=True)` needs no backup.
4. **`/undo`**: REPL command restores the most recent mutation of the session (backup content, or delete a
   file the agent created), bounded in-memory stack (~20), friendly empty-stack message; define `CMD_UNDO`
   locally in `cmd_handler.py` (precedent: `CMD_PERMISSIONS`, `CMD_COMPACT`), dispatch + `handle_undo()`,
   minimal `cli.py` plumbing, discoverable in help/completer where slash commands are enumerated.

Architecture: builtins are standalone (no yaicli internal imports), so the guard lives in a new stdlib-only
`yaicli/tools/workspace.py` called from `yaicli/tools/__init__.py::execute_tool_call` before dispatch.
Guard reads `WORKSPACE_ROOT` from cfg (env `YAI_WORKSPACE_ROOT` already exported). No printing from the guard.

## Files (write scope)

`yaicli/tools/workspace.py` (new), `yaicli/tools/__init__.py`, `yaicli/cmd_handler.py`, `yaicli/cli.py`,
`tests/test_workspace_safety.py` (new), `tests/tools/test_tools_init.py`, `tests/tools/test_fs_*.py` (fixtures only).

## DO NOT touch

`yaicli/const.py`, `yaicli/config.py`, `yaicli/llms/**`, `yaicli/entry.py`, `yaicli/printer.py`,
`yaicli/functions/buildin/**`, `docs/`, `openspec/`, `.trellis/spec/`. No new dependencies, Python 3.10,
ruff F, 120 cols. No git state commands.

## Acceptance

- [ ] Outside-workspace write/edit/delete/move refused (in-band, untouched); override works; default root = cwd.
- [ ] Protected paths refused; undo restores backup content / deletes created files; append undo works.
- [ ] Backups exist with 0600; backup failure refuses mutation; dry-run creates none.
- [ ] `/undo` wired into REPL + help; empty stack handled; direct `Function.execute()` unit tests still pass.
- [ ] `tests/test_workspace_safety.py` + affected tools/command tests pass; ruff clean.
