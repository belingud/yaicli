"""Tests for the opt-in debug log used to diagnose terminal/viewer issues."""

from yaicli.debug_log import debug_log


def test_noop_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("YAI_DEBUG_LOG", raising=False)
    debug_log("event", any=1)
    assert list(tmp_path.iterdir()) == []


def test_writes_when_path_is_set(monkeypatch, tmp_path):
    target = tmp_path / "debug.log"
    monkeypatch.setenv("YAI_DEBUG_LOG", str(target))
    debug_log("watcher.ctrl-o", entries=2)
    text = target.read_text(encoding="utf-8")
    assert "watcher.ctrl-o" in text
    assert "entries=2" in text
    assert "[MainThread]" in text


def test_never_raises_for_unwritable_path(monkeypatch, tmp_path):
    monkeypatch.setenv("YAI_DEBUG_LOG", str(tmp_path / "missing-parent" / "debug.log"))
    debug_log("event")  # parent is created; must not raise
    assert (tmp_path / "missing-parent" / "debug.log").exists()
