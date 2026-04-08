#!/usr/bin/env python3
"""lsgpu — list connected GPUs in a terminal grid with ASCII art."""

import argparse
import os
import random
import re
import select
import shutil
import signal
import subprocess
import sys
import time
import tty
import termios
from dataclasses import dataclass, field
from typing import Optional

from ansi import RESET, BOLD, DIM, GREEN, CYAN, YELLOW, RED, BLUE, WHITE, strip_ansi
from themes import THEME_REGISTRY
from themes.base import Theme
from entities import ENTITY_REGISTRY
from entities.base import EntitySpec, Entity, spawn, overlay
from spotify import SpotifyClient, SpotifyPoller


# ── GPU ASCII art templates ───────────────────────────────────────────────────

GPU_ART_NVIDIA = r"""
  ___________________________________________
 |  .---.  NVIDIA  ______________________   |
 | /     \        |:::::::::::::::::::::: |  |
 |( CHIP  )       |:::::::::::::::::::::: |  |
 | \     /        |::__________________:: |  |
 |  '---'         |__|  PCIe x16        |_|  |
 |___________________________________________|
""".strip().splitlines()

GPU_ART_AMD = r"""
  ___________________________________________
 |  .---.   AMD    ______________________   |
 | /     \        |:::::::::::::::::::::: |  |
 |( CHIP  )       |:::::::::::::::::::::: |  |
 | \     /        |::__________________:: |  |
 |  '---'         |__|  PCIe x16        |_|  |
 |___________________________________________|
""".strip().splitlines()

GPU_ART_INTEL = r"""
  ___________________________________________
 |  .---.  Intel   ______________________   |
 | /     \        |:::::::::::::::::::::: |  |
 |( CHIP  )       |:::::::::::::::::::::: |  |
 | \     /        |::__________________:: |  |
 |  '---'         |__|  PCIe x16        |_|  |
 |___________________________________________|
""".strip().splitlines()

GPU_ART_GENERIC = r"""
  ___________________________________________
 |  .---.   GPU    ______________________   |
 | /     \        |:::::::::::::::::::::: |  |
 |( CHIP  )       |:::::::::::::::::::::: |  |
 | \     /        |::__________________:: |  |
 |  '---'         |__|  PCIe x16        |_|  |
 |___________________________________________|
""".strip().splitlines()

VENDOR_COLOURS = {"nvidia": GREEN, "amd": RED, "intel": BLUE}
SPINNER        = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
FPS            = 12


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class GPUInfo:
    index: int
    name: str
    vendor: str
    vram_total_mib: Optional[int] = None
    vram_used_mib:  Optional[int] = None
    temp_c:         Optional[int] = None
    util_pct:       Optional[int] = None
    driver:         Optional[str] = None
    pcie_width:     Optional[int] = None
    art: list[str]  = field(default_factory=list)


# ── GPU detection ─────────────────────────────────────────────────────────────

def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL,
                                       text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _parse_mib(s: str) -> Optional[int]:
    try:
        return int(s.strip().replace(" MiB", "").replace("MiB", ""))
    except ValueError:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s.strip().replace(" %", "").replace("%", ""))
    except ValueError:
        return None


def detect_nvidia() -> list[GPUInfo]:
    fields = ["index", "name", "memory.total", "memory.used",
              "temperature.gpu", "utilization.gpu",
              "driver_version", "pcie.link.width.current"]
    out = _run(["nvidia-smi",
                f"--query-gpu={','.join(fields)}",
                "--format=csv,noheader,nounits"])
    if not out:
        return []
    gpus = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        idx, name, mem_total, mem_used, temp, util, driver, pcie = parts[:8]
        gpus.append(GPUInfo(
            index=int(idx) if idx.isdigit() else len(gpus),
            name=name, vendor="nvidia",
            vram_total_mib=_parse_mib(mem_total),
            vram_used_mib=_parse_mib(mem_used),
            temp_c=_parse_int(temp), util_pct=_parse_int(util),
            driver=driver, pcie_width=_parse_int(pcie),
            art=GPU_ART_NVIDIA[:],
        ))
    return gpus


def detect_lspci_integrated() -> list[GPUInfo]:
    out = _run(["lspci"])
    if not out:
        return []
    gpus, seen = [], set()
    for line in out.splitlines():
        lower = line.lower()
        if "vga compatible" not in lower and "display controller" not in lower:
            continue
        if "nvidia" in lower:
            continue
        pci_id = line.split()[0]
        if pci_id in seen:
            continue
        seen.add(pci_id)
        desc = line.split(":", 2)[-1].strip()
        if (re.search(r'\bamd\b', lower) or re.search(r'\bati\b', lower)
                or "radeon" in lower or "advanced micro devices" in lower):
            vendor, art = "amd",     GPU_ART_AMD[:]
        elif "intel" in lower:
            vendor, art = "intel",   GPU_ART_INTEL[:]
        else:
            vendor, art = "unknown", GPU_ART_GENERIC[:]
        gpus.append(GPUInfo(index=len(gpus), name=desc, vendor=vendor, art=art))
    return gpus


def _enrich_amd_vram(gpus: list[GPUInfo]) -> None:
    amd = [g for g in gpus if g.vendor == "amd"]
    if not amd:
        return
    out = _run(["rocm-smi", "--showmeminfo", "vram", "--csv"])
    if not out:
        return
    rows: list[tuple[int, int, int]] = []
    for line in out.splitlines():
        if not line.strip() or line.startswith("GPU"):
            continue
        parts = line.split(",")
        if len(parts) >= 3:
            try:
                rows.append((int(parts[0].strip()),
                             int(parts[1].strip()) // (1024 * 1024),
                             int(parts[2].strip()) // (1024 * 1024)))
            except (ValueError, IndexError):
                pass
    for i, (_, used, total) in enumerate(rows):
        if i < len(amd):
            amd[i].vram_used_mib  = used
            amd[i].vram_total_mib = total


def collect_gpus() -> list[GPUInfo]:
    gpus = detect_nvidia() + detect_lspci_integrated()
    _enrich_amd_vram(gpus)
    for i, g in enumerate(gpus):
        g.index = i
    return gpus


# ── Card rendering ────────────────────────────────────────────────────────────

def _bar(used: int, total: int, width: int = 20) -> str:
    pct    = used / total if total else 0.0
    filled = int(pct * width)
    colour = GREEN if pct < 0.6 else YELLOW if pct < 0.85 else RED
    return f"{colour}{'█' * filled}{'░' * (width - filled)}{RESET}"


def _temp_colour(t: int) -> str:
    return GREEN if t < 50 else YELLOW if t < 75 else RED


def render_card(gpu: GPUInfo, card_width: int) -> list[str]:
    colour = VENDOR_COLOURS.get(gpu.vendor, WHITE)
    inner  = card_width - 2
    lines: list[str] = []

    def border_top():
        return f"{colour}╔{'═' * inner}╗{RESET}"

    def border_bot():
        return f"{colour}╚{'═' * inner}╝{RESET}"

    def border_row(content: str):
        pad = inner - len(strip_ansi(content))
        if pad < 0:
            content, pad = content[:inner], 0
        return f"{colour}║{RESET}{content}{' ' * pad}{colour}║{RESET}"

    lines.append(border_top())

    name_display = gpu.name
    if len(name_display) > inner - 5:
        name_display = name_display[:inner - 6] + "…"
    lines.append(border_row(
        f" {colour}{BOLD}[{gpu.index}]{RESET} {BOLD}{name_display}{RESET}"
    ))
    lines.append(border_row(f"{colour}{'─' * inner}{RESET}"))

    art_lines = gpu.art
    art_w = max(len(l) for l in art_lines) if art_lines else 0
    for art_line in art_lines:
        pad_left = max(0, (inner - art_w) // 2)
        clipped  = art_line[:inner - pad_left]
        lines.append(border_row(" " * pad_left + f"{colour}{clipped}{RESET}"))

    lines.append(border_row(f"{colour}{'─' * inner}{RESET}"))

    bar_w = max(10, inner - 24)
    if gpu.vram_total_mib is not None and gpu.vram_used_mib is not None:
        bar = _bar(gpu.vram_used_mib, gpu.vram_total_mib, bar_w)
        lines.append(border_row(
            f" VRAM {bar} {CYAN}{gpu.vram_used_mib:>5}{RESET}"
            f"/{gpu.vram_total_mib}{DIM} MiB{RESET}"
        ))
    elif gpu.vram_total_mib is not None:
        lines.append(border_row(f" VRAM {CYAN}{gpu.vram_total_mib} MiB{RESET}"))
    else:
        lines.append(border_row(f" VRAM {DIM}N/A{RESET}"))

    if gpu.util_pct is not None:
        lines.append(border_row(
            f" UTIL {_bar(gpu.util_pct, 100, bar_w)} {CYAN}{gpu.util_pct:>3}{RESET}%"
        ))
    else:
        lines.append(border_row(f" UTIL {DIM}N/A{RESET}"))

    if gpu.temp_c is not None:
        lines.append(border_row(f" TEMP {_temp_colour(gpu.temp_c)}{gpu.temp_c}°C{RESET}"))
    else:
        lines.append(border_row(f" TEMP {DIM}N/A{RESET}"))

    info_parts = []
    if gpu.driver:
        info_parts.append(f"Driver {DIM}{gpu.driver}{RESET}")
    if gpu.pcie_width:
        info_parts.append(f"PCIe x{gpu.pcie_width}")
    lines.append(border_row(" " + "  ".join(info_parts) if info_parts else ""))

    lines.append(border_bot())
    return lines


# ── Grid / header / footer ────────────────────────────────────────────────────

MIN_CARD_WIDTH = 48


def compute_grid(n_gpus: int, term_cols: int) -> tuple[int, int]:
    best_cols, best_w = 1, min(term_cols, 100)
    for cols in range(1, n_gpus + 1):
        w = (term_cols - (cols - 1)) // cols
        if w < MIN_CARD_WIDTH:
            break
        best_cols, best_w = cols, w
    return best_cols, best_w


def render_grid(gpus: list[GPUInfo], term_cols: int, frame: int = 0) -> str:
    if not gpus:
        return f"{YELLOW}No GPUs detected.{RESET}\n"
    cols, card_w = compute_grid(len(gpus), term_cols)
    rendered = [render_card(g, card_w) for g in gpus]
    out: list[str] = []
    for row_start in range(0, len(gpus), cols):
        row_cards = rendered[row_start:row_start + cols]
        max_h     = max(len(c) for c in row_cards)
        padded    = [c + [" " * card_w] * (max_h - len(c)) for c in row_cards]
        for li in range(max_h):
            out.append(" ".join(c[li] for c in padded))
    return "\n".join(out) + "\n"


def render_header(gpus: list[GPUInfo], term_cols: int, frame: int = 0) -> str:
    n     = len(gpus)
    spin  = SPINNER[frame % len(SPINNER)]
    title = f" {spin} lsgpu — {n} {'GPU' if n == 1 else 'GPUs'} detected {spin} "
    pad   = max(0, term_cols - len(title)) // 2
    line  = "─" * term_cols
    return (f"{CYAN}{line}{RESET}\n"
            f"{' ' * pad}{BOLD}{CYAN}{title}{RESET}\n"
            f"{CYAN}{line}{RESET}\n")


def render_footer(term_cols: int, last_poll_ago: float) -> str:
    body = (f" {GREEN}●{RESET} {BOLD}LIVE{RESET}  "
            f"updated {last_poll_ago:.1f}s ago   "
            f"{DIM}[q]{RESET} quit  {DIM}[/]{RESET} command ")
    pad  = max(0, term_cols - len(strip_ansi(body)))
    line = "─" * term_cols
    return f"{CYAN}{line}{RESET}\n{body}{' ' * pad}\n"


_SPOTIFY_BRAILLE = [
    "⠀⠀⣀⣴⣶⣾⣿⣷⣶⣦⣀⠀⠀",
    "⢀⣼⣿⠿⠿⠿⠿⠿⣿⣿⣿⣧⡀",
    "⣸⣿⣧⣶⠶⠶⠶⣶⣤⣌⣙⣿⣇",
    "⢿⣿⣿⣶⠶⠶⠶⣶⣤⣍⣿⣿⡿",
    "⠸⣿⣿⣶⣶⣿⣷⣶⣮⣽⣿⣿⠇",
    "⠀⠘⠿⣿⣿⣿⣿⣿⣿⣿⠿⠃⠀",
    "⠀⠀⠀⠈⠉⠙⠛⠋⠉⠁⠀⠀⠀",
]
_BRAILLE_W = 13                    # visible cols per logo row
_LEFT_COL  = _BRAILLE_W + 2       # 15: 1 margin + 13 logo + 1 gap


def render_spotify_widget(
    track: "dict | None",
    connected: bool,
    term_cols: int,
) -> str:
    colour  = GREEN
    width   = min(72, max(52, term_cols - 2))
    inner   = width - 2
    right_w = inner - _LEFT_COL    # chars available for track info column

    def _t(s: str, max_len: int) -> str:
        return s if len(s) <= max_len else s[:max_len - 1] + "…"

    def top(): return f"{colour}╔{'═' * inner}╗{RESET}"
    def bot(): return f"{colour}╚{'═' * inner}╝{RESET}"

    def row(lp: str, lc: str, rp: str, rc: str = "") -> str:
        """lp/rp = plain (for width); lc/rc = colored (to emit)."""
        rpad = max(0, right_w - len(rp))
        body = lc + (rc if rc else rp) + " " * rpad
        return f"{colour}║{RESET}{body}{colour}║{RESET}"

    # ── build right-column lines depending on state ───────────────────────────
    right_rows: list[tuple[str, str]] = []
    if not connected:
        right_rows = [
            ("", ""),
            (f" Not connected",      f" {DIM}Not connected{RESET}"),
            (f" /connect-spotify",   f" {DIM}/connect-spotify{RESET}"),
        ]
    elif track is None:
        right_rows = [
            ("", ""),
            (f" Nothing playing",    f" {DIM}Nothing playing{RESET}"),
        ]
    else:
        status = "▶" if track["is_playing"] else "⏸"
        title  = _t(track["title"],  right_w - 4)
        artist = _t(track["artist"], right_w - 2)
        album  = _t(track["album"],  right_w - 2)
        prog   = track["progress_ms"]
        dur    = track["duration_ms"]
        p_str  = f"{prog // 60000}:{(prog // 1000) % 60:02d}"
        d_str  = f"{dur  // 60000}:{(dur  // 1000) % 60:02d}"
        time_s = f"{p_str}/{d_str}"
        bar_w  = max(4, right_w - len(time_s) - 3)
        filled = int((prog / dur) * bar_w)
        bar_p  = f" {'█' * filled}{'░' * (bar_w - filled)} {time_s}"
        bar_c  = f" {GREEN}{'█' * filled}{'░' * (bar_w - filled)}{RESET} {DIM}{time_s}{RESET}"
        right_rows = [
            ("", ""),
            (f" {status} {title}",   f" {GREEN}{status}{RESET} {BOLD}{title}{RESET}"),
            (f"  {artist}",          f"  {DIM}{artist}{RESET}"),
        ]
        if album:
            right_rows.append((f"  {album}", f"  {DIM}{album}{RESET}"))
        right_rows.append((bar_p, bar_c))

    # ── assemble rows: logo rows (0-6) + label row (7) ────────────────────────
    n_logo  = len(_SPOTIFY_BRAILLE)          # 7
    n_total = max(n_logo + 1, len(right_rows))
    lines   = [top()]

    for i in range(n_total):
        # left column
        if i < n_logo:
            lp = " " + _SPOTIFY_BRAILLE[i] + " "
            lc = f" {GREEN}{_SPOTIFY_BRAILLE[i]}{RESET} "
        elif i == n_logo:
            label = f"{'Spotify':^{_BRAILLE_W}}"   # "   Spotify   " (13 chars)
            lp = " " + label + " "
            lc = f" {BOLD}{GREEN}{label}{RESET} "
        else:
            lp = " " * _LEFT_COL
            lc = lp

        # right column
        rp, rc = right_rows[i] if i < len(right_rows) else ("", "")

        lines.append(row(lp, lc, rp, rc))

    lines.append(bot())
    return "\n".join(lines) + "\n"


def render_cmd_footer(term_cols: int, cmd_buf: str, error: str = "") -> str:
    line = f"{CYAN}{'─' * term_cols}{RESET}"
    if error:
        body = f" {RED}✗ {error}{RESET}"
    else:
        body = f" {CYAN}/{cmd_buf}█{RESET}"
    pad = max(0, term_cols - len(strip_ansi(body)))
    return f"{line}\n{body}{' ' * pad}\n"


# ── Fire effect ───────────────────────────────────────────────────────────────

FIRE_ROWS   = 5          # terminal rows consumed at the bottom of the screen
_FIRE_PROWS = FIRE_ROWS * 2   # pixel-rows (▄ gives 2 per terminal row)
_FIRE_COOL  = 50.0       # cooling per step — must be high enough to reach 0 over ~8 rows


def _fire_rgb(v: int) -> tuple[int, int, int]:
    v = max(0, min(255, v))
    if v < 85:
        return (v * 3, 0, 0)
    elif v < 170:
        return (255, (v - 85) * 3, 0)
    else:
        return (255, 255, (v - 170) * 3)


def fire_init(width: int) -> list[list[float]]:
    w   = max(1, width)
    buf = [[0.0] * w for _ in range(_FIRE_PROWS)]
    buf[-1] = [255.0] * w
    buf[-2] = [220.0] * w
    return buf


def fire_step(buf: list[list[float]]) -> None:
    h, w = len(buf), len(buf[0])
    for y in range(h - 2):
        for x in range(w):
            v = (buf[y + 1][x] +
                 buf[y + 1][(x - 1) % w] +
                 buf[y + 1][(x + 1) % w] +
                 buf[y + 2][x]) / 4.0
            v -= random.random() * _FIRE_COOL
            buf[y][x] = max(0.0, v)
    # Randomise the source row so distinct flame tongues form
    for x in range(w):
        buf[-1][x] = 210.0 + random.random() * 45.0
        buf[-2][x] = 160.0 + random.random() * 60.0


def fire_render(buf: list[list[float]], term_cols: int, term_lines: int) -> str:
    """Return cursor-positioned escape sequences for the fire strip.

    Deduplicates consecutive cells with the same colour pair to keep output
    small (~5-10× reduction vs naïve per-cell sequences).
    """
    w   = min(term_cols, len(buf[0]))
    out = []
    for row in range(FIRE_ROWS):
        term_row = term_lines - FIRE_ROWS + row + 1   # 1-indexed
        out.append(f"\033[{term_row};1H")
        py_top  = row * 2
        py_bot  = row * 2 + 1
        last_bg = last_fg = None
        for x in range(w):
            bg = _fire_rgb(int(buf[py_top][x]))
            fg = _fire_rgb(int(buf[py_bot][x]))
            if bg != last_bg:
                out.append(f"\033[48;2;{bg[0]};{bg[1]};{bg[2]}m")
                last_bg = bg
            if fg != last_fg:
                out.append(f"\033[38;2;{fg[0]};{fg[1]};{fg[2]}m")
                last_fg = fg
            out.append("\u2584")
        out.append("\033[0m")
    return "".join(out)


# ── TUI ───────────────────────────────────────────────────────────────────────

def execute_command(
    cmd: str,
    theme: Theme,
    entities: list[Entity],
    entity_specs: list[EntitySpec],
    fire_enabled: bool,
    spotify_enabled: bool,
    term_cols: int,
    term_lines: int,
) -> "tuple[Theme, list[Entity], list[EntitySpec], bool, bool] | str":
    """Parse and execute a TUI command. Returns updated state tuple or error string."""
    parts = cmd.split()
    if not parts:
        return (theme, entities, entity_specs, fire_enabled, spotify_enabled)
    name = parts[0].lower()

    def _ok(**kw):
        return (
            kw.get("theme",           theme),
            kw.get("entities",        entities),
            kw.get("entity_specs",    entity_specs),
            kw.get("fire_enabled",    fire_enabled),
            kw.get("spotify_enabled", spotify_enabled),
        )

    if name == "change-theme":
        if len(parts) < 2:
            return f"usage: change-theme <name>  known: {', '.join(THEME_REGISTRY)}"
        t = parts[1]
        if t not in THEME_REGISTRY:
            return f"unknown theme {t!r}  known: {', '.join(THEME_REGISTRY)}"
        return _ok(theme=THEME_REGISTRY[t])

    elif name == "change-theme-random":
        return _ok(theme=random.choice(list(THEME_REGISTRY.values())))

    elif name == "killall":
        return _ok(entities=[], entity_specs=[])

    elif name == "kill":
        if len(parts) < 2:
            return "usage: kill <entity-name>"
        target    = parts[1]
        new_ents  = [e for e in entities     if e.spec.name != target]
        new_specs = [s for s in entity_specs if s.name      != target]
        if len(new_ents) == len(entities):
            return f"no live entity named {target!r}"
        return _ok(entities=new_ents, entity_specs=new_specs)

    elif name == "spawn":
        if len(parts) < 2:
            return f"usage: spawn <entity> [qty]  known: {', '.join(ENTITY_REGISTRY)}"
        ent_name = parts[1]
        if ent_name not in ENTITY_REGISTRY:
            return f"unknown entity {ent_name!r}  known: {', '.join(ENTITY_REGISTRY)}"
        qty = 1
        if len(parts) >= 3:
            try:
                qty = max(1, int(parts[2]))
            except ValueError:
                return f"invalid quantity {parts[2]!r}"
        spec     = ENTITY_REGISTRY[ent_name]
        new_ents = entities + [
            spawn(spec, term_cols, term_lines, phase=i * 7) for i in range(qty)
        ]
        return _ok(entities=new_ents, entity_specs=entity_specs + [spec] * qty)

    elif name == "fire":
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            return "usage: fire <on|off>"
        return _ok(fire_enabled=parts[1].lower() == "on")

    elif name == "spotify":
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            return "usage: spotify <on|off>"
        return _ok(spotify_enabled=parts[1].lower() == "on")

    elif name == "connect-spotify":
        return "__CONNECT_SPOTIFY__"

    else:
        return (f"unknown command {name!r}  "
                "try: change-theme, change-theme-random, killall, kill, "
                "spawn, fire, spotify, connect-spotify")


def _read_key(fd: int, timeout: float) -> str:
    """Read one keypress from raw fd, bypassing Python's buffered IO."""
    if not select.select([fd], [], [], timeout)[0]:
        return ""
    data = os.read(fd, 1)
    if data == b"\x1b":
        # Drain the rest of any escape sequence (arrow keys etc.)
        while select.select([fd], [], [], 0.02)[0]:
            os.read(fd, 32)
        return "\x1b"
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _tui_exit(fd: int, old_term) -> None:
    termios.tcsetattr(fd, termios.TCSADRAIN, old_term)
    sys.stdout.write("\033[?1049l\033[?25h\033[0m")
    sys.stdout.flush()


def _tui_enter(fd: int) -> None:
    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    sys.stdout.flush()
    tty.setraw(fd)


def run_tui(theme: Theme, entity_specs: list[EntitySpec],
            fire_enabled: bool = False,
            spotify_enabled: bool = False) -> None:
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    _tui_enter(fd)
    signal.signal(signal.SIGWINCH, lambda *_: None)

    frame           = 0
    gpus: list[GPUInfo]    = []
    entities: list[Entity] = []
    last_poll       = 0.0
    spawned         = False
    cmd_mode        = False
    cmd_buf         = ""
    cmd_error       = ""
    fire_buf: list[list[float]] = []
    fire_width      = 0

    spotify_client  = SpotifyClient()
    spotify_poller: "SpotifyPoller | None" = None

    def _ensure_poller():
        nonlocal spotify_poller
        if spotify_enabled and spotify_poller is None:
            spotify_poller = SpotifyPoller(spotify_client)

    def _stop_poller():
        nonlocal spotify_poller
        if spotify_poller is not None:
            spotify_poller.stop()
            spotify_poller = None

    try:
        while True:
            now  = time.monotonic()
            term = shutil.get_terminal_size()

            if not spawned:
                entities = [spawn(spec, term.columns, term.lines, phase=i * 7)
                            for i, spec in enumerate(entity_specs)]
                spawned = True

            if fire_enabled and (not fire_buf or fire_width != term.columns):
                fire_buf   = fire_init(term.columns)
                fire_width = term.columns

            if now - last_poll >= 1.0:
                gpus      = collect_gpus()
                last_poll = now

            if fire_enabled and fire_buf:
                fire_step(fire_buf)

            _ensure_poller()
            if not spotify_enabled:
                _stop_poller()

            track = spotify_poller.get() if spotify_poller else None

            poll_age = time.monotonic() - last_poll
            header   = theme.apply(render_header(gpus, term.columns, frame), frame)
            grid     = theme.apply(render_grid(gpus,   term.columns, frame), frame)

            if spotify_enabled:
                spotify_box = render_spotify_widget(
                    track, spotify_client.is_connected(), term.columns
                )
            else:
                spotify_box = ""

            if cmd_mode:
                footer = render_cmd_footer(term.columns, cmd_buf, cmd_error)
            else:
                footer = theme.apply(render_footer(term.columns, poll_age), frame)

            grid_part = "\033[H" + header + grid + spotify_box + "\033[J"
            footer_part = (
                f"\033[{term.lines - 1};1H"
                + footer
                + overlay(entities, frame)
            )
            sys.stdout.write(grid_part.replace("\r\n", "\n").replace("\n", "\r\n"))
            if fire_enabled and fire_buf:
                sys.stdout.write(fire_render(fire_buf, term.columns, term.lines))
            sys.stdout.write(footer_part.replace("\r\n", "\n").replace("\n", "\r\n"))
            sys.stdout.flush()

            for e in entities:
                e.tick(term.columns, term.lines)
            frame += 1

            ch = _read_key(fd, 1.0 / FPS)

            if cmd_mode:
                if ch in ("\r", "\n"):
                    result = execute_command(
                        cmd_buf.strip(), theme, entities, entity_specs,
                        fire_enabled, spotify_enabled, term.columns, term.lines,
                    )
                    if result == "__CONNECT_SPOTIFY__":
                        # Temporarily leave TUI, run OAuth, come back
                        _tui_exit(fd, old)
                        ok, msg = spotify_client.connect()
                        print(f"\n{msg}")
                        input("\nPress Enter to return to lsgpu…")
                        old = termios.tcgetattr(fd)
                        _tui_enter(fd)
                        cmd_mode = False
                        cmd_buf  = cmd_error = ""
                    elif isinstance(result, str):
                        cmd_error = result
                        cmd_buf   = ""
                    else:
                        theme, entities, entity_specs, fire_enabled, spotify_enabled = result
                        if fire_enabled and (not fire_buf or fire_width != term.columns):
                            fire_buf   = fire_init(term.columns)
                            fire_width = term.columns
                        cmd_mode = False
                        cmd_buf  = cmd_error = ""
                elif ch == "\x1b":
                    cmd_mode = False
                    cmd_buf  = cmd_error = ""
                elif ch in ("\x7f", "\x08"):
                    cmd_buf   = cmd_buf[:-1]
                    cmd_error = ""
                elif ch == "\x15":
                    cmd_buf   = ""
                    cmd_error = ""
                elif ch and ch.isprintable():
                    cmd_buf  += ch
                    cmd_error = ""
            else:
                if ch in ("q", "Q", "\x03", "\x1b"):
                    break
                elif ch == "/":
                    cmd_mode = True
                    cmd_buf  = cmd_error = ""

    except KeyboardInterrupt:
        pass
    finally:
        _stop_poller()
        _tui_exit(fd, old)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lsgpu",
        description="List connected GPUs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("themes:   " + ", ".join(THEME_REGISTRY) + "\n"
                "entities: " + ", ".join(ENTITY_REGISTRY)),
    )
    parser.add_argument("--theme", default="default", metavar="NAME",
                        help="display theme (default: default)")
    parser.add_argument("--entities", default="", metavar="a,b,c",
                        help="comma-separated entity names to bounce on screen")
    parser.add_argument("--entities-random", type=int, default=0, metavar="N",
                        help="spawn N randomly chosen entities")
    parser.add_argument("--fire", action="store_true",
                        help="enable fire animation along the bottom of the screen")
    parser.add_argument("--connect-spotify", action="store_true",
                        help="run Spotify OAuth flow and save credentials, then exit")
    parser.add_argument("--spotify", action="store_true",
                        help="show Spotify now-playing widget")
    args = parser.parse_args()

    theme = THEME_REGISTRY.get(args.theme)
    if theme is None:
        parser.error(f"unknown theme {args.theme!r}. known: {', '.join(THEME_REGISTRY)}")

    entity_specs: list[EntitySpec] = []
    if args.entities:
        for name in args.entities.split(","):
            name = name.strip()
            if name not in ENTITY_REGISTRY:
                parser.error(f"unknown entity {name!r}. known: {', '.join(ENTITY_REGISTRY)}")
            entity_specs.append(ENTITY_REGISTRY[name])
    if args.entities_random > 0:
        entity_specs += random.choices(list(ENTITY_REGISTRY.values()),
                                       k=args.entities_random)

    if args.connect_spotify:
        ok, msg = SpotifyClient().connect()
        print(msg)
        sys.exit(0 if ok else 1)

    if sys.stdout.isatty():
        run_tui(theme, entity_specs,
                fire_enabled=args.fire,
                spotify_enabled=args.spotify)
    else:
        term   = shutil.get_terminal_size(fallback=(80, 24))
        gpus   = collect_gpus()
        output = render_header(gpus, term.columns) + render_grid(gpus, term.columns)
        print(theme.apply(output, 0), end="")


if __name__ == "__main__":
    main()
