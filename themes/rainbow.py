from ansi import _ANSI_RE, RESET
from .base import Theme


def _hsv_to_rgb(h: float) -> tuple[int, int, int]:
    h = h % 360
    x = 1.0 * (1 - abs((h / 60) % 2 - 1))
    if   h < 60:  r, g, b = 1.0, x,   0.0
    elif h < 120: r, g, b = x,   1.0, 0.0
    elif h < 180: r, g, b = 0.0, 1.0, x
    elif h < 240: r, g, b = 0.0, x,   1.0
    elif h < 300: r, g, b = x,   0.0, 1.0
    else:         r, g, b = 1.0, 0.0, x
    return int(r * 255), int(g * 255), int(b * 255)


def _esc(col: int, row: int, offset: float = 0.0) -> str:
    hue = (col * 4 + row * 8 + offset) % 360
    r, g, b = _hsv_to_rgb(hue)
    return f"\033[38;2;{r};{g};{b}m"


def rainbowize(text: str, offset: float = 0.0) -> str:
    """Re-paint every non-space character with an animated diagonal rainbow."""
    result: list[str] = []
    row = col = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\033" and i + 1 < len(text) and text[i + 1] == "[":
            m = _ANSI_RE.match(text, i)
            if m:
                inner = m.group()[2:-1]
                kept = [p for p in inner.split(";") if p in ("1", "2", "7")]
                if kept:
                    result.append(f"\033[{';'.join(kept)}m")
                i += len(m.group())
            else:
                result.append(ch)
                i += 1
        elif ch == "\n":
            result.append(RESET + "\n")
            row += 1
            col = 0
            i += 1
        else:
            if ch != " ":
                result.append(_esc(col, row, offset))
            result.append(ch)
            col += 1
            i += 1
    return "".join(result)


class RainbowTheme(Theme):
    """Animated diagonal rainbow — hue shifts 3° per frame."""
    name = "rainbow"

    def apply(self, text: str, frame: int) -> str:
        return rainbowize(text, frame * 3.0)


THEME = RainbowTheme()
