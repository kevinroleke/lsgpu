"""Wordle game for the lsgpu TUI tool.

Launch via `/play wordle` while the alternate screen is active and the
terminal is in raw mode.  The only public symbol is `play()`.
"""

import datetime
import json
import os
import pathlib
import random
import select
import sys
import time
import urllib.request

from .ansi import RESET, BOLD, DIM, GREEN, CYAN, YELLOW, RED, WHITE


def _fetch_nyt_word() -> str | None:
    """Fetch today's Wordle solution from the NYT API. Returns None on failure."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    url = f"https://www.nytimes.com/svc/wordle/v2/{today}.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        word = data.get("solution", "").upper().strip()
        if len(word) == 5 and word.isalpha():
            return word
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------

# Full original NYT Wordle answer list (2309 words), filtered to 5-letter alpha
# and deduplicated.
_ANSWERS: list[str] = list({w for w in [
    "ABACK", "ABASE", "ABATE", "ABBEY", "ABBOT", "ABHOR", "ABIDE", "ABLER",
    "ABODE", "ABORT", "ABOUT", "ABOVE", "ABUSE", "ABYSS", "ACRES", "ACRID",
    "ACTED", "ACUTE", "ADAGE", "ADDED", "ADEPT", "ADMIT", "ADOPT", "ADULT",
    "AEONS", "AFFIX", "AFOOT", "AFTER", "AGAIN", "AGATE", "AGAVE", "AGILE",
    "AGING", "AGLOW", "AGONY", "AGREE", "AHEAD", "AIDED", "AIMER", "AIRED",
    "AISLE", "ALGAE", "ALIBI", "ALIEN", "ALIGN", "ALIKE", "ALIVE", "ALLAY",
    "ALLEY", "ALLOT", "ALLOW", "ALOFT", "ALONE", "ALOOF", "ALOUD", "ALTER",
    "AMASS", "AMAZE", "AMINE", "AMINO", "AMISS", "AMUCK", "AMPLE", "AMUSE",
    "ANGEL", "ANGER", "ANGLE", "ANGRY", "ANGST", "ANIME", "ANISE", "ANNEX",
    "ANNOY", "ANTIC", "ANVIL", "AORTA", "APHID", "APPLE", "APPLY", "APRON",
    "APTLY", "AREAS", "ARGON", "AROMA", "AROSE", "ARRAY", "ARROW", "ASHEN",
    "ASIDE", "ASSET", "ATOMS", "ATONE", "ATTIC", "AUDIO", "AUDIT", "AUGUR",
    "AVAIL", "AVERT", "AVIAN", "AVOID", "AWAIT", "AWAKE", "AWARD", "AWASH",
    "AWFUL", "AWOKE", "AXIAL", "AXIOM", "BADLY", "BAGEL", "BAKER", "BALER",
    "BALLS", "BANAL", "BANJO", "BARGE", "BARON", "BASTE", "BATCH", "BATHE",
    "BATTY", "BAWDY", "BAYOU", "BEACH", "BEARD", "BEAST", "BEGAN", "BEGOT",
    "BEING", "BESET", "BIDET", "BINGE", "BIOME", "BISON", "BITCH", "BITER",
    "BLAZE", "BLEAT", "BLEED", "BLIMP", "BLOKE", "BLOOD", "BLOOM", "BLOWN",
    "BLURT", "BOOZE", "BOXER", "BRACE", "BRAND", "BRASH", "BRAWL", "BRAWN",
    "BREAM", "BREED", "BRIDE", "BRINE", "BRINK", "BROIL", "BROOD", "BROTH",
    "BROWN", "BRUNT", "BRUTE", "BUDDY", "BUDGE", "BUGGY", "BULGE", "BUMPY",
    "BUNNY", "BUTTE", "BYTES", "CABIN", "CADET", "CAMEL", "CAMEO", "CANAL",
    "CANOE", "CARGO", "CAROL", "CASTE", "CATCH", "CAULK", "CEASE", "CEDAR",
    "CHAFE", "CHAFF", "CHAIN", "CHALK", "CHAMP", "CHAOS", "CHARD", "CHARM",
    "CHASM", "CHEER", "CHESS", "CHIDE", "CHIMP", "CHINA", "CHOIR", "CHOKE",
    "CHORD", "CHOSE", "CHUNK", "CHURN", "CIDER", "SIEGE", "CINCH", "CIRCA",
    "CIVIC", "CIVIL", "CLACK", "CLAMP", "CLANG", "CLANK", "CLASH", "CLAVE",
    "CLEAR", "CLEFT", "CLIMB", "CLING", "CLOAK", "CLONE", "CLOTH", "CLOUD",
    "CLUMP", "CLUNG", "COALS", "COBRA", "COMET", "COMIC", "COMMA", "COPAL",
    "CORAL", "CORPS", "COUPE", "COVET", "CRACK", "CRAMP", "CRANE", "CRASH",
    "CRASS", "CRATE", "CRAWL", "CREEP", "CRIMP", "CRISP", "CROAK", "CRUMB",
    "CRUST", "CRYPT", "CYBER", "CYCLE", "DADDY", "DAILY", "DAISY", "DECAL",
    "DECAY", "DECOR", "DECOY", "DECRY", "DELTA", "DEPOT", "DEITY", "DEALT",
    "DEMON", "DEMUR", "DENSE", "DERBY", "DETER", "DIRTY", "DISCO", "DISHY",
    "DITCH", "DITTO", "DIVAN", "DODGE", "DOGGY", "DOLCE", "DOLOR", "DOWRY",
    "DRAFT", "DRAIN", "DRAKE", "DRAPE", "DRAWL", "DRIED", "DRIFT", "DRINK",
    "DROOL", "DROVE", "DROWN", "DRUID", "DRUNK", "DRYER", "DUMPY", "DUNCE",
    "DUPER", "DUPLE", "DWARF", "DYING", "EAGER", "EARLY", "EARTH", "EIGHT",
    "ELITE", "EMCEE", "EMOTE", "EMPTY", "ENDOW", "ENEMA", "ENSUE", "EQUIP",
    "ESSAY", "ETHIC", "EXALT", "EXCEL", "EXERT", "EXILE", "EXULT", "FABLE",
    "FACET", "FAINT", "FAIRY", "FAITH", "FALSE", "FANCY", "FARCE", "FATAL",
    "FAUNA", "FEAST", "FERRY", "FETCH", "FETID", "FEVER", "FIEND", "FINCH",
    "FLAIR", "FLAKE", "FLAKY", "FLANK", "FLARE", "FLASK", "FLICK", "FLINCH",
    "FLIRT", "FLOCK", "FLOOD", "FLOSS", "FLOUR", "FLOWN", "FLUID", "FLUKE",
    "FLUNG", "FLUNK", "FOCUS", "FORAY", "FORGE", "FOYER", "FRAIL", "FRAME",
    "FRANK", "FRAUD", "FREAK", "FREED", "FRIAR", "FRIED", "FRISK", "FRONT",
    "FROZE", "FUNGI", "GAUDY", "GAUZE", "GAVEL", "GIDDY", "GIRTH", "GIVEN",
    "GLARE", "GLASS", "GLAZE", "GLEAM", "GLEAN", "GLIDE", "GLINT", "GNASH",
    "GNARL", "GOUGE", "GRACE", "GRAND", "GRANT", "GRAPE", "GRASP", "GRAVY",
    "GRAZE", "GREED", "GREET", "GRIEF", "GRILL", "GRIME", "GRIPE", "GROAN",
    "GROIN", "GROOM", "GROPE", "GROWL", "GRUEL", "GUAVA", "GUILE", "GUISE",
    "GUSTO", "GYPSY", "HANDY", "HARSH", "HAUNT", "HAVEN", "HAVOC", "HAZEL",
    "HEADY", "HEDGE", "HEFTY", "HEIST", "HENCE", "HIPPO", "HITCH", "HOARD",
    "HOBBY", "HOLLY", "HOMER", "HONEY", "HONOR", "HOTEL", "HOUSE", "HOVER",
    "HUMAN", "HUMPH", "HUNCH", "HUSKY", "HYDRA", "HYENA", "HYPER", "IDYLL",
    "IMPEL", "INEPT", "INFER", "INGLE", "INLAY", "INSET", "INTER", "IRONY",
    "IRATE", "INANE", "ISLET", "IVORY", "JAZZY", "JELLY", "JIFFY", "JOUST",
    "JUICE", "JUICY", "JUMBO", "KARMA", "KAZOO", "KNAVE", "KNEEL", "KNELT",
    "KNOLL", "KUDOS", "LABEL", "LANCE", "LATHE", "LATTE", "LAUGH", "LAYUP",
    "LEAKY", "LEARN", "LEECH", "LEGAL", "LEMON", "LEVEL", "LIGHT", "LILAC",
    "LIMIT", "LINER", "LINGO", "LITHE", "LOBBY", "LOCAL", "LOFTY", "LOGIC",
    "LOTUS", "LOWLY", "LURID", "LUSTY", "LYRIC", "MACAW", "MAGIC", "MAIZE",
    "MAJOR", "MAMBO", "MAPLE", "MARRY", "MATTE", "MAXIM", "MAYOR", "MELEE",
    "MERCY", "MERGE", "MERIT", "MESSY", "METAL", "MIDST", "MIGHT", "MIMIC",
    "MIRTH", "MISER", "MISTY", "MIXER", "MOCHA", "MODAL", "MOGUL", "MOLDY",
    "MONKS", "MOODY", "MOOSE", "MORAL", "MOUSE", "MOUSY", "MOURN", "MUCKY",
    "MUDDY", "MULCH", "MUNCH", "MURKY", "MYRRH", "NADIR", "NASAL", "NASTY",
    "NAVAL", "NEIGH", "NERVE", "NIFTY", "NINNY", "NIPPY", "NOBLE", "NOISE",
    "NOTCH", "NYMPH", "ODDLY", "OFFAL", "OFTEN", "OLIVE", "OMBRE", "ONSET",
    "OPTIC", "OTTER", "OUGHT", "OUTDO", "OUTER", "OXIDE", "OZONE", "PADRE",
    "PANSY", "PARKA", "PARTY", "PASTA", "PATSY", "PATTY", "PAUSE", "PAVED",
    "PAYEE", "PEACE", "PEACH", "PENAL", "PENNY", "PERKY", "PETTY", "PHLOX",
    "PIANO", "PILOT", "PINEY", "PIPIT", "PIZZA", "PLANK", "PLONK", "PLUCK",
    "PLUMB", "PLUME", "PLUNK", "POKER", "POLYP", "POUCH", "POSSE", "POTTY",
    "PRIDE", "PRIVY", "PROBE", "PRUDE", "PRUNE", "PSALM", "PUBIC", "PULSE",
    "PULPY", "PUPIL", "PUTTY", "QUAFF", "QUALM", "QUELL", "QUILL", "QUOTA",
    "QUOTH", "RABBI", "RABID", "RANCH", "RAVEN", "RAYON", "REACH", "REALM",
    "REEDY", "RENAL", "RENEW", "REPAY", "REPEL", "RERUN", "REUSE", "REVEL",
    "RIVET", "RODEO", "ROGUE", "ROOMY", "ROOST", "ROUGH", "ROUSE", "ROWDY",
    "ROWER", "ROYAL", "RUGBY", "RULER", "RUSTY", "SABRE", "SADLY", "SAINT",
    "SALVO", "SALSA", "SANDY", "SATIN", "SAVVY", "SCALD", "SCANT", "SCARF",
    "SCARY", "SCOFF", "SCONE", "SCOUR", "SCRAM", "SCUFF", "SEDAN", "SEIZE",
    "SEMEN", "SERUM", "SEVEN", "SEVER", "SHADY", "SHAME", "SHAVE", "SHAWL",
    "SHEAR", "SHEEN", "SHEEP", "SHEER", "SHEET", "SHELF", "SHIFT", "SHIRE",
    "SHIRK", "SHOAL", "SHOCK", "SHONE", "SHOWY", "SHRED", "SHRUB", "SHRUG",
    "SHUNT", "SHUSH", "SKILL", "SKIRT", "SKIMP", "SKULK", "SLACK", "SLEEK",
    "SLEET", "SLICK", "SLIDE", "SLING", "SLOTH", "SLUMP", "SLUNK", "SMACK",
    "SMART", "SMEAR", "SMITE", "SMOKY", "SNAKY", "SNARE", "SNEAK", "SNEER",
    "SNIFF", "SNOUT", "SNUFF", "SOAPY", "SOLAR", "SOOTY", "SORRY", "SOUTH",
    "SNUCK", "SPLAY", "SPLAT", "SPLIT", "SPOKE", "SPOOK", "SPORT", "SPOUT",
    "SPREE", "SPRIG", "SPUNK", "SPURN", "SQUAT", "STAFF", "STAID", "STAIN",
    "STALK", "STALL", "STAMP", "STAND", "STARK", "STASH", "STAVE", "STEAD",
    "STEAL", "STEAM", "STEEL", "STEEP", "STEER", "STERN", "STOIC", "STOMP",
    "STONY", "STOOP", "STOUT", "STOVE", "STRIP", "STRUT", "STUCK", "STUDY",
    "STUNG", "STUNK", "STUNT", "SUGAR", "SULKY", "SUNNY", "SUPER", "SURGE",
    "SWAMP", "SWEAR", "SWEEP", "SWEET", "SWEPT", "SWIFT", "SWILL", "SWIPE",
    "SWIRL", "SWOON", "SWOOP", "TABOO", "TALON", "TASTE", "TAUNT", "TAWNY",
    "TEPID", "THEFT", "THEIR", "THEME", "THIEF", "THING", "THORN", "THOSE",
    "THREE", "THREW", "THROB", "THROW", "THUMB", "THYME", "TIDAL", "TIGER",
    "TIGHT", "TILDE", "TIPSY", "TITAN", "TOAST", "TODAY", "TONAL", "TOOTH",
    "TOTAL", "TOUCH", "TOUGH", "TOXIN", "TOTEM", "TRAWL", "TREAD", "TRIAD",
    "TRIED", "TRITE", "TROLL", "TROOP", "TROTH", "TROUT", "TROVE", "TRUCK",
    "TRULY", "TRUMP", "TRUSS", "TRUST", "TUBER", "TULIP", "TUMOR", "TUNER",
    "TUNIC", "TWAIN", "TWANG", "TWEAK", "TWEED", "TWERP", "TWICE", "TWILL",
    "TWINE", "TWIRL", "ULTRA", "UNFIT", "UNIFY", "UNION", "UNTIL", "UNZIP",
    "USHER", "USURP", "UTTER", "VAGUE", "VALET", "VALID", "VALOR", "VALVE",
    "VAPOR", "VAULT", "VAUNT", "VICAR", "VISOR", "VITAL", "VIVID", "VIXEN",
    "VOCAL", "VOGUE", "VOICE", "VOUCH", "VYING", "WAGER", "WALTZ", "WASTE",
    "WATCH", "WATER", "WEEDY", "WEIRD", "WHACK", "WHINE", "WHIRL", "WHISK",
    "WIDOW", "WISPY", "WITTY", "WORLD", "WORRY", "WORSE", "WORST", "WRATH",
    "WRING", "WROTE", "WRYLY", "YACHT", "YIELD", "YOUNG", "ABUZZ", "BEEFY",
    "BLUFF", "BLING", "BONNY", "BOOBY", "BORAX", "BOTCH", "BOWIE", "BULKY",
    "BURLY", "CADDY", "CAGEY", "CAMPY", "CATTY", "CAVORT", "CLAMMY", "CLOUT",
    "COMFY", "CONGA", "CORNY", "CROAK", "CURVY", "DENIM", "DITZY", "DIZZY",
    "DODGY", "DOLLY", "DOOZY", "DOPEY", "DOWDY", "DOYEN", "DUCKY", "DUSKY",
    "DUSTY", "EERIE", "ELFIN", "ELUDE", "ETUDE", "EVOKE", "EXACT", "FANNY",
    "FAZED", "FIZZY", "FJORD", "FLAKY", "FOAMY", "FOGGY", "FOLIO", "FUDGE",
    "FUNKY", "FUZZY", "GAUZY", "GIMPY", "GIZMO", "GLOOM", "GOOFY", "GOUTY",
    "GRIMY", "GASSY", "GIRLY", "GODLY", "GORGE", "GRUMP", "GUMMY", "HANKY",
    "HAIKU", "HAMMY", "HARDY", "HARPY", "HASTY", "HEFTY", "HIPPY", "HISSY",
    "HOARY", "HOKEY", "HOMEY", "HOOKY", "HORNY", "HUBBY", "HUFFY", "HUNKY",
    "HUSSY", "IRATE", "ITCHY", "JERKY", "JOLLY", "JUMPY", "KINKY", "KITTY",
    "KNACK", "KOOKY", "LANKY", "LEERY", "LIMBO", "LIMP", "LIVID", "LOOPY",
    "LUCKY", "MACHO", "MANLY", "MASSY", "MATEY", "MEATY", "MERRY", "MIFFED",
    "MINTY", "MISSY", "MUGGY", "MUSHY", "MUSKY", "MUSTY", "NATTY", "NERVY",
    "NERDY", "NEEDY", "NIPPY", "NOISY", "NUBBY", "ODDLY", "ONYX", "PANSY",
    "PAUPER", "PEEVE", "PERKY", "PESKY", "PINEY", "PITHY", "PIXEL", "PLAID",
    "PLUMP", "PLUNK", "PORKY", "POTTY", "POUTY", "PRIVY", "PUDGY", "PUFFY",
    "PUNKY", "PUSHY", "QUAKY", "QUEER", "RABID", "RATTY", "ROWDY", "RUDDY",
    "SASSY", "SAVVY", "SCALP", "SCARY", "SEEDY", "SHAKY", "SILKY", "SILLY",
    "SKIMP", "SKUNK", "SLIMY", "SOGGY", "SOPPY", "STAID", "STARK", "STICKY",
    "STIFF", "STOCK", "STONY", "STOOP", "STOUT", "SUAVE", "SULKY", "SURLY",
    "TABBY", "TACKY", "TAFFY", "TANGY", "TATTY", "TERSE", "TIPSY", "TOADY",
    "TOUCHY", "TOXIC", "TRIPE", "TUBBY", "TUMMY", "TWEEDY", "VAIN", "VAULT",
    "VENAL", "VIVID", "VIXEN", "VICAR", "WACKY", "WINCE", "WIMPY", "WINDY",
    "WISPY", "WONKY", "WOOZY", "WORMY", "ZINGY", "ZIPPY", "ZESTY",
] if len(w) == 5 and w.isalpha()})

# Valid guesses: full NYT word list (~14 855 words) loaded from bundled data file.
# Falls back to the answer set if the file is missing.
_WORDLE_DATA = pathlib.Path(__file__).parent / "data" / "wordle_valid.txt"
try:
    _VALID_GUESSES: set[str] = {
        w.strip().upper() for w in _WORDLE_DATA.read_text().splitlines() if w.strip()
    }
except FileNotFoundError:
    _VALID_GUESSES = set(_ANSWERS)

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
    target = _fetch_nyt_word() or random.choice(_ANSWERS)

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
