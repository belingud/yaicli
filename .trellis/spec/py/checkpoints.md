# Conversation Checkpoint Contracts

## 1. Scope / Trigger

Applies to `checkpoints.py`, `checkpoint_lock.py`, checkpoint metadata in `chat.py`,
the REPL lifecycle in `cli.py`, slash commands in `cmd_handler.py`, and mutation capture
in `tools/`. Read [config-and-context.md](./config-and-context.md),
[function-tool-guidelines.md](./function-tool-guidelines.md) and
[cli-and-rendering.md](./cli-and-rendering.md) for the existing surrounding contracts.

Checkpoints are a local conversation/file-history feature. They do not prescribe tests,
run automatic verification, or turn YAICLI into a coding-specific agent.

## 2. Signatures

User-facing commands:

```text
/checkpoints
/rewind [id]
/fork [id] [title]
```

`id` is a non-negative checkpoint number; omitted means the previous retained checkpoint.
The optional fork title preserves case and may contain spaces. Invalid arguments print the
matching usage string. An explicit current id is a no-op, not a new checkpoint.

Core entry points include:

```python
CheckpointStore(directory, root, session_id, keep=20, max_mb=50,
                session_path=None, expected_head=None)
store.begin_turn(turn)  # returns a TurnCapture holding the session writer lock
store.finish_turn(capture, snapshot, commit_chat=None)  # returns (head, optional_warning)
store.preview(target, head)  # validates without workspace writes
store.rewind(target, head, commit_chat, source_snapshot=None, before_apply=None)
CLI._checkpoint_store()
CLI._checkpoint_reset(only_if_new=False)
```

The CLI owns conversation state; the tool executor records actual
mutations; the store owns validation, retention and recovery. Do not import the CLI from the store
or teach providers about checkpoints. `checkpoint_lock.py` is a small stdlib-only lock primitive.
For persisted CLI turns, pass `commit_chat` to `finish_turn` so the saved chat and index advance
under the same session writer lock; an unlocked save after releasing the capture is not sufficient.

## 3. Contracts

### Eligibility and configuration

Only saved, interactive terminal chats record checkpoints. Before the first `/save`, temporary
conversations have no checkpoint history. Disabled, quiet, machine-output and non-TTY paths must
not initialize checkpoint storage. Keep the checkpoint implementation lazily imported; tool
execution may consult an already loaded capture without importing the store on ordinary startup.

| Config | Type | Default | Environment |
| --- | --- | --- | --- |
| `CHECKPOINT_ENABLED` | bool | true | `YAI_CHECKPOINT_ENABLED` |
| `CHECKPOINT_KEEP` | int, minimum 1 | 20 | `YAI_CHECKPOINT_KEEP` |
| `CHECKPOINT_MAX_MB` | int, minimum 1 MiB | 50 | `YAI_CHECKPOINT_MAX_MB` |

Use the existing env > config file > default resolution. The budget is MiB per conversation,
including retained snapshots and owned backups. A conversation snapshot is at most 2 MiB.
If a complete snapshot or mutation history cannot be retained, cut the old chain and establish
a new baseline only when the current state is recordable; never leave a partially replayable chain.

Disabling preserves an existing `checkpoint_session_id` for ownership tracking, sets the saved
`checkpoint_head` to `-1`, and performs no checkpoint-directory IO. Re-enabling after an old chain
was detached establishes a fresh UUID/baseline. Deletion can find old owned chains through their
bound saved-chat path, including chains whose identity is no longer in the latest chat JSON.

### Identity and disk format

- Chat JSON adds optional `checkpoint_session_id` (UUID encoded as 32 lowercase hex characters)
  and `checkpoint_head` (integer,
  `-1` when unbound). Legacy chats without them remain loadable.
- Storage is `<actual-chat-store>/checkpoints/<project-key>/<session-id>/`. Reuse the existing
  resolved-cwd project key even with a shared `CHAT_HISTORY_DIR` override. Identity is independent
  of titles and list indexes. A copied conversation must not acquire another saved file's chain.
- The versioned manifest binds the session id, workspace root and saved chat path. Its `head`,
  `next`, `barrier_floor` and ordered `records` describe one continuous retained chain. Each record has `id`,
  `parent`, `turn`, `ts`, `snapshot` and `files`. Keep `next` above every previously issued id,
  including after rewind, pruning or a barrier.
- File mutation records contain relative `path` and `before`/`after` states: existence, SHA-256,
  file mode and any owned backup reference. Backups hold exact bytes; serialize chat snapshots
  through the existing redaction policy. Use 0700 directories and 0600 store files.
- Use same-directory temporary files plus atomic replacement for individual JSON writes.
  Acquire the session writer lock before advancing history and check both the manifest and saved
  chat version; a stale client must reload instead of overwriting a newer state.
- A hard interruption can leave JSON-write temporary files. Under the session writer lock,
  and only without unresolved recovery, remove files matching the store's exact owned temporary
  naming pattern before pruning. Preserve unknown files and recovery data; a cleanup failure
  must report that the budget cannot be verified rather than silently exceeding it.
- Session deletion/retention removes its owned checkpoint history. Never delete unresolved
  recovery data as routine retention work.

### Mutation and recovery boundaries

- Capture the pre-mutation state at the guarded executor, before a supported builtin actually
  writes. Record completion and post-state after it returns. Carry capture context into the
  streaming worker; never let an abandoned worker contribute to a different turn or session.
- Support ordinary file create/edit/delete/copy/move and identifiable newly created empty parents.
  Guarded tools, rewind and `/undo` use the same workspace mutation lock.
- Directory trees, symlinks, shell execution, MCP, custom tools (including overrides of builtin
  names), plan-state changes and unknown/interrupted mutations are barriers. A failed tool may
  still have changed files; an exception is not evidence of no side effects.
- `/undo` that might change the workspace restarts the baseline, `/clear` resets checkpoint
  history, `/retry` starts capture from actual current files, and snapshots retain the conversation
  after normal compaction/trimming. Rewind clears undo, retry and output-viewer state.
- Rewind restores conversation history and recorded files. It preserves current model, role,
  usage and external plan state. Fork saves an independent conversation without a plan binding
  or the source checkpoint identity; both chats still use the same workspace.
- Preflight the complete reverse chain before writing, including repeated mutations of one path.
  Validate workspace/protected/internal paths, types, modes, hashes, parents and backups; recheck
  after confirmation and before each write. Never follow a symlink or restore an internal store.
- Before changing files, persist source/target recovery information and source backups within
  the budget. On failure, compensate files, chat and manifest. If compensation is incomplete,
  retain the recovery record, identify the affected paths and block further rewind.
- `recovery.json` binds `version`, `session_id` and `root`; `source`/`target` are checkpoint ids,
  `chat`/`target_chat` are conversation snapshots, `manifest` is the source index, and each
  `files` entry has `path`, source `state` and `target`. These fields are one recovery contract;
  do not change just the file restore code when changing the commit protocol.
- After restart, recovery reconciliation only reads the workspace. A fully matching source or
  target version can be finalized; mixed state keeps recovery data and requires manual repair.
  Never silently restore workspace files during startup.

## 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Temporary / disabled / noninteractive | Explain the prerequisite; no restore or archive writes |
| `TOOL_POLICY=readonly` | Listing allowed; `Rewind and fork are unavailable in readonly mode.` |
| Missing retained id | `Checkpoint #<id> is unavailable.`; no changes |
| Workspace/session writer busy | `Workspace is busy. Try again when its file operations finish.` |
| Saved path, session id or head mismatch | Refuse the stale chain; request reload or establish a distinct identity for a copied chat |
| External file edit or mode/type change | Refuse the entire rewind before its first write |
| Missing/corrupt backup, symlink or protected path | Refuse the entire rewind; do not repair data by guessing |
| Fork title already exists / cannot save | No rewind; never overwrite an existing conversation |
| Empty response, `n`, EOF or Ctrl+C at confirmation | `Cancelled.`; no fork or rewind side effects |
| Snapshot exceeds 2 MiB | `Checkpoint skipped: chat snapshot exceeds 2 MiB.`; cut the chain |
| I/O failure after restore starts | Compensate; report full restoration or paths needing manual recovery |
| Unresolved recovery | Refuse further rewind and preserve the recovery files |

Results, lists and confirmation prompts use plain stdout; errors/warnings use stderr. Escape
control characters in user-controlled titles and paths. Interactive refusal returns to the REPL
without introducing a process exit code. In headless mode `/rewind 1` remains a model prompt.

## 5. Good / Base / Bad Cases

- Good: checkpoint #1 has an existing file; #2 edits it and creates a file under a new parent.
  Confirming rewind restores original bytes/mode, removes the new file and empty parent, restores
  #1 conversation history, and makes #2 unavailable. A later turn gets a fresh id above #2.
- Base: a pure conversation turn records history without file entries and survives process restart.
- Bad: a shell/custom tool ran, a file changed externally, a backup disappeared or another client
  advanced the chat. Refuse unsafe replay rather than restoring only the paths that still work.

## 6. Tests Required

- `tests/test_checkpoints.py`: real subprocess persistence/locking, monotonic ids, continuous
  reverse chains, exact bytes/modes, parent directories, guarded boundary checks, missing backups,
  barriers, pruning/byte caps, corruption, pending work and injected failure compensation.
- `tests/test_checkpoint_commands.py`: command grammar/help/completion, output/confirmation,
  cancellation, readonly/non-TTY/temp/disabled behavior, fork collision and save failure,
  real CLI turn lifecycle, stale/copy identities and resume/load across processes.
- `tests/test_checkpoint_integration.py`: isolated real entry/REPL/client/tool execution with a
  fake provider, including the actual stream worker, cross-process resume/load/rewind/fork,
  binary file copy/move/delete/recreate and exact machine-output comparisons. Only provider
  and terminal input are replaced; do not mock capture or the saved-chat commit being asserted.
- Existing session, workspace, tool dispatch, streaming, plan and headless tests must pass.
  Verify no startup checkpoint imports/IO and run the existing startup benchmark gate.
- Use temporary homes/stores and mocked providers. For multi-step failure tests, assert workspace,
  saved chat, manifest and recovery data together; a printed success message is insufficient.

## 7. Wrong vs Correct

Wrong: infer support from `tool_call.name == "fs_write_file"`, restore all paths with a backup,
then save the chat without checking its current version. A same-name override can have unknown
side effects, external changes can be overwritten, and another process's conversation can be lost.

Correct: verify the actual builtin implementation at dispatch, journal the guarded mutation before
execution, check the complete chain and current saved-chat version under locks, then commit with
recoverable source/target data. An unknown effect cuts history instead of advertising unsafe undo.

## Feature examples

```text
💬 > /rewind 1
Rewind to checkpoint #1 and drop 1 turn?
  Restore: trip.md
  Remove:  packing.md
Proceed? [y/N]: y
Rewound to #1. Restored 1 path, removed 1 path, dropped 1 turn.
```

This is an interactive stdout exchange. Any answer other than explicit `y` cancels. A conflict
discovered after confirmation prints to stderr and leaves the chat and workspace unchanged.
There is no new headless command or exit status.
