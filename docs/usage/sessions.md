# Chat Sessions & `--resume`

Since v0.21, saved chat sessions are **isolated per project** instead of sharing one temporary
directory, sessions record how they were produced, and `--resume` continues the newest session of
the current project. This page covers the session store, the metadata notice, `--resume`, the
`--chat <title>` behaviour and the migration options for sessions saved by older releases.

## Where sessions live

By default every working directory gets its own store:

```
~/.yaicli/sessions/<key>/
└── 20261107-231500-title-<title>.json
```

Session files are named `<YYYYMMDD-HHMMSS>-title-<title>.json`; indexes in `/list`, `/load` and
`/del` follow newest-first order.

- `<key>` is `sha256(<resolved working directory>)[:16]` — 16 hex characters. It is stable across
  runs, resolves symlinks (a symlinked project path maps to the same store), and is deliberately
  not human readable so a directory listing does not leak usernames or project names.
- The store is **HOME-derived**: `~/.yaicli/sessions`, also when `XDG_CONFIG_HOME` is set. Sessions
  are user data, kept out of the editable config directory.
- Sessions are keyed by the **working directory**, not by the git root. Running `ai --chat` from
  `repo/` and from `repo/sub/` uses two different stores. To keep one store for a project, always
  start from the same directory (or use `--cwd repo/`). `/list`, `/load`, `/del`, `--resume` and
  `--chat "<title>"` all operate on the store of the current working directory.
- Set `CHAT_HISTORY_DIR` (or `YAI_CHAT_HISTORY_DIR`) to an explicit directory to keep the old flat
  layout; see [Overriding the session directory](#overriding-the-session-directory).

### Permissions and layout

| Item | Mode |
| --- | --- |
| `~/.yaicli/sessions/` and per-project directories | `0700` |
| Session JSON files | `0600` |

Session files are written atomically (hidden temp file → `fsync` → `os.replace`) and contain the
full conversation, including tool calls, images and reasoning. `MAX_SAVED_CHATS` (default `20`)
applies within the active store; older sessions are removed when the limit is exceeded.

The managed store under `~/.yaicli/sessions` is hardened on use. With an explicit
`CHAT_HISTORY_DIR` the override directory is created/used `0700` as well (session files stay
`0600`), but its parent directories are not modified — point it at a directory whose location and
permissions you control.

## Session metadata

Each save records how the session was produced:

| Field | Meaning |
| --- | --- |
| `model` | `MODEL` in effect for the session |
| `provider` | `PROVIDER` in effect for the session |
| `role` | Assistant role used |
| `cwd` | Absolute working directory the session belongs to |
| `created_at` | When the session was first saved (fixed after that) |
| `updated_at` | When the session was last saved |

Sessions saved by older releases (no metadata) load normally and are backfilled on their next save.
Metadata describes **how the conversation was recorded**: resuming does not switch the current
configuration back to that model/provider — the current config supplies the model for new turns, and
the notice just lets you see the mismatch.

A session also records its active plan (id, path, status, revision, session id and todos) when one
exists, so the resume hint above can point at the plan file; the plan-mode state itself is never
persisted or restored.

When `--resume` finds a session, it prints one line to the terminal before the REPL starts:

```
Resumed session "refactor the config loader" (model=gpt-5.2, provider=openai, role=DEFAULT, messages=14)
```

## `--resume`

```bash
ai --resume
```

- Implies `--chat`: it opens the interactive REPL continuing the **newest saved session for the
  current project** (newest by file modification time).
- Takes no title. To continue a specific session use `ai --chat "<title>"`; a positional
  prompt/title passed together with `--resume` is ignored.
- **No saved session**: prints `No saved session found for this project; starting a new session.`
  to stderr and starts a **temporary** session — use `/save <title>` if you want to keep it.
- **Interactive only.** It is ignored (with a warning) when combined with `-p/--print`, with
  `--output-format` other than `text`, or when stdin is redirected. Those runs continue as normal
  one-shot runs; no session is resumed.
- **Plan mode is never restored.** A resumed session always starts in the normal mode, even if it
  was closed while planning or executing a plan. If the session has an unfinished plan, one hint is
  printed after the resume notice — `⚠ unfinished plan found: <id> (draft, revision N)` with
  `Use /plan review to continue it, or /plan list to see all plans.`, or the `(in-progress, ...)`
  variant pointing at `/plan resume`. A plan whose file is missing, corrupt or bound to another
  session is ignored with `saved plan not found/inconsistent; starting in normal mode` on stderr;
  see [Plan Mode](plan-mode.md#resuming-a-session).

## The `--chat` title behaviour

`ai --chat "<title>"` loads the session with that exact title from the current project's store:

- **Title found**: the session is loaded and the REPL continues it.
- **Title missing**: v0.21 prints an explicit notice to stderr instead of silently starting a new
  session — `No saved session titled "<title>" for this project; starting a new session.` — and
  continues with a new **persistent** session under that title (it is saved automatically when the
  session ends with messages).

Because sessions are per project, a title saved in one directory is not found in another. Run the
same command from the same directory (or use `--cwd`) to load it.

## Listing and managing sessions

| Command | Scope |
| --- | --- |
| `ai --list-chats` | Saved sessions of the **invocation** working directory |
| `/list` (REPL) | Saved sessions of the current (post-`--cwd`) working directory |
| `/load <index>`, `/del <index>`, `/save <title>` | The current project's store |

With an explicit `CHAT_HISTORY_DIR` override, all of these operate on that flat directory instead
of a per-project store.

> **Known caveat:** `--list-chats` is implemented as an option callback that runs before `--cwd` is
> applied. `ai --list-chats --cwd other-project` therefore still lists the sessions of the directory
> you ran the command from. `cd` into the project first, or use `/list` inside `ai --cwd <dir>`.

## Overriding the session directory

An **explicit** `CHAT_HISTORY_DIR` value (config file or `YAI_CHAT_HISTORY_DIR`) that differs from
the old built-in default keeps the previous flat-directory behaviour: every project's sessions are
stored together in that directory, `--resume` continues the newest session there, and
`MAX_SAVED_CHATS` applies to the directory as a whole.

The built-in default is `<tempdir>/yaicli/chats` (`python -c "from yaicli.const import
DEFAULT_CHAT_HISTORY_DIR; print(DEFAULT_CHAT_HISTORY_DIR)"`). A `CHAT_HISTORY_DIR` equal to that
built-in default is treated as **unset** and gets the per-project store.

> **Existing config files:** `config.ini` files created by v0.19/v0.20 contain a materialised
> `CHAT_HISTORY_DIR=<temp path>` line. On the same machine that path usually equals the built-in
> default, so it counts as unset and sessions become per-project. If the temp path has changed
> (different boot/container), the line is treated as an explicit override and sessions keep going
> to that flat directory. Delete or comment the line to opt into the per-project store.

```ini
# config.ini — keep the old flat layout in a stable directory
[core]
CHAT_HISTORY_DIR=/home/me/yaicli-sessions
```

## Migrating from old sessions

Sessions saved by v0.20 and earlier live in the old temporary directory
(`<tempdir>/yaicli/chats`). v0.21 **does not migrate them**: they are left in place and are no
longer listed by default. Nothing is deleted.

> The old directory is a system temp directory, so copy anything important out of it before it is
> cleaned up by the OS.

Two ways to get them back:

**Option A — copy them into the current project's store** (they then appear in `/list` and
`--resume` for that project):

```bash
# Run inside the project directory, using the Python environment that has yaicli
# installed. Locate the old sessions and the new project store:
OLD="$(python -c 'from yaicli.const import DEFAULT_CHAT_HISTORY_DIR as d; print(d)')"
NEW="$(python -c 'from yaicli.const import get_project_sessions_dir; print(get_project_sessions_dir())')"

# Create the destination and copy the JSON sessions
mkdir -p "$NEW"
cp "$OLD"/*.json "$NEW"/
```

**Option B — keep a flat store for the old sessions** (all projects listed together):

```bash
# OLD is defined as above; use a dedicated directory (not the old built-in default path)
mkdir -p ~/yaicli-legacy-sessions
cp "$OLD"/*.json ~/yaicli-legacy-sessions/
export YAI_CHAT_HISTORY_DIR=~/yaicli-legacy-sessions
```

If the old temporary directory has already been cleaned up by the OS there is nothing to migrate;
new sessions are unaffected.

Legacy JSON files load fine. Their missing metadata is filled with the then-current
configuration (`model`/`provider`/`role`/`cwd`) when the session is resumed or next saved, so the
**first** resume notice of a legacy session shows `unknown` and later notices show the recovered
values.

## Prompt history file

The REPL prompt history is a separate file: `$XDG_STATE_HOME/yaicli/history` when `XDG_STATE_HOME`
is set, otherwise `~/.yaicli_history`. Since v0.21 it is created with mode `0600` (its directories
`0700`), because it contains every prompt you typed, possibly including pasted secrets. A legacy
history file with mode `0644` is repaired to `0600` the next time it is appended to or trimmed.

## Privacy notes

- Session files contain the full conversation (including tool output and image payloads) and are
  private per user; keep the `0600`/`0700` modes and do not commit them.
- Deleting a session file removes that conversation; there is no automatic backup of sessions.
- `--list-chats` prints titles and creation dates only; it does not load the conversations.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Old chats are missing after upgrading | Per-project store is now the default; see [Migrating from old sessions](#migrating-from-old-sessions) |
| `--resume` says no session | You are in a different working directory than the session's; `cd` back or use `--cwd` |
| `--list-chats` lists nothing for `--cwd DIR` | Callback runs before `--cwd`; `cd` first or use `/list` in the REPL |
| `--chat "title"` starts a new session | No session with that title exists in this project's store (see the notice above the prompt) |
| Resume notice shows a different model/provider | Metadata describes how the session was recorded; the current config supplies the new turns |
| Sessions not visible in `~/.yaicli/sessions` | An explicit `CHAT_HISTORY_DIR`/`YAI_CHAT_HISTORY_DIR` override is active |

## Related

- [Configuration](configuration.md) — `CHAT_HISTORY_DIR`, `MAX_SAVED_CHATS`, session metadata
- [Conversation & History](../advanced/history.md) — session JSON format, atomic saves, history limits
- [Command Reference](commands.md) — `/save`, `/load`, `/list`, `/del`
- [Project Context](project-context.md) — the other per-project behaviour added in v0.21
- [Plan Mode](plan-mode.md) — plan files and the `--resume` plan hint
- [Upgrade Notes](../advanced/upgrade.md) — migration stance and what changed in v0.21
