import pytest
from unittest.mock import patch
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


@pytest.fixture(scope="function")
def cli():
    """CLI config fixture. Will use the patched CONFIG_PATH due to autouse."""
    # Since patched_config_path is autouse=True, this CLI instance
    # will use the temporary config path when calling load_config.
    app = CLI()
    return app
