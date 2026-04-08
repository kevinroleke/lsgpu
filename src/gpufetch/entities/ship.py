from ..ansi import YELLOW
from .base import EntitySpec

SPEC = EntitySpec("ship", color=YELLOW, frames=[
    [
        "  /\\  ",
        " /  \\ ",
        "/----\\",
        "\\    /",
        " >++< ",
    ],
    [
        "  /\\  ",
        " /  \\ ",
        "/----\\",
        "\\    /",
        " >**< ",
    ],
])
