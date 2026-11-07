## Purpose

Define how YAICLI discovers and loads project instruction files (AGENTS.md and friends) so the agent
follows the conventions of the repository it is run in, without unbounded context cost and with an
explicit opt-out.

## Requirements

### Requirement: Project instruction files are auto-loaded from the working directory to the git root

When project context is enabled, the system SHALL discover `AGENTS.md`, `CLAUDE.md` and `.yaicli.md`
starting from the current working directory and walking up to the nearest git root (a `.git` directory
or worktree file), inclusive, never above it. When no git root is found, the walk SHALL stop at the
filesystem root. Each discovered file SHALL be read as UTF-8 text (undecodable bytes replaced) and the
resulting instructions SHALL be included in the system prompt. Directories SHALL be emitted
outermost-to-innermost so the most specific (nearest) instructions come last; within one directory the
documented order SHALL be `.yaicli.md`, then `AGENTS.md`, then `CLAUDE.md`. Files resolving to the same
real path (for example a symlinked `AGENTS.md` → `CLAUDE.md`) SHALL be loaded once.

#### Scenario: Nested working directory loads outer and inner instructions
- **WHEN** the agent runs in a nested directory below the git root and both the repository root and the nested directory contain project instruction files
- **THEN** both SHALL be included, with the nested (more specific) instructions after the root instructions

#### Scenario: Files above the git root are not loaded
- **WHEN** a project instruction file exists in a parent directory above the git root
- **THEN** it SHALL NOT be loaded

#### Scenario: No project files adds nothing to the request
- **WHEN** no project instruction file exists between the working directory and the git root
- **THEN** the system prompt SHALL be byte-identical to the prompt without project context and no extra request cost SHALL be incurred

### Requirement: Loaded project context is bounded with a visible truncation notice

The system SHALL bound the total emitted project-context block to a configurable character limit
(`PROJECT_CONTEXT_MAX_CHARS`, environment `YAI_PROJECT_CONTEXT_MAX_CHARS`, default 20000; `0` means no
cap). When content is truncated or a file is omitted because of the limit, the system SHALL print
exactly one notice to stderr naming the files/chars involved and how to raise the limit or disable the
feature, and SHALL NOT fail the turn.

#### Scenario: Oversized context is truncated with a notice
- **WHEN** the discovered project instructions exceed the configured limit
- **THEN** the emitted block SHALL be at most the limit and one stderr notice SHALL explain the truncation and the fix

#### Scenario: Unreadable file is skipped
- **WHEN** a discovered project instruction file cannot be read
- **THEN** the system SHALL warn once, skip that file, and continue with the remaining files

### Requirement: Project context can be disabled

The system SHALL expose `ENABLE_PROJECT_CONTEXT` (environment `YAI_ENABLE_PROJECT_CONTEXT`, default
enabled). When disabled, the system SHALL NOT read or discover any project instruction file and the
system prompt SHALL be identical to the pre-feature prompt.

#### Scenario: Disabled means zero filesystem reads
- **WHEN** project context is disabled
- **THEN** no project instruction file SHALL be discovered or read and no context block SHALL be added

### Requirement: Feature is safe on import and failure

Importing or configuring the feature SHALL NOT create or write any file. Filesystem or unexpected
errors during discovery/collection SHALL degrade to an empty block without crashing the CLI.

#### Scenario: Import creates no files
- **WHEN** the project-context module is imported in a fresh/read-only environment
- **THEN** no configuration or session file SHALL be created
