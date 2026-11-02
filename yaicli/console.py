import re
from typing import Any, Optional, Union

from rich.console import Console, JustifyMethod, OverflowMethod
from rich.markup import escape as _rich_escape
from rich.style import Style
from rich.text import Text

from .config import cfg
from .const import DEFAULT_JUSTIFY

_console = None

# C0/C1 control characters other than tab/newline. Model output and tool output
# must never be able to emit ANSI/OSC escape sequences into the terminal.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


class YaiConsole(Console):
    """Custom Console class that defaults to the configured justify value."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._default_justify: JustifyMethod = DEFAULT_JUSTIFY
        if "JUSTIFY" in cfg:
            self._default_justify = cfg["JUSTIFY"]

    def print(
        self,
        *objects: Any,
        sep: str = " ",
        end: str = "\n",
        style: Optional[Union[str, Style]] = None,
        justify: Optional[JustifyMethod] = None,
        overflow: Optional[OverflowMethod] = None,
        no_wrap: Optional[bool] = None,
        emoji: Optional[bool] = None,
        markup: Optional[bool] = None,
        highlight: Optional[bool] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        crop: bool = True,
        soft_wrap: Optional[bool] = None,
        new_line_start: bool = False,
    ):
        """Override the print method to default to the configured justify value."""
        if justify is None:
            justify = self._default_justify
        return super().print(
            *objects,
            sep=sep,
            end=end,
            style=style,
            justify=justify,
            overflow=overflow,
            no_wrap=no_wrap,
            emoji=emoji,
            markup=markup,
            highlight=highlight,
            width=width,
            height=height,
            crop=crop,
            soft_wrap=soft_wrap,
            new_line_start=new_line_start,
        )


def get_console() -> YaiConsole:
    """Use a singleton pattern to ensure only one instance of Console is created."""
    global _console
    if _console is None:
        _console = YaiConsole()
    return _console


def strip_control_chars(text: Any) -> str:
    """Return ``text`` as a string with C0/C1 control characters removed.

    Newlines and tabs are preserved (they are meaningful in chat output and
    command panels); everything else is dropped so untrusted model/tool output
    can not emit ANSI/OSC terminal escapes.
    """
    if text is None:
        return ""
    return _CONTROL_CHARS_RE.sub("", str(text))


def escape_markup(text: Any) -> str:
    """Escape ``text`` so Rich renders it literally inside a markup string."""
    if text is None:
        return ""
    return _rich_escape(str(text))


def safe_text(text: Any) -> str:
    """Sanitize untrusted text for interpolation into a trusted Rich markup string."""
    return escape_markup(strip_control_chars(text))


def untrusted_text(text: Any, style: Optional[Union[str, Style]] = None) -> Text:
    """Build a Text renderable from untrusted text.

    ``rich.text.Text`` never interprets Rich markup, so the content is always
    rendered literally. Control characters are stripped so model/tool output can
    not emit ANSI/OSC sequences.
    """
    return Text(strip_control_chars(text), style=style or "")


def print_untrusted(console: Any, text: Any, **kwargs: Any) -> None:
    """Print untrusted text literally, with control characters stripped.

    Falls back to ``console.print(..., markup=False)`` so plain strings and
    Text renderables both stay literal; extra keyword arguments (``style``,
    ``end``, ...) are forwarded.
    """
    kwargs.setdefault("markup", False)
    console.print(strip_control_chars(text), **kwargs)
