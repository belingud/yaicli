# CLAUDE.md

This file provides guidance when working with code in this repository.

## Project Overview

YAICLI is a CLI tool for interacting with LLMs from the terminal. It supports 30+ providers (OpenAI, Anthropic, Gemini, Ollama, etc.), multiple interaction modes (chat, shell command execution, quick query), function calling, and MCP integration.

## Common Commands

```bash
# Install dependencies (all extras for development)
uv sync --all-groups --all-extras

# Run tests
uv run pytest                      # all tests
uv run pytest tests/test_cli.py    # single file
uv run pytest -k "test_name"       # single test by name
uv run pytest --cov=yaicli         # with coverage

# Multi-version testing
tox                                # all Python versions (3.10-3.13)
tox -e py312                       # specific version
tox -e lint                        # lint only

# Linting and formatting
just format                        # format with ruff + isort
ruff check yaicli tests            # check only
ruff check --fix yaicli tests      # check and fix

# Build
uv build

# Version bump (uses bump2version)
uv run bump2version patch|minor|major
```

## Architecture

### Core Flow
```
entry.py (Typer app) → cli.py (CLI orchestrator) → llms/client.py (LLMClient)
                                                  → llms/provider.py (ProviderFactory → Provider)
```

### Key Modules

- **`yaicli/cli.py`**: Main orchestrator handling chat, exec, and temp modes. Manages roles, sessions, keybindings, and history.
- **`yaicli/llms/client.py`**: `LLMClient` coordinates provider calls, tool execution (recursive with depth limit), and streaming.
- **`yaicli/llms/provider.py`**: `Provider` ABC + `ProviderFactory`. Each provider in `providers/` extends this.
- **`yaicli/config.py`**: Layered config (env vars `YAI_*` > config file `~/.config/yaicli/config.ini` > defaults).
- **`yaicli/tools/function.py`**: Function calling schema generation and execution.
- **`yaicli/tools/mcp.py`**: MCP protocol integration (lazy-loaded).
- **`yaicli/printer.py`**: Rich text rendering for streaming responses.

### Adding a New Provider

1. Create `yaicli/llms/providers/your_provider.py`
2. Extend `Provider` ABC from `yaicli/llms/provider.py`
3. Implement required methods: `completion()`, `detect_tool_role()`, `_convert_messages()`
4. Add to provider imports in `yaicli/llms/providers/__init__.py`

### Configuration Priority

Environment variables (`YAI_*`) > Config file (`~/.config/yaicli/config.ini`) > Default values in `yaicli/const.py`

## Testing Patterns

- **Fixtures** in `tests/conftest.py`: `patched_config_path` (session-scoped), `setup_test_environment`, `cli()`, `mock_console()`
- **Mock external APIs**: Never make real API calls in tests
- **Provider tests**: Located in `tests/llms/`
- **Tool tests**: Located in `tests/tools/`

## Code Style

- Line length: 120 characters
- Import sorting: `isort` with black profile
- Linting: `ruff` with F (pyflakes) rules only
- Type hints used throughout
- Lazy imports for heavy libraries (e.g., `fastmcp`) to reduce startup time
