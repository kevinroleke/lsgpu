"""US National Debt clock widget — fetches from the Treasury Fiscal Data API
and extrapolates forward in real-time at the current annual deficit rate."""

import json
import threading
import time
import urllib.request
from typing import Optional

from .ansi import RESET, BOLD, DIM, GREEN, CYAN, YELLOW, RED, WHITE, strip_ansi

# Treasury Fiscal Data API — debt to the penny, most recent record
_API_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
    "/v2/accounting/od/debt_to_penny"
    "?fields=record_date,tot_pub_debt_out_amt"
    "&sort=-record_date&page%5Bnumber%5D=1&page%5Bsize%5D=2"
)

POLL_INTERVAL = 3600  # re-fetch from API every hour

# Fallback annual deficit used to estimate per-second tick rate (~$1.8 T/yr)
_FALLBACK_ANNUAL_DEFICIT = 1_800_000_000_000


# ── Background poller ─────────────────────────────────────────────────────────

class DebtPoller:
    """Fetches the latest debt figure and deficit rate; caches for extrapolation."""

    def __init__(self) -> None:
        self._lock        = threading.Lock()
        self._base_debt:  Optional[float] = None   # dollars at _base_time
        self._base_time:  float           = 0.0
        self._per_second: float           = _FALLBACK_ANNUAL_DEFICIT / 365.25 / 86400
        self._record_date: str            = ""
        self._stop        = threading.Event()
        self._thread      = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _fetch(self) -> None:
        try:
            req = urllib.request.Request(
                _API_URL,
                headers={"Accept": "application/json",
                         "User-Agent": "gpufetch-tui/0.1"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            records = data.get("data", [])
            if not records:
                return

            latest = records[0]
            debt   = float(latest["tot_pub_debt_out_amt"])
            date   = latest["record_date"]

            # Estimate per-second rate from two consecutive daily records if available
            per_sec = self._per_second
            if len(records) >= 2:
                prev_debt = float(records[1]["tot_pub_debt_out_amt"])
                daily_delta = debt - prev_debt
                if daily_delta > 0:
                    per_sec = daily_delta / 86400

            with self._lock:
                self._base_debt   = debt
                self._base_time   = time.time()
                self._per_second  = per_sec
                self._record_date = date

        except Exception:
            pass

    def _loop(self) -> None:
        self._fetch()
        while not self._stop.is_set():
            self._stop.wait(POLL_INTERVAL)
            if not self._stop.is_set():
                self._fetch()

    def get(self) -> "dict | None":
        with self._lock:
            if self._base_debt is None:
                return None
            elapsed = time.time() - self._base_time
            current = self._base_debt + self._per_second * elapsed
            return {
                "debt":        current,
                "per_second":  self._per_second,
                "record_date": self._record_date,
            }

    def stop(self) -> None:
        self._stop.set()


# ── Widget renderer ───────────────────────────────────────────────────────────

def _fmt_debt(n: float) -> str:
    """Format dollar amount with comma grouping."""
    return f"${n:,.0f}"


def _fmt_rate(per_sec: float) -> str:
    if per_sec >= 1_000_000:
        return f"+${per_sec/1_000_000:,.1f}M/s"
    if per_sec >= 1_000:
        return f"+${per_sec/1_000:,.1f}K/s"
    return f"+${per_sec:,.0f}/s"


def render_debt_widget(data: "dict | None", term_cols: int) -> str:
    colour = RED
    width  = min(62, max(44, term_cols - 2))
    inner  = width - 2
    lines: list[str] = []

    def top():
        return f"{colour}╔{'═' * inner}╗{RESET}"

    def bot():
        return f"{colour}╚{'═' * inner}╝{RESET}"

    def sep():
        return f"{colour}╠{'═' * inner}╣{RESET}"

    def row(plain: str, colored: str = "") -> str:
        content = colored or plain
        pad = inner - len(strip_ansi(content))
        if pad < 0:
            content = content[:inner]
            pad = 0
        return f"{colour}║{RESET}{content}{' ' * pad}{colour}║{RESET}"

    def center(plain: str, colored: str = "") -> str:
        content = colored or plain
        pad_total = max(0, inner - len(strip_ansi(content)))
        lpad = pad_total // 2
        rpad = pad_total - lpad
        return f"{colour}║{RESET}{' ' * lpad}{content}{' ' * rpad}{colour}║{RESET}"

    lines.append(top())
    lines.append(center(
        "  US NATIONAL DEBT  ",
        f"  {RED}{BOLD}US NATIONAL DEBT{RESET}  ",
    ))
    lines.append(sep())

    if data is None:
        lines.append(center("fetching…", f"{DIM}fetching…{RESET}"))
    else:
        debt      = data["debt"]
        per_sec   = data["per_second"]
        rec_date  = data["record_date"]

        debt_str  = _fmt_debt(debt)
        rate_str  = _fmt_rate(per_sec)

        # Big debt number — split into trillions / remainder for emphasis
        trillions  = int(debt // 1_000_000_000_000)
        remainder  = debt % 1_000_000_000_000
        rem_str    = f"{remainder:012,.0f}"   # billions, millions, thousands, ones

        # Line: "$36  ,  123,456,789,012"
        big_plain   = f"${trillions:,},{rem_str}"
        big_colored = (
            f"{RED}{BOLD}${trillions:,}{RESET}"
            f"{YELLOW}{BOLD},{rem_str}{RESET}"
        )
        lines.append(center(big_plain, big_colored))

        lines.append(sep())
        lines.append(row(
            f" Rate   {rate_str}",
            f" {DIM}Rate{RESET}   {GREEN}{BOLD}{rate_str}{RESET}",
        ))
        lines.append(row(
            f" Source Treasury  {rec_date}",
            f" {DIM}Source{RESET} Treasury  {DIM}{rec_date}{RESET}",
        ))

    lines.append(bot())
    return "\n".join(lines) + "\n"
