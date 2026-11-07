# Workspace Safety: Writes, Backups & Undo

Agents write files. Since v0.21, YAICLI's built-in filesystem tools treat your project directory
as a **workspace**: writes are confined to it, the most sensitive paths are refused, existing files
are backed up before they change, and `/undo` reverts the last change.

This page documents the write guard. For *which* tool calls are allowed to run at all, see
[Permissions & Safety](permissions.md).

## What is guarded

| Tool | Guarded operations |
| --- | --- |
| `fs_write_file` | create, overwrite and append (`append=true`) |
| `fs_edit_file` | every edit type (`replace`, `replace_line`, `insert_line`, `delete_line`, `append`); `dry_run=true` previews do not mutate, back up or create an undo entry |
| `fs_file_operations` | `delete`, `move`, `copy`, `create_dir`; the read-only operations (`exists`, `get_info`) do not mutate and are not guarded |

The guard runs in the tool execution layer *before* the tool executes. If it refuses a call, the
filesystem is untouched and the model receives an in-band JSON result it can read (see
[Denials](#denials)).

**Not guarded:** shell commands (`execute_shell_command`), MCP tools and custom functions. Shell
commands are confined by their working directory and their own guardrails (timeout, filtered
environment) but their file effects are not backed up and cannot be undone — use git for those.
MCP tools and custom functions run as their servers/authors implement them.

## The workspace root

| Source | Effect |
| --- | --- |
| `WORKSPACE_ROOT` in `config.ini` | Workspace root for guarded writes and the shell `cwd` |
| `YAI_WORKSPACE_ROOT` (environment) | Same, higher priority than `config.ini` |
| `--cwd DIR` | Changes into `DIR` for the run and sets the workspace root to it |
| *(none of the above)* | The process working directory — the directory you started `ai` in |

```bash
# Confine a run to a project, even if started somewhere else
ai --cwd ~/projects/my-app "refactor the config loader"

# Equivalent for a whole shell session
export YAI_WORKSPACE_ROOT="$PWD"
```

The root is resolved to a real path when the mutation runs. A not-yet-existing root is allowed at
resolution time, but the write then fails closed (in-band error) if it cannot be created or is not
writable.

> **Relative paths resolve against the process working directory**, not against the workspace
> root: `main.py` means `<cwd>/main.py`, then that path must still be inside the workspace root. If
> you set `WORKSPACE_ROOT` to a directory different from where you launched `ai`, relative tool
> paths will usually resolve outside it and be refused. Either launch `ai` from the project (or use
> `--cwd`), or give the model absolute paths inside the workspace.

## Path rules

Before running a write tool, the guard resolves the target and checks it:

| Target | Result |
| --- | --- |
| Relative path | Resolved against the process working directory, then checked against the workspace root |
| Absolute path inside the workspace | Allowed |
| Absolute path outside the workspace (`/tmp/x`, `~/.ssh/id_rsa`, `../other-project/file`) | Refused: `outside_workspace` |
| `..` segments that escape the root | Resolved first, then refused because the result is outside |
| Symlink pointing outside the workspace | Refused (`outside_workspace`); the real target is outside |
| Symlink pointing inside the workspace | Allowed; the operation applies to the resolved target |
| A file that does not exist yet but is inside the root | Allowed (creating a new file is the normal case) |
| The workspace root itself | Refused: `workspace_root` — the root cannot be written, moved or deleted as a whole |
| A protected path (see below) | Refused: `protected_path`, even inside the workspace |

For `fs_file_operations` the guard also checks the **destination** of `move`/`copy`, including the
implicit destination when a file is moved/copied into an existing directory
(`dest/file.txt`).

## Protected paths

These are refused even when they are inside the workspace:

| Protected | Matches |
| --- | --- |
| `.git`, `.ssh`, `.aws`, `.gnupg` directories | Any path component with one of those names (any depth, case-insensitive) |
| `.env` files | Basename `.env` or `.env.*` (`.env.local`, `.env.production`, ...) |
| Certificate / key files | Basenames ending in `.pem` or `.key` (case-insensitive) |

Normal project files are not affected: `.gitignore`, `.github/`, `.envrc`, `keys/README.md` and
`backups.db` are all writable. The backup directory `.yaicli-backups` is intentionally not
protected (the guard itself writes there).

The protected-path check applies to every guarded target: writing, editing, deleting, and the
source or destination of a move/copy. To change such a file, do it yourself (or export an
environment variable / use a secret manager) — the agent will only get a refusal.

## Backups

Before an **existing** file or directory is overwritten, edited, appended to, deleted or moved, it
is copied into the workspace:

```
<workspace>/.yaicli-backups/<UTC stamp>/<path relative to the workspace root>
```

The stamp is generated once per mutation: `YYYYMMDDTHHMMSSffffffZ` (UTC, microsecond precision), for
example:

```
my-project/
├── .yaicli-backups/
│   └── 20261107T143456123456Z/
│       └── src/config.py        # copy of the previous src/config.py
├── .gitignore
└── src/config.py                # the new version
```

- **Modes**: backup directories are created `0700` and files are copied with mode `0600` (best
  effort; tool arguments can contain secrets, so backups are private).
- **Directories** are copied recursively, preserving symlinks (they are not followed).
- **Created files have no backup**: `undo` deletes them instead.
- **`fs_edit_file(dry_run=true)`** creates no backup.
- **Fail closed**: if a backup cannot be written (disk full, permissions), the mutation is
  **refused** with a `backup_failed` denial and the original file is left untouched. YAICLI never
  changes a file it cannot back up.
- **No automatic cleanup**: backups accumulate until you delete them. The directory is created on
  the first backup, inside the workspace root.

> **Add `.yaicli-backups/` to your `.gitignore`** so agent backups are not committed:
>
> ```gitignore
> .yaicli-backups/
> ```
>
> Use a global gitignore if you do not want to edit each repository. Backups may contain secrets,
> so delete old stamps once you no longer need them: they are ordinary files inside the workspace,
> readable (and writable) by both you and the agent — old versions of a file may contain API keys
> that you have since rotated.

## `/undo`

In the interactive REPL, `/undo` reverts the **last** file change made by a guarded tool:

| Change | What `/undo` does |
| --- | --- |
| Overwrote, edited or appended a file | Restores its previous content from the backup, recreating missing parent directories |
| Deleted a file or directory | Restores it from the backup |
| Moved a file/directory | Restores the source (and the destination's previous content, if it was overwritten) |
| Created a file or directory | Deletes it; a copied/moved directory tree is removed in full |

A restored file also gets its previous permission bits back (best effort).

- **One mutation per command.** Undo the last change, then run `/undo` again for the one before it.
- **Bounded:** the last **20** mutations are kept in memory; older entries are dropped silently.
- **Process-local:** the undo stack lives in the running `ai` process and is lost when it exits.
  A one-shot run that mutates files and exits can no longer be `/undo`-ed; its backups are still in
  `.yaicli-backups/`, so you can restore by hand.
- **Only guarded tools:** shell commands, MCP tools and custom functions are not recorded.
- The command reports what it restored and deleted, and lists partial failures. If a created
  directory is no longer empty (the agent wrote files into it afterwards), undo reports an error and
  leaves it in place — undo the later writes first.
- With an empty stack: `Nothing to undo: no file changes were recorded in this session.`

Example session:

```bash
💬 > refactor src/config.py and update the README
Assistant:
...

💬 > /undo
Undid the last file change (fs_edit_file): restore 1 path(s).
  restored: src/config.py

💬 > /undo
Undid the last file change (fs_write_file): remove 1 path(s).
  deleted: README.bak
```

## Denials

A refused mutation is an **in-band result**, not an exception and not a permission-gate denial:
the model sees the reason, the filesystem stays untouched, and the agent loop continues so the
model can choose another path. The payload looks like:

```json
{
  "success": false,
  "error": "Refusing to modify '/tmp/report.md': it resolves outside the workspace root '/home/me/project'. ...",
  "reason": "outside_workspace",
  "path": "/tmp/report.md",
  "workspace_root": "/home/me/project"
}
```

| `reason` | Meaning | What to do |
| --- | --- | --- |
| `outside_workspace` | Target is outside `WORKSPACE_ROOT` | Run `ai` in the right directory, pass `--cwd`, or set `WORKSPACE_ROOT` |
| `protected_path` | Target is `.git`/`.ssh`/`.aws`/`.gnupg` or a `.env*`/`*.pem`/`*.key` file | Edit it yourself |
| `workspace_root` | Target is the workspace root itself | Choose a file inside it |
| `backup_failed` | The pre-change backup could not be written | Fix disk space/permissions; the file was not modified |
| `workspace_guard_error` | The guard itself failed | Nothing was changed; run `ai --verbose` and report a bug |

Because these denials are not permission-gate denials, `--fail-on-tool-denied` does not exit on
them; the model simply receives the refusal.

## Known limits

- **Directory targets are not expanded.** Deleting or moving a directory is checked at the
  directory path itself; a protected path *inside* it (for example `project/.git` when deleting
  `project/`) does not block that delete. The whole tree is backed up first, so `/undo` can restore
  it — but do not rely on the protected-path check for directory-level operations.
- **Shell side effects are not guarded or undoable.** Only the shell's working directory and its
  timeout/environment guardrails apply.
- **MCP and custom functions are not guarded.** They can write anywhere the process can.
- **Only the REPL has `/undo`.** Headless/one-shot runs still get confinement and backups, but the
  undo stack dies with the process; restore from `.yaicli-backups/` manually if needed.
- **It is a cooperating-tool guard, not an OS sandbox.** Shell commands and MCP/custom tools can
  still write outside the workspace; the guard protects against mistakes by the built-in
  filesystem tools, not against a malicious tool.
- **Windows**: symlink escape protection depends on OS symlink support; private backup modes are
  best effort on filesystems without POSIX permissions.

## Related

- [Permissions & Safety](permissions.md) — approval prompt, `TOOL_POLICY` modes, danger
  classification and the audit log
- [Configuration](configuration.md) — `WORKSPACE_ROOT`, `TOOL_POLICY` and the other tool settings
- [Command Reference](commands.md) — `/undo` and the other REPL commands
- [Upgrade Notes](../advanced/upgrade.md) — what changed in v0.21
