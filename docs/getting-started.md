# Getting Started with YAICLI

YAICLI is a lightweight agent that runs in your terminal. It can read and edit files, search the
web and run shell commands through its built-in tools, and it keeps working through a task until it
is done. This page gets you from zero to a completed multi-step task in three steps.

## Agent Quick Start (3 steps)

### Step 1 — Install and give it a key

```bash
pip install yaicli

# Option A: keep the key in an environment variable (recommended for scripts/CI)
export YAI_API_KEY="sk-..."

# Option B: run a real command once (e.g. `ai "hi"`); it creates the config file, then edit it
ai "hi"
nano ~/.config/yaicli/config.ini
```

`pipx install yaicli` and `uv tool install yaicli` work the same way. Verify the install with
`ai --version` (this fast path does not read or write any config).

### Step 2 — Give the agent a real task

```bash
ai "Use your tools to find the 3 largest files in this repository and write a summary to REPORT.md"
```

The model chooses the tools it needs from the built-in set and reads each result before deciding
the next step:

| Tool group | Built-in tools |
| --- | --- |
| Filesystem (read) | `fs_get_filesystem_info`, `fs_list_directory`, `fs_read_file`, `fs_read_image`, `fs_search_files` |
| Filesystem (write) | `fs_write_file`, `fs_edit_file`, `fs_file_operations` |
| Shell (exec) | `execute_shell_command` |
| Network | `fetch_webpage`, `web_search`, `get_weather` |

You do **not** need to run `ai --install-functions` first: the definitions ship with the package
and are loaded directly. `ai --list-functions` shows all 12 built-in tools on a fresh install.

### Step 3 — Approve tool calls (the one safety rule to learn)

Before a tool runs, YAICLI asks:

```
╭─ Confirm tool call ─────────────────────────────────────╮
│ execute_shell_command({"shell_command": "du -sh ."})    │
╰─────────────────────────────────────────────────────────╯
Execute tool? [y]once, [a]session, [A]always, [n]o:
```

| Key | Meaning |
|-----|---------|
| `y` | Allow this call only |
| `a` | Allow this tool for the rest of the session |
| `A` | Always allow — saved to `tool_permissions.json` |
| `n` | Deny — the model receives the refusal and adapts |

Read-level tools are marked `read`; write, network and shell tools are classified more strictly, and
a dangerous shell command (such as `rm -r -f`, `mkfs`, `dd of=/dev/*` or `curl … | sh`) always
requires an explicit confirmation. In scripts, allow tools up front with `--allowed-tools`.

That's the whole safety model — the details (rules, audit log, headless approval) are in
[Permissions & Safety](usage/permissions.md).

## Everyday Usage

Once the agent works, the classic modes are still there:

```bash
# Quick answer (no tool loop needed)
ai "What is the capital of France?"

# Interactive chat session
ai --chat

# Generate and execute a shell command
ai --shell "Create a backup of my Documents folder"

# Generate code (Python by default)
ai --code "Write a function to sort a list"

# Pipe input
cat error.log | ai "Explain these errors"
```

## First-time Setup Details

### Configuration file

Run `ai --template` to see the full default configuration (the file itself is created on the first
real model run). The config directory is resolved in this order: `YAI_CONFIG_DIR` → `XDG_CONFIG_HOME/yaicli` → `%APPDATA%/yaicli` (Windows)
→ `~/.config/yaicli`. The file is created with mode `0600` because it may store API keys;
environment variables are the preferred way to provide keys.

YAICLI uses a layered configuration approach:

- Command-line arguments (highest priority)
- Environment variables
- Config file (`config.ini`)
- Sensible defaults (lowest priority)

See [Configuration](usage/configuration.md) for every option.

### Check the agent is ready

```bash
ai --list-functions     # should list 12 builtin tools
ai --list-providers     # should list the provider keys
ai --version            # fast, no config writes
```

If `--list-functions` lists nothing, the built-in function loader failed for every file; reinstall
the package (`pip install -U yaicli`) and open an issue with the warning printed at startup.

## Script It

The same agent runs headless — stdout carries only the result, everything else goes to stderr:

```bash
ai -p "summarize the changes in the last 5 commits" --output-format json | jq .content

# Answer-only output, safe for pipelines
ai -q -p "count the TODO comments in src/" > todos.txt

# Non-interactive tool approval for a CI job
ai -p "run the test suite and summarize failures" --allowed-tools "execute_shell_command" -y
```

See [Headless & Scripting](usage/headless.md) for the JSON schema, exit codes and signal handling.

## Next Steps

- [Headless & Scripting](usage/headless.md) — JSON output, exit codes, CI usage
- [Permissions & Safety](usage/permissions.md) — rules, risk levels, audit log
- [Context & Limits](usage/context-limits.md) — tool-output truncation, budget, `/compact`
- [Command Reference](usage/commands.md) — all options and REPL commands
- [Configuration](usage/configuration.md) — all config keys
- [LLM Providers](providers/overview.md) — provider setup matrix
- [Upgrade Notes](advanced/upgrade.md) — what changes when you update
