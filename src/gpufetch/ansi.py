"""Shared ANSI escape code constants and helpers."""

import re

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
GREEN   = "\033[32m"
CYAN    = "\033[36m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
WHITE   = "\033[37m"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)
