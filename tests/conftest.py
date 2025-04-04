import pytest

from yaicli import CLI


@pytest.fixture(scope="function")
def cli(tmp_path_factory):
    """CLI config fixture"""
    test_dir = tmp_path_factory.mktemp("test_data")
    app = CLI()
    app.CONFIG_PATH = test_dir / "config.ini"
    app.load_config()
    return app
