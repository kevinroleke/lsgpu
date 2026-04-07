from .base import Theme, _theme_walk, _rgb


class HalloweenTheme(Theme):
    """Spooky orange and purple with flickers of ghostly yellow."""
    name = "halloween"
    _ORANGE = _rgb(255, 102,   0)
    _PURPLE = _rgb(102,   0, 153)
    _YELLOW = _rgb(255, 230,   0)

    def apply(self, text: str, frame: int) -> str:
        orange, purple, yellow = self._ORANGE, self._PURPLE, self._YELLOW
        def color(col, row):
            p = (col * 2 + row * 3 + frame) % 14
            if p == 0:
                return yellow
            return orange if p < 7 else purple
        return _theme_walk(text, color)


THEME = HalloweenTheme()
