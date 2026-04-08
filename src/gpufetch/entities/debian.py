from ..ansi import RED
from .base import EntitySpec

SPEC = EntitySpec("debian", color=RED, frames=[
    [
        "   ,-----,   ",
        "  / ,-, . \\  ",
        " | ( o )  |  ",
        "  \\ '-'  /   ",
        "   '----'    ",
        "   DEBIAN    ",
    ],
    [
        "  ,-----,    ",
        " / ,-,   \\   ",
        "| ( o )   |  ",
        " \\ '--'  /   ",
        "  '------'   ",
        "   DEBIAN    ",
    ],
])
