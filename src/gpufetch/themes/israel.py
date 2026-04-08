from ..ansi import RESET
from .base import Theme, _theme_walk, _rgb


class IsraelTheme(Theme):
    """Blue stripes top and bottom with a neutral centre, like the Israeli flag."""
    name = "israel"
    _BLUE = _rgb(0, 56, 184)

    def apply(self, text: str, frame: int) -> str:
        blue = self._BLUE
        def color(col, row):
            r = row % 9
            return blue if (r < 2 or r >= 7) else RESET
        return _theme_walk(text, color)


THEME = IsraelTheme()
