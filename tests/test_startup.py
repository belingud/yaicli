"""K08 startup boundary tests: lazy imports and lazy LLM-client construction."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from yaicli.cli import CLI

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_python(code: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


class TestImportBoundary:
    def test_entry_import_does_not_load_cli_stack(self):
        """--help/--version must not import the CLI, prompt_toolkit or provider SDKs."""
        proc = _run_python(
            "import sys, yaicli.entry\n"
            "bad = [name for name in ('prompt_toolkit', 'yaicli.cli', 'yaicli.llms') if name in sys.modules]\n"
            "print(','.join(bad) or 'clean')\n"
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "clean", proc.stdout

    def test_cli_construction_does_not_import_prompt_toolkit(self):
        """K08: building a CLI (headless or TTY) defers prompt_toolkit until the REPL."""
        proc = _run_python(
            "import sys\n"
            "from unittest.mock import MagicMock\n"
            "from yaicli.cli import CLI\n"
            "CLI(client=MagicMock())\n"
            "print('prompt_toolkit' in sys.modules)\n"
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "False", proc.stdout


class TestLazyClient:
    def test_client_constructed_on_first_access_only(self):
        sentinel = MagicMock(name="client")
        with (
            patch.object(CLI, "_stdin_is_tty", return_value=False),
            patch.object(CLI, "_stdout_is_tty", return_value=False),
            patch.object(CLI, "_create_client", return_value=sentinel) as create,
        ):
            cli = CLI()
            create.assert_not_called()
            assert cli.client is sentinel
            create.assert_called_once()
            assert cli.client is sentinel
            create.assert_called_once()

    def test_client_setter_injects_ready_client(self):
        injected = MagicMock(name="injected-client")
        with (
            patch.object(CLI, "_stdin_is_tty", return_value=False),
            patch.object(CLI, "_stdout_is_tty", return_value=False),
            patch.object(CLI, "_create_client") as create,
        ):
            cli = CLI()
            cli.client = injected

        assert cli.client is injected
        create.assert_not_called()
