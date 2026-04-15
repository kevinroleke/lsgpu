"""Market price ticker widget.

Data sources (no API keys required):
  - CoinGecko  — BTC/USD, XMR/USD  (price + true 24 h change %)
  - Stooq      — NVDA, S&P 500     (OHLCV; change = close vs open)
"""

import csv
import io
import json
import threading
import urllib.parse
import urllib.request
from typing import Optional

from .ansi import RESET, BOLD, DIM, GREEN, YELLOW, RED, MAGENTA, WHITE, strip_ansi

POLL_INTERVAL = 60   # seconds between full refresh cycles

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "application/json,text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Display order — (internal_key, label, show_dollar_sign)
_TICKER_DEFS = [
    ("BTC",   "BTC/USD", True),
    ("XMR",   "XMR/USD", True),
    ("GSPC",  "S&P 500", False),
    ("NVDA",  "NVDA",    True),
]


# ── CoinGecko ─────────────────────────────────────────────────────────────────

def _fetch_coingecko() -> "dict[str, dict]":
    """Return {BTC: {price, change_pct}, XMR: {price, change_pct}} or {}."""
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin,monero&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {
            "BTC": {
                "price":      float(data["bitcoin"]["usd"]),
                "change_pct": float(data["bitcoin"].get("usd_24h_change", 0)),
            },
            "XMR": {
                "price":      float(data["monero"]["usd"]),
                "change_pct": float(data["monero"].get("usd_24h_change", 0)),
            },
        }
    except Exception:
        return {}


# ── Stooq ─────────────────────────────────────────────────────────────────────

def _stooq_quote(stooq_sym: str) -> "dict | None":
    """Fetch a single live quote from Stooq. Returns {price, change_pct} or None."""
    url = f"https://stooq.com/q/l/?s={urllib.parse.quote(stooq_sym)}&f=sd2t2ohlcv&h&e=csv"
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        row = next(reader)
        price = float(row["Close"])
        open_ = float(row["Open"])
        change_pct = ((price - open_) / open_ * 100) if open_ else 0.0
        return {"price": price, "change_pct": change_pct}
    except Exception:
        return None


def _fetch_stooq() -> "dict[str, dict]":
    """Return {GSPC: {price, change_pct}, NVDA: {price, change_pct}} or partial."""
    result: dict[str, dict] = {}
    for key, sym in (("GSPC", "^spx"), ("NVDA", "nvda.us")):
        q = _stooq_quote(sym)
        if q is not None:
            result[key] = q
    return result


# ── Background poller ─────────────────────────────────────────────────────────

class TickerPoller:
    """Daemon thread — refreshes all tickers every POLL_INTERVAL seconds."""

    def __init__(self) -> None:
        self._data:  dict[str, dict] = {}
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _fetch_all(self) -> None:
        crypto = _fetch_coingecko()
        if self._stop.is_set():
            return
        self._stop.wait(1.0)
        stocks = _fetch_stooq()
        combined = {**crypto, **stocks}
        if combined:
            with self._lock:
                self._data.update(combined)

    def _loop(self) -> None:
        self._fetch_all()
        while not self._stop.wait(POLL_INTERVAL):
            self._fetch_all()

    def get(self) -> "dict[str, dict]":
        with self._lock:
            return dict(self._data)

    def stop(self) -> None:
        self._stop.set()


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_price(price: float, dollar: bool) -> str:
    if price >= 10_000:
        s = f"{price:,.0f}"
    elif price >= 1_000:
        s = f"{price:,.2f}"
    elif price >= 100:
        s = f"{price:.2f}"
    else:
        s = f"{price:.4f}"
    return ("$" + s) if dollar else s


def _fmt_change(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def _change_color(pct: float) -> str:
    return GREEN if pct >= 0 else RED


# ── Widget renderer ───────────────────────────────────────────────────────────

def render_tickers_widget(data: "dict[str, dict]", term_cols: int) -> str:
    colour = MAGENTA
    width  = min(62, max(44, term_cols - 2))
    inner  = width - 2

    def top() -> str:
        return f"{colour}╔{'═' * inner}╗{RESET}"
    def sep() -> str:
        return f"{colour}╠{'═' * inner}╣{RESET}"
    def bot() -> str:
        return f"{colour}╚{'═' * inner}╝{RESET}"

    def center(plain: str, colored: str = "") -> str:
        content = colored or plain
        pad_total = max(0, inner - len(strip_ansi(content)))
        lpad = pad_total // 2
        rpad = pad_total - lpad
        return f"{colour}║{RESET}{' ' * lpad}{content}{' ' * rpad}{colour}║{RESET}"

    def row(plain: str, colored: str = "") -> str:
        content = colored or plain
        pad = max(0, inner - len(strip_ansi(content)))
        return f"{colour}║{RESET}{content}{' ' * pad}{colour}║{RESET}"

    lines = [
        top(),
        center("  MARKET PRICES  ", f"  {MAGENTA}{BOLD}MARKET PRICES{RESET}  "),
        sep(),
    ]

    if not data:
        lines.append(center("fetching…", f"{DIM}fetching…{RESET}"))
        lines.append(bot())
        return "\n".join(lines) + "\n"

    label_w  = 7
    price_w  = 13
    change_w = 9

    for key, label, dollar in _TICKER_DEFS:
        q = data.get(key)
        if q is None:
            plain   = f" {label:<{label_w}}  {'…':>{price_w}}  {'':>{change_w}}"
            colored = (
                f" {DIM}{label:<{label_w}}{RESET}"
                f"  {DIM}{'…':>{price_w}}{RESET}"
                f"  {' ' * change_w}"
            )
        else:
            price_str  = _fmt_price(q["price"], dollar)
            pct        = q["change_pct"]
            arrow      = "▲" if pct >= 0 else "▼"
            change_str = f"{arrow} {_fmt_change(pct)}"
            ccol       = _change_color(pct)

            plain   = f" {label:<{label_w}}  {price_str:>{price_w}}  {change_str:>{change_w}}"
            colored = (
                f" {WHITE}{BOLD}{label:<{label_w}}{RESET}"
                f"  {YELLOW}{BOLD}{price_str:>{price_w}}{RESET}"
                f"  {ccol}{BOLD}{change_str:>{change_w}}{RESET}"
            )
        lines.append(row(plain, colored))

    lines.append(bot())
    return "\n".join(lines) + "\n"
