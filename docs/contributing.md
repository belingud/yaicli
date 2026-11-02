# Contributing

Contributions to YAICLI are welcome! This page outlines how you can help improve the project.

## Ways to Contribute

There are several ways to contribute to YAICLI:

- **Bug Reports**: Open an issue describing the bug and how to reproduce it
- **Feature Requests**: Suggest new features or improvements
- **Code Contributions**: Submit a pull request with your changes
- **Documentation**: Help improve or translate the documentation

## Development Setup

### Prerequisites

- Python 3.10 or higher
- uv, the Python project manager (https://github.com/astral-sh/uv)
- Git
- A GitHub account

### Setting Up Your Development Environment

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/yaicli.git
   cd yaicli
   ```
3. Create a virtual environment and activate it:
   ```bash
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
4. Install dependencies for development (dev tools, docs tooling and all provider extras):
   ```bash
   uv sync --all-groups --all-extras
   ```

## Development Guidelines

### Code Style

YAICLI follows these style guidelines:

- Use [Ruff](https://github.com/astral-sh/ruff) for code formatting
- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guidelines
- Write docstrings for all public functions, classes, and methods

### Testing

Before submitting a PR, make sure to run the tests and the linter:

```bash
uv run pytest
uv run ruff check yaicli tests
```

### Pull Request Process

1. Create a new branch for your feature or bugfix
2. Make your changes
3. Run the tests to ensure everything works
4. Update the documentation if necessary
5. Submit a pull request describing your changes

### Adding a New Provider

To add a new LLM provider to YAICLI:

1. Create a new file in `yaicli/llms/providers/` named after your provider (e.g., `my_provider.py`)
2. Implement the provider class following the interface pattern of existing providers
3. Register the provider in `ProviderFactory.providers_map` (`yaicli/llms/provider.py`); `yaicli/llms/providers/__init__.py` is empty. See [Add a New Provider](dev/add-provider.md) for the full walkthrough
4. Update any configuration-related code to recognize the new provider
5. Add tests for your provider in the `tests/llms/` directory

## Documentation

When contributing documentation:

1. Follow the existing structure
2. Use Markdown for all documentation files
3. Test changes locally using MkDocs (docs tooling is in the `docs` dependency group):
   ```bash
   uv run mkdocs serve
   ```

## License

By contributing to YAICLI, you agree that your contributions will be licensed under the project's [Apache License 2.0](https://github.com/belingud/yaicli/blob/master/LICENSE).
