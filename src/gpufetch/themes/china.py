from .base import Theme, _theme_walk, _rgb


class ChinaTheme(Theme):
    """Red field with golden columns shifting across like scattered stars."""
    name = "china"
    _RED  = _rgb(222, 41,  16)
    _GOLD = _rgb(255, 215,  0)

    def apply(self, text: str, frame: int) -> str:
        gold_col = (frame // 3) % 20
        red, gold = self._RED, self._GOLD
        def color(col, row):
            return gold if col % 20 == gold_col else red
        return _theme_walk(text, color)


THEME = ChinaTheme()
