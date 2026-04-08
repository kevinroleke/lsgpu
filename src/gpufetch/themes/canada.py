from ..ansi import RESET
from .base import Theme, _theme_walk, _rgb


class CanadaTheme(Theme):
    """Red side-stripes with a neutral centre, like the maple-leaf flag."""
    name = "canada"
    _RED = _rgb(255, 0, 28)

    def apply(self, text: str, frame: int) -> str:
        red = self._RED
        def color(col, row):
            band = (col // 10) % 4
            return red if band in (0, 3) else RESET
        return _theme_walk(text, color)


THEME = CanadaTheme()
