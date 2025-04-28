from typing import Any, Optional, Union

from rich.console import Console, JustifyMethod, OverflowMethod
from rich.style import Style

from yaicli.config import cfg
from yaicli.const import DEFAULT_JUSTIFY

_console = None


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
