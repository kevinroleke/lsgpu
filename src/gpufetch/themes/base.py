"""Base Theme class and shared helpers for theme authors."""

from ..ansi import _ANSI_RE, RESET


def _rgb(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


def _theme_walk(text: str, color_fn) -> str:
    """
    Walk rendered text, strip colour codes (preserve bold/dim/reverse),
    and re-colour every non-space character using color_fn(col, row) -> str.
    """
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
                result.append(color_fn(col, row))
            result.append(ch)
            col += 1
            i += 1
    return "".join(result)


class Theme:
    """
    Base display theme.

    To add a new theme:
      1. Create themes/<yourname>.py
      2. Subclass Theme, set name, override apply()
      3. Set module-level  THEME = YourTheme()
      4. Done — it's auto-discovered on next run.
    """
    name: str = "default"

    def apply(self, text: str, frame: int) -> str:
        """Transform rendered text. Default: pass-through."""
        return text
