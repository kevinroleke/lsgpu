from .base import Theme, _theme_walk, _rgb


class ChristmasTheme(Theme):
    """Festive red and green with occasional gold sparkles."""
    name = "christmas"
    _RED   = _rgb(220,  20,  60)
    _GREEN = _rgb(0,   154,  23)
    _GOLD  = _rgb(255, 215,   0)

    def apply(self, text: str, frame: int) -> str:
        red, green, gold = self._RED, self._GREEN, self._GOLD
        def color(col, row):
            if (col + row * 3 + frame // 4) % 22 == 0:
                return gold
            return red if (col + row) % 4 < 2 else green
        return _theme_walk(text, color)


THEME = ChristmasTheme()
