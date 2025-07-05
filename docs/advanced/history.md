# Conversation & History Management

YAICLI provides robust conversation history management features to help you maintain context and revisit past interactions. This page explains how the history system works and how to manage your chat history.

## Command History

YAICLI maintains a history of your commands and interactions, allowing you to:
- Search through previous commands
- Reuse past queries
- Keep track of your AI conversations

### History Storage

By default, command history is stored in:
- Linux/macOS: `~/.yaicli_history`
- Windows: `%USERPROFILE%\.yaicli_history`

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

In interactive mode, use the `/his` command to view your command history:

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

Chat history is stored in:
- Default: A temporary directory specific to your system
- Configurable through `CHAT_HISTORY_DIR` setting

```ini
[core]
CHAT_HISTORY_DIR=/path/to/custom/directory
MAX_SAVED_CHATS=20
```

### Listing Saved Chats

To list your saved chat sessions:

```bash
# From command line
ai --list-chats

# From interactive mode
💬 > /list
```

This displays a numbered list of saved chats with their creation dates.

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

### History File Format

The chat history files are stored as JSON with this structure:

```json
{
  "title": "Chat Title",
  "created_at": "2024-06-01T12:00:00Z",
  "updated_at": "2024-06-01T13:30:00Z",
  "messages": [
    {
      "role": "user",
      "content": "User message here"
    },
    {
      "role": "assistant",
      "content": "Assistant response here"
    }
  ]
}
```

### Manual History Editing

You can manually edit the history files:

1. Navigate to your chat history directory
2. Open the JSON file with any text editor
3. Modify as needed (keeping the JSON structure intact)
4. Save the file

### History Migration

When upgrading YAICLI, history files are automatically migrated to newer formats if needed. If you're experiencing issues with history after an upgrade, try:

```bash
# Backup your history
cp ~/.yaicli_history ~/.yaicli_history.bak

# Remove the history file to create a fresh one
rm ~/.yaicli_history
```

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

- Learn about [streaming output features](sse.md)
- Explore [debugging and logging](debugging.md)
- Check out [prompt templates](prompts.md)
