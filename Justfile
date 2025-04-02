# Justfile for Python project management

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

# Run tests with pytest
test:
    @echo "Running tests..."
    @pytest tests/

# Build package with hatch (runs clean first)
build:
    @echo "Building package..."
    @rm -rf dist/
    @uv build

# Install package in editable mode
install:
    @echo "Installing packages..."
    @pip install -e .

# Generate changelog from git log
changelog:
    @echo "Generating changelog..."
    @git log --oneline --decorate --graph > CHANGELOG.md