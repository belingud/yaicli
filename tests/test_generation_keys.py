"""Tests for the generation-time Ctrl+O key watcher (pipe-based, no real TTY)."""

import os
import time

import pytest

from yaicli.generation_keys import GenerationKeyWatcher


def wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def pipe_fd():
    read_fd, write_fd = os.pipe()
    try:
        yield read_fd, write_fd
    finally:
        for fd in (read_fd, write_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def started_watcher(read_fd):
    watcher = GenerationKeyWatcher(fd=read_fd, tty_check=lambda _fd: True)
    assert watcher.start() is True
    return watcher


class TestStartStop:
    def test_non_tty_is_not_watched(self, pipe_fd):
        read_fd, _ = pipe_fd
        watcher = GenerationKeyWatcher(fd=read_fd, tty_check=lambda _fd: False)
        assert watcher.start() is False
        assert watcher.stop() == ""

    def test_stop_without_start(self):
        assert GenerationKeyWatcher(tty_check=lambda _fd: False).stop() == ""

    def test_start_is_idempotent(self, pipe_fd):
        read_fd, _ = pipe_fd
        watcher = started_watcher(read_fd)
        assert watcher.start() is True
        watcher.stop()

    def test_stop_is_idempotent(self, pipe_fd):
        read_fd, _ = pipe_fd
        watcher = started_watcher(read_fd)
        assert watcher.stop() == ""
        assert watcher.stop() == ""


class TestViewerRequest:
    def test_ctrl_o_sets_request_once(self, pipe_fd):
        read_fd, write_fd = pipe_fd
        watcher = started_watcher(read_fd)
        os.write(write_fd, b"\x0f")
        assert wait_for(watcher.take_viewer_request) is True
        assert watcher.take_viewer_request() is False
        watcher.stop()

    def test_other_keys_do_not_request_viewer(self, pipe_fd):
        read_fd, write_fd = pipe_fd
        watcher = started_watcher(read_fd)
        os.write(write_fd, b"abc")
        time.sleep(0.3)
        assert watcher.take_viewer_request() is False
        watcher.stop()


class TestPendingText:
    def test_typed_text_is_returned_on_stop(self, pipe_fd):
        read_fd, write_fd = pipe_fd
        watcher = started_watcher(read_fd)
        os.write(write_fd, b"hello world")
        time.sleep(0.3)
        assert watcher.stop() == "hello world"

    def test_ansi_escape_sequences_are_filtered(self, pipe_fd):
        read_fd, write_fd = pipe_fd
        watcher = started_watcher(read_fd)
        os.write(write_fd, b"ab\x1b[Ac")
        time.sleep(0.3)
        assert watcher.stop() == "abc"

    def test_backspace_edits_pending_text(self, pipe_fd):
        read_fd, write_fd = pipe_fd
        watcher = started_watcher(read_fd)
        os.write(write_fd, b"abc\x7f")
        time.sleep(0.3)
        assert watcher.stop() == "ab"

    def test_ctrl_o_bytes_are_not_part_of_pending_text(self, pipe_fd):
        read_fd, write_fd = pipe_fd
        watcher = started_watcher(read_fd)
        os.write(write_fd, b"a\x0fb")
        time.sleep(0.3)
        assert watcher.take_viewer_request() is True
        assert watcher.stop() == "ab"


class TestPauseResume:
    def test_pause_then_resume_keeps_reading(self, pipe_fd):
        read_fd, write_fd = pipe_fd
        watcher = started_watcher(read_fd)
        watcher.pause()
        os.write(write_fd, b"queued")
        time.sleep(0.3)
        watcher.resume()
        time.sleep(0.3)
        assert watcher.stop() == "queued"

    def test_pause_is_idempotent(self, pipe_fd):
        read_fd, _ = pipe_fd
        watcher = started_watcher(read_fd)
        watcher.pause()
        watcher.pause()
        watcher.resume()
        watcher.resume()
        watcher.stop()


class TestExtendedCtrlOEncodings:
    def test_csi_u_ctrl_o_requests_viewer(self, pipe_fd):
        read_fd, write_fd = pipe_fd
        watcher = started_watcher(read_fd)
        os.write(write_fd, b"\x1b[111;5u")  # kitty CSI-u encoding of Ctrl+O
        assert wait_for(watcher.take_viewer_request) is True
        assert watcher.stop().strip() == ""

    def test_modify_other_keys_ctrl_o_requests_viewer(self, pipe_fd):
        read_fd, write_fd = pipe_fd
        watcher = started_watcher(read_fd)
        os.write(write_fd, b"\x1b[27;5;111~")  # xterm modifyOtherKeys encoding
        assert wait_for(watcher.take_viewer_request) is True
        watcher.stop()


class TestOutputControlKeys:
    """macOS keeps VDISCARD (^O) active in cbreak mode; the watcher must disable it."""

    def _attrs(self):
        import yaicli.generation_keys as gk

        cc = [b"\x00"] * 32
        cc[gk.termios.VDISCARD] = b"\x0f"
        return [[], [], [], gk.termios.IXON | gk.termios.ICRNL, 0, 0, cc, []]

    def test_discard_and_flow_control_are_disabled(self, monkeypatch):
        import yaicli.generation_keys as gk

        captured = {}
        base = self._attrs()

        def fake_getattr(fd):
            import copy

            return copy.deepcopy(base)

        def fake_setattr(fd, when, attrs):
            captured["attrs"] = attrs

        monkeypatch.setattr(gk.termios, "tcgetattr", fake_getattr)
        monkeypatch.setattr(gk.termios, "tcsetattr", fake_setattr)

        discard, flow = gk._disable_output_control_keys(0)
        assert discard is True
        assert flow is True
        assert captured["attrs"][6][gk.termios.VDISCARD] == gk._POSIX_VDISABLE_BYTE
        assert captured["attrs"][3] & gk.termios.IXON == 0

    def test_non_tty_returns_false(self, monkeypatch):
        import yaicli.generation_keys as gk

        def fake_getattr(fd):
            raise gk.termios.error("not a tty")

        monkeypatch.setattr(gk.termios, "tcgetattr", fake_getattr)
        assert gk._disable_output_control_keys(0) == (False, False)
