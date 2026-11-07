## Purpose

Define how YAICLI stores chat sessions so they are isolated per project, private on disk, resumable,
and never silently replaced by a new session when the user intended to continue an existing one.

## Requirements

### Requirement: Sessions are stored per project

Stored chat sessions SHALL be isolated by the resolved current working directory: the default session
directory SHALL be `<home>/.yaicli/sessions/<sha256(resolved cwd)[:16]>/`, so two projects never mix
their sessions and the opaque key does not leak the project name. The hash SHALL be stable across runs
and normalize symlinked/relative spellings of the same directory. An explicitly configured
`CHAT_HISTORY_DIR` (config file or `YAI_CHAT_HISTORY_DIR`) that differs from the built-in legacy
default SHALL be honored unchanged as a single flat directory, for backward compatibility.

#### Scenario: Two projects have separate session lists
- **WHEN** the user saves a session in project A and lists sessions in project B
- **THEN** project B's listing SHALL NOT include project A's session

#### Scenario: Explicit CHAT_HISTORY_DIR keeps the flat directory
- **WHEN** `CHAT_HISTORY_DIR` is explicitly set to a custom path
- **THEN** sessions SHALL be read from and written to that flat directory

### Requirement: Session storage is private

Session directories created by the feature SHALL be mode 0700 (best effort) and session files SHALL
be mode 0600, created through the existing atomic temp-file-then-replace write. The prompt history
file SHALL also be created 0600 with 0700 parent directories, and legacy 0644 history files SHALL be
repaired on the next append/trim. An unmanaged user-provided `CHAT_HISTORY_DIR` directory SHALL NOT be
chmod'ed. Filesystem errors SHALL degrade with a warning, never crash the CLI.

#### Scenario: Session file is not world-readable
- **WHEN** a session is saved in the managed session store
- **THEN** the session file SHALL be 0600 and its project directory 0700 (best effort)

### Requirement: Sessions record how they were produced

Each saved session SHALL record metadata: the model, provider and role it was created with, the cwd,
and created/updated timestamps, in a way that legacy session JSON without those fields still loads
(fields default to empty and are backfilled on the next save). Resuming or loading a session SHALL NOT
silently switch the active model/provider/role: the recorded metadata is informational and the current
configuration continues to drive the turn.

#### Scenario: Metadata is persisted and legacy files load
- **WHEN** a session is saved and later loaded
- **THEN** model/provider/role/cwd/timestamps SHALL round-trip, and an old file without them SHALL load without error

### Requirement: The newest session can be resumed

The CLI SHALL provide a `--resume` flag that implies interactive chat mode and continues the newest
saved session of the current project. When a session is resumed, the CLI SHALL print a one-line notice
with the session title and recorded metadata. When no session exists for the project, the CLI SHALL
print an explicit notice and start a new session. Like `--chat`, `--resume` SHALL be ignored with a
warning under `--print`/structured output and when stdin is redirected.

#### Scenario: Resume continues the newest project session
- **WHEN** the project has saved sessions and the user runs the CLI with `--resume`
- **THEN** the newest session SHALL be loaded, its notice printed, and the REPL SHALL continue that conversation

#### Scenario: Resume with no sessions starts a new one explicitly
- **WHEN** the project has no saved sessions and the user runs the CLI with `--resume`
- **THEN** the CLI SHALL print an explicit notice and start a new session

### Requirement: A missed title never silently starts a new session

When interactive chat is started with a title that matches no saved session, the CLI SHALL print an
explicit notice that a new session is being started instead of silently falling back to a new session.

#### Scenario: Unknown startup title is reported
- **WHEN** the user starts chat with a title that has no matching saved session
- **THEN** the CLI SHALL print that a new session is starting

### Requirement: Existing sessions are not migrated automatically

Pre-existing sessions in the legacy flat directory (the old temp-dir default) SHALL be left in place
without automatic copying or deletion. Users who need them listed can set `CHAT_HISTORY_DIR` to the old
path. The out-of-the-box behavior SHALL be the per-project store.

#### Scenario: Upgrade does not move or delete old sessions
- **WHEN** an upgraded installation starts with sessions in the legacy flat directory
- **THEN** those files SHALL remain untouched and the default store SHALL be the per-project directory
