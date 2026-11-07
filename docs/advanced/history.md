# Conversation & History Management

YAICLI provides robust conversation history management features to help you maintain context and revisit past interactions. This page explains how the history system works and how to manage your chat history.

## Command History

YAICLI maintains a history of your commands and interactions, allowing you to:
- Search through previous commands
- Reuse past queries
- Keep track of your AI conversations

### History Storage

By default, command history is stored in `$XDG_STATE_HOME/yaicli/history` when `XDG_STATE_HOME` is
set, otherwise in `~/.yaicli_history` (`%USERPROFILE%\.yaicli_history` on Windows).

Since v0.21 the history file is created with mode `0600` (and the directories created for it with
`0700`) because it contains every prompt you typed, possibly including pasted secrets; a legacy
`0644` file is repaired the next time it is appended to or trimmed.

The history file uses a simple text format with each command on a new line.

### History Size

You can configure the maximum number of history entries to retain:

```ini
[core]
MAX_HISTORY=500
```

Or using an environment variable:

```bash
export YAI_MAX_HISTORY=1000
```

### Viewing History

In interactive mode, use the `/his` command to view your chat history:

```
💬 > /his
Chat History:
1 User: What is quantum computing?
    Assistant: Quantum computing is a type of computation...
2 User: What are qubits?
    Assistant: Qubits (quantum bits) are the basic...
```

### Searching History

Use `Ctrl+R` to search through your command history:

1. Press `Ctrl+R`
2. Type part of a previous command
3. Press `Ctrl+R` again to cycle through matching results
4. Press `Enter` to select the current match

### Auto-Suggestion

YAICLI can suggest commands based on your history as you type. Enable this feature in your config:

```ini
[core]
AUTO_SUGGEST=true
```

When enabled, YAICLI will show suggestions in light gray text as you type. Press the right arrow key to accept a suggestion.

## Chat Sessions

### Chat Persistence

Chat sessions can be persistent or temporary:

- **Persistent Session**: Automatically saved with a title
- **Temporary Session**: Not saved unless explicitly requested

To start a persistent chat session:

```bash
ai --chat "Python programming"
```

To convert a temporary session to persistent:

```
💬 > /save "Python programming"
Chat saved as: Python programming
```

### Chat Storage Location

Since v0.21, saved chat sessions are isolated per project:

- Default: `~/.yaicli/sessions/<sha256(resolved working directory)[:16]>/` — one directory per
  working directory, containing JSON session files. Directories are `0700`, files `0600`.
- The store is keyed by the **working directory** (not the git root): running `ai --chat` from two
  different directories uses two stores. Use `--cwd` (or always start from the project directory) to
  keep one store.
- Override with `CHAT_HISTORY_DIR` (config file) or `YAI_CHAT_HISTORY_DIR` (environment) to keep the
  previous flat directory. A value equal to the built-in default `<tempdir>/yaicli/chats` is treated
  as unset (per-project store).
- `MAX_SAVED_CHATS` applies within the active store.

```ini
[core]
# Explicit override: keep the old flat layout in a stable directory
CHAT_HISTORY_DIR=/path/to/custom/directory
MAX_SAVED_CHATS=20
```

Each session records `model`, `provider`, `role`, `cwd`, `created_at` and `updated_at`; a resumed
session prints a one-line notice with that metadata. See
[Chat Sessions & Resume](../usage/sessions.md) for the layout, `--resume`, the `--list-chats`
caveat and how to migrate sessions saved by older releases.

### Listing Saved Chats

To list your saved chat sessions:

```bash
# From command line
ai --list-chats

# From interactive mode
💬 > /list
```

This displays a numbered list of saved chats with their creation dates, scoped to the current
project's store. (`ai --list-chats` uses the invocation directory; its option callback runs before
`--cwd` applies.)

### Loading Saved Chats

You can load saved chats in two ways:

```bash
# From command line (using the chat title)
ai --chat "Python programming"

# From interactive mode (using the chat index from /list)
💬 > /load 3
```

### Deleting Saved Chats

To delete a saved chat:

```bash
# From interactive mode
💬 > /del 3
```

This will permanently remove the selected chat session.

## Context Management

### Context Window

YAICLI automatically manages the conversation context based on:
- The model's context window limitations
- The number of messages in the current session
- The complexity and length of each message

### Clearing Context

To clear the current conversation context:

```
💬 > /clear
```

This removes all previous messages from the current session's context but does not delete saved chat history.

## Advanced History Features

### Chat File Format

Chat sessions are stored as JSON files in `CHAT_HISTORY_DIR` (see
[Configuration](../usage/configuration.md)). The current format keeps every field of a
message, so restoring a session preserves tool calls, images, and reasoning content:

```json
{
  "title": "Chat Title",
  "date": "2024-06-01T12:00:00+00:00",
  "model": "gpt-5.2",
  "provider": "openai",
  "role": "DEFAULT",
  "cwd": "/home/me/project",
  "created_at": "2024-06-01T12:00:00+00:00",
  "updated_at": "2024-06-01T12:05:00+00:00",
  "history": [
    {
      "role": "user",
      "content": "look at before.png"
    },
    {
      "role": "assistant",
      "content": "",
      "reasoning": "I should read the image first.",
      "tool_calls": [
        {
          "id": "call_1",
          "name": "fs_read_image",
          "arguments": "{\"image_paths\": [\"before.png\"]}"
        }
      ]
    },
    {
      "role": "tool",
      "content": "{\"images\": [...]}",
      "name": "fs_read_image",
      "tool_call_id": "call_1"
    },
    {
      "role": "user",
      "content": "and this one?",
      "images": [
        {
          "data": "<base64 or URL>",
          "media_type": "image/png",
          "is_url": false
        }
      ]
    }
  ]
}
```

Optional fields are written only when they are set: `name`, `tool_call_id`, `tool_calls`,
`reasoning`, and `images`. A `tool_calls` entry is `{"id", "name", "arguments"}`; an `images`
entry is `{"data", "media_type", "is_url"}`. Session metadata (`model`, `provider`, `role`, `cwd`,
`created_at`, `updated_at`) was added in v0.21; legacy files without it load normally and are
backfilled on their next save.

### Atomic Saves

Sessions are written atomically: the new JSON is written to a hidden temporary file in the
same directory (`.filename.pid.tmp`), flushed/`fsync`-ed, and then moved over the target file
with `os.replace`. Consequences:

- an interrupted or failed save never truncates or corrupts the previously saved session;
- `FileChatManager` writes the replacement file **before** deleting older sessions with the
  same title, so a failed `/save` keeps the previous version loadable;
- a failed save still raises `ChatSaveError` and is reported in the CLI.

### Compatibility and Migration

Old session files that only contain `{"role", "content"}` messages still load: missing
optional fields default to empty. New files are a superset of the legacy format, so no
explicit migration step is required — loading then saving a session rewrites it in the
current format. The same applies to `tool_calls`/`images`/`reasoning`: sessions saved by older
versions simply do not contain them.

You can still edit a session file manually. Keep the top-level `title`/`date`/`history` keys;
each message must at least have `role` and `content`, and any `tool_calls`/`images` entries must
keep the shapes shown above (a damaged entry is skipped, but tool results whose assistant
`tool_calls` were removed will make provider requests invalid).

If a session file is corrupted, fix or delete that JSON file; the other sessions are
unaffected.

### Disabling History

You can disable command history saving completely by setting:

```ini
[core]
MAX_HISTORY=0
```

## Best Practices

1. **Regular Cleaning**: Periodically review and delete unnecessary chat sessions
2. **Meaningful Titles**: Use descriptive titles for your persistent chats
3. **Context Awareness**: Clear context when switching topics within the same session
4. **Backup**: Occasionally backup your chat history directory for important conversations

## Next Steps

- Explore [debugging and logging](debugging.md)
- Check out [prompt templates](prompts.md)
