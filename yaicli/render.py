from typing import Any

from rich.markdown import Markdown

from yaicli.config import cfg


class JustifyMarkdown(Markdown):
    """Custom Markdown class that defaults to the configured justify value."""

    def __init__(self, *args, **kwargs):
        if "justify" not in kwargs:
            kwargs["justify"] = cfg["JUSTIFY"]
        super().__init__(*args, **kwargs)


def plain_formatter(text: str, **kwargs: Any) -> str:
    """Format the text for display, without Markdown formatting."""
    return text
