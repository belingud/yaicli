"""Tiny console entry point for the ``ai`` / ``yaicli`` commands.

``--version`` is answered here *before* importing the rest of the package, so
the command stays fast (~40ms instead of ~500ms) and produces zero filesystem
writes: it still works on a read-only HOME, in containers and in CI. Every
other invocation is delegated to :mod:`yaicli.entry` exactly as before.

This module deliberately imports only ``sys`` at import time; the version comes
from the installed distribution metadata (``importlib.metadata``) which is
imported lazily inside the version handler.
"""

import sys

#: Flags that only need the version string (``-v`` is the historical shortcut).
_VERSION_FLAGS = ("-v", "--version")


def _version_string() -> str:
    """Return the package version without scanning installed distribution metadata.

    The static constant in ``yaicli/__init__.py`` is the primary source (it is
    kept in sync by bump2version) and costs a single tiny package import;
    ``importlib.metadata`` (100ms+ on some filesystems) is only a fallback for
    unusual installs where the package module cannot be imported.
    """
    try:
        from yaicli import __version__

        if __version__:
            return str(__version__)
    except Exception:  # pragma: no cover - broken/partial install
        pass

    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("yaicli")
    except PackageNotFoundError:  # pragma: no cover - running from an unpacked sdist
        return "unknown"


def _print_version() -> None:
    """Print ``yaicli <version>`` without importing the CLI stack."""
    package_version = _version_string()
    if sys.stdout is None:  # closed stdout (``ai --version >&-``): nothing to print
        return
    sys.stdout.write(f"yaicli {package_version}\n")
    # Flush here so a closed pipe raises BrokenPipeError inside main()'s handler
    # instead of failing during interpreter shutdown (which would break ``| head``).
    sys.stdout.flush()


def _silence_broken_pipe() -> None:
    """Point stdout at /dev/null so interpreter shutdown does not re-raise EPIPE."""
    import os

    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except (OSError, ValueError, AttributeError):  # pragma: no cover - exotic platforms
        pass


def main(argv=None) -> None:
    """Entry point used by the ``ai``/``yaicli`` console scripts and ``-m yaicli``."""
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        if any(arg in _VERSION_FLAGS for arg in args):
            _print_version()
            return

        # Delegate to the Typer application; this import is what pulls in the
        # config/roles/CLI stack, deliberately after the fast path above.
        from yaicli.entry import app

        app()
    except BrokenPipeError:
        # ``ai ... | head``: a closed pipe is not an error for the producer.
        _silence_broken_pipe()
