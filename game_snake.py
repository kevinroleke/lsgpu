"""Snake game for the lsgpu TUI tool."""

import os
import random
import select
import sys
from collections import deque

from ansi import RESET, BOLD, GREEN, CYAN, YELLOW, RED, WHITE, DIM

# ---------------------------------------------------------------------------
# Module-level high score (persists within a session)
# ---------------------------------------------------------------------------

_HIGH_SCORE: int = 0

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BRIGHT_GREEN = "\033[92m"

# Direction vectors: (row_delta, col_delta)
UP    = (-1,  0)
DOWN  = ( 1,  0)
LEFT  = ( 0, -1)
RIGHT = ( 0,  1)

OPPOSITES = {UP: DOWN, DOWN: UP, LEFT: RIGHT, RIGHT: LEFT}

# Speed: initial and max frames-per-second
INITIAL_SPEED = 12.0
MAX_SPEED     = 20.0
SPEED_STEP    =  0.8   # FPS increase per food eaten

# Speed indicator: 5 dots
SPEED_DOTS    = 5

# ---------------------------------------------------------------------------
# Input helper
# ---------------------------------------------------------------------------

def _read_key(fd: int, timeout: float = 0.0) -> bytes:
    """Non-blocking read of one byte; returns b'' if nothing available."""
    if not select.select([fd], [], [], timeout)[0]:
        return b""
    return os.read(fd, 1)


def _read_escape(fd: int) -> str:
    """
    Called after reading \\x1b.  Peeks ahead to detect arrow-key sequences
    (\\x1b[A/B/C/D).  Returns a descriptive string or 'ESC'.
    """
    # Peek for '['
    ch = _read_key(fd, timeout=0.05)
    if ch != b"[":
        return "ESC"
    ch2 = _read_key(fd, timeout=0.05)
    if ch2 == b"A":
        return "UP"
    if ch2 == b"B":
        return "DOWN"
    if ch2 == b"C":
        return "RIGHT"
    if ch2 == b"D":
        return "LEFT"
    return "ESC"


# ---------------------------------------------------------------------------
# Cursor / screen helpers
# ---------------------------------------------------------------------------

def _go(row: int, col: int) -> str:
    return f"\033[{row};{col}H"


def _write(s: str) -> None:
    sys.stdout.write(s)


def _flush() -> None:
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Border drawing
# ---------------------------------------------------------------------------

def _draw_border(pf_top: int, pf_left: int, pf_height: int, pf_width: int) -> None:
    """Draw box-drawing border around the playfield."""
    # pf_top / pf_left are the first *interior* row/col.
    # Border sits one cell outside.
    border_top  = pf_top  - 1
    border_left = pf_left - 1

    top_row    = border_top
    bottom_row = border_top + pf_height + 1
    left_col   = border_left
    right_col  = border_left + pf_width + 1

    buf = [CYAN]
    # Top edge
    buf.append(_go(top_row, left_col))
    buf.append("┌" + "─" * pf_width + "┐")
    # Bottom edge
    buf.append(_go(bottom_row, left_col))
    buf.append("└" + "─" * pf_width + "┘")
    # Side edges
    for r in range(pf_top, pf_top + pf_height):
        buf.append(_go(r, left_col))
        buf.append("│")
        buf.append(_go(r, right_col))
        buf.append("│")
    buf.append(RESET)
    _write("".join(buf))


# ---------------------------------------------------------------------------
# Score / header rendering
# ---------------------------------------------------------------------------

def _speed_dots(speed: float) -> str:
    """Return a 5-dot speed indicator string."""
    ratio = (speed - INITIAL_SPEED) / max(1.0, MAX_SPEED - INITIAL_SPEED)
    filled = round(ratio * SPEED_DOTS)
    filled = max(0, min(SPEED_DOTS, filled))
    dots = YELLOW + "●" * filled + DIM + "○" * (SPEED_DOTS - filled) + RESET
    return dots


def _render_header(score: int, high: int, speed: float, term_cols: int) -> str:
    """Build the header line (row 1)."""
    score_str = f"{score:04d}"
    high_str  = f"{high:04d}"
    dots      = _speed_dots(speed)
    dots_plain = "●" * SPEED_DOTS  # for length calculation

    title   = f"{BOLD}{GREEN} SNAKE {RESET}"
    scorep  = f"  Score: {BOLD}{WHITE}{score_str}{RESET}"
    highp   = f"   High: {BOLD}{YELLOW}{high_str}{RESET}"
    speedp  = f"   Speed: {dots}{RESET}"
    hints   = f"  {DIM}[WASD/↑↓←→] move  [q] quit{RESET}"

    return title + scorep + highp + speedp + hints


def _draw_header(score: int, high: int, speed: float, term_cols: int) -> None:
    _write(_go(1, 1))
    _write("\033[2K")   # erase line
    _write(_render_header(score, high, speed, term_cols))


# ---------------------------------------------------------------------------
# Cell rendering
# ---------------------------------------------------------------------------

def _draw_cell(row: int, col: int, char: str, color: str) -> str:
    return _go(row, col) + color + char + RESET


def _clear_cell(row: int, col: int) -> str:
    return _go(row, col) + " "


# ---------------------------------------------------------------------------
# Food placement
# ---------------------------------------------------------------------------

def _place_food(snake: deque, pf_top: int, pf_left: int,
                pf_height: int, pf_width: int) -> tuple[int, int]:
    snake_set = set(snake)
    while True:
        r = random.randint(pf_top, pf_top + pf_height - 1)
        c = random.randint(pf_left, pf_left + pf_width - 1)
        if (r, c) not in snake_set:
            return (r, c)


# ---------------------------------------------------------------------------
# Game-over overlay
# ---------------------------------------------------------------------------

def _draw_game_over(score: int, term_cols: int, term_lines: int) -> None:
    """Draw a centered game-over box."""
    inner_text = [
        "  GAME  OVER  ",
        f" Score: {score:04d}  ",
        " Press any key\u2026",
    ]
    box_width  = max(len(t) for t in inner_text) + 4
    box_height = len(inner_text) + 2  # top + bottom border

    start_row = max(1, (term_lines - box_height) // 2 + 1)
    start_col = max(1, (term_cols  - box_width)  // 2 + 1)

    inner = box_width - 2
    buf   = [CYAN]

    # Top
    buf.append(_go(start_row, start_col))
    buf.append("┌" + "─" * inner + "┐")
    # Content rows
    for i, text in enumerate(inner_text):
        pad   = inner - len(text)
        lp    = pad // 2
        rp    = pad - lp
        color = BOLD + RED if i == 0 else (WHITE if i == 1 else DIM + WHITE)
        buf.append(_go(start_row + 1 + i, start_col))
        buf.append(f"│{' ' * lp}{RESET}{color}{text}{RESET}{CYAN}{' ' * rp}│")
    # Bottom
    buf.append(_go(start_row + box_height - 1, start_col))
    buf.append("└" + "─" * inner + "┘")
    buf.append(RESET)

    _write("".join(buf))
    _flush()


# ---------------------------------------------------------------------------
# Controls hint (bottom area)
# ---------------------------------------------------------------------------

def _draw_controls(term_lines: int, term_cols: int) -> None:
    hint = f"{DIM}  Snake — a classic  {RESET}"
    _write(_go(term_lines - 1, 1))
    _write("\033[2K")
    _write(hint)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def play(fd: int, term_cols: int, term_lines: int) -> None:
    """
    Play a full game of Snake in the already-active alternate screen buffer.

    Parameters
    ----------
    fd         : sys.stdin.fileno(), already in raw mode
    term_cols  : terminal width
    term_lines : terminal height
    """
    global _HIGH_SCORE

    # ---- Layout math -------------------------------------------------------
    header_rows  = 3
    footer_rows  = 2
    pf_height    = max(5, term_lines - header_rows - footer_rows)
    pf_width     = max(10, term_cols - 2)

    # Top-left interior corner of the playfield (1-based)
    pf_top  = header_rows + 2   # row after header + border row
    pf_left = 2                  # col after border col

    # ---- Initial state ------------------------------------------------------
    score = 0
    speed = INITIAL_SPEED
    direction  = RIGHT
    next_dir   = RIGHT

    # Start snake in the center, 3 segments long, moving right
    mid_r = pf_top  + pf_height // 2
    mid_c = pf_left + pf_width  // 2

    snake: deque[tuple[int, int]] = deque([
        (mid_r, mid_c),
        (mid_r, mid_c - 1),
        (mid_r, mid_c - 2),
    ])

    food = _place_food(snake, pf_top, pf_left, pf_height, pf_width)

    # ---- Initial draw -------------------------------------------------------
    _write("\033[2J\033[H")  # clear screen
    _draw_border(pf_top, pf_left, pf_height, pf_width)
    _draw_header(score, _HIGH_SCORE, speed, term_cols)
    _draw_controls(term_lines, term_cols)

    # Draw initial snake
    buf = []
    for i, (r, c) in enumerate(snake):
        color = BRIGHT_GREEN if i == 0 else GREEN
        buf.append(_draw_cell(r, c, "█", color))
    # Draw food
    buf.append(_draw_cell(food[0], food[1], "●", RED))
    _write("".join(buf))
    _flush()

    # ---- Game loop ----------------------------------------------------------
    running    = True
    ate_food   = False
    last_score = score

    while running:
        # Frame timing: block up to 1/speed seconds waiting for a key
        frame_timeout = 1.0 / speed
        key = _read_key(fd, timeout=frame_timeout)

        # --- Direction input ---
        if key:
            action = None
            if key == b"\x1b":
                action = _read_escape(fd)
            else:
                ch = key.decode("utf-8", errors="replace").lower()
                if ch in ("q",):
                    break
                if ch == "w":
                    action = "UP"
                elif ch == "s":
                    action = "DOWN"
                elif ch == "a":
                    action = "LEFT"
                elif ch == "d":
                    action = "RIGHT"

            if action == "ESC":
                break
            elif action == "UP"    and direction != DOWN:
                next_dir = UP
            elif action == "DOWN"  and direction != UP:
                next_dir = DOWN
            elif action == "LEFT"  and direction != RIGHT:
                next_dir = LEFT
            elif action == "RIGHT" and direction != LEFT:
                next_dir = RIGHT

        # --- Advance snake ---
        direction = next_dir
        head_r, head_c = snake[0]
        dr, dc = direction
        new_head = (head_r + dr, head_c + dc)
        nr, nc = new_head

        # --- Collision: wall ---
        if (nr < pf_top or nr >= pf_top + pf_height or
                nc < pf_left or nc >= pf_left + pf_width):
            running = False
            break

        # --- Collision: self ---
        if new_head in snake:
            running = False
            break

        # --- Ate food? ---
        ate_food = (new_head == food)

        # --- Partial render ---
        buf = []

        # Old head becomes body color
        old_head = snake[0]
        buf.append(_draw_cell(old_head[0], old_head[1], "█", GREEN))

        # Add new head
        snake.appendleft(new_head)
        buf.append(_draw_cell(nr, nc, "█", BRIGHT_GREEN))

        if ate_food:
            score += 1
            speed  = min(MAX_SPEED, speed + SPEED_STEP)
            if score > _HIGH_SCORE:
                _HIGH_SCORE = score
            # Spawn new food (snake grew, no tail removal)
            food = _place_food(snake, pf_top, pf_left, pf_height, pf_width)
            buf.append(_draw_cell(food[0], food[1], "●", RED))
        else:
            # Remove tail
            old_tail = snake.pop()
            buf.append(_clear_cell(old_tail[0], old_tail[1]))

        _write("".join(buf))

        # Update header only when score or speed changed
        if score != last_score:
            _draw_header(score, _HIGH_SCORE, speed, term_cols)
            last_score = score

        _flush()

    # ---- Game over ----------------------------------------------------------
    if score > _HIGH_SCORE:
        _HIGH_SCORE = score

    _draw_game_over(score, term_cols, term_lines)

    # Wait for any key before returning to lsgpu
    while True:
        k = _read_key(fd, timeout=30.0)
        if k:
            break
