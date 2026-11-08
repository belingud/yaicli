"""YAICLI — a lightweight agent in your terminal.

The version is kept as a static constant so ``ai --version`` does not have to
scan installed distribution metadata (``importlib.metadata`` costs ~100ms+ in
some environments). ``.bumpversion.cfg`` keeps this value in sync with
``pyproject.toml`` on a release bump.
"""

__version__ = "0.21.2"
