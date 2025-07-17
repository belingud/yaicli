import os
from unittest.mock import MagicMock, patch

import pytest

import yaicli.config  # Import module to patch
from yaicli.cli import CLI


# Session-scoped fixture to patch CONFIG_PATH globally for all tests
@pytest.fixture(scope="session", autouse=True)
def patched_config_path(tmp_path_factory):
    """Patches yaicli.config.CONFIG_PATH to use a session-scoped temp dir."""
    # Create a temporary directory for the session
    base_temp_dir = tmp_path_factory.mktemp("global_config")
    # Define the mock config file path within the temp dir
    config_file = base_temp_dir / ".config" / "yaicli" / "config.ini"
    # Patch the CONFIG_PATH constant in the yaicli.config module
    with patch.object(yaicli.config, "CONFIG_PATH", config_file):
        # Yield the path in case some tests need to interact with the file
        yield config_file
    # Patch is automatically reverted after yield, tmp dir is cleaned up by pytest


# Add a session-scoped fixture to set test provider and credentials
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up the test environment with mock credentials and default provider."""
    # Store original environment variables
    original_env = {}
    for key in [
        "YAI_PROVIDER",
        "YAI_API_KEY",
        "YAI_MODEL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "PROJECT_ID",
        "CLOUD_ML_REGION",
        "ANTHROPIC_BEDROCK_BASE_URL",
        "ANTHROPIC_VERTEX_BASE_URL",
        "FIREWORKS_API_KEY",
    ]:
        original_env[key] = os.environ.get(key)

    # Set test environment variables
    os.environ["YAI_PROVIDER"] = "openai"  # Use OpenAI as the test provider
    os.environ["YAI_API_KEY"] = "test_api_key"
    os.environ["YAI_MODEL"] = "gpt-3.5-turbo"

    # Add mock AWS credentials to prevent failures in Anthropic provider tests
    os.environ["AWS_ACCESS_KEY_ID"] = "test_access_key"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test_secret_key"
    os.environ["AWS_SESSION_TOKEN"] = "test_session_token"
    os.environ["AWS_REGION"] = "us-east-1"
    
    # Add mock Fireworks credentials
    os.environ["FIREWORKS_API_KEY"] = "test_fireworks_api_key"

    # Run the tests
    yield

    # Restore original environment variables
    for key, value in original_env.items():
        if value is None:
            if key in os.environ:
                del os.environ[key]
        else:
            os.environ[key] = value


@pytest.fixture(scope="function")
def cli():
    """CLI config fixture. Will use the patched CONFIG_PATH due to autouse."""
    # Since patched_config_path is autouse=True, this CLI instance
    # will use the temporary config path when calling load_config.
    app = CLI()
    return app


@pytest.fixture(scope="function")
def mock_console():
    return MagicMock()
