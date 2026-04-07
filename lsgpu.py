#!/usr/bin/env python3
"""lsgpu — list connected GPUs in a terminal grid with ASCII art."""

import argparse
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


# ── ASCII art templates ──────────────────────────────────────────────────────

# Each art block is a list of lines; all lines must be the same length.
# Width is used for layout calculations.

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

ART_ROWS = len(GPU_ART_NVIDIA)   # all templates share the same height
SPINNER  = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
FPS      = 12                    # target frames per second

# ANSI colours
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
RED    = "\033[31m"
BLUE   = "\033[34m"
MAGENTA= "\033[35m"
WHITE  = "\033[37m"
DIM    = "\033[2m"

VENDOR_COLOURS = {
    "nvidia": GREEN,
    "amd":    RED,
    "intel":  BLUE,
}

# ── Rainbow ───────────────────────────────────────────────────────────────────

def _hsv_to_rgb(h: float) -> tuple[int, int, int]:
    """Hue in [0, 360) → (R, G, B) each in [0, 255]."""
    h = h % 360
    c = 1.0
    x = c * (1 - abs((h / 60) % 2 - 1))
    if   h < 60:  r, g, b = c, x, 0.0
    elif h < 120: r, g, b = x, c, 0.0
    elif h < 180: r, g, b = 0.0, c, x
    elif h < 240: r, g, b = 0.0, x, c
    elif h < 300: r, g, b = x, 0.0, c
    else:         r, g, b = c, 0.0, x
    return int(r * 255), int(g * 255), int(b * 255)


def _rainbow_esc(col: int, row: int, offset: float = 0.0) -> str:
    """24-bit foreground colour cycling diagonally through the rainbow."""
    hue = (col * 4 + row * 8 + offset) % 360
    r, g, b = _hsv_to_rgb(hue)
    return f"\033[38;2;{r};{g};{b}m"


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

def rainbowize(text: str, offset: float = 0.0) -> str:
    """
    Strip all colour codes from text and re-paint every non-space
    character with a position-based rainbow colour.
    offset shifts the hue globally so callers can animate it over time.
    Non-colour attributes (bold, dim, reset) are preserved.
    """
    result: list[str] = []
    row = col = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\033" and i + 1 < len(text) and text[i + 1] == "[":
            # consume ANSI escape
            m = _ANSI_RE.match(text, i)
            if m:
                seq = m.group()
                inner = seq[2:-1]
                # keep only bold (1), dim (2), reverse (7); drop colour codes
                kept = [p for p in inner.split(";") if p in ("1", "2", "7")]
                if kept:
                    result.append(f"\033[{';'.join(kept)}m")
                i += len(seq)
            else:
                result.append(ch)
                i += 1
        elif ch == "\n":
            result.append(RESET + "\n")
            row += 1
            col = 0
            i += 1
        else:
            if ch != " ":
                result.append(_rainbow_esc(col, row, offset))
            result.append(ch)
            col += 1
            i += 1
    return "".join(result)


# ── Themes ────────────────────────────────────────────────────────────────────

def _rgb(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


def _theme_walk(text: str, color_fn) -> str:
    """
    Walk rendered text, strip colour codes (preserve bold/dim/reverse),
    and re-colour every non-space character using color_fn(col, row) -> str.
    """
    result: list[str] = []
    row = col = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\033" and i + 1 < len(text) and text[i + 1] == "[":
            m = _ANSI_RE.match(text, i)
            if m:
                inner = m.group()[2:-1]
                kept = [p for p in inner.split(";") if p in ("1", "2", "7")]
                if kept:
                    result.append(f"\033[{';'.join(kept)}m")
                i += len(m.group())
            else:
                result.append(ch)
                i += 1
        elif ch == "\n":
            result.append(RESET + "\n")
            row += 1
            col = 0
            i += 1
        else:
            if ch != " ":
                result.append(color_fn(col, row))
            result.append(ch)
            col += 1
            i += 1
    return "".join(result)


class Theme:
    """Base display theme. Subclass, set name, override apply(), add to THEME_REGISTRY."""
    name: str = "default"

    def apply(self, text: str, frame: int) -> str:
        return text


class RainbowTheme(Theme):
    name = "rainbow"

    def apply(self, text: str, frame: int) -> str:
        return rainbowize(text, frame * 3.0)


class MatrixTheme(Theme):
    """Digital-rain green; a band of bright columns sweeps across each frame."""
    name = "matrix"
    _STRIDE = 19

    def apply(self, text: str, frame: int) -> str:
        bright_base = (frame // 2) * 3
        stride = self._STRIDE
        def color(col, row):
            if ((col - bright_base) % stride) < 2:
                return "\033[1m" + _rgb(0, 255, 65)
            return _rgb(0, 185, 45)
        return _theme_walk(text, color)


class FourTwentyTheme(Theme):
    """Cannabis greens and purples rolling in a slow haze."""
    name = "420"

    def apply(self, text: str, frame: int) -> str:
        def color(col, row):
            p = (col * 3 + row * 6 + frame) % 80
            if p < 50:
                g = 130 + int(p * 2.5)
                return _rgb(25, g, 45)
            else:
                v = 80 + int((p - 50) * 3.5)
                return _rgb(v, 10, v + 55)
        return _theme_walk(text, color)


class AmericaTheme(Theme):
    """Red, white, and blue horizontal stripes that slowly scroll."""
    name = "america"
    _RED  = _rgb(178, 34,  52)   # Old Glory Red
    _BLUE = _rgb(60,  59, 110)   # Old Glory Blue
    # white rows use RESET so they show in the terminal's own foreground colour

    def apply(self, text: str, frame: int) -> str:
        red, blue = self._RED, self._BLUE
        shift = frame // 8
        def color(col, row):
            s = (row + shift) % 3
            if s == 0: return red
            if s == 2: return blue
            return RESET     # middle stripe: terminal default = readable on any bg
        return _theme_walk(text, color)


class ChinaTheme(Theme):
    """Red field with golden columns shifting across like scattered stars."""
    name = "china"
    _RED  = _rgb(222, 41,  16)
    _GOLD = _rgb(255, 215,  0)

    def apply(self, text: str, frame: int) -> str:
        gold_col = (frame // 3) % 20
        red, gold = self._RED, self._GOLD
        def color(col, row):
            return gold if col % 20 == gold_col else red
        return _theme_walk(text, color)


class CanadaTheme(Theme):
    """Red side-stripes with a neutral centre, like the maple-leaf flag."""
    name = "canada"
    _RED = _rgb(255, 0, 28)

    def apply(self, text: str, frame: int) -> str:
        red = self._RED
        def color(col, row):
            # 1:2:1 proportions — every 40 cols: 10 red | 20 default | 10 red
            band = (col // 10) % 4
            return red if band in (0, 3) else RESET
        return _theme_walk(text, color)


class IsraelTheme(Theme):
    """Blue stripes top and bottom with a neutral centre, like the Israeli flag."""
    name = "israel"
    _BLUE = _rgb(0, 56, 184)

    def apply(self, text: str, frame: int) -> str:
        blue = self._BLUE
        def color(col, row):
            r = row % 9
            return blue if (r < 2 or r >= 7) else RESET
        return _theme_walk(text, color)


class ChristmasTheme(Theme):
    """Festive red and green with occasional gold sparkles."""
    name = "christmas"
    _RED   = _rgb(220,  20,  60)
    _GREEN = _rgb(0,   154,  23)
    _GOLD  = _rgb(255, 215,   0)

    def apply(self, text: str, frame: int) -> str:
        red, green, gold = self._RED, self._GREEN, self._GOLD
        def color(col, row):
            if (col + row * 3 + frame // 4) % 22 == 0:
                return gold
            return red if (col + row) % 4 < 2 else green
        return _theme_walk(text, color)


class HalloweenTheme(Theme):
    """Spooky orange and purple with flickers of ghostly yellow."""
    name = "halloween"
    _ORANGE = _rgb(255, 102,   0)
    _PURPLE = _rgb(102,   0, 153)
    _YELLOW = _rgb(255, 230,   0)

    def apply(self, text: str, frame: int) -> str:
        orange, purple, yellow = self._ORANGE, self._PURPLE, self._YELLOW
        def color(col, row):
            p = (col * 2 + row * 3 + frame) % 14
            if p == 0:
                return yellow
            return orange if p < 7 else purple
        return _theme_walk(text, color)


THEME_REGISTRY: dict[str, Theme] = {
    t.name: t for t in (
        Theme(), RainbowTheme(), MatrixTheme(), FourTwentyTheme(),
        AmericaTheme(), ChinaTheme(), CanadaTheme(), IsraelTheme(),
        ChristmasTheme(), HalloweenTheme(),
    )
}


# ── Entities ──────────────────────────────────────────────────────────────────

@dataclass
class EntitySpec:
    """Static definition of an entity type: frames of ASCII art + display colour."""
    name:   str
    frames: list[list[str]]
    color:  str

    @property
    def width(self) -> int:
        return max(len(line) for frame in self.frames for line in frame)

    @property
    def height(self) -> int:
        return max(len(frame) for frame in self.frames)


@dataclass
class Entity:
    """Live instance of an EntitySpec with position and velocity."""
    spec:  EntitySpec
    x:     float
    y:     float
    dx:    float
    dy:    float
    phase: int = 0   # frame offset so clones animate out of sync

    def current_frame(self, tick: int) -> list[str]:
        idx = (tick // 4 + self.phase) % len(self.spec.frames)
        return self.spec.frames[idx]

    def tick(self, cols: int, rows: int) -> None:
        max_x = max(0, cols  - self.spec.width  - 1)
        max_y = max(0, rows  - self.spec.height - 3)   # -3 reserves footer
        self.x += self.dx
        self.y += self.dy
        if self.x <= 0:        self.x = 0.0;          self.dx =  abs(self.dx)
        elif self.x >= max_x:  self.x = float(max_x); self.dx = -abs(self.dx)
        if self.y <= 0:        self.y = 0.0;          self.dy =  abs(self.dy)
        elif self.y >= max_y:  self.y = float(max_y); self.dy = -abs(self.dy)


def _spawn(spec: EntitySpec, cols: int, rows: int, phase: int = 0) -> Entity:
    max_x = max(1, cols - spec.width  - 1)
    max_y = max(1, rows - spec.height - 3)
    return Entity(
        spec=spec,
        x=float(random.randint(0, max_x)),
        y=float(random.randint(0, max_y)),
        dx=random.uniform(0.25, 0.55) * random.choice([-1, 1]),
        dy=random.uniform(0.15, 0.40) * random.choice([-1, 1]),
        phase=phase,
    )



def _overlay(entities: list[Entity], tick: int) -> str:
    """Build a string of cursor-move + art sequences to stamp entities on screen."""
    buf: list[str] = []
    for e in entities:
        for i, line in enumerate(e.current_frame(tick)):
            row = int(e.y) + i + 1   # 1-based
            col = int(e.x) + 1
            buf.append(f"\033[{row};{col}H{e.spec.color}{line}{RESET}")
    return "".join(buf)


# ── Entity registry ───────────────────────────────────────────────────────────

ENTITY_REGISTRY: dict[str, EntitySpec] = {}

def _reg(spec: EntitySpec) -> EntitySpec:
    ENTITY_REGISTRY[spec.name] = spec
    return spec

_reg(EntitySpec("ufo", color=CYAN, frames=[
    [
        '   .-"-.  ',
        ' _/ o  o\\_',
        '(=========)',
        " `-------' ",
    ],
    [
        '   .-"-.  ',
        ' _/* ** *\\_',
        '(=========)',
        " `-------' ",
    ],
]))

_reg(EntitySpec("ghost", color=WHITE, frames=[
    [
        "  .-.  ",
        " (o o) ",
        "  )=(  ",
        " /   \\ ",
        "/`---'\\",
    ],
    [
        "  .-.  ",
        " (- -) ",
        "  )=(  ",
        " /   \\ ",
        "|_/ \\_|",
    ],
]))

_reg(EntitySpec("tux", color=WHITE, frames=[
    [
        "  .--. ",
        " (o  o)",
        "  |=|  ",
        " /   \\ ",
        "(_____)",
    ],
]))

_reg(EntitySpec("dvd", color=MAGENTA, frames=[
    [
        ".------.",
        "| D V D|",
        "`------'",
    ],
]))

_reg(EntitySpec("ship", color=YELLOW, frames=[
    [
        "  /\\  ",
        " /  \\ ",
        "/----\\",
        "\\    /",
        " >++< ",
    ],
    [
        "  /\\  ",
        " /  \\ ",
        "/----\\",
        "\\    /",
        " >**< ",
    ],
]))

_reg(EntitySpec("crab", color=RED, frames=[
    [
        " /Y\\ /Y\\ ",
        "(o  ~  o)",
        " \\_ ^ _/ ",
        "  |   |  ",
    ],
    [
        " \\Y/ \\Y/ ",
        "(o  ~  o)",
        " /- ^ -\\ ",
        "  |   |  ",
    ],
]))


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class GPUInfo:
    index: int
    name: str
    vendor: str          # "nvidia" | "amd" | "intel" | "unknown"
    vram_total_mib: Optional[int] = None
    vram_used_mib:  Optional[int] = None
    temp_c:         Optional[int] = None
    util_pct:       Optional[int] = None
    driver:         Optional[str] = None
    pcie_width:     Optional[int] = None
    art: list[str]  = field(default_factory=list)


# ── GPU detection ────────────────────────────────────────────────────────────

def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL,
                                       text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _parse_mib(s: str) -> Optional[int]:
    s = s.strip().replace(" MiB", "").replace("MiB", "")
    try:
        return int(s)
    except ValueError:
        return None


def _parse_int(s: str) -> Optional[int]:
    s = s.strip().replace(" %", "").replace("%", "")
    try:
        return int(s)
    except ValueError:
        return None


def detect_nvidia() -> list[GPUInfo]:
    """Query nvidia-smi for all NVIDIA GPUs."""
    fields = [
        "index", "name", "memory.total", "memory.used",
        "temperature.gpu", "utilization.gpu",
        "driver_version", "pcie.link.width.current",
    ]
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
        g = GPUInfo(
            index=int(idx) if idx.isdigit() else len(gpus),
            name=name,
            vendor="nvidia",
            vram_total_mib=_parse_mib(mem_total),
            vram_used_mib=_parse_mib(mem_used),
            temp_c=_parse_int(temp),
            util_pct=_parse_int(util),
            driver=driver,
            pcie_width=_parse_int(pcie),
            art=GPU_ART_NVIDIA[:],
        )
        gpus.append(g)
    return gpus


def detect_lspci_integrated() -> list[GPUInfo]:
    """Detect integrated / non-NVIDIA GPUs from lspci."""
    out = _run(["lspci"])
    if not out:
        return []
    gpus = []
    seen_indices: set[str] = set()
    for line in out.splitlines():
        lower = line.lower()
        if "vga compatible" not in lower and "display controller" not in lower:
            continue
        # skip NVIDIA — already handled
        if "nvidia" in lower:
            continue
        pci_id = line.split()[0]
        if pci_id in seen_indices:
            continue
        seen_indices.add(pci_id)

        # Extract description after ':'
        desc = line.split(":", 2)[-1].strip()

        if (re.search(r'\bamd\b', lower) or re.search(r'\bati\b', lower)
                or "radeon" in lower or "advanced micro devices" in lower):
            vendor = "amd"
            art = GPU_ART_AMD[:]
        elif "intel" in lower:
            vendor = "intel"
            art = GPU_ART_INTEL[:]
        else:
            vendor = "unknown"
            art = GPU_ART_GENERIC[:]

        gpus.append(GPUInfo(
            index=len(gpus),
            name=desc,
            vendor=vendor,
            art=art,
        ))
    return gpus


def _enrich_amd_vram(gpus: list[GPUInfo]) -> None:
    """Try rocm-smi to fill in VRAM for AMD GPUs."""
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
                rows.append((
                    int(parts[0].strip()),
                    int(parts[1].strip()) // (1024 * 1024),
                    int(parts[2].strip()) // (1024 * 1024),
                ))
            except (ValueError, IndexError):
                pass
    for rocm_idx, (_, used_mib, total_mib) in enumerate(rows):
        if rocm_idx < len(amd):
            amd[rocm_idx].vram_used_mib = used_mib
            amd[rocm_idx].vram_total_mib = total_mib


def collect_gpus() -> list[GPUInfo]:
    nvidia = detect_nvidia()
    integrated = detect_lspci_integrated()

    all_gpus = nvidia + integrated
    _enrich_amd_vram(all_gpus)

    for i, g in enumerate(all_gpus):
        g.index = i
    return all_gpus


# ── Card rendering ───────────────────────────────────────────────────────────

def _bar(used: int, total: int, width: int = 20) -> str:
    """Render a simple ASCII progress bar."""
    if total == 0:
        pct = 0.0
    else:
        pct = used / total
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    colour = GREEN if pct < 0.6 else YELLOW if pct < 0.85 else RED
    return f"{colour}{bar}{RESET}"


def _temp_colour(t: int) -> str:
    if t < 50:
        return GREEN
    if t < 75:
        return YELLOW
    return RED


def render_card(gpu: GPUInfo, card_width: int) -> list[str]:
    """
    Return a list of text lines representing one GPU card.
    Each line is exactly `card_width` visible characters wide
    (may contain ANSI escape sequences).
    """
    colour = VENDOR_COLOURS.get(gpu.vendor, WHITE)
    inner = card_width - 2  # subtract border chars

    lines: list[str] = []

    def border_top():
        return f"{colour}╔{'═' * inner}╗{RESET}"

    def border_bot():
        return f"{colour}╚{'═' * inner}╝{RESET}"

    def border_row(content: str, fill: str = " "):
        # content may contain ANSI; we need its *visible* length
        visible = _strip_ansi(content)
        pad = inner - len(visible)
        if pad < 0:
            # truncate
            content = content[:inner]
            pad = 0
        return f"{colour}║{RESET}{content}{fill * pad}{colour}║{RESET}"

    def section(text: str, col: str = BOLD):
        return border_row(f"{col}{text}{RESET}")

    def blank():
        return border_row("")

    # ── Top border
    lines.append(border_top())

    # ── GPU index + name
    name_display = gpu.name
    max_name = inner - 5
    if len(name_display) > max_name:
        name_display = name_display[:max_name - 1] + "…"
    lines.append(border_row(
        f" {colour}{BOLD}[{gpu.index}]{RESET} {BOLD}{name_display}{RESET}"
    ))
    lines.append(border_row(f"{colour}{'─' * inner}{RESET}"))

    # ── ASCII art (centred, clipped to inner width)
    art_lines = gpu.art
    art_w = max(len(l) for l in art_lines) if art_lines else 0
    for i, art_line in enumerate(art_lines):
        pad_left = max(0, (inner - art_w) // 2)
        clipped = art_line[:inner - pad_left]
        coloured = f"{colour}{clipped}{RESET}"
        lines.append(border_row(" " * pad_left + coloured))

    lines.append(border_row(f"{colour}{'─' * inner}{RESET}"))

    # ── VRAM bar (always present)
    bar_w = max(10, inner - 24)
    if gpu.vram_total_mib is not None and gpu.vram_used_mib is not None:
        bar = _bar(gpu.vram_used_mib, gpu.vram_total_mib, bar_w)
        vram_str = (
            f" VRAM {bar} "
            f"{CYAN}{gpu.vram_used_mib:>5}{RESET}/"
            f"{gpu.vram_total_mib}{DIM} MiB{RESET}"
        )
        lines.append(border_row(vram_str))
    elif gpu.vram_total_mib is not None:
        lines.append(border_row(
            f" VRAM {CYAN}{gpu.vram_total_mib} MiB{RESET}"
        ))
    else:
        lines.append(border_row(f" VRAM {DIM}N/A{RESET}"))

    # ── Utilisation (always present)
    if gpu.util_pct is not None:
        util_bar = _bar(gpu.util_pct, 100, bar_w)
        lines.append(border_row(
            f" UTIL {util_bar} {CYAN}{gpu.util_pct:>3}{RESET}%"
        ))
    else:
        lines.append(border_row(f" UTIL {DIM}N/A{RESET}"))

    # ── Temperature (always present)
    if gpu.temp_c is not None:
        tc = _temp_colour(gpu.temp_c)
        lines.append(border_row(f" TEMP {tc}{gpu.temp_c}°C{RESET}"))
    else:
        lines.append(border_row(f" TEMP {DIM}N/A{RESET}"))

    # ── Driver / PCIe (always present)
    info_parts = []
    if gpu.driver:
        info_parts.append(f"Driver {DIM}{gpu.driver}{RESET}")
    if gpu.pcie_width:
        info_parts.append(f"PCIe x{gpu.pcie_width}")
    lines.append(border_row(" " + "  ".join(info_parts) if info_parts else ""))

    lines.append(border_bot())
    return lines


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


# ── Grid layout ──────────────────────────────────────────────────────────────

MIN_CARD_WIDTH = 48

def compute_grid(n_gpus: int, term_cols: int) -> tuple[int, int]:
    """Return (columns, card_width) that best fills the terminal."""
    best_cols = 1
    best_w = min(term_cols, 100)

    for cols in range(1, n_gpus + 1):
        gap = cols - 1  # single space gap between cards
        w = (term_cols - gap) // cols
        if w < MIN_CARD_WIDTH:
            break
        best_cols = cols
        best_w = w

    return best_cols, best_w


def render_grid(gpus: list[GPUInfo], term_cols: int, frame: int = 0) -> str:
    if not gpus:
        return f"{YELLOW}No GPUs detected.{RESET}\n"

    cols, card_w = compute_grid(len(gpus), term_cols)

    rendered = [render_card(g, card_w) for g in gpus]

    output_lines: list[str] = []

    for row_start in range(0, len(gpus), cols):
        row_cards = rendered[row_start:row_start + cols]

        # Pad shorter cards to same height
        max_h = max(len(c) for c in row_cards)
        padded = []
        for card in row_cards:
            pad_line = " " * card_w
            padded.append(card + [pad_line] * (max_h - len(card)))

        for line_idx in range(max_h):
            row_line = " ".join(c[line_idx] for c in padded)
            output_lines.append(row_line)

    return "\n".join(output_lines) + "\n"


# ── Header ───────────────────────────────────────────────────────────────────

def render_header(gpus: list[GPUInfo], term_cols: int, frame: int = 0) -> str:
    n = len(gpus)
    noun = "GPU" if n == 1 else "GPUs"
    spin = SPINNER[frame % len(SPINNER)]
    title = f" {spin} lsgpu — {n} {noun} detected {spin} "
    pad = max(0, term_cols - len(title)) // 2
    line = "─" * term_cols
    return (
        f"{CYAN}{line}{RESET}\n"
        f"{' ' * pad}{BOLD}{CYAN}{title}{RESET}\n"
        f"{CYAN}{line}{RESET}\n"
    )


def render_footer(term_cols: int, last_poll_ago: float) -> str:
    age = f"{last_poll_ago:.1f}s ago"
    dot = f"{GREEN}●{RESET}"
    hint = f"{DIM}[q / ESC / Ctrl-C]{RESET} quit"
    body = f" {dot} {BOLD}LIVE{RESET}  updated {age}   {hint} "
    pad = max(0, term_cols - len(_strip_ansi(body)))
    line = "─" * term_cols
    return (
        f"{CYAN}{line}{RESET}\n"
        f"{body}{' ' * pad}\n"
    )


# ── TUI ───────────────────────────────────────────────────────────────────────

def _read_key(timeout: float) -> str:
    """Return the next keypress within `timeout` seconds, or ''."""
    if not select.select([sys.stdin], [], [], timeout)[0]:
        return ""
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        # Drain any escape sequence that follows (arrow keys etc.)
        while select.select([sys.stdin], [], [], 0.02)[0]:
            sys.stdin.read(1)
    return ch


def run_tui(theme: Theme, entity_specs: list[EntitySpec]) -> None:
    """Full-screen animated TUI. Exits on q / ESC / Ctrl-C."""
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    sys.stdout.flush()

    signal.signal(signal.SIGWINCH, lambda *_: None)   # reread size each frame

    frame        = 0
    gpus: list[GPUInfo]     = []
    entities: list[Entity]  = []
    last_poll  = 0.0
    spawned    = False

    try:
        tty.setraw(fd)

        while True:
            now  = time.monotonic()
            term = shutil.get_terminal_size()

            # ── spawn entities once we know the terminal size ─────────────────
            if not spawned:
                entities = [
                    _spawn(spec, term.columns, term.lines, phase=i * 7)
                    for i, spec in enumerate(entity_specs)
                ]
                spawned = True

            # ── poll GPU stats every second ───────────────────────────────────
            if now - last_poll >= 1.0:
                gpus      = collect_gpus()
                last_poll = now

            poll_age = time.monotonic() - last_poll

            # ── build themed base ─────────────────────────────────────────────
            header = render_header(gpus, term.columns, frame)
            grid   = render_grid(gpus,   term.columns, frame)
            footer = render_footer(term.columns, poll_age)

            header = theme.apply(header, frame)
            grid   = theme.apply(grid,   frame)
            footer = theme.apply(footer, frame)

            footer_row = term.lines - 1

            output = (
                "\033[H"
                + header + grid
                + "\033[J"
                + f"\033[{footer_row};1H"
                + footer
                + _overlay(entities, frame)   # entities float on top
            )

            sys.stdout.write(output.replace("\r\n", "\n").replace("\n", "\r\n"))
            sys.stdout.flush()

            # ── tick entities ─────────────────────────────────────────────────
            for e in entities:
                e.tick(term.columns, term.lines)

            frame += 1

            ch = _read_key(1.0 / FPS)
            if ch in ("q", "Q", "\x03", "\x1b"):
                break

    except KeyboardInterrupt:
        pass

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\033[?1049l\033[?25h\033[0m")
        sys.stdout.flush()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lsgpu",
        description="List connected GPUs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "themes:   " + ", ".join(THEME_REGISTRY) + "\n"
            "entities: " + ", ".join(ENTITY_REGISTRY)
        ),
    )
    parser.add_argument(
        "--theme", default="default", metavar="NAME",
        help="display theme (default: default)",
    )
    parser.add_argument(
        "--entities", default="", metavar="a,b,c",
        help="comma-separated entity names to bounce on screen",
    )
    parser.add_argument(
        "--entities-random", type=int, default=0, metavar="N",
        help="spawn N randomly chosen entities",
    )
    args = parser.parse_args()

    # ── resolve theme ─────────────────────────────────────────────────────────
    theme = THEME_REGISTRY.get(args.theme)
    if theme is None:
        known = ", ".join(THEME_REGISTRY)
        parser.error(f"unknown theme {args.theme!r}. known: {known}")

    # ── resolve entities ──────────────────────────────────────────────────────
    entity_specs: list[EntitySpec] = []

    if args.entities:
        for name in args.entities.split(","):
            name = name.strip()
            if name not in ENTITY_REGISTRY:
                known = ", ".join(ENTITY_REGISTRY)
                parser.error(f"unknown entity {name!r}. known: {known}")
            entity_specs.append(ENTITY_REGISTRY[name])

    if args.entities_random > 0:
        pool = list(ENTITY_REGISTRY.values())
        entity_specs += random.choices(pool, k=args.entities_random)

    # ── run ───────────────────────────────────────────────────────────────────
    if sys.stdout.isatty():
        run_tui(theme, entity_specs)
    else:
        term   = shutil.get_terminal_size(fallback=(80, 24))
        gpus   = collect_gpus()
        output = render_header(gpus, term.columns) + render_grid(gpus, term.columns)
        output = theme.apply(output, 0)
        print(output, end="")


if __name__ == "__main__":
    main()
