# Context Management Feature Implementation Plan

## Goal Description
Implement a Context Management feature that allows users to explicitly add files and directories to the AI's context. This enables "Chat with your Code" scenarios where the user can provide specific files for the AI to analyze, independent of the chat history.

## User Review Required
> [!NOTE]
> The `/context` and `/add` commands will be added. `/add` is an alias for `/context add`.

## Proposed Changes

### Core Logic
#### [NEW] [yaicli/context.py](file:///Users/vic/Documents/codes/git/yaicli/yaicli/context.py)
Create a `ContextManager` class to handle the state of the active context.
-   **Structs**: `ContextItem` (path, type).
-   **Methods**:
    -   `add(path: str)`: Add a file or directory. Validates existence.
    -   `remove(path: str)`: Remove an item from context.
    -   `clear()`: Clear all context.
    -   `list()`: Return current context items.
    -   `get_context_messages()`: Read content of files and return formatted `ChatMessage` list (e.g. system messages with file content).

### CLI Integration
#### [MODIFY] [yaicli/const.py](file:///Users/vic/Documents/codes/git/yaicli/yaicli/const.py)
-   Add `CMD_CONTEXT = ("context", "ctx")` (tuple for aliases)
-   Add `CMD_ADD = "/add"`

#### [MODIFY] [yaicli/cmd_handler.py](file:///Users/vic/Documents/codes/git/yaicli/yaicli/cmd_handler.py)
-   Update `CmdHandler` to handle `/context`, `/ctx`, and `/add`.
    -   `/add <path>` -> calls `context_manager.add()`
    -   `/context list` or `/ctx list` -> calls `context_manager.list()` and prints table.
    -   `/context clear` or `/ctx clear` -> calls `context_manager.clear()`
    -   `/context remove <path>` or `/ctx remove <path>` -> calls `context_manager.remove()`

#### [MODIFY] [yaicli/cli.py](file:///Users/vic/Documents/codes/git/yaicli/yaicli/cli.py)
-   Initialize `ContextManager` in `CLI.__init__`.
-   Update `_build_messages()` to include context messages (via `context_manager.get_context_messages()`) *after* the system prompt and *before* conversation history.

## Verification Plan

### Automated Tests
-   **[NEW] `tests/test_context.py`**:
    -   Test `ContextManager.add` with valid/invalid files.
    -   Test `ContextManager.add` with directories (and recursive adding, maybe limited depth).
    -   Test `ContextManager.get_context_messages` to ensure file content is correctly formatted.
-   **[MODIFY] `tests/test_command_handler.py`**:
    -   Test the new `/context` and `/add` commands.

### Manual Verification
1.  Start `ai --chat`.
2.  Run `/add README.md`.
    -   Verify output confirms addition.
3.  Run `/context list`.
    -   Verify `README.md` is listed.
4.  Ask "What is the title of this project?".
    -   Verify AI answers "YAICLI" (from README).
5.  Run `/context clear`.
6.  Run `/context list` (should be empty).
