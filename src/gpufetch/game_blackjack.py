"""Blackjack game for the lsgpu TUI tool."""

import os
import random
import select
import sys
import time

from .ansi import RESET, BOLD, DIM, GREEN, CYAN, YELLOW, RED, WHITE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FPS  = 20
_TICK = 1.0 / _FPS

SUITS  = ["♠", "♥", "♦", "♣"]
RANKS  = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
VALUES = {"A": 11, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
          "8": 8, "9": 9, "10": 10, "J": 10, "Q": 10, "K": 10}

RED_SUITS   = {"♥", "♦"}

# Card art dimensions
_CW = 7   # card width
_CH = 5   # card height

_CARD_BACK = [
    "┌─────┐",
    "│░░░░░│",
    "│░░░░░│",
    "│░░░░░│",
    "└─────┘",
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


def _card_art(rank: str, suit: str) -> list[str]:
    """Return 5-line card art for a face-up card."""
    color = RED if suit in RED_SUITS else WHITE
    r = rank.ljust(2)
    return [
        f"{WHITE}┌─────┐{RESET}",
        f"{WHITE}│{color}{r}   {WHITE}│{RESET}",
        f"{WHITE}│  {color}{suit}  {WHITE}│{RESET}",
        f"{WHITE}│   {color}{r}{WHITE}│{RESET}",
        f"{WHITE}└─────┘{RESET}",
    ]


def _back_art() -> list[str]:
    return [
        f"{DIM}┌─────┐{RESET}",
        f"{DIM}│░░░░░│{RESET}",
        f"{DIM}│░░░░░│{RESET}",
        f"{DIM}│░░░░░│{RESET}",
        f"{DIM}└─────┘{RESET}",
    ]

# ---------------------------------------------------------------------------
# Card / deck
# ---------------------------------------------------------------------------

def _new_deck(num_decks: int = 6) -> list[tuple[str, str]]:
    deck = [(r, s) for r in RANKS for s in SUITS] * num_decks
    random.shuffle(deck)
    return deck


def _hand_value(hand: list[tuple[str, str]]) -> int:
    total = sum(VALUES[r] for r, _ in hand)
    aces  = sum(1 for r, _ in hand if r == "A")
    while total > 21 and aces:
        total -= 10
        aces  -= 1
    return total


def _is_blackjack(hand: list[tuple[str, str]]) -> bool:
    return len(hand) == 2 and _hand_value(hand) == 21


def _is_bust(hand: list[tuple[str, str]]) -> bool:
    return _hand_value(hand) > 21

# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _draw_hand(
    buf: list[str],
    hand: list[tuple[str, str]],
    start_row: int,
    start_col: int,
    hide_first: bool = False,
    label: str = "",
    label_color: str = WHITE,
) -> None:
    """Render a hand of cards at the given position."""
    if label:
        buf.append(_go(start_row - 1, start_col) + label_color + BOLD + label + RESET)

    for idx, (rank, suit) in enumerate(hand):
        col = start_col + idx * (_CW + 1)
        if idx == 0 and hide_first:
            art = _back_art()
        else:
            art = _card_art(rank, suit)
        for row_off, line in enumerate(art):
            buf.append(_go(start_row + row_off, col) + line)


def _draw_chips(buf: list[str], row: int, col: int, chips: int, bet: int) -> None:
    chips_str = f"Chips: {BOLD}{YELLOW}{chips:>6}{RESET}"
    bet_str   = f"  Bet: {BOLD}{CYAN}{bet:>6}{RESET}"
    buf.append(_go(row, col) + chips_str + bet_str)


def _draw_value(buf: list[str], row: int, col: int, hand: list, hide: bool = False) -> None:
    if hide:
        buf.append(_go(row, col) + DIM + "   ?" + RESET)
    else:
        v = _hand_value(hand)
        color = RED if v > 21 else YELLOW if v == 21 else GREEN
        bust  = "  BUST!" if v > 21 else (" BLACKJACK!" if _is_blackjack(hand) else "")
        buf.append(_go(row, col) + color + BOLD + f"  {v}{RESET}" + RED + BOLD + bust + RESET)


def _centered_msg(row: int, term_cols: int, msg: str, plain: str, color: str = WHITE) -> str:
    col = max(1, (term_cols - len(plain)) // 2)
    return _go(row, col) + color + BOLD + msg + RESET


# ---------------------------------------------------------------------------
# Betting screen
# ---------------------------------------------------------------------------

def _bet_screen(
    fd: int, term_cols: int, term_lines: int,
    chips: int, wins: int, losses: int, pushes: int,
) -> int | None:
    """Show betting UI. Returns bet amount, or None to quit."""
    bet = min(10, chips)

    while True:
        buf: list[str] = []
        mid_r = term_lines // 2
        mid_c = term_cols  // 2

        title = "♠ BLACKJACK ♥"
        buf.append(_centered_msg(mid_r - 6, term_cols, title, title, GREEN))

        stats = f"W:{wins}  L:{losses}  P:{pushes}"
        buf.append(_centered_msg(mid_r - 5, term_cols, DIM + stats + RESET, stats, ""))

        chips_line = f"Chips: {chips}"
        buf.append(_centered_msg(mid_r - 3, term_cols,
                                 YELLOW + BOLD + chips_line + RESET, chips_line, ""))

        bet_line = f"Bet:   {bet}"
        buf.append(_centered_msg(mid_r - 1, term_cols,
                                 CYAN + BOLD + bet_line + RESET, bet_line, ""))

        hint = "↑/↓ adjust  ×2 double  [D]eal  [Q]uit"
        buf.append(_centered_msg(mid_r + 1, term_cols, DIM + hint + RESET, hint, ""))

        if chips <= 0:
            broke = "You're broke!  [Q] to quit"
            buf.append(_centered_msg(mid_r + 3, term_cols,
                                     RED + BOLD + broke + RESET, broke, ""))

        _write("".join(buf))

        k = _key(fd, _TICK)
        if k in (b"q", b"Q"):
            return None
        if chips <= 0:
            continue
        if k in (b"d", b"D", b"\r", b"\n"):
            return bet
        if k == b"\x1b":
            # arrow key
            seq = _key(fd, 0.05)
            if seq == b"[":
                arrow = _key(fd, 0.05)
                if arrow == b"A":   # up
                    bet = min(bet + 10, chips)
                elif arrow == b"B": # down
                    bet = max(1, bet - 10)
        if k in (b"u", b"U"):   # double
            bet = min(bet * 2, chips)


# ---------------------------------------------------------------------------
# Round result overlay
# ---------------------------------------------------------------------------

_RESULT_COLORS = {
    "blackjack": GREEN,
    "win":       GREEN,
    "push":      YELLOW,
    "lose":      RED,
    "bust":      RED,
}
_RESULT_LABELS = {
    "blackjack": "BLACKJACK! +{gain}",
    "win":       "YOU WIN +{gain}",
    "push":      "PUSH  ±0",
    "lose":      "DEALER WINS  -{loss}",
    "bust":      "BUST!  -{loss}",
}


def _show_result(buf: list[str], outcome: str, bet: int,
                 row: int, term_cols: int) -> None:
    color = _RESULT_COLORS.get(outcome, WHITE)
    gain  = int(bet * 1.5) if outcome == "blackjack" else bet
    label = _RESULT_LABELS.get(outcome, "").format(gain=gain, loss=bet)
    col   = max(1, (term_cols - len(label)) // 2)
    buf.append(_go(row, col) + color + BOLD + label + RESET)

# ---------------------------------------------------------------------------
# Main play function
# ---------------------------------------------------------------------------

def play(fd: int, term_cols: int, term_lines: int) -> None:
    """Run the blackjack game."""
    sys.stdout.write("\033[?7l\033[2J\033[H")
    sys.stdout.flush()

    chips   = 500
    wins    = 0
    losses  = 0
    pushes  = 0
    deck: list[tuple[str, str]] = []

    # Layout rows
    dealer_label_row = 4
    dealer_row       = 5
    player_label_row = dealer_row + _CH + 3
    player_row       = player_label_row + 1
    status_row       = player_row + _CH + 1
    chips_row        = term_lines - 2

    while True:
        # ── betting phase ────────────────────────────────────────────────────
        sys.stdout.write("\033[2J")
        sys.stdout.flush()
        bet = _bet_screen(fd, term_cols, term_lines, chips, wins, losses, pushes)
        if bet is None:
            break

        # ── deal ─────────────────────────────────────────────────────────────
        if len(deck) < 52:
            deck = _new_deck()

        player: list[tuple[str, str]] = [deck.pop(), deck.pop()]
        dealer: list[tuple[str, str]] = [deck.pop(), deck.pop()]

        sys.stdout.write("\033[2J")
        sys.stdout.flush()

        start_col = max(2, (term_cols - (_CW + 1) * 5) // 2)

        def redraw(hide_dealer: bool = True, outcome: str = "") -> None:
            buf: list[str] = []
            # Dealer
            _draw_hand(buf, dealer, dealer_row, start_col,
                       hide_first=hide_dealer,
                       label="Dealer", label_color=RED)
            _draw_value(buf, dealer_label_row, start_col + 10,
                        dealer, hide=hide_dealer)
            # Player
            _draw_hand(buf, player, player_row, start_col,
                       label="You", label_color=GREEN)
            _draw_value(buf, player_label_row, start_col + 6, player)
            # Chips / bet
            _draw_chips(buf, chips_row, start_col, chips, bet)
            # Outcome
            if outcome:
                _show_result(buf, outcome, bet, status_row, term_cols)
            else:
                hint = "[H]it  [S]tand  [D]ouble  [Q]uit"
                buf.append(_go(status_row, max(1, (term_cols - len(hint)) // 2))
                           + DIM + hint + RESET)
            _write("".join(buf))

        # ── check immediate blackjack ─────────────────────────────────────────
        if _is_blackjack(player):
            redraw(hide_dealer=False, outcome="blackjack")
            chips += int(bet * 1.5)
            wins  += 1
            _key(fd, 2.0)
            continue

        # ── player turn ───────────────────────────────────────────────────────
        doubled    = False
        stood      = False
        player_out = ""   # "bust" if player busted mid-turn

        while not stood and not player_out:
            redraw(hide_dealer=True)

            k = _key(fd, _TICK)
            if k in (b"q", b"Q"):
                sys.stdout.write("\033[?7h")
                sys.stdout.flush()
                return

            if k in (b"h", b"H"):
                player.append(deck.pop())
                if _is_bust(player):
                    player_out = "bust"

            elif k in (b"s", b"S"):
                stood = True

            elif k in (b"d", b"D") and len(player) == 2 and not doubled:
                actual_extra = min(bet, chips - bet)
                bet    += actual_extra
                doubled = True
                player.append(deck.pop())
                if _is_bust(player):
                    player_out = "bust"
                else:
                    stood = True

        if player_out == "bust":
            chips   -= bet
            losses  += 1
            redraw(hide_dealer=False, outcome="bust")
            _key(fd, 2.0)
            continue

        # ── dealer turn ───────────────────────────────────────────────────────
        # Reveal dealer card, then dealer draws to 17
        redraw(hide_dealer=False)
        time.sleep(0.6)

        while _hand_value(dealer) < 17:
            dealer.append(deck.pop())
            redraw(hide_dealer=False)
            time.sleep(0.4)

        # ── outcome ───────────────────────────────────────────────────────────
        pv = _hand_value(player)
        dv = _hand_value(dealer)

        if _is_bust(dealer) or pv > dv:
            outcome  = "win"
            chips   += bet
            wins    += 1
        elif pv < dv:
            outcome  = "lose"
            chips   -= bet
            losses  += 1
        else:
            outcome  = "push"
            pushes  += 1

        redraw(hide_dealer=False, outcome=outcome)
        _key(fd, 2.0)

    sys.stdout.write("\033[?7h")
    sys.stdout.flush()
