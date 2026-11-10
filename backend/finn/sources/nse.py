"""NSE corporate announcements (fallback feed) and NSE filing documents.

NSE's API needs a cookie from a homepage visit. BSE is the primary feed, but BSE's API
answers 403 to GitHub-hosted runners, so in the scheduled job NSE is often the live source.
Records are normalised to the same shape as sources/bse.py.

Important: an NSE filing's PDF lives on NSE's archive host (nsearchives.nseindia.com), not
on BSE. The first live run fetched NSE attachment names from BSE and got 404 for every one.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .. import http

HOME = "https://www.nseindia.com/"
API = "https://www.nseindia.com/api/corporate-announcements"
ARCHIVE = "https://nsearchives.nseindia.com/corporate/{}"
HEADERS = {"Referer": HOME, "Accept": "application/json, text/plain, */*"}
_warm = False


def _warmup() -> None:
    global _warm
    if not _warm:
        http.client().get(HOME, headers={"Accept": "text/html"})
        _warm = True


def announcements(symbol: str, start: date, end: date) -> list[dict]:
    _warmup()
    j = http.get_json(API, ttl=30 * 60, headers=HEADERS, params={
        "index": "equities", "symbol": symbol,
        "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")})
    return j if isinstance(j, list) else j.get("data", [])


def parse_ts(r: dict) -> str:
    """ISO 'YYYY-MM-DDTHH:MM:SS' from sort_date ('2026-11-06 15:21:56') or an_dt ('06-Nov-2026 15:21:56')."""
    for key, fmt in (("sort_date", "%Y-%m-%d %H:%M:%S"), ("an_dt", "%d-%b-%Y %H:%M:%S"),
                     ("exchdisstime", "%d-%b-%Y %H:%M:%S"), ("dt", "%d%m%Y%H%M%S")):
        v = (r.get(key) or "").strip()
        if not v:
            continue
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return ""


def parse_size(s) -> int | None:
    """'673.49 KB' / '3.43 MB' -> bytes."""
    if isinstance(s, (int, float)):
        return int(s)
    m = re.match(r"\s*([\d.]+)\s*(B|KB|MB|GB)?\s*$", str(s or ""), re.I)
    if not m:
        return None
    mult = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[(m.group(2) or "B").upper()]
    return int(float(m.group(1)) * mult)


def normalise(r: dict, symbol: str) -> dict:
    ts = parse_ts(r)
    url = (r.get("attchmntFile") or "").strip() or None
    att = url.rsplit("/", 1)[-1] if url else None
    if url and not url.lower().startswith("http"):
        url = ARCHIVE.format(att)
    desc = (r.get("desc") or "").strip()
    return {
        "id": f"NSE-{r.get('seq_id') or abs(hash((symbol, ts, desc)))}",
        "symbol": symbol,
        "exchange": "NSE",
        "ts": ts,
        "date": ts[:10],
        "subject": desc,
        "headline": (r.get("attchmntText") or "").strip(),
        "more": "",
        "exch_category": desc,                  # NSE's 'desc' is its category label
        "exch_subcategory": desc,
        "critical": False,                      # NSE has no equivalent of BSE's critical flag
        "attachment": att,
        "url": url,
        "size": parse_size(r.get("attFileSize") or r.get("fileSize")),
    }


def document(url: str) -> bytes:
    """Filing PDF bytes from NSE's archive (immutable -> cached forever)."""
    if not url.lower().startswith("http"):
        url = ARCHIVE.format(url)
    return http.get(url, binary=True, ttl=None, headers={"Referer": HOME, "Accept": "application/pdf,*/*"})
