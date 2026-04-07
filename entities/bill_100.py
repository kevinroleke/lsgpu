from ansi import GREEN
from .base import EntitySpec

SPEC = EntitySpec("bill_100", color=GREEN, frames=[
    [
        ".-------------------------.",
        "|$100   [FRANKLIN]    $100|",
        "|  UNITED STATES OF AME  |",
        "|    ONE HUNDRED DOLLARS  |",
        "|  * * * * * * * * * * * |",
        "'-------------------------'",
    ],
    [
        ".-------------------------.",
        "|$100  ** SN:4206942 **$100|",
        "|  UNITED STATES OF AME  |",
        "|    ONE HUNDRED DOLLARS  |",
        "|  ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ |",
        "'-------------------------'",
    ],
])
