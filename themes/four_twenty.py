from .base import Theme, _theme_walk, _rgb


class FourTwentyTheme(Theme):
    """Cannabis greens and purples rolling in a slow haze."""
    name = "420"

    def apply(self, text: str, frame: int) -> str:
        def color(col, row):
            p = (col * 3 + row * 6 + frame) % 80
            if p < 50:
                g = 130 + int(p * 2.5)
                return _rgb(25, g, 45)
            else:
                v = 80 + int((p - 50) * 3.5)
                return _rgb(v, 10, v + 55)
        return _theme_walk(text, color)


THEME = FourTwentyTheme()
