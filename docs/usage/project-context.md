# Project Context (AGENTS.md / CLAUDE.md)

Since v0.21, YAICLI automatically loads project instruction files into the system prompt: the
conventions, build commands and rules you already keep in the repository are available to the agent
on the very first request. The feature is on by default and needs no setup in a normal repository.

## How discovery works

1. **Start** at the current working directory (the `--cwd` target when that option is used).
2. **Walk upward** to the nearest git root — a directory containing a `.git` directory or the `.git`
   file of a git worktree — and stop there. If there is no git root, the walk continues to the
   filesystem root.
3. **Order directories outermost first** (git root first, the working directory last), so the most
   specific instructions appear last in the prompt.
4. **In every directory** include `.yaicli.md`, then `AGENTS.md`, then `CLAUDE.md` (each existing
   file is loaded, in that order).
5. **De-duplicate symlinks**: two names that resolve to the same real file (for example `AGENTS.md`
   symlinked to `CLAUDE.md`) are loaded only once.

All matching files are included — they are not merged or overridden; the model sees each file's
block in the order described above.

For example, running `ai` in `repo/packages/api/src/` with a git root at `repo/` sends:

```
repo/AGENTS.md                    ← outermost, first
repo/CLAUDE.md
repo/packages/api/AGENTS.md
repo/packages/api/src/.yaicli.md  ← innermost, last
```

The files are appended to the role system prompt as one block, after the role prompt and before
session context:

```markdown
## Project context (auto-loaded instruction files)

### AGENTS.md (/home/me/repo/AGENTS.md)

<file contents>

### .yaicli.md (/home/me/repo/packages/api/src/.yaicli.md)

<file contents>
```

Opening a new `ai` process in a different directory therefore uses that directory's instructions; a
monorepo can have root-level rules plus package-specific rules without repeating them.

## Size cap and truncation

The collected block is bounded by `PROJECT_CONTEXT_MAX_CHARS` (default **20000** characters,
including the heading; env `YAI_PROJECT_CONTEXT_MAX_CHARS`):

- when the cap cuts a file, the file's content is shortened; when the remaining budget cannot fit
  another file, that file is skipped entirely;
- **exactly one warning** is printed to stderr, naming each file with the kept/original character
  counts and telling you how to raise the limit;
- unreadable files (permissions, invalid encoding) are skipped with one warning and never fail the
  turn;
- set the key to `0` for no cap.

Example warning:

```
WARNING: Project context was truncated to PROJECT_CONTEXT_MAX_CHARS=20000: 19342 chars kept from 3 file(s)
(/home/me/repo/AGENTS.md (5120 chars), /home/me/repo/docs/AGENTS.md (6000 of 8123 chars kept), ...).
Raise PROJECT_CONTEXT_MAX_CHARS (env YAI_PROJECT_CONTEXT_MAX_CHARS) or set ENABLE_PROJECT_CONTEXT=false to disable.
```

If the cap is so small that even the heading does not fit, nothing is added to the prompt (the
warning still explains what was skipped).

## Disabling it

```ini
# config.ini
[core]
ENABLE_PROJECT_CONTEXT=false
```

```bash
# Environment variable (wins over config.ini)
export YAI_ENABLE_PROJECT_CONTEXT=false
```

Disabled mode performs **no filesystem reads at all**. Use it when you do not want a repository to
influence the agent (third-party checkouts, CI over untrusted forks, scripted runs with a pinned
prompt).

## When it is loaded

- The files are discovered **once per `ai` process, on the first request** and then reused for the
  whole REPL session. Edits to `AGENTS.md`/`CLAUDE.md` during a chat are **not** picked up — restart
  `ai` to load the new version.
- One-shot runs always load the current files.
- It applies to every mode (chat, one-shot, `--shell`, `--code`) because it is part of the system
  prompt.
- With **no** project files, nothing is appended: the system prompt and the provider request are
  byte-identical to the pre-v0.21 behaviour (no extra message, no extra API call).
- It only reads the instruction files. Loading them does not grant any tool permission and does not
  bypass the approval prompt, `TOOL_POLICY` or the workspace write guard.

## Configuration

| Key | Default | Environment variable | Purpose |
| --- | --- | --- | --- |
| `ENABLE_PROJECT_CONTEXT` | `true` | `YAI_ENABLE_PROJECT_CONTEXT` | Auto-load project instruction files (`false` = no filesystem reads) |
| `PROJECT_CONTEXT_MAX_CHARS` | `20000` | `YAI_PROJECT_CONTEXT_MAX_CHARS` | Max characters added to the system prompt (`0` = no cap) |

## Security note

**Project instruction files are untrusted input.** They become part of the system prompt, so a
malicious or careless repository can steer the model: ask it to read secrets, change files, run
commands or reveal conversation content. The normal safeguards still apply — tool calls go through
the approval prompt/`TOOL_POLICY`, file writes are confined by the workspace guard, and decisions are
audited — but the instructions themselves are not filtered.

Practical rules:

- run the agent only in repositories whose `AGENTS.md`/`CLAUDE.md` you trust, and review changes to
  those files like any other code;
- for third-party code or public forks, set `ENABLE_PROJECT_CONTEXT=false`, and consider
  `TOOL_POLICY=readonly` as well;
- remember that the files may contain secrets or internal URLs — keep them out of public repos;
- instruction files are just context: they cannot grant capabilities the tool system does not allow.

## Related

- [Configuration](configuration.md) — `ENABLE_PROJECT_CONTEXT`, `PROJECT_CONTEXT_MAX_CHARS` and the
  other options
- [Permissions & Safety](permissions.md) — what the agent may do with the instructions it reads
- [Workspace Safety](workspace-safety.md) — write confinement and backups
- [File Context Management](context.md) — `@file` references and `/add` for ad-hoc files
- [Chat Sessions & Resume](sessions.md) — the other per-project behaviour
