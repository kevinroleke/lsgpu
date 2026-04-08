"""Magic 8-ball widget for the lsgpu TUI tool."""

import random

from .ansi import (
    RESET, BOLD, DIM,
    GREEN, CYAN, YELLOW, RED,
)

# ---------------------------------------------------------------------------
# Response data
# ---------------------------------------------------------------------------

_POSITIVE = [
    "It is certain",
    "It is decidedly so",
    "Without a doubt",
    "Yes definitely",
    "You may rely on it",
    "As I see it yes",
    "Most likely",
    "Outlook good",
    "Yes",
    "Signs point to yes",
]

_NEUTRAL = [
    "Reply hazy try again",
    "Ask again later",
    "Better not tell you now",
    "Cannot predict now",
    "Concentrate and ask again",
]

_NEGATIVE = [
    "Don't count on it",
    "My reply is no",
    "My sources say no",
    "Outlook not so good",
    "Very doubtful",
]

_CATEGORY_COLOR = {
    "positive": GREEN,
    "neutral":  YELLOW,
    "negative": RED,
}


def random_response() -> tuple[str, str]:
    """Return a (response_text, category) tuple chosen randomly."""
    all_entries = (
        [(t, "positive") for t in _POSITIVE]
        + [(t, "neutral")  for t in _NEUTRAL]
        + [(t, "negative") for t in _NEGATIVE]
    )
    text, category = random.choice(all_entries)
    return text, category


# ---------------------------------------------------------------------------
# ASCII art lines (plain, no ANSI)
# ---------------------------------------------------------------------------

_ART_LINES = [
    "    ___    ",
    "  /     \\  ",
    " |   8   | ",
    "  \\ ___ /  ",
]


def _art_lines_colored() -> list[str]:
    """Return art lines with CYAN color applied."""
    return [f"{CYAN}{line}{RESET}" for line in _ART_LINES]


# ---------------------------------------------------------------------------
# Box-drawing helpers
# ---------------------------------------------------------------------------

def _top(width: int, colour: str) -> str:
    return f"{colour}╔{'═' * (width - 2)}╗{RESET}"


def _sep(width: int, colour: str) -> str:
    return f"{colour}╠{'═' * (width - 2)}╣{RESET}"


def _bot(width: int, colour: str) -> str:
    return f"{colour}╚{'═' * (width - 2)}╝{RESET}"


def _row(plain: str, colored: str, width: int, colour: str) -> str:
    """One content row padded to fit inside the box."""
    inner = width - 2
    pad = max(0, inner - len(plain))
    body = colored if colored else plain
    return f"{colour}║{RESET}{body}{' ' * pad}{colour}║{RESET}"


def _center_row(plain: str, colored: str, width: int, colour: str) -> str:
    """Centered content row."""
    inner = width - 2
    total_pad = max(0, inner - len(plain))
    left_pad  = total_pad // 2
    right_pad = total_pad - left_pad
    body = colored if colored else plain
    return f"{colour}║{RESET}{' ' * left_pad}{body}{' ' * right_pad}{colour}║{RESET}"


def _blank_row(width: int, colour: str) -> str:
    inner = width - 2
    return f"{colour}║{RESET}{' ' * inner}{colour}║{RESET}"


# ---------------------------------------------------------------------------
# Widget (sidebar panel)
# ---------------------------------------------------------------------------

def render_eightball_widget(response, term_cols: int) -> str:
    """
    Render a Magic 8-ball box widget.

    Parameters
    ----------
    response  : None  |  tuple[str, str]
        None  → not yet asked; show shake prompt.
        (text, category) → result from random_response().
    term_cols : int
        Current terminal width.

    Returns
    -------
    str
        Multi-line string ending with '\\n'.
    """
    width = min(50, max(36, term_cols - 2))
    colour = CYAN
    lines: list[str] = []

    # Top border
    lines.append(_top(width, colour))

    # Header
    header_plain   = " \u2726 Magic 8-Ball"
    header_colored = f" {BOLD}{CYAN}\u2726 Magic 8-Ball{RESET}"
    lines.append(_row(header_plain, header_colored, width, colour))

    # Separator
    lines.append(_sep(width, colour))

    # ASCII art
    lines.append(_blank_row(width, colour))
    for art_plain, art_colored in zip(_ART_LINES, _art_lines_colored()):
        lines.append(_center_row(art_plain.rstrip(), art_colored.rstrip(), width, colour))
    lines.append(_blank_row(width, colour))

    # Separator
    lines.append(_sep(width, colour))

    # Response area
    lines.append(_blank_row(width, colour))
    if response is None:
        prompt_plain   = "  Ask with /8ball <question>"
        prompt_colored = f"  {DIM}Ask with /8ball <question>{RESET}"
        lines.append(_row(prompt_plain, prompt_colored, width, colour))
    else:
        text, category = response
        cat_color = _CATEGORY_COLOR.get(category, RESET)
        # Response text centered
        resp_colored = f"{BOLD}{cat_color}{text}{RESET}"
        lines.append(_center_row(text, resp_colored, width, colour))
        # Category indicator
        cat_plain   = f"[ {category.upper()} ]"
        cat_colored = f"{DIM}{cat_color}[ {category.upper()} ]{RESET}"
        lines.append(_center_row(cat_plain, cat_colored, width, colour))
    lines.append(_blank_row(width, colour))

    # Bottom border
    lines.append(_bot(width, colour))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Overlay (full-screen centered popup)
# ---------------------------------------------------------------------------

def render_eightball_overlay(
    question: str,
    response: tuple[str, str],
    term_cols: int,
    term_lines: int,
) -> str:
    """
    Render a centered overlay using cursor-positioning escape sequences.

    Parameters
    ----------
    question   : str                 The user's question.
    response   : tuple[str, str]     (text, category) from random_response().
    term_cols  : int                 Terminal width in columns.
    term_lines : int                 Terminal height in lines.

    Returns
    -------
    str
        Escape-sequence string that draws the overlay when printed.
        No trailing newline.
    """
    text, category = response
    cat_color = _CATEGORY_COLOR.get(category, RESET)

    width  = min(50, term_cols - 4)
    inner  = width - 2
    colour = CYAN

    # ---- Build the logical rows of the overlay box -------------------------

    def go(r: int, c: int) -> str:
        return f"\033[{r};{c}H"

    def overlay_top() -> str:
        return f"{colour}╔{'═' * inner}╗{RESET}"

    def overlay_sep() -> str:
        return f"{colour}╠{'═' * inner}╣{RESET}"

    def overlay_bot() -> str:
        return f"{colour}╚{'═' * inner}╝{RESET}"

    def overlay_blank() -> str:
        return f"{colour}║{RESET}{' ' * inner}{colour}║{RESET}"

    def overlay_center(plain: str, colored: str) -> str:
        total_pad = max(0, inner - len(plain))
        lp = total_pad // 2
        rp = total_pad - lp
        body = colored if colored else plain
        return f"{colour}║{RESET}{' ' * lp}{body}{' ' * rp}{colour}║{RESET}"

    # Truncate question to fit
    q_max   = inner - 2
    q_plain = question if len(question) <= q_max else question[: q_max - 1] + "\u2026"

    box_rows: list[str] = [
        overlay_top(),
        overlay_blank(),
        overlay_center(q_plain, f"{BOLD}{q_plain}{RESET}"),
        overlay_blank(),
        overlay_sep(),
        overlay_blank(),
    ]
    for art_plain, art_colored in zip(_ART_LINES, _art_lines_colored()):
        box_rows.append(overlay_center(art_plain.rstrip(), art_colored.rstrip()))
    box_rows += [
        overlay_blank(),
        overlay_sep(),
        overlay_blank(),
        overlay_center(text, f"{BOLD}{cat_color}{text}{RESET}"),
        overlay_center(
            f"[ {category.upper()} ]",
            f"{DIM}{cat_color}[ {category.upper()} ]{RESET}",
        ),
        overlay_blank(),
        overlay_bot(),
    ]

    box_height = len(box_rows)

    # Center position
    start_row = max(1, (term_lines - box_height) // 2 + 1)
    start_col = max(1, (term_cols  - width)      // 2 + 1)

    # Assemble with cursor positioning
    out_parts: list[str] = []
    for i, row_str in enumerate(box_rows):
        out_parts.append(go(start_row + i, start_col) + row_str)

    return "".join(out_parts)
