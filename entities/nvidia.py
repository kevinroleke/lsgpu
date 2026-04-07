from ansi import GREEN
from .base import EntitySpec

SPEC = EntitySpec("nvidia", color=GREEN, frames=[
    [
        " .----------. ",
        "/   NVIDIA   \\",
        "|  ___   _   |",
        "| /   \\ / \\  |",
        "| \\___/ \\_/  |",
        "|   GeForce  |",
        "\\____________/",
    ],
    [
        " .----------. ",
        "/  *NVIDIA*  \\",
        "|  ___   _   |",
        "| /   \\ / \\  |",
        "| \\___/ \\_/  |",
        "|  *GeForce* |",
        "\\____________/",
    ],
])
