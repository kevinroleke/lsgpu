"""Chrome-style dinosaur jump game for the lsgpu TUI tool."""

import os
import random
import select
import sys
import time

from .ansi import RESET, BOLD, DIM, GREEN, CYAN, YELLOW, RED, WHITE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FPS          = 30
_TICK         = 1.0 / _FPS
_GRAVITY      = 2.5        # velocity added per tick (downward = positive)
_JUMP_VEL     = -9.0       # initial upward velocity (negative = up)
_DINO_COL     = 4          # fixed column for the dino (1-indexed)
_CACTUS_WIDTH = 3

# Dino art: each entry is [top_row, mid_row, bot_row] (3-char wide + padding)
_DINO_RUN = [
    [r" ,@  ", r"/_|  ", r"/ \  "],
    [r" ,@  ", r"/_|  ", r" \_\ "],
]
_DINO_JUMP = [r" ,@  ", r"/|\  ", r"     "]
_DINO_DEAD = [r" x@  ", r"/_|  ", r"/ \  "]

_DINO_HEIGHT = 3   # rows used by dino art
_DINO_W      = 5   # display width of each art row

# Cactus art lines (bottom-aligned, 3 wide)
_CACTUS_TALL = [
    r" | ",
    r"|_|",
    r" | ",
]
_CACTUS_SHORT = [
    r"   ",
    r"|_|",
    r" | ",
]


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


def _clear_rect(row: int, col: int, width: int, height: int) -> str:
    """Return escape sequence to blank a rectangle."""
    blank = " " * width
    return "".join(_go(row + r, col) + blank for r in range(height))


# ---------------------------------------------------------------------------
# Cactus
# ---------------------------------------------------------------------------

class Cactus:
    def __init__(self, col: int) -> None:
        self.col  = col
        self.art  = random.choice([_CACTUS_TALL, _CACTUS_SHORT])
        self.dead = False   # flagged when it leaves the screen

    def move(self, speed: int) -> None:
        self.col -= speed

    def rows(self, ground_row: int) -> list[tuple[int, int, str]]:
        """Return (row, col, text) for each art line."""
        result = []
        for i, line in enumerate(self.art):
            r = ground_row - (_CACTUS_HEIGHT - 1 - i)
            result.append((r, self.col, line))
        return result


_CACTUS_HEIGHT = 3


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------

def _collides(dino_row: int, dino_col: int, cactuses: list[Cactus]) -> bool:
    """Simple bounding-box collision."""
    # Dino occupies rows [dino_row-2 .. dino_row], cols [dino_col .. dino_col+3]
    dino_rows = set(range(dino_row - _DINO_HEIGHT + 1, dino_row + 1))
    dino_cols = set(range(dino_col, dino_col + 4))
    for c in cactuses:
        cac_cols = set(range(c.col, c.col + _CACTUS_WIDTH))
        if dino_cols & cac_cols:
            # Cactus is bottom-anchored at its own ground_row
            ground = c._ground_row  # type: ignore[attr-defined]
            cac_rows = set(range(ground - _CACTUS_HEIGHT + 1, ground + 1))
            if dino_rows & cac_rows:
                return True
    return False


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_dino(row: int, col: int, frame_art: list[str], color: str = GREEN) -> str:
    out = []
    for i, line in enumerate(frame_art):
        out.append(_go(row - (_DINO_HEIGHT - 1 - i), col) + color + line + RESET)
    return "".join(out)


def _draw_cactus(c: Cactus, color: str = CYAN) -> str:
    out = []
    ground_row = c._ground_row  # type: ignore[attr-defined]
    for i, line in enumerate(c.art):
        r = ground_row - (_CACTUS_HEIGHT - 1 - i)
        out.append(_go(r, c.col) + color + line + RESET)
    return "".join(out)


def _erase_dino(row: int, col: int) -> str:
    return _clear_rect(row - _DINO_HEIGHT + 1, col, _DINO_W, _DINO_HEIGHT)


def _erase_cactus(c: Cactus) -> str:
    ground_row = c._ground_row  # type: ignore[attr-defined]
    return _clear_rect(ground_row - _CACTUS_HEIGHT + 1, c.col, _CACTUS_WIDTH, _CACTUS_HEIGHT)


# ---------------------------------------------------------------------------
# Main play function
# ---------------------------------------------------------------------------

def play(fd: int, term_cols: int, term_lines: int) -> None:
    """Run the dinosaur jump game."""

    # ── layout ──────────────────────────────────────────────────────────────
    header_row  = 1
    divider_row = 2
    ground_row  = term_lines - 2   # dino base row
    sky_row     = ground_row - 1   # separator between sky and ground

    # ── state ───────────────────────────────────────────────────────────────
    score          = 0
    hi_score       = 0
    dino_row       = ground_row        # current bottom row of dino
    dino_col       = _DINO_COL
    jump_vel: float = 0.0
    airborne       = False
    frame_tick     = 0
    anim_frame     = 0
    cactuses: list[Cactus] = []
    next_cactus    = random.randint(20, 45)  # ticks until first cactus
    cactus_timer   = 0
    game_over      = False
    dead_flash     = 0
    speed          = 1                # cols per tick cactus moves
    speed_timer    = 0

    # ── initial full draw ────────────────────────────────────────────────────
    # Disable auto-wrap so lines filling the terminal width don't garble output
    sys.stdout.write("\033[?7l")
    buf = ["\033[2J\033[H"]

    # Header
    hint = " [SPACE] jump  [q] quit"
    score_str = f"Score: {score:05d}   HI: {hi_score:05d}"
    buf.append(_go(header_row, 1) + BOLD + WHITE + score_str + RESET)
    hint_col = max(1, term_cols - len(hint))
    buf.append(_go(header_row, hint_col) + DIM + hint + RESET)

    line_w = term_cols - 1   # avoid auto-wrap at exact terminal width

    # Divider
    buf.append(_go(divider_row, 1) + CYAN + "─" * line_w + RESET)

    # Ground line
    buf.append(_go(ground_row + 1, 1) + CYAN + "─" * line_w + RESET)

    # Initial dino
    buf.append(_draw_dino(dino_row, dino_col, _DINO_RUN[0], GREEN))

    _write("".join(buf))

    # ── game loop ────────────────────────────────────────────────────────────
    prev_dino_row = dino_row
    prev_dino_col = dino_col

    while True:
        tick_start = time.monotonic()

        # ── input ────────────────────────────────────────────────────────────
        k = _key(fd, 0.0)
        if k in (b"q", b"Q", b"\x1b") and game_over:
            break
        if k in (b"q", b"Q"):
            break
        if k in (b" ", b"\x1b[A"):
            if game_over:
                # restart
                score         = 0
                dino_row      = ground_row
                jump_vel      = 0.0
                airborne      = False
                cactuses      = []
                next_cactus   = random.randint(20, 45)
                cactus_timer  = 0
                game_over     = False
                dead_flash    = 0
                speed         = 1
                speed_timer   = 0
                frame_tick    = 0
                anim_frame    = 0
                prev_dino_row = dino_row
                # clear play area
                buf = ["\033[2J\033[H"]
                buf.append(_go(divider_row, 1) + CYAN + "─" * (term_cols - 1) + RESET)
                buf.append(_go(ground_row + 1, 1) + CYAN + "─" * (term_cols - 1) + RESET)
                _write("".join(buf))
                continue
            if not airborne:
                jump_vel = _JUMP_VEL
                airborne  = True

        if game_over:
            # wait for key
            elapsed = time.monotonic() - tick_start
            time.sleep(max(0.0, _TICK - elapsed))
            continue

        # ── physics ──────────────────────────────────────────────────────────
        if airborne or jump_vel != 0.0:
            dino_row_f = float(dino_row) + jump_vel
            jump_vel  += _GRAVITY
            dino_row   = int(dino_row_f)
            if dino_row >= ground_row:
                dino_row  = ground_row
                jump_vel  = 0.0
                airborne  = False

        # ── cacti ────────────────────────────────────────────────────────────
        cactus_timer += 1
        if cactus_timer >= next_cactus:
            cac = Cactus(term_cols - 1)
            cac._ground_row = ground_row  # type: ignore[attr-defined]
            cactuses.append(cac)
            cactus_timer = 0
            next_cactus  = random.randint(25, 55)

        for c in cactuses:
            c.move(speed)
        cactuses = [c for c in cactuses if c.col + _CACTUS_WIDTH > 0]

        # ── collision ────────────────────────────────────────────────────────
        if _collides(dino_row, dino_col, cactuses):
            game_over = True
            hi_score  = max(hi_score, score)

        # ── score & speed ────────────────────────────────────────────────────
        score       += 1
        speed_timer += 1
        if speed_timer >= 150:
            speed_timer = 0
            speed = min(speed + 1, 4)

        frame_tick += 1
        if frame_tick >= 8:
            frame_tick  = 0
            anim_frame ^= 1

        # ── draw ─────────────────────────────────────────────────────────────
        buf = []

        # Score
        score_str = f"Score: {score:05d}   HI: {hi_score:05d}"
        buf.append(_go(header_row, 1) + BOLD + WHITE + score_str + RESET)

        # Erase dino at old position if moved
        if prev_dino_row != dino_row or prev_dino_col != dino_col:
            buf.append(_erase_dino(prev_dino_row, prev_dino_col))

        # Draw dino
        if game_over:
            dead_flash += 1
            color = RED if (dead_flash // 3) % 2 == 0 else WHITE
            buf.append(_draw_dino(dino_row, dino_col, _DINO_DEAD, color))
        else:
            if airborne or dino_row < ground_row:
                art = _DINO_JUMP
            else:
                art = _DINO_RUN[anim_frame]
            buf.append(_draw_dino(dino_row, dino_col, art, GREEN))

        prev_dino_row = dino_row
        prev_dino_col = dino_col

        # Redraw ground (dino may have overwritten it)
        buf.append(_go(ground_row + 1, 1) + CYAN + "─" * (term_cols - 1) + RESET)

        # Erase old cactus positions by blanking a column ahead of each cactus
        # (easier: we redraw every cactus each frame at their new position after
        #  blanking the trailing column they just left)
        for c in cactuses:
            old_col = c.col + speed   # where it was last tick
            if 1 <= old_col < term_cols:
                # blank the column the cactus vacated
                for r in range(ground_row - _CACTUS_HEIGHT + 1, ground_row + 1):
                    buf.append(_go(r, old_col + _CACTUS_WIDTH) + " ")

        # Draw cacti
        for c in cactuses:
            if c.col + _CACTUS_WIDTH > 0 and c.col < term_cols:
                buf.append(_draw_cactus(c, YELLOW))

        # Game over overlay
        if game_over:
            msg1 = "  G A M E   O V E R  "
            msg2 = f"  Score: {score:05d}  "
            msg3 = "  Press SPACE to restart  |  q to quit  "
            box_w = max(len(msg1), len(msg2), len(msg3)) + 4
            box_r = term_lines // 2 - 2
            box_c = max(1, (term_cols - box_w) // 2)
            flash = (dead_flash // 5) % 2 == 0
            hdr_color = RED if flash else WHITE
            buf.append(_go(box_r,     box_c) + hdr_color + BOLD + "┌" + "─" * (box_w - 2) + "┐" + RESET)
            buf.append(_go(box_r + 1, box_c) + hdr_color + BOLD + "│" + msg1.center(box_w - 2) + "│" + RESET)
            buf.append(_go(box_r + 2, box_c) + WHITE      + "│" + msg2.center(box_w - 2) + "│" + RESET)
            buf.append(_go(box_r + 3, box_c) + DIM        + "│" + msg3.center(box_w - 2) + "│" + RESET)
            buf.append(_go(box_r + 4, box_c) + hdr_color + BOLD + "└" + "─" * (box_w - 2) + "┘" + RESET)

        _write("".join(buf))

        # ── frame timing ─────────────────────────────────────────────────────
        elapsed = time.monotonic() - tick_start
        time.sleep(max(0.0, _TICK - elapsed))

    # Re-enable auto-wrap before returning to lsgpu
    sys.stdout.write("\033[?7h")
    sys.stdout.flush()
