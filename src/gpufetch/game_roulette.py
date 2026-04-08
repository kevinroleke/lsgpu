"""File-delete Russian Roulette for the lsgpu TUI tool."""

import os
import random
import select
import sys
import time

from .ansi import RESET, BOLD, DIM, GREEN, CYAN, YELLOW, RED, WHITE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SKIP_DIRS   = {".config", ".cache", ".local", ".git", ".ssh", ".gnupg"}
_MAX_SIZE    = 10 * 1024 * 1024   # 10 MB
_CHAMBERS    = 6
_BULLET_POS  = 0                  # we'll randomize which chamber fires


# ---------------------------------------------------------------------------
# ASCII art
# ---------------------------------------------------------------------------

_GUN = [
    r"        ___          ",
    r"       /o o \_______ ",
    r"   ===|    *       |>",
    r"       \___/         ",
]

_BANG_ART = [
    r" ██████╗  █████╗ ███╗  ██╗ ██████╗ ██╗",
    r" ██╔══██╗██╔══██╗████╗ ██║██╔════╝ ██║",
    r" ██████╔╝███████║██╔██╗██║██║  ███╗██║",
    r" ██╔══██╗██╔══██║██║╚████║██║   ██║╚═╝",
    r" ██████╔╝██║  ██║██║ ╚███║╚██████╔╝██╗",
    r" ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚══╝ ╚═════╝ ╚═╝",
]

_CHAMBER_SPIN = ["·", "○", "●", "○", "·", " "]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _key(fd: int, timeout: float = 0.0) -> bytes:
    if not select.select([fd], [], [], timeout)[0]:
        return b""
    return os.read(fd, 1)


def _go(row: int, col: int) -> str:
    return f"\033[{row};{col}H"


def _write(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def _center_col(text: str, term_cols: int) -> int:
    return max(1, (term_cols - len(text)) // 2 + 1)


def _draw_gun(start_row: int, term_cols: int, chamber_char: str = "*") -> str:
    """Return escape sequence drawing the gun art centered, with chamber_char."""
    out = []
    for i, line in enumerate(_GUN):
        filled = line.replace("*", chamber_char, 1)
        col = _center_col(filled, term_cols)
        color = YELLOW if i == 2 else WHITE
        out.append(_go(start_row + i, col) + color + filled + RESET)
    return "".join(out)


def _centered_line(row: int, text: str, term_cols: int, color: str = WHITE) -> str:
    col = _center_col(text, term_cols)
    return _go(row, col) + color + text + RESET


def _wait_key(fd: int) -> bytes:
    """Block until a key is pressed."""
    while True:
        k = _key(fd, 0.1)
        if k:
            return k


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------

def _is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(512)
        return b"\x00" in chunk
    except OSError:
        return True


def _scan_dir(directory: str) -> list[str]:
    """Scan directory (depth 1) for safe candidate files."""
    candidates: list[str] = []
    try:
        entries = os.scandir(directory)
    except PermissionError:
        return candidates

    for entry in entries:
        # skip hidden
        if entry.name.startswith("."):
            continue
        # skip blacklisted subdirs
        if entry.is_dir(follow_symlinks=False):
            continue
        if not entry.is_file(follow_symlinks=False):
            continue
        try:
            st = entry.stat()
        except OSError:
            continue
        # skip too large
        if st.st_size > _MAX_SIZE:
            continue
        # skip binary
        if _is_binary(entry.path):
            continue
        candidates.append(entry.path)

    return candidates


def _find_target() -> str | None:
    """Return a random file path to potentially delete, or None."""
    home = os.path.expanduser("~")
    candidates: list[str] = []

    # Scan home dir (depth 1)
    try:
        for entry in os.scandir(home):
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                # Only recurse one level into non-blacklisted dirs
                if entry.name in _SKIP_DIRS:
                    continue
                candidates.extend(_scan_dir(entry.path))
            elif entry.is_file(follow_symlinks=False):
                try:
                    st = entry.stat()
                    if st.st_size <= _MAX_SIZE and not _is_binary(entry.path):
                        candidates.append(entry.path)
                except OSError:
                    pass
    except PermissionError:
        pass

    if not candidates:
        candidates = _scan_dir(os.getcwd())

    if not candidates:
        return None

    return random.choice(candidates)


# ---------------------------------------------------------------------------
# Main play function
# ---------------------------------------------------------------------------

def play(fd: int, term_cols: int, term_lines: int) -> None:
    """Run the Russian Roulette file-delete game."""

    # ── Clear screen ─────────────────────────────────────────────────────────
    _write("\033[2J\033[H")

    # ── Find target file ─────────────────────────────────────────────────────
    center_row = term_lines // 2
    _write(
        _centered_line(center_row, "Scanning for victims...", term_cols, DIM + CYAN)
    )

    target = _find_target()

    if target is None:
        _write("\033[2J\033[H")
        _write(_centered_line(center_row - 1, "No files found.", term_cols, YELLOW + BOLD))
        _write(_centered_line(center_row,     "You live another day.", term_cols, DIM))
        _write(_centered_line(center_row + 2, "Press any key...", term_cols, DIM))
        _wait_key(fd)
        return

    # ── Determine bullet position (randomize) ─────────────────────────────────
    bullet_chamber = random.randint(0, _CHAMBERS - 1)
    fires          = (bullet_chamber == 0)   # chamber 0 is where we "stop"

    # ── Phase 1: Show gun + filename ─────────────────────────────────────────
    _write("\033[2J\033[H")

    gun_top = max(1, center_row - 6)

    # Title
    title = "  ══  RUSSIAN  ROULETTE  ══  "
    _write(_centered_line(gun_top - 2, title, term_cols, RED + BOLD))

    # Gun
    _write(_draw_gun(gun_top, term_cols, "●"))

    # Loading label
    _write(_centered_line(gun_top + len(_GUN) + 1, "Loading chamber...", term_cols, YELLOW + BOLD))

    # Filename (dimmed)
    display_path = target
    if len(display_path) > term_cols - 4:
        display_path = "..." + display_path[-(term_cols - 7):]
    _write(_centered_line(gun_top + len(_GUN) + 2, display_path, term_cols, DIM + WHITE))

    time.sleep(1.2)

    # ── Phase 2: Spin animation (~1.5 s) ─────────────────────────────────────
    spin_row = gun_top + len(_GUN) + 1
    spin_label = "S P I N N I N G . . ."
    _write(_centered_line(spin_row, " " * 30, term_cols))  # clear old label

    spin_end = time.monotonic() + 1.6
    spin_idx  = 0
    while time.monotonic() < spin_end:
        char = _CHAMBER_SPIN[spin_idx % len(_CHAMBER_SPIN)]
        _write(_draw_gun(gun_top, term_cols, char))
        _write(_centered_line(spin_row, spin_label, term_cols, CYAN + BOLD))
        sys.stdout.flush()
        time.sleep(0.12)
        spin_idx += 1

    # Settle on loaded symbol
    _write(_draw_gun(gun_top, term_cols, "●"))

    # ── Phase 3: Pull trigger prompt ─────────────────────────────────────────
    prompt = "  PULL THE TRIGGER?  [y / N]  "
    _write(_centered_line(spin_row,     " " * 40, term_cols))
    _write(_centered_line(spin_row,     prompt,   term_cols, RED + BOLD))
    _write(_centered_line(spin_row + 2, display_path, term_cols, DIM + WHITE))

    while True:
        k = _key(fd, 0.1)
        if not k:
            continue
        if k in (b"y", b"Y"):
            break
        if k in (b"n", b"N", b"\x1b", b"q", b"Q"):
            # chickened out
            _write("\033[2J\033[H")
            _write(_centered_line(center_row - 1, "*click*", term_cols, DIM))
            _write(_centered_line(center_row,     "You chickened out. The file lives.", term_cols, YELLOW + BOLD))
            _write(_centered_line(center_row + 2, "Press any key...", term_cols, DIM))
            _wait_key(fd)
            return

    # ── Phase 4: Fire ────────────────────────────────────────────────────────
    _write("\033[2J\033[H")

    if not fires:
        # ── SAFE ─────────────────────────────────────────────────────────────
        # Dramatic pause with click sound text
        for i in range(4):
            _write(_centered_line(center_row, "*" + "." * i, term_cols, DIM))
            time.sleep(0.18)

        _write("\033[2J\033[H")

        click_art = [
            "           ",
            "  *click*  ",
            "           ",
        ]
        cr = center_row - 3
        for i, line in enumerate(click_art):
            _write(_centered_line(cr + i, line, term_cols, DIM + WHITE + BOLD))

        _write(_centered_line(cr + 4, "The chamber was empty.", term_cols, GREEN + BOLD))
        _write(_centered_line(cr + 5, "You got lucky.",         term_cols, GREEN))
        _write(_centered_line(cr + 7, "Press any key to tempt fate again... or q to flee", term_cols, DIM))

    else:
        # ── BANG ─────────────────────────────────────────────────────────────
        # Flash effect
        for _ in range(3):
            _write("\033[2J" + "\033[7m" + " " * (term_cols * term_lines))
            time.sleep(0.06)
            _write("\033[0m\033[2J\033[H")
            time.sleep(0.06)

        _write("\033[2J\033[H")

        # Big BANG art
        bang_top = max(1, center_row - len(_BANG_ART) - 3)
        for i, line in enumerate(_BANG_ART):
            _write(_centered_line(bang_top + i, line, term_cols, RED + BOLD))

        # Actually delete the file
        deleted = False
        try:
            os.remove(target)
            deleted = True
        except OSError:
            deleted = False

        del_row = bang_top + len(_BANG_ART) + 2
        if deleted:
            _write(_centered_line(del_row,     "DELETED:", term_cols, RED + BOLD))
            _write(_centered_line(del_row + 1, display_path, term_cols, RED + DIM))
        else:
            _write(_centered_line(del_row,     "Tried to delete (failed — permission denied?):", term_cols, YELLOW + BOLD))
            _write(_centered_line(del_row + 1, display_path, term_cols, DIM))

        _write(_centered_line(del_row + 3, "Press any key...", term_cols, DIM))

    _wait_key(fd)
