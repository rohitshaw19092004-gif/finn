"""BSE corporate announcements (primary filings feed).

BSE's JSON API is the same one bseindia.com's own announcements page calls. It returns
BSE's own category/sub-category for each filing, which lets us classify ~90% of filings
with rules alone (no LLM). NSE is the fallback (sources/nse.py).
"""
from __future__ import annotations

from datetime import date, datetime

from .. import http

API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{}"
ATTACH_HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{}"
HEADERS = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com",
           "Accept": "application/json, text/plain, */*"}
KEEP = ["NEWSID", "SCRIP_CD", "NEWSSUB", "HEADLINE", "NEWS_DT", "DissemDT", "CATEGORYNAME", "SUBCATNAME",
        "ATTACHMENTNAME", "MORE", "CRITICALNEWS", "Fld_Attachsize", "SLONGNAME", "NSURL", "QUARTER_ID",
        "AUDIO_VIDEO_FILE"]


def announcements(scrip: str, start: date, end: date, max_pages: int = 8) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        j = http.get_json(API, headers=HEADERS, ttl=30 * 60, params={
            "pageno": page, "strCat": -1, "strPrevDate": start.strftime("%Y%m%d"), "strScrip": scrip,
            "strSearch": "P", "strToDate": end.strftime("%Y%m%d"), "strType": "C", "subcategory": -1})
        table = j.get("Table") or []
        rows += [{k: r.get(k) for k in KEEP} for r in table]
        total = ((j.get("Table1") or [{}])[0] or {}).get("ROWCNT") or 0
        if not table or len(rows) >= total:
            break
    return rows


def normalise(r: dict, symbol: str) -> dict:
    """BSE row -> FINN filing record (exchange-agnostic)."""
    att = r.get("ATTACHMENTNAME")
    ts = r.get("NEWS_DT") or r.get("DissemDT")
    return {
        "id": f"BSE-{r.get('NEWSID')}",
        "symbol": symbol,
        "exchange": "BSE",
        "ts": ts,
        "date": (ts or "")[:10],
        "subject": (r.get("NEWSSUB") or "").strip(),
        "headline": (r.get("HEADLINE") or "").strip(),
        "more": (r.get("MORE") or "").strip(),
        "exch_category": (r.get("CATEGORYNAME") or "").strip(),
        "exch_subcategory": (r.get("SUBCATNAME") or "").strip(),
        "critical": str(r.get("CRITICALNEWS") or "0").strip() == "1",
        "attachment": att,
        "url": ATTACH.format(att) if att else r.get("NSURL"),
        "size": r.get("Fld_Attachsize"),
    }


def document(name: str) -> bytes:
    """Filing PDF bytes (immutable -> cached forever). Older files move from AttachLive to AttachHis."""
    try:
        return http.get(ATTACH.format(name), binary=True, ttl=None, headers=HEADERS)
    except RuntimeError:
        return http.get(ATTACH_HIS.format(name), binary=True, ttl=None, headers=HEADERS)


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts[:19])
