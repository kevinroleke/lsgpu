#!/usr/bin/env python3
"""lsgpu — list connected GPUs in a terminal grid with ASCII art."""

import argparse
import re
import shutil
import subprocess
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


def _rainbow_esc(col: int, row: int) -> str:
    """24-bit foreground colour cycling diagonally through the rainbow."""
    hue = (col * 4 + row * 8) % 360
    r, g, b = _hsv_to_rgb(hue)
    return f"\033[38;2;{r};{g};{b}m"


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

def rainbowize(text: str) -> str:
    """
    Strip all colour codes from text and re-paint every non-space
    character with a position-based rainbow colour.
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
                # keep only bold (1) and dim (2); drop colour codes
                kept = [p for p in inner.split(";") if p in ("1", "2")]
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
                result.append(_rainbow_esc(col, row))
            result.append(ch)
            col += 1
            i += 1
    return "".join(result)


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
    for art_line in art_lines:
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


def render_grid(gpus: list[GPUInfo], term_cols: int) -> str:
    if not gpus:
        return f"{YELLOW}No GPUs detected.{RESET}\n"

    cols, card_w = compute_grid(len(gpus), term_cols)

    # Render each card
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

def render_header(gpus: list[GPUInfo], term_cols: int) -> str:
    n = len(gpus)
    noun = "GPU" if n == 1 else "GPUs"
    title = f" lsgpu — {n} {noun} detected "
    pad = max(0, term_cols - len(title)) // 2
    line = "─" * term_cols
    return (
        f"{CYAN}{line}{RESET}\n"
        f"{' ' * pad}{BOLD}{CYAN}{title}{RESET}\n"
        f"{CYAN}{line}{RESET}\n"
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(prog="lsgpu", description="List connected GPUs")
    parser.add_argument("--rainbow", action="store_true",
                        help="Paint output in glorious rainbow colours")
    args = parser.parse_args()

    term = shutil.get_terminal_size(fallback=(80, 24))
    term_cols = term.columns

    gpus = collect_gpus()

    output = render_header(gpus, term_cols) + render_grid(gpus, term_cols)
    if args.rainbow:
        output = rainbowize(output)
    print(output, end="")


if __name__ == "__main__":
    main()
