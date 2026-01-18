# File Context Management

YAICLI provides powerful file context management capabilities that allow you to include files and directories in your AI conversations. This helps the AI understand your codebase, configuration files, documentation, and any other relevant context.

## Overview

There are two ways to include files in your conversations:

1. **Persistent Context (`/add`)**: Add files/directories that stay in context for the entire session
2. **Temporary References (`@`)**: Reference files on-the-fly for a single message

## Persistent Context

Use the `/add` command to add files or directories to your session context. These items remain available throughout your conversation until you remove them.

### Adding Files

```bash
# Add a single file
/add src/main.py
# Output: Added file to context: /path/to/src/main.py

# Add a directory (scans recursively)
/add tests/
# Output: Added directory to context: /path/to/tests/

# Add multiple files
/add config.yaml README.md
```

### Viewing Context

```bash
/context list
# or
/ctx list
```

Output example:
```
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Type   ┃ Path                          ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ FILE   │ src/main.py                   │
│ FILE   │ config.yaml                   │
│ DIR    │ tests/                        │
└────────┴───────────────────────────────┘
```

### Removing Context Items

```bash
# Remove by exact path
/context remove /path/to/src/main.py

# Remove by filename (partial match)
/context remove main.py

# Clear all context
/context clear
```

### Complete Command Reference

| Command | Alias | Description |
|---------|-------|-------------|
| `/add <path>` | - | Add file/directory to context |
| `/context list` | `/ctx list` | List all context items |
| `/context clear` | `/ctx clear` | Remove all items |
| `/context add <path>` | - | Same as `/add` |
| `/context remove <path>` | `/ctx rm` | Remove specific item |

## Temporary @ References

For quick, one-time file inclusion, use the `@` symbol directly in your messages.

### Basic Usage

```bash
# Reference a single file
@README.md What is this project about?

# Reference multiple files
@src/main.py @config.yaml Explain the architecture

# The AI sees the file contents and responds based on them
```

### Paths with Spaces

Use quotes for filenames or paths containing spaces:

```bash
@"my document.txt" Summarize this

@'path with spaces/file.md' What does this do?
```

### Auto-completion

Type `@` and press `Tab` to browse files:

```bash
💬 > @src/[Tab]
# Shows file browser:
# src/main.py
# src/utils.py
# src/config/
```

Use arrow keys to navigate and select files.

## How Context Works

### File Reading Process

1. **File Detection**: YAICLI checks if the path exists
2. **Type Check**: Determines if it's a file or directory
3. **Content Reading**:
   - Files: Read entire content
   - Directories: Recursively scan (2 levels deep by default)
4. **Formatting**: Content is formatted as Markdown code blocks
5. **Submission**: Formatted content is sent to the AI as a system message

### Smart File Handling

**Binary Files**: Automatically skipped
- Images: `.png`, `.jpg`, `.jpeg`, `.gif`, `.ico`
- Archives: `.zip`, `.tar`, `.gz`
- Compiled: `.pyc`, `.pdf`

**Size Limits**: Files larger than 1MB are skipped

**Encoding**: UTF-8 with error replacement for non-UTF-8 characters

### Directory Scanning

When you add a directory, YAICLI:

1. Scans files recursively (default: 2 levels deep)
2. Skips hidden files (starting with `.`)
3. Ignores common patterns:
   - `.git/`
   - `__pycache__/`
   - `.venv/`, `venv/`
   - `node_modules/`
   - `.idea/`, `.vscode/`
   - `.DS_Store`

**Example Directory Structure:**

```
project/
├── src/
│   ├── main.py
│   └── utils/
│       ├── helpers.py
│       └── config.py
├── tests/
│   └── test_main.py
└── .git/          # Skipped
└── node_modules/  # Skipped
```

```bash
/add src/
# Includes:
# - src/main.py
# - src/utils/helpers.py
# - src/utils/config.py
```

## Use Cases

### Codebase Analysis

```bash
# Add entire source directory
/add src/

💬 > Explain the architecture of this codebase
# AI now has full visibility into src/
```

### Configuration Review

```bash
# Multiple config files
/add .env
/add docker-compose.yml
/add config.yaml

💬 > Are there any security issues in this configuration?
# AI reviews all config files together
```

### Debugging

```bash
# Add error log and source file
/add error.log
/add src/handler.py

💬 > Why is this error happening in handler.py?
# AI correlates the error with source code
```

### Documentation

```bash
# Quick reference for documentation
@api-docs.md @docs/api-guide.md Implement this endpoint

# vs persistent context for long sessions
/add docs/

💬 > Help me implement user authentication
💬 > Now add password reset
💬 > Finally, add email verification
# docs/ stays in context for entire session
```

## Best Practices

### When to Use `/add` (Persistent)

- **Working on a specific feature**: Add relevant source files
- **Code reviews**: Include all files being reviewed
- **Debugging sessions**: Keep error logs and source files available
- **Documentation**: Reference docs while implementing features
- **Multi-step tasks**: Avoid repeating file references

### When to Use `@` (Temporary)

- **Quick questions**: One-time file checks
- **Comparing files**: `@file1.json @file2.json`
- **Minimal context**: Don't clutter the conversation
- **Ad-hoc analysis**: Quick look at a file

### Tips

1. **Be Specific**: Add only relevant files to avoid context bloat
2. **Clean Up**: Remove items with `/context remove` when done
3. **Check Context**: Use `/context list` to see what's active
4. **Use Quoted Paths**: For files with spaces, use `@"path"`
5. **Combine Both**: Use `/add` for core files, `@` for temporary references

### Example Workflow

```bash
# Start a coding session
ai --chat

# Add core source files
/add src/
/add config.yaml

💬 > Add a new user registration endpoint

# Add a specific test file temporarily
@tests/test_auth.py Write tests for this

# Reference documentation once
@docs/api-spec.md Follow these specs

# Context still has src/ and config.yaml
💬 > Update the password validation

# Clean up when done
/context clear
```

## Limitations

- **File Size**: Files > 1MB are skipped
- **Binary Files**: Automatically filtered out
- **Directory Depth**: Limited to 2 levels by default
- **Context Window**: Total content limited by your model's context window
- **Session Scope**: Context doesn't persist across different `ai` invocations

## Troubleshooting

### File Not Found

```bash
💬 > /add nonexistent.py
Error: Path does not exist: /path/to/nonexistent.py
```

**Solution**: Use relative paths from current directory or absolute paths

### Binary File Warning

```bash
💬 > @image.png
Warning: Cannot include @image.png: [Binary file omitted]
```

**Expected behavior**: Binary files are automatically skipped

### Too Large Warning

```bash
💬 > @large-file.log
Warning: Cannot include @large-file.log: [File too large: 2097152 bytes - omitted]
```

**Solution**: Split the file or extract relevant portions

### Context Too Long

If the AI stops responding or behaves unexpectedly, your context may be too large.

**Solution**:
```bash
/context list
/context remove <unnecessary-files>
```

## Related Features

- **Function Calling**: Use functions to interact with the file system
- **Pipe Input**: `cat file.txt | ai "analyze this"`
- **MCP Tools**: External tools for file system operations
- **History Management**: Save and restore conversations with context

## See Also

- [Command Reference](commands.md)
- [Interactive Mode](interactive.md)
- [Configuration](configuration.md)
