"""NSE corporate announcements (fallback feed).

NSE's API needs a cookie from a homepage visit and often blocks cloud IPs, which is why
BSE is the primary feed. Records are normalised to the same shape as sources/bse.py.
"""
from __future__ import annotations

from datetime import date

from .. import http

HOME = "https://www.nseindia.com/"
API = "https://www.nseindia.com/api/corporate-announcements"
_warm = False


def _warmup() -> None:
    global _warm
    if not _warm:
        http.client().get(HOME, headers={"Accept": "text/html"})
        _warm = True


def announcements(symbol: str, start: date, end: date) -> list[dict]:
    _warmup()
    j = http.get_json(API, ttl=30 * 60, headers={"Referer": HOME, "Accept": "application/json"}, params={
        "index": "equities", "symbol": symbol,
        "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")})
    return j if isinstance(j, list) else j.get("data", [])


def normalise(r: dict, symbol: str) -> dict:
    ts = r.get("sort_date") or r.get("an_dt") or ""
    return {
        "id": f"NSE-{r.get('seq_id') or hash((symbol, ts, r.get('desc')))}",
        "symbol": symbol,
        "exchange": "NSE",
        "ts": ts.replace(" ", "T"),
        "date": ts[:10],
        "subject": (r.get("desc") or "").strip(),
        "headline": (r.get("attchmntText") or "").strip(),
        "more": "",
        "exch_category": (r.get("desc") or "").strip(),     # NSE's 'desc' is its category label
        "exch_subcategory": (r.get("desc") or "").strip(),
        "critical": False,
        "attachment": (r.get("attchmntFile") or "").rsplit("/", 1)[-1] or None,
        "url": r.get("attchmntFile"),
        "size": None,
    }
