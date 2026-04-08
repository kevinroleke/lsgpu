from ..ansi import RESET, BLUE, YELLOW, GREEN, RED, WHITE, BOLD, DIM
from .base import EntitySpec

# Colour shortcuts (all reset at end of each line by the overlay renderer)
_B = BLUE    # blue hair
_Y = YELLOW  # skin / face
_G = GREEN   # dress
_R = RED     # shoes
_W = WHITE   # eyes / collar

# Hair lines: fully blue (EntitySpec.color = BLUE handles these automatically)
# Face/body lines: start with RESET so the spec-level BLUE doesn't bleed in,
# then apply per-section colours.

def _h(spaces: int, hashes: int) -> str:
    """Hair line: <spaces>(<hashes>)"""
    return " " * spaces + "(" + "#" * hashes + ")"


def _face_line(before: str, hair: str) -> str:
    """Face-area line: yellow section then blue hair on the right."""
    return f"{RESET}{_Y}{before}{_B}{hair}{RESET}"


SPEC = EntitySpec("marge", color=BLUE, frames=[
    [
        # ── hair (blue via spec color) ──────────────────────────────────────
        _h(12, 4),    #             (####)
        _h(10, 7),    #           (#######)
        _h(8,  9),    #         (#########)
        _h(7,  9),    #        (#########)
        _h(6,  9),    #       (#########)
        _h(5,  9),    #      (#########)
        _h(4,  9),    #     (#########)
        _h(3,  9),    #    (#########)
        _h(2,  9),    #   (#########)
        # ── face row: eyes + hair ───────────────────────────────────────────
        f"{RESET}   {_B}({_Y}o{_B})({_Y}o{_B})({BOLD}{_B}##){RESET}",
        # ── collar / necklace: ,_  necklace beads  C  then hair ────────────
        f"{RESET} {_Y},_{_R}ooo{_Y}C     {_B}(##){RESET}",
        # ── dress top + hair ────────────────────────────────────────────────
        f"{RESET}{_G}/___,   {_B}(##){RESET}",
        # ── dress mid + hair ────────────────────────────────────────────────
        f"{RESET}  {_G}\\     {_B}(#){RESET}",
        # ── legs ────────────────────────────────────────────────────────────
        f"{RESET}   {_G}|    |{RESET}",
        # ── shoes ───────────────────────────────────────────────────────────
        f"{RESET}   {_R}OOOOOO{RESET}",
        f"{RESET}  {_R}/      \\{RESET}",
    ],
])
