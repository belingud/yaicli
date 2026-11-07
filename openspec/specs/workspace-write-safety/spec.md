## Purpose

Define the execution-layer guard that confines mutations made by builtin filesystem tools to the
workspace, protects sensitive paths, backs up existing targets before a mutation, and lets the user
undo the last mutation made by the agent in the current process.

## Requirements

### Requirement: Filesystem mutations are confined to the workspace root

Before an `fs_write_file`, `fs_edit_file` or `fs_file_operations` call mutates the filesystem, the
system SHALL resolve the attempted target path and SHALL refuse the call unless the resolved target
lies strictly inside the effective workspace root. The effective root SHALL be `WORKSPACE_ROOT`
(config file / `YAI_WORKSPACE_ROOT` environment) when set, otherwise the process working directory.
Path resolution SHALL mirror the builtin tools (`expanduser` + `resolve(strict=False)`), so symlinks
and `..` segments are resolved before the containment check and a link pointing outside the
workspace is refused. A refusal SHALL return an in-band JSON error (never raise, never print), SHALL
name the attempted path and the effective root, and SHALL leave the filesystem untouched.

#### Scenario: Out-of-workspace target is refused
- **WHEN** the model calls a builtin mutating filesystem tool with a path outside the effective workspace root
- **THEN** the tool call SHALL return an in-band JSON error with reason `outside_workspace` and SHALL NOT modify the filesystem

#### Scenario: Symlink escape is refused
- **WHEN** the attempted target is a symlink inside the workspace that resolves to a path outside it
- **THEN** the call SHALL be refused as `outside_workspace`

#### Scenario: Workspace root itself is not mutable
- **WHEN** the attempted target is the workspace root directory itself
- **THEN** the call SHALL be refused with reason `workspace_root`

#### Scenario: Relative target inside the workspace is allowed
- **WHEN** the attempted target is a relative path that resolves inside the effective workspace root
- **THEN** the mutation SHALL proceed to the tool (subject to the remaining guard rules)

### Requirement: Sensitive paths are protected inside the workspace

Even inside the workspace, the system SHALL refuse a mutation whose target (or, for move/copy, whose
source or actual destination, including the destination-is-a-directory case) has a `.git`, `.ssh`,
`.aws` or `.gnupg` path component, or whose basename matches `.env`, `.env.*`, `*.pem` or `*.key`.
A refusal SHALL be in-band with reason `protected_path` and SHALL leave the filesystem untouched.

#### Scenario: Repository internals are protected
- **WHEN** the model attempts to write, edit, delete or move `.git/config` inside the workspace
- **THEN** the call SHALL be refused as `protected_path`

#### Scenario: Secret-bearing files are protected
- **WHEN** the model attempts to overwrite `.env`, `server.pem` or a `*.key` file inside the workspace
- **THEN** the call SHALL be refused as `protected_path`

### Requirement: Existing targets are backed up before a mutation

Before an existing file or directory is overwritten, edited, appended to, deleted or moved, the
system SHALL copy it to `<workspace>/.yaicli-backups/<UTC stamp>/<workspace-relative path>`, with
backup files created mode `0600` and directories `0700` (best effort). If the backup cannot be
created, the mutation SHALL be refused with reason `backup_failed` (fail closed) and the filesystem
SHALL be left untouched. `fs_edit_file` with `dry_run=true` performs no mutation and SHALL create no
backup and no undo entry.

#### Scenario: Overwrite creates a backup
- **WHEN** an existing file is overwritten through a builtin filesystem tool
- **THEN** the pre-mutation content SHALL exist under `.yaicli-backups` before the tool runs

#### Scenario: Backup failure refuses the mutation
- **WHEN** the backup copy cannot be written
- **THEN** the mutation SHALL be refused and the original file left unchanged

### Requirement: The last mutation can be undone from the REPL

The system SHALL record every successful mutation on a bounded, process-local undo stack (most
recent kept, a small finite depth) and SHALL provide a `/undo` REPL command that reverts the most
recent entry: restoring file/directory content from its backup, or deleting a file/directory the
agent created. `/undo` with an empty stack SHALL print a friendly message and SHALL NOT error.
Partial restore failures SHALL be reported to the user.

#### Scenario: Undo restores the previous content
- **WHEN** the agent overwrote or edited a file and the user runs `/undo`
- **THEN** the file SHALL be restored to its pre-mutation content

#### Scenario: Undo removes an agent-created file
- **WHEN** the agent created a new file and the user runs `/undo`
- **THEN** the created file SHALL be deleted

#### Scenario: Undo with an empty stack is harmless
- **WHEN** no mutation has been recorded in the current process and the user runs `/undo`
- **THEN** the command SHALL print a friendly message and the REPL SHALL continue

### Requirement: Guard denials preserve the tool-call result contract

A guard refusal SHALL be delivered as the tool result for the matching tool call (so the provider
request stays valid and the model can adapt), SHALL use the `{"success": false, "error": ...,
"reason": ...}` JSON shape, SHALL be recorded in the tool-output history like normal results, and
SHALL NOT raise an exception or write to stdout from the guard itself.

#### Scenario: Denied mutation keeps the conversation valid
- **WHEN** a mutating tool call is refused by the guard
- **THEN** the model SHALL receive a matched in-band error result and the next provider request SHALL remain valid

### Requirement: Guard scope is limited to the builtin mutating tools

The guard SHALL apply to `fs_write_file`, `fs_edit_file` and `fs_file_operations` only. MCP and
user-installed custom tools are not intercepted. Deleting a directory that merely contains a
protected child path is not expanded or refused (documented limitation).
