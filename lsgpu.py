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

from ansi import RESET, BOLD, DIM, GREEN, CYAN, YELLOW, RED, BLUE, WHITE, strip_ansi
from themes import THEME_REGISTRY
from themes.base import Theme
from entities import ENTITY_REGISTRY
from entities.base import EntitySpec, Entity, spawn, overlay


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
            f"{DIM}[q / ESC / Ctrl-C]{RESET} quit ")
    pad  = max(0, term_cols - len(strip_ansi(body)))
    line = "─" * term_cols
    return f"{CYAN}{line}{RESET}\n{body}{' ' * pad}\n"


# ── TUI ───────────────────────────────────────────────────────────────────────

def _read_key(timeout: float) -> str:
    if not select.select([sys.stdin], [], [], timeout)[0]:
        return ""
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        while select.select([sys.stdin], [], [], 0.02)[0]:
            sys.stdin.read(1)
    return ch


def run_tui(theme: Theme, entity_specs: list[EntitySpec]) -> None:
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    sys.stdout.flush()
    signal.signal(signal.SIGWINCH, lambda *_: None)

    frame    = 0
    gpus: list[GPUInfo]    = []
    entities: list[Entity] = []
    last_poll = 0.0
    spawned   = False

    try:
        tty.setraw(fd)
        while True:
            now  = time.monotonic()
            term = shutil.get_terminal_size()

            if not spawned:
                entities = [spawn(spec, term.columns, term.lines, phase=i * 7)
                            for i, spec in enumerate(entity_specs)]
                spawned = True

            if now - last_poll >= 1.0:
                gpus      = collect_gpus()
                last_poll = now

            poll_age = time.monotonic() - last_poll
            header   = theme.apply(render_header(gpus, term.columns, frame), frame)
            grid     = theme.apply(render_grid(gpus,   term.columns, frame), frame)
            footer   = theme.apply(render_footer(term.columns, poll_age),    frame)

            output = (
                "\033[H"
                + header + grid
                + "\033[J"
                + f"\033[{term.lines - 1};1H"
                + footer
                + overlay(entities, frame)
            )
            sys.stdout.write(output.replace("\r\n", "\n").replace("\n", "\r\n"))
            sys.stdout.flush()

            for e in entities:
                e.tick(term.columns, term.lines)
            frame += 1

            if _read_key(1.0 / FPS) in ("q", "Q", "\x03", "\x1b"):
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
        epilog=("themes:   " + ", ".join(THEME_REGISTRY) + "\n"
                "entities: " + ", ".join(ENTITY_REGISTRY)),
    )
    parser.add_argument("--theme", default="default", metavar="NAME",
                        help="display theme (default: default)")
    parser.add_argument("--entities", default="", metavar="a,b,c",
                        help="comma-separated entity names to bounce on screen")
    parser.add_argument("--entities-random", type=int, default=0, metavar="N",
                        help="spawn N randomly chosen entities")
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

    if sys.stdout.isatty():
        run_tui(theme, entity_specs)
    else:
        term   = shutil.get_terminal_size(fallback=(80, 24))
        gpus   = collect_gpus()
        output = render_header(gpus, term.columns) + render_grid(gpus, term.columns)
        print(theme.apply(output, 0), end="")


if __name__ == "__main__":
    main()
