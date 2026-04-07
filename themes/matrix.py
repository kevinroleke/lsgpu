from .base import Theme, _theme_walk, _rgb


class MatrixTheme(Theme):
    """Digital-rain green; bright columns sweep across each frame."""
    name = "matrix"
    _STRIDE = 19

    def apply(self, text: str, frame: int) -> str:
        bright_base = (frame // 2) * 3
        stride = self._STRIDE
        def color(col, row):
            if ((col - bright_base) % stride) < 2:
                return "\033[1m" + _rgb(0, 255, 65)
            return _rgb(0, 185, 45)
        return _theme_walk(text, color)


THEME = MatrixTheme()
