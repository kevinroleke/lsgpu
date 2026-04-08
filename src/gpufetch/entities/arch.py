from ..ansi import CYAN
from .base import EntitySpec

SPEC = EntitySpec("arch", color=CYAN, frames=[
    [
        "      /\\      ",
        "     /  \\     ",
        "    / /\\ \\    ",
        "   / /  \\ \\   ",
        "  / / /\\ \\ \\  ",
        " /_/_/  \\_\\_\\ ",
        "              ",
        "     ARCH     ",
    ],
    [
        "    * /\\ *    ",
        "     /  \\     ",
        "    / /\\ \\    ",
        "   / /  \\ \\   ",
        "  / / /\\ \\ \\  ",
        " /_/_/  \\_\\_\\ ",
        "              ",
        "   * ARCH *   ",
    ],
])
