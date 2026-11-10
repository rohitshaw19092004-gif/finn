"""screener.in company pages -> standardised fundamentals + document links.

Output schema (identical to the browser capture in data/raw/screener.json):
  {symbol, name, basis, companyId, warehouseId, topRatios{}, about, keyPoints, sector[],
   quarters{cols, rows{label: [..]}, links{raw:[..]}}, pl, plRanges, bs, cf, ratios, shp,
   annualReports[{t,h}], concalls[{d, links[{t,h}]}], creditRatings[{t,h}]}
All money values are INR crore as published by screener.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from .. import http

BASE = "https://www.screener.in"


def _txt(el: Tag | None) -> str | None:
    return re.sub(r"\s+", " ", el.get_text(" ")).strip() if el else None


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = re.sub(r"[,%\s]", "", s)
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _table(soup: BeautifulSoup, sel: str) -> dict | None:
    sec = soup.select_one(sel)
    if not sec:
        return None
    t = sec.select_one("table.data-table") or sec.select_one("table")
    if not t:
        return None
    cols = [_txt(th) for th in t.select("thead th")][1:]
    rows: dict[str, list] = {}
    links: dict[str, list] = {}
    for tr in t.select("tbody tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        label = re.sub(r"\s*\+$", "", _txt(tds[0]) or "").strip()
        if re.search(r"Raw PDF", label, re.I):
            links["raw"] = [(td.find("a") or {}).get("href") if td.find("a") else None for td in tds[1:]]
            continue
        rows[label] = [_num(td.get_text()) for td in tds[1:]]
    return {"cols": cols, "rows": rows, "links": links}


def _ranges(soup: BeautifulSoup) -> dict:
    out: dict[str, dict] = {}
    for t in soup.select("#profit-loss table.ranges-table"):
        head = _txt(t.find("th"))
        if not head:
            continue
        out[head] = {}
        for tr in t.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) == 2:
                out[head][(_txt(tds[0]) or "").rstrip(":")] = _txt(tds[1])
    return out


def _doc_block(soup: BeautifulSoup, name: str) -> Tag | None:
    docs = soup.select_one("#documents")
    if not docs:
        return None
    for h in docs.find_all("h3"):
        if _txt(h) == name:
            return h.find_parent("div", class_="documents") or h.parent.parent
    return None


def parse_company(html: str, symbol: str, basis: str = "consolidated") -> dict:
    soup = BeautifulSoup(html, "lxml")
    o: dict = {"symbol": symbol, "basis": basis}
    o["name"] = _txt(soup.find("h1"))
    el = soup.select_one("[data-company-id]")
    o["companyId"] = el.get("data-company-id") if el else None
    el = soup.select_one("[data-warehouse-id]")
    o["warehouseId"] = el.get("data-warehouse-id") if el else None
    o["topRatios"] = {
        _txt(li.select_one(".name")): _txt(li.select_one(".value")) for li in soup.select("#top-ratios li")
    }
    o["about"] = _txt(soup.select_one(".company-profile .about"))
    o["keyPoints"] = _txt(soup.select_one(".company-profile .commentary"))
    o["sector"] = [_txt(a) for a in soup.select('#peers a[href*="/market/"]')]
    o["quarters"] = _table(soup, "#quarters")
    o["pl"] = _table(soup, "#profit-loss")
    o["plRanges"] = _ranges(soup)
    o["bs"] = _table(soup, "#balance-sheet")
    o["cf"] = _table(soup, "#cash-flow")
    o["ratios"] = _table(soup, "#ratios")
    o["shp"] = _table(soup, "#quarterly-shp")
    ar = _doc_block(soup, "Annual reports")
    o["annualReports"] = [
        {"t": _txt(a), "h": a.get("href")} for a in (ar.find_all("a") if ar else [])
        if re.search(r"\.pdf|AnnPdf|bseindia|nseindia", a.get("href") or "", re.I)
    ][:6]
    cc = _doc_block(soup, "Concalls")
    o["concalls"] = []
    if cc:
        for li in cc.select("ul li")[:10]:
            o["concalls"].append({
                "d": _txt(li.find("div")),
                "links": [{"t": _txt(a), "h": a.get("href")} for a in li.find_all("a")],
            })
    cr = _doc_block(soup, "Credit ratings")
    o["creditRatings"] = [{"t": _txt(a), "h": a.get("href")} for a in (cr.select("ul li a") if cr else [])][:4]
    o["consolidatedMissing"] = not (o["quarters"] and o["quarters"]["rows"])
    return o


def fetch_company(symbol: str) -> dict:
    """Consolidated first; fall back to standalone when a company has no subsidiaries."""
    html = http.get(f"{BASE}/company/{symbol}/consolidated/", ttl=12 * 3600)
    o = parse_company(html, symbol, "consolidated")
    if o["consolidatedMissing"]:
        html = http.get(f"{BASE}/company/{symbol}/", ttl=12 * 3600)
        o = parse_company(html, symbol, "standalone")
    if not o["companyId"] or not o["name"]:
        raise RuntimeError(f"screener: no company page for {symbol}")
    return o


def price_series(company_id: str, days: int = 400) -> dict:
    """Daily close + volume from screener's chart endpoint (fallback when Yahoo is unavailable)."""
    j = http.get_json(f"{BASE}/api/company/{company_id}/chart/",
                      params={"q": "Price-Volume", "days": days, "consolidated": "true"}, ttl=3 * 3600)
    out = {"dates": [], "close": [], "volume": []}
    ds = {d["metric"]: d["values"] for d in j.get("datasets", [])}
    vol = {v[0]: v[1] for v in ds.get("Volume", [])}
    for d, p in ds.get("Price", []):
        out["dates"].append(d)
        out["close"].append(float(p))
        out["volume"].append(vol.get(d))
    return out


def search(q: str) -> list[dict]:
    """Company name/ticker search -> [{name, symbol}] (used by the Ask bar)."""
    j = http.get_json(f"{BASE}/api/company/search/", params={"q": q}, ttl=24 * 3600)
    out = []
    for it in j:
        m = re.match(r"/company/([^/]+)/", it.get("url", ""))
        if m:
            out.append({"name": it.get("name"), "symbol": m.group(1)})
    return out


def transcript_links(company: dict, n: int = 5) -> list[dict]:
    """Most recent n concall transcripts -> [{period, url, file}]"""
    out = []
    for c in company.get("concalls", []):
        for l in c.get("links", []):
            if (l.get("t") or "").lower().startswith("transcript") and l.get("h"):
                m = re.search(r"Pname=([0-9a-fA-F-]+\.pdf)", l["h"])
                out.append({"period": c.get("d"), "url": l["h"], "file": m.group(1) if m else None})
                break
        if len(out) >= n:
            break
    return out
