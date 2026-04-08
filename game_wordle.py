"""Wordle game for the lsgpu TUI tool.

Launch via `/play wordle` while the alternate screen is active and the
terminal is in raw mode.  The only public symbol is `play()`.
"""

import os
import random
import select
import sys
import time

from ansi import RESET, BOLD, DIM, GREEN, CYAN, YELLOW, RED, WHITE

# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------

_WORDS: list[str] = [
    "CRANE", "STARE", "AUDIO", "RAISE", "SLATE", "CRATE", "TRACE", "SAUCE",
    "BLAZE", "STORM", "FLASH", "NIGHT", "FLAME", "BREAD", "CLOCK", "DANCE",
    "EVERY", "FLOAT", "GHOST", "HEART", "JOKER", "KNIFE", "LEMON", "METAL",
    "NOVEL", "OCEAN", "PANIC", "QUEEN", "RIVER", "SHADE", "TIGER", "ULTRA",
    "VAPOR", "WHALE", "XENON", "YACHT", "ZEBRA", "ANGEL", "BLACK", "CHAIR",
    "DELTA", "EAGLE", "FIGHT", "GRAVE", "HONOR", "IVORY", "KARMA", "LASER",
    "MAGIC", "NORTH", "ORBIT", "PLANT", "QUEST", "ROMAN", "SHARP", "TORCH",
    "UNION", "VIVID", "WAGON", "EXACT", "YOUTH", "CABLE", "BLUNT", "GLOBE",
    "IDEAL", "JUMPY", "KNEEL", "LOYAL", "MOODY", "NOBLE", "OZONE", "PIVOT",
    "ROCKY", "SQUAD", "TRUTH", "UNTIL", "VALID", "WORKS", "EXTRA", "YOUNG",
    "PIXEL", "PROXY", "RAPID", "SCOUT", "TOWER", "SWIFT", "POWER", "BOUND",
    "CROWN", "DRAIN", "ELBOW", "FANCY", "GRANT", "HINGE", "INPUT", "JUDGE",
    "KIOSK", "LIGHT", "MOUTH", "NERVE", "OTHER", "PRIDE", "QUIRK", "ROUGH",
    "SHIFT", "THINK", "UPSET", "VOICE", "WITCH", "FIRST", "PLACE", "BRING",
    "AMONG", "NEVER", "THEIR", "THESE", "STILL", "WHERE", "THOSE", "WHILE",
    "THREE", "SEVEN", "EIGHT", "SPACE", "WATER", "WORLD", "FORCE", "GREAT",
    "SMALL", "SOUND", "POINT", "WOMAN", "MONEY", "STAND", "THING", "STATE",
    "JAZZY", "ZONAL", "ZONES", "SMOKE", "STRIP", "GROAN", "PLUMB", "CLOWN",
    "SHRUG", "BRISK", "GLYPH", "CRIMP", "CINCH", "CLEFT", "PROWL", "STOMP",
    "SNORE", "STING", "GRIME", "FLINT", "BRAID", "SLUNK", "TROUT", "SCOUT",
    "SHAWL", "BROTH", "CLAMP", "CRISP", "FROWN", "GRUMP", "PLANK", "SWAMP",
    "THICK", "TRAWL", "TREMBLE", "YELP", "CLEFT", "GRAFT", "SHRUB", "STUMP",
    "BLAND", "BLEND", "BLOWN", "BRUNT", "CHAMP", "CLANG", "CLASP", "CLOVE",
    "COAST", "CRAMP", "CREEP", "CRISP", "CROUP", "DRAFT", "DRANK", "DREAD",
    "DWARF", "EXPEL", "EXULT", "FLAIR", "FLANK", "FLARE", "FLECK", "FLING",
    "FLIRT", "FLOCK", "FLOOD", "FLOOR", "FLOSS", "FLOUT", "FLOWN", "FLUFF",
    "FLUNG", "FLUNK", "FLUTE", "FRAIL", "FREAK", "FRESH", "FRILL", "FRISK",
    "FRIZZ", "FRONT", "FROST", "FROTH", "FROZE", "FRUIT", "GRAIL", "GRASP",
    "GRASS", "GRATE", "GRAZE", "GREED", "GREET", "GRIEF", "GRILL", "GRIPE",
    "GROAN", "GROIN", "GROOM", "GROPE", "GROSS", "GROUP", "GROUT", "GROVE",
    "GROWL", "GRUEL", "GRUFF", "GRUNK", "GRUNT", "GUILE", "GUISE", "GUSTO",
    "GYPSY", "HAUNT", "HAVEN", "HOIST", "HOLLY", "HOMER", "HORDE", "HUSKY",
]

# Filter to exactly 5-letter words and deduplicate
_WORDS = list({w for w in _WORDS if len(w) == 5})

# Valid guesses = same list (can be extended)
_VALID_GUESSES: set[str] = set(_WORDS)

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

# Tile background colours
_BG_GREEN  = "\033[48;2;83;141;78m"
_BG_YELLOW = "\033[48;2;181;159;59m"
_BG_GRAY   = "\033[48;2;58;58;60m"
_BG_EMPTY  = "\033[48;2;18;18;19m"     # very dark, "unguessed"
_BG_ACTIVE = "\033[48;2;30;30;32m"     # current row (slightly lighter)

_FG_WHITE  = "\033[38;2;255;255;255m"
_FG_DIM    = "\033[38;2;130;130;130m"

# Keyboard key backgrounds
_KB_GREEN  = _BG_GREEN
_KB_YELLOW = _BG_YELLOW
_KB_GRAY   = _BG_GRAY
_KB_NONE   = "\033[48;2;40;40;42m"     # untouched key


def _go(row: int, col: int) -> str:
    return f"\033[{row};{col}H"


def _tile(letter: str, bg: str) -> str:
    """Render a single 3-wide tile with given background."""
    return f"{bg}{_FG_WHITE}{BOLD} {letter} {RESET}"


def _key_chip(letter: str, bg: str) -> str:
    """Render a small keyboard key chip."""
    return f"{bg}{_FG_WHITE}{BOLD} {letter} {RESET}"


# ---------------------------------------------------------------------------
# Input helper
# ---------------------------------------------------------------------------

def _key(fd: int, timeout: float = 0.1) -> str:
    if not select.select([fd], [], [], timeout)[0]:
        return ""
    b = os.read(fd, 1)
    if b == b"\x1b":
        # drain escape sequence
        while select.select([fd], [], [], 0.02)[0]:
            os.read(fd, 16)
        return "ESC"
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return ""


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_guess(guess: str, target: str) -> list[str]:
    """
    Return a list of 5 status strings: 'green', 'yellow', or 'gray'.
    Handles duplicate letters correctly (Wordle rules).
    """
    result = ["gray"] * 5
    target_remaining = list(target)

    # First pass: greens
    for i, (g, t) in enumerate(zip(guess, target)):
        if g == t:
            result[i] = "green"
            target_remaining[i] = None  # consumed

    # Second pass: yellows
    for i, g in enumerate(guess):
        if result[i] == "green":
            continue
        if g in target_remaining:
            result[i] = "yellow"
            target_remaining[target_remaining.index(g)] = None

    return result


_STATUS_BG = {
    "green":  _BG_GREEN,
    "yellow": _BG_YELLOW,
    "gray":   _BG_GRAY,
}

# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class _WordleUI:
    """Manages all rendering for the Wordle game."""

    ROWS = 6
    COLS = 5

    # Tile dimensions: each tile is 3 chars wide, 1 char tall, with 1-char gap
    TILE_W = 3
    TILE_GAP = 1
    # Board width in chars = 5 tiles * 3 + 4 gaps = 19
    BOARD_W = COLS * TILE_W + (COLS - 1) * TILE_GAP  # 19

    def __init__(self, term_cols: int, term_lines: int):
        self.tc = term_cols
        self.tl = term_lines

        # Compute board top-left so it's centered
        # Layout (rows used):
        #   1  title
        #   1  blank
        #   6  board rows
        #   1  blank
        #   1  current guess line
        #   1  blank
        #   2  keyboard rows
        #   1  blank
        #   1  hints line
        # total ≈ 15 rows
        total_h = 1 + 1 + self.ROWS + 1 + 1 + 1 + 2 + 1 + 1
        self.board_top = max(2, (self.tl - total_h) // 2 + 1)
        self.board_left = max(1, (self.tc - self.BOARD_W) // 2 + 1)

    # -- coordinate helpers --------------------------------------------------

    def _tile_col(self, col_idx: int) -> int:
        """Left column of tile col_idx (0-based)."""
        return self.board_left + col_idx * (self.TILE_W + self.TILE_GAP)

    def _tile_row(self, row_idx: int) -> int:
        """Screen row of board row row_idx (0-based)."""
        return self.board_top + 2 + row_idx  # +2 for title + blank

    # -- draw helpers --------------------------------------------------------

    def _write(self, s: str) -> None:
        sys.stdout.write(s)

    def _flush(self) -> None:
        sys.stdout.flush()

    def draw_full(
        self,
        guesses: list[str],
        scores: list[list[str]],
        current: str,
        kb_state: dict[str, str],
    ) -> None:
        """Redraw the entire game screen."""
        out: list[str] = ["\033[2J"]  # clear

        # -- Title -----------------------------------------------------------
        title = f"{BOLD}{CYAN}W O R D L E{RESET}"
        title_plain = "W O R D L E"
        title_col = max(1, (self.tc - len(title_plain)) // 2 + 1)
        out.append(_go(self.board_top, title_col) + title)

        # -- Board rows ------------------------------------------------------
        for r in range(self.ROWS):
            row_y = self._tile_row(r)
            if r < len(guesses):
                # Scored row
                word = guesses[r]
                sc   = scores[r]
                for c in range(self.COLS):
                    bg = _STATUS_BG[sc[c]]
                    out.append(
                        _go(row_y, self._tile_col(c))
                        + _tile(word[c], bg)
                    )
            elif r == len(guesses):
                # Current (active) row
                for c in range(self.COLS):
                    letter = current[c] if c < len(current) else " "
                    bg = _BG_ACTIVE
                    out.append(
                        _go(row_y, self._tile_col(c))
                        + _tile(letter, bg)
                    )
            else:
                # Empty future row
                for c in range(self.COLS):
                    out.append(
                        _go(row_y, self._tile_col(c))
                        + _tile(" ", _BG_EMPTY)
                    )

        # -- Current guess display -------------------------------------------
        guess_y = self._tile_row(self.ROWS) + 1
        dots = current + "_" * (self.COLS - len(current))
        guess_line = f"{DIM}Guess: {RESET}{BOLD}{WHITE}{dots}{RESET}"
        guess_plain = f"Guess: {dots}"
        guess_col = max(1, (self.tc - len(guess_plain)) // 2 + 1)
        out.append(_go(guess_y, guess_col) + guess_line)

        # -- Keyboard --------------------------------------------------------
        kb_y = guess_y + 2
        self._render_keyboard(out, kb_state, kb_y)

        # -- Hints line ------------------------------------------------------
        hint_y = kb_y + 3
        hint = f"{DIM}[Enter] submit  [Bksp] delete  [Esc] quit{RESET}"
        hint_plain = "[Enter] submit  [Bksp] delete  [Esc] quit"
        hint_col = max(1, (self.tc - len(hint_plain)) // 2 + 1)
        out.append(_go(hint_y, hint_col) + hint)

        self._write("".join(out))
        self._flush()

    def _render_keyboard(
        self,
        out: list[str],
        kb_state: dict[str, str],
        start_row: int,
    ) -> None:
        rows = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
        # Each key chip: 3 chars + 1 gap = 4 chars; last key no gap
        for ri, row_letters in enumerate(rows):
            row_w = len(row_letters) * 4 - 1
            row_col = max(1, (self.tc - row_w) // 2 + 1)
            col = row_col
            y = start_row + ri
            for letter in row_letters:
                status = kb_state.get(letter, "none")
                bg = {
                    "green":  _KB_GREEN,
                    "yellow": _KB_YELLOW,
                    "gray":   _KB_GRAY,
                    "none":   _KB_NONE,
                }[status]
                out.append(_go(y, col) + _key_chip(letter, bg))
                col += 4

    def draw_tile(
        self,
        row_idx: int,
        col_idx: int,
        letter: str,
        bg: str,
    ) -> None:
        """Redraw a single tile (fast update)."""
        y = self._tile_row(row_idx)
        x = self._tile_col(col_idx)
        sys.stdout.write(_go(y, x) + _tile(letter, bg))
        sys.stdout.flush()

    def update_current_row(self, row_idx: int, current: str) -> None:
        """Redraw just the active row tiles."""
        y = self._tile_row(row_idx)
        out: list[str] = []
        for c in range(self.COLS):
            letter = current[c] if c < len(current) else " "
            out.append(_go(y, self._tile_col(c)) + _tile(letter, _BG_ACTIVE))
        # Also refresh dots line
        guess_y = self._tile_row(self.ROWS) + 1
        dots = current + "_" * (self.COLS - len(current))
        guess_line = f"{DIM}Guess: {RESET}{BOLD}{WHITE}{dots}{RESET}"
        guess_plain = f"Guess: {dots}"
        guess_col = max(1, (self.tc - len(guess_plain)) // 2 + 1)
        out.append(_go(guess_y, guess_col) + guess_line)
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def show_message(self, msg: str, row_offset: int = 0) -> None:
        """Display a centered temporary message."""
        y = self._tile_row(self.ROWS) + 1 + row_offset
        plain_len = len(msg.replace(BOLD, "").replace(RESET, "")
                        .replace(RED, "").replace(YELLOW, "").replace(GREEN, ""))
        col = max(1, (self.tc - len(msg)) // 2 + 1)
        # Fallback: just center using raw length
        col = max(1, (self.tc - 30) // 2 + 1)
        sys.stdout.write(_go(y, col) + f"{BOLD}{msg}{RESET}" + "          ")
        sys.stdout.flush()

    def show_centered_message(self, msg: str, y: int) -> None:
        plain = msg  # caller passes plain text separately if needed
        col = max(1, (self.tc - len(msg)) // 2 + 1)
        sys.stdout.write(_go(y, col) + msg + "     ")
        sys.stdout.flush()

    def draw_end_screen(
        self,
        won: bool,
        target: str,
        guesses: list[str],
        scores: list[list[str]],
        kb_state: dict[str, str],
    ) -> None:
        """Draw the win/lose screen."""
        out: list[str] = ["\033[2J"]

        # Replay the board (scored)
        title = f"{BOLD}{CYAN}W O R D L E{RESET}"
        title_plain = "W O R D L E"
        title_col = max(1, (self.tc - len(title_plain)) // 2 + 1)
        out.append(_go(self.board_top, title_col) + title)

        for r in range(self.ROWS):
            row_y = self._tile_row(r)
            if r < len(guesses):
                word = guesses[r]
                sc   = scores[r]
                for c in range(self.COLS):
                    bg = _STATUS_BG[sc[c]]
                    out.append(
                        _go(row_y, self._tile_col(c))
                        + _tile(word[c], bg)
                    )
            else:
                for c in range(self.COLS):
                    out.append(
                        _go(row_y, self._tile_col(c))
                        + _tile(" ", _BG_EMPTY)
                    )

        # Result message
        msg_y = self._tile_row(self.ROWS) + 1
        if won:
            attempts = len(guesses)
            label = f"{BOLD}{GREEN}You got it in {attempts}/6!{RESET}"
            label_len = len(f"You got it in {attempts}/6!")
        else:
            label = f"{BOLD}{RED}The word was: {target}{RESET}"
            label_len = len(f"The word was: {target}")
        label_col = max(1, (self.tc - label_len) // 2 + 1)
        out.append(_go(msg_y, label_col) + label)

        # Press any key
        pak_y = msg_y + 2
        pak = f"{DIM}Press any key to return to lsgpu...{RESET}"
        pak_plain = "Press any key to return to lsgpu..."
        pak_col = max(1, (self.tc - len(pak_plain)) // 2 + 1)
        out.append(_go(pak_y, pak_col) + pak)

        self._write("".join(out))
        self._flush()


# ---------------------------------------------------------------------------
# Main game loop
# ---------------------------------------------------------------------------

def _update_kb(kb_state: dict[str, str], letter: str, status: str) -> None:
    """Update keyboard state — green beats yellow beats gray."""
    precedence = {"green": 3, "yellow": 2, "gray": 1, "none": 0}
    current = kb_state.get(letter, "none")
    if precedence[status] > precedence[current]:
        kb_state[letter] = status


def play(fd: int, term_cols: int, term_lines: int) -> None:
    """Entry point called by lsgpu."""
    target = random.choice(_WORDS)

    guesses: list[str] = []
    scores:  list[list[str]] = []
    current: str = ""
    kb_state: dict[str, str] = {}  # letter -> 'green'/'yellow'/'gray'/'none'

    ui = _WordleUI(term_cols, term_lines)

    # Initial draw
    ui.draw_full(guesses, scores, current, kb_state)

    game_over = False
    won       = False

    while not game_over:
        k = _key(fd, timeout=0.5)
        if not k:
            continue

        if k == "ESC":
            return  # exit back to lsgpu immediately

        if k in ("\r", "\n"):
            # Submit guess
            if len(current) < 5:
                # Too short — flash message
                ui.show_message(f"{YELLOW}Not enough letters{RESET}", row_offset=0)
                time.sleep(0.8)
                ui.draw_full(guesses, scores, current, kb_state)
                continue

            if current not in _VALID_GUESSES:
                ui.show_message(f"{RED}Not a word{RESET}", row_offset=0)
                time.sleep(0.8)
                ui.draw_full(guesses, scores, current, kb_state)
                continue

            # Score it
            sc = _score_guess(current, target)
            guesses.append(current)
            scores.append(sc)

            # Update keyboard
            for letter, status in zip(current, sc):
                _update_kb(kb_state, letter, status)

            current = ""

            if all(s == "green" for s in sc):
                won = True
                game_over = True
            elif len(guesses) >= 6:
                won = False
                game_over = True
            else:
                ui.draw_full(guesses, scores, current, kb_state)

        elif k in ("\x7f", "\x08"):
            # Backspace
            if current:
                current = current[:-1]
                ui.update_current_row(len(guesses), current)

        elif k.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if len(current) < 5:
                current += k.upper()
                ui.update_current_row(len(guesses), current)

        # else: ignore other keys

    # Show end screen
    ui.draw_end_screen(won, target, guesses, scores, kb_state)

    # Wait for any key
    while True:
        k = _key(fd, timeout=1.0)
        if k:
            break
