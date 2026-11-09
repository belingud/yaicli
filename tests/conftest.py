import os
import re

# The config singleton is created at import time, so the test credentials must be
# in the environment *before* any `yaicli` module is imported. Setting them in a
# session fixture is too late: tests that build a real provider (e.g.
# tests/test_image.py through the `cli` fixture) would see an empty API_KEY in a
# fresh HOME / clean CI environment and fail with "API_KEY is required".
# ``setup_test_environment`` restores the original values at session teardown.
_TEST_ENV = {
    "YAI_PROVIDER": "openai",
    "YAI_API_KEY": "test_api_key",
    "YAI_MODEL": "gpt-3.5-turbo",
    # Mock AWS credentials so Anthropic Bedrock/Vertex provider tests do not fail
    "AWS_ACCESS_KEY_ID": "test_access_key",
    "AWS_SECRET_ACCESS_KEY": "test_secret_key",
    "AWS_SESSION_TOKEN": "test_session_token",
    "AWS_REGION": "us-east-1",
    # Extra provider credentials used by tests
    "PROJECT_ID": None,
    "CLOUD_ML_REGION": None,
    "ANTHROPIC_BEDROCK_BASE_URL": None,
    "ANTHROPIC_VERTEX_BASE_URL": None,
    "FIREWORKS_API_KEY": "test_fireworks_api_key",
}
_ORIGINAL_ENV = {key: os.environ.get(key) for key in _TEST_ENV}
os.environ.update({key: value for key, value in _TEST_ENV.items() if value is not None})

from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402


# Session-scoped fixture to patch CONFIG_PATH globally for all tests
@pytest.fixture(scope="session", autouse=True)
def patched_config_path(tmp_path_factory):
    """Patches yaicli.config.CONFIG_PATH to use a session-scoped temp dir."""
    import yaicli.config  # imported after the test env is in place

    # Create a temporary directory for the session
    base_temp_dir = tmp_path_factory.mktemp("global_config")
    # Define the mock config file path within the temp dir
    config_file = base_temp_dir / ".config" / "yaicli" / "config.ini"
    # Patch the CONFIG_PATH constant in the yaicli.config module
    with patch.object(yaicli.config, "CONFIG_PATH", config_file):
        # Yield the path in case some tests need to interact with the file
        yield config_file
    # Patch is automatically reverted after yield, tmp dir is cleaned up by pytest


# Session-scoped fixture to keep REPL history writes inside the test sandbox.
# Tests that exercise prompt_toolkit/history setup without patching the history
# path would otherwise write the real ``~/.yaicli_history``, which fails in a
# read-only HOME / CI sandbox (and is not the test's subject anyway).
@pytest.fixture(scope="session", autouse=True)
def patched_history_file(tmp_path_factory):
    """Point REPL history at a temp file for the whole test session."""
    import yaicli.cli
    import yaicli.const

    history_file = tmp_path_factory.mktemp("history") / "yaicli_history"
    with patch.object(yaicli.cli, "HISTORY_FILE", history_file):
        with patch.object(yaicli.const, "HISTORY_FILE", history_file):
            yield history_file


# Session-scoped fixture that owns the test credentials set above and restores the
# developer's environment when the session ends.
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up the test environment with mock credentials and default provider."""
    yield

    # Restore original environment variables set at import time (see _TEST_ENV).
    for key, value in _ORIGINAL_ENV.items():
        if value is None:
            if key in os.environ:
                del os.environ[key]
        else:
            os.environ[key] = value


@pytest.fixture(scope="function")
def cli():
    """CLI config fixture. Will use the patched CONFIG_PATH due to autouse."""
    from yaicli.cli import CLI

    # Since patched_config_path is autouse=True, this CLI instance
    # will use the temporary config path when calling load_config.
    app = CLI()
    return app


@pytest.fixture(scope="function")
def mock_console():
    return MagicMock()


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@pytest.fixture(scope="function")
def strip_ansi():
    """Strip ANSI SGR sequences from captured CLI output.

    Typer renders help through Rich; when ``TERM`` is unset (common on CI runners)
    Rich styles the output, which breaks substring assertions like ``"Usage: main"``
    because style codes are inserted mid-line. Tests that assert on help text use
    this helper so they behave the same in a styled and a plain terminal.
    """

    def _strip(text):
        return _ANSI_ESCAPE.sub("", text)

    return _strip

