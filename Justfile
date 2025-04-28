# Justfile for Python project management
# list of commands
help:
    @just -l

# Format code with ruff and isort
format:
    @echo "Formatting code with ruff..."
    @ruff format yaicli
    @ruff format tests
    @echo "Formatting code with isort..."
    @isort yaicli tests

# Clean build artifacts
clean:
    @echo "Cleaning build artifacts..."
    @rm -rf build/ dist/ *.egg-info/
    @echo "Cleaning cache files..."
    @find . -type d -name "__pycache__" -exec rm -rf {} +
    @echo "Cleaning test artifacts..."
    @rm -rf .pytest_cache/
    @echo "Cleaning pdm build artifacts..."
    @rm -rf .pdm_build/
    @echo "Cleaning ruff cache..."
    @rm -rf .ruff_cache/

# Run tests with pytest
test:
    @echo "Running tests..."
    @pytest

# Build package with hatch (runs clean first)
build:
    @echo "Building package..."
    @rm -rf dist/
    @uv build

# Publish package to PyPI
publish: build
    @echo "Publishing package..."
    @uv-publish

# Install package in editable mode by uv
install:
    @echo "Installing packages..."
    @uv sync

# Lock uv file and generate changelog from git log
changelog:
    @echo "Lock and Generating changelog..."
    @uv lock
    @git cliff -l --prepend CHANGELOG.md