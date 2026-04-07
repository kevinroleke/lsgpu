from ansi import MAGENTA
from .base import EntitySpec

SPEC = EntitySpec("shadow_wizard", color=MAGENTA, frames=[
    [
        "    /\\    ",
        "   /##\\   ",
        "  /####\\  ",
        " (x   x)  ",
        "  \\ ^ /   ",
        "  |---|   ",
        " /|   |\\ ",
        "/  \\ /  \\",
        "    |    ",
        "    *    ",
    ],
    [
        " *  /\\    ",
        "   /##\\   ",
        "  /####\\  ",
        " (x   x)  ",
        "  \\ ^ /   ",
        "  |---|   ",
        " /|   |\\ *",
        "/  \\ /  \\",
        "    |    ",
        "   ***   ",
    ],
])
