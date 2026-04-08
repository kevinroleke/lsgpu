"""Weather integration: background polling from wttr.in + TUI widget rendering."""

import json
import threading
import time
import urllib.request
from typing import Optional

from .ansi import (
    RESET, BOLD, DIM,
    GREEN, CYAN, YELLOW, RED,
    BLUE, MAGENTA, WHITE,
    strip_ansi,
)

_WEATHER_URL   = "https://wttr.in/Rochester+NY?format=j1"
POLL_INTERVAL  = 600   # 10 minutes


# ── condition → icon mapping ──────────────────────────────────────────────────

def _condition_icon(condition: str) -> str:
    c = condition.lower()
    if "thunder" in c:
        return "⚡"
    if "snow" in c:
        return "❄"
    if "rain" in c or "drizzle" in c or "shower" in c:
        return "⛆"
    if "fog" in c or "mist" in c or "haze" in c:
        return "≈"
    if "clear" in c or "sunny" in c:
        return "☀"
    if "cloud" in c or "overcast" in c:
        return "☁"
    return "·"


# ── JSON parsing ──────────────────────────────────────────────────────────────

def _parse(raw: dict) -> dict:
    cur  = (raw.get("current_condition") or [{}])[0]
    area = (raw.get("nearest_area")      or [{}])[0]
    wx   = (raw.get("weather")           or [{}])[0]

    # location string
    area_name    = (area.get("areaName")    or [{}])[0].get("value", "Rochester")
    country_name = (area.get("country")     or [{}])[0].get("value", "")
    region_name  = (area.get("region")      or [{}])[0].get("value", "New York")
    if region_name and country_name:
        location = f"{area_name}, {region_name}"
    else:
        location = area_name

    condition = (cur.get("weatherDesc") or [{}])[0].get("value", "Unknown")

    # hourly: next 3 entries from today's forecast
    hourly_raw = wx.get("hourly") or []
    hourly: list[dict] = []
    for h in hourly_raw[:3]:
        raw_time = h.get("time", "0")
        try:
            hour_num = int(raw_time) // 100
            time_str = f"{hour_num:02d}:00"
        except (ValueError, TypeError):
            time_str = str(raw_time)
        h_cond = (h.get("weatherDesc") or [{}])[0].get("value", "")
        hourly.append({
            "time":   time_str,
            "temp_f": int(h.get("tempF", 0)),
            "condition": h_cond,
        })

    return {
        "location":        location,
        "temp_f":          int(cur.get("temp_F", 0)),
        "temp_c":          int(cur.get("temp_C", 0)),
        "feels_like_f":    int(cur.get("FeelsLikeF", 0)),
        "feels_like_c":    int(cur.get("FeelsLikeC", 0)),
        "condition":       condition,
        "humidity":        int(cur.get("humidity", 0)),
        "wind_mph":        int(cur.get("windspeedMiles", 0)),
        "wind_dir":        cur.get("winddir16Point", ""),
        "precip_in":       float(cur.get("precipInches", 0.0)),
        "visibility_miles": int(cur.get("visibility", 0)),
        "uv_index":        int(cur.get("uvIndex", 0)),
        "hourly":          hourly,
    }


# ── poller ────────────────────────────────────────────────────────────────────

class WeatherPoller:
    """Daemon thread — fetches weather from wttr.in every POLL_INTERVAL seconds."""

    def __init__(self):
        self._data:   Optional[dict] = None
        self._lock    = threading.Lock()
        self._stop    = threading.Event()
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _fetch(self) -> None:
        try:
            req = urllib.request.Request(
                _WEATHER_URL,
                headers={"User-Agent": "lsgpu-weather/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read())
            parsed = _parse(raw)
            with self._lock:
                self._data = parsed
        except Exception:
            # keep last successful fetch; do not clear _data on error
            pass

    def _run(self) -> None:
        # immediate fetch on start
        self._fetch()
        while not self._stop.wait(POLL_INTERVAL):
            self._fetch()

    def get(self) -> Optional[dict]:
        with self._lock:
            return self._data

    def stop(self) -> None:
        self._stop.set()


# ── widget renderer ───────────────────────────────────────────────────────────

def render_weather_widget(data: "dict | None", term_cols: int) -> str:
    colour = CYAN
    width  = min(62, max(44, term_cols - 2))
    inner  = width - 2

    def top()  -> str:
        return f"{colour}╔{'═' * inner}╗{RESET}"
    def sep()  -> str:
        return f"{colour}╠{'═' * inner}╣{RESET}"
    def bot()  -> str:
        return f"{colour}╚{'═' * inner}╝{RESET}"

    def row(plain: str, colored: str = "") -> str:
        pad  = max(0, inner - len(plain))
        body = colored if colored else plain
        return f"{colour}║{RESET}{body}{' ' * pad}{colour}║{RESET}"

    lines = [top()]

    if data is None:
        # header placeholder
        header_p = " · Rochester, NY"
        header_c = f" {DIM}· Rochester, NY{RESET}"
        lines.append(row(header_p, header_c))
        lines.append(sep())
        fetch_p = " Fetching weather\u2026"
        fetch_c = f" {DIM}Fetching weather\u2026{RESET}"
        lines.append(row(fetch_p, fetch_c))
        lines.append(bot())
        return "\n".join(lines) + "\n"

    # ── header: icon + location ───────────────────────────────────────────────
    icon      = _condition_icon(data.get("condition", ""))
    loc       = data.get("location", "Rochester, NY")
    header_p  = f" {icon} {loc}"
    header_c  = f" {icon} {BOLD}{CYAN}{loc}{RESET}"
    lines.append(row(header_p, header_c))
    lines.append(sep())

    # ── temp + condition ──────────────────────────────────────────────────────
    tf   = data.get("temp_f", 0)
    tc   = data.get("temp_c", 0)
    cond = data.get("condition", "Unknown")
    temp_p = f"  {tf}°F / {tc}°C  {cond}"
    temp_c = f"  {YELLOW}{tf}°F{RESET} / {DIM}{tc}°C{RESET}  {WHITE}{cond}{RESET}"
    lines.append(row(temp_p, temp_c))

    # ── feels like ────────────────────────────────────────────────────────────
    flf = data.get("feels_like_f", 0)
    flc = data.get("feels_like_c", 0)
    feels_p = f"  Feels like {flf}°F / {flc}°C"
    feels_c = f"  {DIM}Feels like{RESET} {YELLOW}{flf}°F{RESET} / {DIM}{flc}°C{RESET}"
    lines.append(row(feels_p, feels_c))

    # ── humidity + wind ───────────────────────────────────────────────────────
    hum     = data.get("humidity", 0)
    wmph    = data.get("wind_mph", 0)
    wdir    = data.get("wind_dir", "")
    wind_p  = f"  Humidity {hum}%   Wind {wmph} mph {wdir}"
    wind_c  = (
        f"  {DIM}Humidity{RESET} {CYAN}{hum}%{RESET}"
        f"   {DIM}Wind{RESET} {CYAN}{wmph} mph {wdir}{RESET}"
    )
    lines.append(row(wind_p, wind_c))

    # ── UV index + visibility ─────────────────────────────────────────────────
    uv   = data.get("uv_index", 0)
    vis  = data.get("visibility_miles", 0)
    uv_p = f"  UV index {uv}   Visibility {vis} mi"
    uv_c = (
        f"  {DIM}UV index{RESET} {CYAN}{uv}{RESET}"
        f"   {DIM}Visibility{RESET} {CYAN}{vis} mi{RESET}"
    )
    lines.append(row(uv_p, uv_c))

    # ── hourly forecast (next 3 hours) ────────────────────────────────────────
    hourly = data.get("hourly") or []
    if hourly:
        lines.append(sep())
        parts_p: list[str] = []
        parts_c: list[str] = []
        for h in hourly:
            t   = h.get("time",   "")
            tf2 = h.get("temp_f", 0)
            ico = _condition_icon(h.get("condition", ""))
            parts_p.append(f"{t} {ico} {tf2}°F")
            parts_c.append(f"{DIM}{t}{RESET} {ico} {YELLOW}{tf2}°F{RESET}")

        # join with separator, pad inside the box
        separator   = "   "
        hourly_p    = "  " + separator.join(parts_p)
        hourly_col  = "  " + separator.join(parts_c)
        lines.append(row(hourly_p, hourly_col))

    lines.append(bot())
    return "\n".join(lines) + "\n"
