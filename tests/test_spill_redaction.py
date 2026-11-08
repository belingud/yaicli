"""Tests for v0.22 K20: tool-output spill files are redacted, the model view is not.

``truncate_tool_output`` still returns the raw head/tail window to the model (the
in-memory result is untouched), but the full output written to ``TOOL_OUTPUT_DIR``
has known secret shapes replaced by ``[redacted]`` while ``REDACT_SECRETS`` is on.
"""

import os
import re
from pathlib import Path

import pytest

from yaicli.config import cfg
from yaicli.tools import limits as limits_module
from yaicli.tools.limits import truncate_tool_output

def _fake(*parts: str) -> str:
    """Assemble a fake credential-shaped value from parts (see test_redaction.py).

    No complete secret-shaped literal may live in the repository: GitHub push
    protection rejects pushes whose commits contain provider token formats.
    """
    return "".join(parts)


SECRET = _fake("sk-", "live-", "DEADBEEF0123456789")
BEARER = _fake("Bearer ", "abcdefghijklmnop")
AWS_KEY_ID = _fake("AKIA", "IOSFODNN7EXAMPLE")
PEM_FRAGMENT = _fake(
    "-----BEGIN ",
    "RSA PRIVATE KEY----- MIIEow",
    "IBAAKCAQEA1234 ",
    "-----END ",
    "RSA PRIVATE KEY-----",
)
_MARKER_RE = re.compile(r"full output saved to (.*?); use fs_read_file")


@pytest.fixture
def spill_config(tmp_path, monkeypatch):
    """Point tool-output spills at a temp dir and force a small cap."""
    monkeypatch.setitem(limits_module.cfg, "TOOL_OUTPUT_DIR", str(tmp_path / "tool-outputs"))
    monkeypatch.setitem(limits_module.cfg, "TOOL_OUTPUT_MAX_CHARS", 32000)
    monkeypatch.setitem(limits_module.cfg, "TOOL_DISPLAY_MAX_LINES", 15)
    return tmp_path


@pytest.fixture
def redaction_on(monkeypatch):
    monkeypatch.setitem(cfg, "REDACT_SECRETS", True)


@pytest.fixture
def redaction_off(monkeypatch):
    monkeypatch.setitem(cfg, "REDACT_SECRETS", False)


def _spilled_text(model_result: str) -> str:
    """Parse the spill path out of the truncation marker and read the file."""
    match = _MARKER_RE.search(model_result)
    assert match is not None, f"no spill marker in {model_result[:200]!r}"
    return Path(match.group(1)).read_text(encoding="utf-8")


def _spilled_path(model_result: str) -> Path:
    match = _MARKER_RE.search(model_result)
    assert match is not None
    return Path(match.group(1))


def _big_payload(header: str, filler: str = "A") -> str:
    """A large output whose first line contains ``header`` (so it is in the head)."""
    return f"{header}\n" + filler * 100_000


class TestSpillFileRedaction:
    def test_spill_file_is_redacted_but_model_text_keeps_the_secret(self, spill_config, redaction_on):
        payload = _big_payload(f"API_KEY={SECRET}")

        result = truncate_tool_output(payload, "execute_shell_command")

        # The model-visible result is the raw text: the secret is in its head window.
        assert SECRET in result
        # ... the copy that hits the disk is redacted.
        spilled = _spilled_text(result)
        assert SECRET not in spilled
        assert "[redacted]" in spilled
        assert spilled.startswith("API_KEY=[redacted]")

    def test_other_secret_shapes_are_redacted_in_the_spill_file(self, spill_config, redaction_on):
        header = f"Authorization: {BEARER} | {AWS_KEY_ID} | {PEM_FRAGMENT}"
        result = truncate_tool_output(_big_payload(header), "execute_shell_command")

        assert "abcdefghijklmnop" in result  # model still sees reality
        spilled = _spilled_text(result)
        assert "abcdefghijklmnop" not in spilled
        assert AWS_KEY_ID not in spilled
        assert "MIIEow" + "IBAAKCAQEA1234" not in spilled
        assert "[redacted]" in spilled

    def test_spill_file_stays_private(self, spill_config, redaction_on):
        result = truncate_tool_output(_big_payload(f"API_KEY={SECRET}"), "execute_shell_command")
        spill_path = _spilled_path(result)
        assert spill_path.exists()
        if os.name != "posix":  # pragma: no cover - Windows chmod semantics differ
            return
        assert (spill_path.stat().st_mode & 0o777) == 0o600

    def test_redaction_off_writes_the_raw_spill_file(self, spill_config, redaction_off):
        payload = _big_payload(f"API_KEY={SECRET}")

        result = truncate_tool_output(payload, "execute_shell_command")

        spilled = _spilled_text(result)
        assert SECRET in spilled
        assert f"API_KEY={SECRET}" in spilled
        assert "[redacted]" not in spilled

    def test_redaction_failure_never_breaks_spilling(self, spill_config, redaction_on, monkeypatch):
        payload = _big_payload("plain output", filler="B")

        def _boom(text):
            raise RuntimeError("redaction bug")

        monkeypatch.setattr(limits_module, "redact_text", _boom)

        result = truncate_tool_output(payload, "execute_shell_command")

        # The spill still happened, with the raw text (spilling wins over redaction).
        spilled = _spilled_text(result)
        assert spilled == payload
        assert "full output saved to" in result

    def test_short_output_never_spills(self, spill_config, redaction_on):
        small = f"API_KEY={SECRET}"
        assert truncate_tool_output(small, "execute_shell_command") == small
