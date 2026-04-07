from ansi import RESET
from .base import Theme, _theme_walk, _rgb


class AmericaTheme(Theme):
    """Red, white, and blue horizontal stripes that slowly scroll."""
    name = "america"
    _RED  = _rgb(178, 34,  52)
    _BLUE = _rgb(60,  59, 110)

    def apply(self, text: str, frame: int) -> str:
        red, blue = self._RED, self._BLUE
        shift = frame // 8
        def color(col, row):
            s = (row + shift) % 3
            if s == 0: return red
            if s == 2: return blue
            return RESET
        return _theme_walk(text, color)


THEME = AmericaTheme()
