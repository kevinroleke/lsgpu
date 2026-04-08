"""CPU + memory monitoring: background poller and TUI widget renderer."""

import threading
from typing import Optional

from .ansi import (
    RESET, BOLD, DIM,
    GREEN, CYAN, YELLOW, RED,
    strip_ansi,
)

POLL_INTERVAL = 2  # seconds between /proc/stat samples


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_proc_stat() -> list[list[int]]:
    """Return a list of tick-count lists, one per cpu* line in /proc/stat."""
    cpus: list[list[int]] = []
    with open("/proc/stat") as fh:
        for line in fh:
            if not line.startswith("cpu"):
                break
            parts = line.split()
            if parts[0] == "cpu":
                # first line is aggregate – insert at position 0
                cpus.insert(0, [int(x) for x in parts[1:]])
            else:
                cpus.append([int(x) for x in parts[1:]])
    return cpus


def _cpu_pct(prev: list[int], curr: list[int]) -> float:
    """Compute CPU usage % between two /proc/stat tick snapshots."""
    prev_idle = prev[3] + (prev[4] if len(prev) > 4 else 0)  # idle + iowait
    curr_idle = curr[3] + (curr[4] if len(curr) > 4 else 0)
    prev_total = sum(prev)
    curr_total = sum(curr)
    delta_total = curr_total - prev_total
    delta_idle  = curr_idle  - prev_idle
    if delta_total == 0:
        return 0.0
    return max(0.0, min(100.0, (1.0 - delta_idle / delta_total) * 100.0))


def _read_meminfo() -> dict[str, int]:
    """Return selected keys from /proc/meminfo (values in kB)."""
    wanted = {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}
    result: dict[str, int] = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, _, val = line.partition(":")
            if key in wanted:
                result[key] = int(val.split()[0])
            if len(result) == len(wanted):
                break
    return result


# ── poller ────────────────────────────────────────────────────────────────────

class SysinfoPoller:
    """Daemon thread — samples /proc/stat and /proc/meminfo every POLL_INTERVAL seconds."""

    def __init__(self):
        self._data:   Optional[dict] = None
        self._lock    = threading.Lock()
        self._stop    = threading.Event()
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ── internal ──────────────────────────────────────────────────────────────

    def _run(self):
        # Take a first snapshot immediately so the first sleep has a baseline.
        try:
            prev_stats = _read_proc_stat()
        except Exception:
            prev_stats = []

        while not self._stop.wait(POLL_INTERVAL):
            try:
                curr_stats = _read_proc_stat()
                mem        = _read_meminfo()

                if prev_stats and curr_stats and len(prev_stats) == len(curr_stats):
                    overall    = _cpu_pct(prev_stats[0], curr_stats[0])
                    per_cpu    = [
                        _cpu_pct(prev_stats[i], curr_stats[i])
                        for i in range(1, len(curr_stats))
                    ]
                else:
                    overall = 0.0
                    per_cpu = []

                prev_stats = curr_stats

                mem_total_kib = mem.get("MemTotal",      0)
                mem_avail_kib = mem.get("MemAvailable",  0)
                swap_total_kib = mem.get("SwapTotal",    0)
                swap_free_kib  = mem.get("SwapFree",     0)

                snapshot = {
                    "cpu_pct":        overall,
                    "per_cpu":        per_cpu,
                    "mem_total_mib":  mem_total_kib  // 1024,
                    "mem_used_mib":   (mem_total_kib - mem_avail_kib) // 1024,
                    "swap_total_mib": swap_total_kib // 1024,
                    "swap_used_mib":  (swap_total_kib - swap_free_kib) // 1024,
                }
                with self._lock:
                    self._data = snapshot

            except Exception:
                pass

    # ── public API ────────────────────────────────────────────────────────────

    def get(self) -> Optional[dict]:
        with self._lock:
            return self._data

    def stop(self):
        self._stop.set()


# ── widget rendering ──────────────────────────────────────────────────────────

def _bar(used: float, total: float, width: int) -> str:
    """Render a filled/empty block bar coloured by usage ratio."""
    pct    = used / total if total else 0.0
    filled = int(pct * width)
    colour = GREEN if pct < 0.60 else YELLOW if pct < 0.85 else RED
    return f"{colour}{'█' * filled}{'░' * (width - filled)}{RESET}"


def render_sysinfo_widget(data: "dict | None", term_cols: int) -> str:
    colour = CYAN
    width  = min(62, max(44, term_cols - 2))
    inner  = width - 2
    bar_w  = max(10, inner - 28)

    lines: list[str] = []

    # ── box helpers ───────────────────────────────────────────────────────────

    def top():
        return f"{colour}╔{'═' * inner}╗{RESET}"

    def bot():
        return f"{colour}╚{'═' * inner}╝{RESET}"

    def sep():
        return f"{colour}╠{'═' * inner}╣{RESET}"

    def row(plain: str, colored: str = "") -> str:
        pad  = max(0, inner - len(strip_ansi(plain if not colored else plain)))
        body = colored if colored else plain
        return f"{colour}║{RESET}{body}{' ' * pad}{colour}║{RESET}"

    # ── header ────────────────────────────────────────────────────────────────

    lines.append(top())
    header_plain  = " System"
    header_colour = f" {CYAN}{BOLD}System{RESET}"
    lines.append(row(header_plain, header_colour))
    lines.append(sep())

    # ── no data yet ───────────────────────────────────────────────────────────

    if data is None:
        collecting_plain  = " Collecting\u2026"
        collecting_colour = f" {DIM}Collecting\u2026{RESET}"
        lines.append(row(collecting_plain, collecting_colour))
        lines.append(bot())
        return "\n".join(lines) + "\n"

    # ── CPU overall ───────────────────────────────────────────────────────────

    cpu_pct  = data["cpu_pct"]
    cpu_bar  = _bar(cpu_pct, 100.0, bar_w)
    pct_col  = GREEN if cpu_pct < 60 else YELLOW if cpu_pct < 85 else RED
    cpu_plain   = f" CPU  {'█' * bar_w} {cpu_pct:>5.1f}%"
    cpu_colored = (
        f" {BOLD}CPU{RESET}  {cpu_bar} {pct_col}{cpu_pct:>5.1f}%{RESET}"
    )
    lines.append(row(cpu_plain, cpu_colored))

    # ── per-CPU cores (two-column layout, max 2 rows each side) ──────────────

    per_cpu: list[float] = data.get("per_cpu", [])
    if per_cpu:
        # We show at most 4 cores (2 rows x 2 columns).
        # Each core cell: "C00 ██░ 100%" — 14 chars wide.
        # Two cells + separator fit inside inner when inner >= ~30.
        max_cores   = min(len(per_cpu), 4)
        half        = (max_cores + 1) // 2  # cores in left column

        cell_bar_w  = 4  # tiny bar inside each cell
        # cell format: " C<n> ████  99%" → 16 chars
        cell_width  = 16

        two_col = inner >= cell_width * 2 + 2

        for row_idx in range(half):
            left_i  = row_idx
            right_i = row_idx + half

            # left cell
            ci      = left_i
            pct_l   = per_cpu[ci]
            bar_l   = _bar(pct_l, 100.0, cell_bar_w)
            col_l   = GREEN if pct_l < 60 else YELLOW if pct_l < 85 else RED
            plain_l = f" C{ci:<2} {'█' * cell_bar_w} {pct_l:>4.0f}%"
            color_l = f" {DIM}C{ci:<2}{RESET} {bar_l} {col_l}{pct_l:>4.0f}%{RESET}"

            if two_col and right_i < len(per_cpu):
                ci      = right_i
                pct_r   = per_cpu[ci]
                bar_r   = _bar(pct_r, 100.0, cell_bar_w)
                col_r   = GREEN if pct_r < 60 else YELLOW if pct_r < 85 else RED
                plain_r = f" C{ci:<2} {'█' * cell_bar_w} {pct_r:>4.0f}%"
                color_r = f" {DIM}C{ci:<2}{RESET} {bar_r} {col_r}{pct_r:>4.0f}%{RESET}"
                # combine: left fills cell_width chars, then right
                pad_between = inner - len(strip_ansi(plain_l)) - len(strip_ansi(plain_r))
                combined_plain  = plain_l + " " * max(0, pad_between) + plain_r
                combined_color  = color_l + " " * max(0, pad_between) + color_r
                lines.append(row(combined_plain, combined_color))
            else:
                lines.append(row(plain_l, color_l))

    # ── memory ────────────────────────────────────────────────────────────────

    mem_total = data["mem_total_mib"]
    mem_used  = data["mem_used_mib"]
    if mem_total > 0:
        mem_bar   = _bar(mem_used, mem_total, bar_w)
        mem_plain   = f" MEM  {'█' * bar_w} {mem_used:>5}/{mem_total} MiB"
        mem_colored = (
            f" {BOLD}MEM{RESET}  {mem_bar}"
            f" {CYAN}{mem_used:>5}{RESET}/{mem_total}{DIM} MiB{RESET}"
        )
        lines.append(row(mem_plain, mem_colored))

    # ── swap ──────────────────────────────────────────────────────────────────

    swap_total = data["swap_total_mib"]
    swap_used  = data["swap_used_mib"]
    if swap_total > 0:
        swap_bar    = _bar(swap_used, swap_total, bar_w)
        swap_plain   = f" SWP  {'█' * bar_w} {swap_used:>5}/{swap_total} MiB"
        swap_colored = (
            f" {BOLD}SWP{RESET}  {swap_bar}"
            f" {CYAN}{swap_used:>5}{RESET}/{swap_total}{DIM} MiB{RESET}"
        )
        lines.append(row(swap_plain, swap_colored))

    lines.append(bot())
    return "\n".join(lines) + "\n"
