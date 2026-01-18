# Path Completion Feature Implementation Plan

## Goal Description
Add inline path completion to yaicli's chat input, triggered by `@` symbol. This allows users to quickly reference files without typing full paths, while preserving the Tab key for mode switching.

## Design Decision

### Trigger Mechanism
Use `@` as the trigger character for path completion:
- User types `@` followed by partial path: `@yaicli/c` → shows completions
- User navigates completions with **Arrow Keys** (↑/↓)
- User selects with **Enter** or **Right Arrow**
- Tab remains dedicated to mode switching

### Technical Approach
Use `prompt_toolkit`'s `Completer` API with a custom completer that:
1. Detects `@` in the input
2. Extracts the partial path after `@`
3. Provides file/directory suggestions
4. Replaces `@path` with the selected absolute path

## Proposed Changes

### Core Logic
#### [NEW] [yaicli/completer.py](file:///Users/vic/Documents/codes/git/yaicli/yaicli/completer.py)
Create a custom `PathCompleter`:
```python
from prompt_toolkit.completion import Completer, Completion
from pathlib import Path

class AtPathCompleter(Completer):
    def get_completions(self, document, complete_event):
        # Extract text before cursor
        text = document.text_before_cursor
        
        # Find last @ symbol
        at_index = text.rfind('@')
        if at_index == -1:
            return
            
        # Extract partial path after @
        partial = text[at_index + 1:]
        
        # Generate completions
        for path in get_path_suggestions(partial):
            yield Completion(
                text=str(path),
                start_position=-len(partial),
                display=format_display(path)
            )
```

### CLI Integration
#### [MODIFY] [yaicli/cli.py](file:///Users/vic/Documents/codes/git/yaicli/yaicli/cli.py)
Update `prepare_chat_loop()` to add completer:
```python
from .completer import AtPathCompleter

self.session = PromptSession(
    key_bindings=self.bindings,
    history=LimitedFileHistory(...),
    auto_suggest=...,
    completer=AtPathCompleter(),  # Add this
    complete_while_typing=False,  # Only on explicit trigger
)
```

### Alternative: Command-specific completion
For `/add` and `/context add` commands, enable automatic path completion:
```python
class ContextCommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text
        if text.startswith(('/add ', '/context add ', '/ctx add ')):
            # Extract path after command
            # Provide completions
```

## User Experience Flow

### Example 1: @ trigger
```
💬 > Analyze @yaicli/c
      ↓ (Shows dropdown)
      - yaicli/chat.py
      - yaicli/cli.py
      - yaicli/cmd_handler.py
      - yaicli/config.py
💬 > Analyze @yaicli/cli.py  (after selection)
```

### Example 2: /add command
```
💬 > /add 
      ↓ (User presses Ctrl+Space or starts typing)
      - README.md
      - pyproject.toml
      - yaicli/
```

## Considerations

### Pros of @ trigger
- Clear visual indicator
- No conflict with Tab
- Familiar pattern (like Slack, Discord)
- Can be used anywhere in the input

### Cons of @ trigger
- Need to remember to use @
- Might feel unnatural initially

### Alternative Approaches
1. **Ctrl+Space**: Universal completion trigger
   - Pro: Standard convention
   - Con: Requires user to remember shortcut
   
2. **Automatic after specific commands**: Complete after `/add `, `/context add `
   - Pro: Context-aware, intuitive
   - Con: Only works in specific contexts
   
3. **Combo approach**: Use both @ for inline and auto-complete after commands

## Recommended Solution
**Hybrid approach**:
1. **@ trigger** for inline path references in chat messages
2. **Automatic completion** after `/add`, `/context add`, `/ctx add` commands
3. **Arrow keys** (↑/↓) for navigation, **Enter** or **Tab** for selection when in completion menu
4. **Esc** to dismiss completion

This provides maximum flexibility without disrupting existing workflows.

## Implementation Stages

1. Create `yaicli/completer.py` with `AtPathCompleter`
2. Add helper functions for path suggestions (with caching for performance)
3. Integrate into `PromptSession` in `cli.py`
4. Add visual styling for completion menu (colors, icons)
5. Test edge cases (spaces in paths, relative vs absolute, hidden files)

## User Preferences (Confirmed)

1. **Path format**: Relative paths (concise) - `./file.py` or `yaicli/cli.py`
2. **Hidden files**: Show hidden files (starting with `.`)
3. **@ symbol handling**: 
   - In completion menu: Display `@yaicli/cli.py` (with @)
   - In context list: Display `yaicli/cli.py` (without @)
   - After selection: Input becomes `@yaicli/cli.py` (preserve @)
4. **Maximum depth**: No strict limit (use sensible defaults)
