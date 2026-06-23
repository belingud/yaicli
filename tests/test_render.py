"""Tests for yaicli.render: JustifyMarkdown default justify and plain_formatter."""

from unittest.mock import patch

from yaicli.render import JustifyMarkdown, plain_formatter


def test_justify_markdown_uses_config_default():
    """When no justify is passed, JustifyMarkdown falls back to the configured value."""
    with patch("yaicli.render.cfg", {"JUSTIFY": "left"}):
        md = JustifyMarkdown("# Title")
    assert md.justify == "left"


def test_justify_markdown_respects_explicit_justify():
    """An explicit justify argument overrides the configured default."""
    with patch("yaicli.render.cfg", {"JUSTIFY": "left"}):
        md = JustifyMarkdown("# Title", justify="center")
    assert md.justify == "center"


def test_plain_formatter_returns_text_unchanged():
    """plain_formatter returns its input verbatim, ignoring extra kwargs."""
    assert plain_formatter("hello world") == "hello world"
    assert plain_formatter("x", code_theme="monokai") == "x"
