"""Daily job: public data -> the snapshot the app reads (web/public/data/*.json).

Run after market close (GitHub Actions cron, see .github/workflows/refresh.yml):
    python -m finn refresh            # live sources
    FINN_OFFLINE=1 python -m finn refresh   # rebuild from data/raw captures only

Outputs
  meta.json        when, what, which models, token usage
  portfolio.json   holdings with EOD series (alerts are computed on-device against the user's thresholds)
  feed.json        classified + scored filings, clustered into stories, with enrichments
  people.json      public profiles of people named in filings
  research/*.json  dossiers for portfolio + research names
  companies.json   org registry (aliases, peers, themes) for the device-side network matcher
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import llm
from .config import DATA, OUT, RAW, settings
from .intel import classify, materiality, people, research, results
from .sources import bse, docs, nse, prices, screener

log = logging.getLogger("finn")
IST = timezone(timedelta(hours=5, minutes=30))


def _write(name: str, obj) -> None:
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")


def _load_raw(name: str):
    p = RAW / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def companies(symbols: list[str]) -> dict[str, dict]:
    cap = _load_raw("screener.json") or {}
    out = {}
    for s in symbols:
        if settings.offline and s in cap:
            out[s] = cap[s]
            continue
        try:
            out[s] = screener.fetch_company(s)
        except Exception as e:
            log.warning("screener %s: %s (using capture if any)", s, e)
            if s in cap:
                out[s] = cap[s]
    return out


def price_data(symbols: list[str], cos: dict) -> dict[str, dict]:
    cap = _load_raw("prices.json") or {}
    now = datetime.now(IST)
    closed = now.hour > 15 or (now.hour == 15 and now.minute >= 35)
    out = {}
    for s in symbols:
        if settings.offline and s in cap:
            out[s] = cap[s]
            continue
        try:
            ser = prices.eod(s, cos.get(s, {}).get("companyId"), settings.price_days)
            out[s] = prices.drop_partial_session(ser, now.strftime("%Y-%m-%d"), closed)
        except Exception as e:
            log.warning("prices %s: %s", s, e)
            if s in cap:
                out[s] = cap[s]
    return out


def filings(codes: dict[str, str], days: int) -> list[dict]:
    end = datetime.now(IST).date()
    start = end - timedelta(days=days)
    cap = _load_raw("bse_announcements.json") or {}
    rows = []
    for sym, code in codes.items():
        if settings.offline and sym in cap:
            raw = cap[sym]
        else:
            try:
                raw = bse.announcements(code, start, end)
            except Exception as e:
                log.warning("BSE %s: %s — trying NSE", sym, e)
                try:
                    rows += [nse.normalise(r, sym) for r in nse.announcements(sym, start, end)]
                    continue
                except Exception as e2:
                    log.warning("NSE %s: %s (using capture if any)", sym, e2)
                    raw = cap.get(sym, [])
        rows += [bse.normalise(r, sym) for r in raw]
    seen, out = set(), []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


def doc_text(f: dict) -> str | None:
    """First pages of a filing PDF. Small files only: annual reports etc. are never pulled here."""
    att = f.get("attachment")
    if not att:
        return None
    local = RAW / "filings" / att.replace(".pdf", ".txt")
    if local.exists():
        return local.read_text(encoding="utf-8")
    if settings.offline:
        return None
    try:
        size = int(f.get("size") or 0)
        if size and size > 3_000_000:
            return None
        pages = docs.cached_text(att, lambda: bse.document(att))
        return "\n".join(pages[:3])
    except Exception as e:
        log.info("doc %s: %s", att, e)
        return None


SUMMARY_SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "line": {"type": "string", "description": "<= 18 words, plain English, what happened + why it matters"}},
    "required": ["i", "line"]}}


def summarise(items: list[dict]) -> None:
    """One-liners for stories worth a glance. Batched on the cheapest tier; seeded/fallback otherwise."""
    seed = _load_raw("llm_seed/_summaries.json") or {}
    todo = []
    for f in items:
        key = f.get("attachment") or f["id"]
        if key in seed:
            f["summary"], f["summary_by"] = seed[key], "seeded"
        else:
            todo.append(f)
    for i in range(0, len(todo), 25):
        chunk = todo[i:i + 25]
        listing = "\n\n".join(f"{j}. [{f['symbol']}] {f['subject']} | {f['headline'][:300]} | {(f.get('doc_excerpt') or '')[:700]}"
                              for j, f in enumerate(chunk))
        out = llm.call("bulk", system=(
            "Write a one-line summary (<= 18 words) of each Indian exchange filing for a busy fund manager: "
            "what happened and the number that matters. No fluff, no 'the company announced'."),
            prompt=listing, schema=SUMMARY_SCHEMA) or []
        got = {o["i"]: o["line"] for o in out if isinstance(o, dict)}
        for j, f in enumerate(chunk):
            if j in got:
                f["summary"], f["summary_by"] = got[j], "llm"
            else:
                f["summary"], f["summary_by"] = fallback_summary(f), "rule"


def fallback_summary(f: dict) -> str:
    h = f.get("headline") or ""
    if len(h) < 25 or re.fullmatch(r"(enclosed|announcement as attached|updates?|general updates|please find enclosed.*)", h.strip(), re.I):
        h = f.get("subject") or h
    h = re.sub(r"^(announcement under regulation 30 \(lodr\)-|disclosure under regulation 30.*?-\s*)", "", h, flags=re.I)
    h = re.sub(r"\s+", " ", h).strip()
    return h[:160]


def build(live_research: bool = True) -> dict:
    cfg = json.loads((DATA / "portfolio.json").read_text(encoding="utf-8"))
    hold = [h["symbol"] for h in cfg["holdings"]]
    universe = hold + [s for s in cfg["research"] if s not in hold]
    log.info("fundamentals for %d companies", len(universe))
    cos = companies(universe)
    px = price_data(universe, cos)

    log.info("filings")
    fs = filings({s: cfg["bse_codes"][s] for s in universe if s in cfg["bse_codes"]}, settings.window_days)
    classify.classify_batch(fs, doc_text=doc_text)
    revenue = {}
    for s, c in cos.items():
        pl = c.get("pl") or {}
        rev = pl.get("rows", {}).get("Sales") or pl.get("rows", {}).get("Revenue") or []
        revenue[s] = next((v for v in reversed(rev) if v), None)
    materiality.score_all(fs, revenue, px)

    weights = {h["symbol"]: h["weight"] for h in cfg["holdings"]}
    # enrich: results cards & people
    filed_people = (_load_raw("people_from_filings.json") or {}).get("people", [])
    by_filing = {}
    for p in filed_people:
        by_filing.setdefault(p["event"]["filing"].split(":")[-1], []).append(p["id"])
    for f in fs:
        if f["category"] == "results" and f["kind"] in ("results", "board_outcome") and f["symbol"] in cos:
            card = results.quarter_card(cos[f["symbol"]])
            if card:
                f["results"] = card
                materiality.results_surprise(f, weights.get(f["symbol"]))
        if f["category"] == "management_change":
            ids = by_filing.get(f.get("attachment") or "", [])
            if not ids and llm.available():
                t = doc_text(f)
                if t:
                    for p in people.extract(t, f["symbol"]):
                        pid = "p-" + re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-")
                        p["id"] = pid
                        p.setdefault("event", {})["filing"] = "BSE:" + (f.get("attachment") or "")
                        filed_people.append(p)
                        ids.append(pid)
            f["people"] = ids
    # people disclosed in earlier filings but relevant to stories in the window
    for p in filed_people:
        if not (p.get("name") or "").strip():
            continue
        full = p["name"].lower()
        for f in fs:
            if f["symbol"] == p["symbol"] and f["category"] == "management_change" and p["id"] not in f.get("people", []):
                if full in ((f.get("doc_excerpt") or "") + " " + f["headline"]).lower():   # full name, not surname
                    f.setdefault("people", []).append(p["id"])
    used = {i for f in fs for i in f.get("people", [])}
    filed_people = [p for p in filed_people if p["id"] in used]   # don't carry stale people forever

    pid = {p["id"]: p for p in filed_people}
    for f in fs:
        if f["category"] == "management_change" and f.get("people"):
            materiality.rescore_people(f, [pid[i] for i in f["people"] if i in pid])
    stories = materiality.cluster(fs)
    lead_ids = {s["lead"] for s in stories if s["tier"] != "routine"}
    summarise([f for f in fs if f["id"] in lead_ids])
    for f in fs:
        f.pop("more", None)
        if f.get("doc_excerpt"):
            f["doc_excerpt"] = f["doc_excerpt"][:400] if f["id"] in lead_ids else None
        if not f.get("doc_excerpt"):
            f.pop("doc_excerpt", None)

    log.info("research dossiers")
    (OUT / "research").mkdir(parents=True, exist_ok=True)
    for s in universe:
        try:
            if s in cos and (live_research or settings.offline):
                d = research.build(s) if s in cfg["research"] or llm.available() else None
                if d is None:  # portfolio names without a key: numbers-only dossier
                    from .intel.fundamentals import dossier_numbers
                    c = cos[s]
                    d = {"symbol": s, "name": c.get("name"), "generated_by": {"numbers": "deterministic", "prose": "unavailable"},
                         "sources": {"transcripts": [{"period": l["period"], "url": l["url"]} for l in screener.transcript_links(c)],
                                     "statements": f"https://www.screener.in/company/{s}/consolidated/"},
                         **dossier_numbers(c), "business_mix": None, "guidance": [], "promises": None, "bull_bear": None}
                _write(f"research/{s}.json", d)
        except Exception as e:
            log.exception("research %s failed: %s", s, e)

    as_of = max((v["dates"][-1] for v in px.values() if v.get("dates")), default=None)
    port = []
    weights = {h["symbol"]: h["weight"] for h in cfg["holdings"]}
    for s in universe:
        c = cos.get(s, {})
        series = px.get(s, {})
        n = 260
        port.append({
            "symbol": s, "name": c.get("name"), "held": s in weights, "weight": weights.get(s),
            "sector": (c.get("sector") or [None])[-1], "industry": (c.get("sector") or [None, None])[-2],
            "mcap_cr": research.dossier_numbers(c)["snapshot"]["mcap_cr"] if c else None,
            "dates": series.get("dates", [])[-n:], "close": series.get("close", [])[-n:], "volume": series.get("volume", [])[-n:],
            "price_source": series.get("source", "screener"),
        })
    meta = {
        "generated_at": datetime.now(IST).isoformat(timespec="minutes"), "as_of": as_of,
        "window_days": settings.window_days, "filings": len(fs), "stories": len(stories),
        "classification": {m: sum(1 for f in fs if (f.get("class_method") or "").startswith(m)) for m in ("exchange", "rule", "llm", "default")},
        "doc_pass": sum(1 for f in fs if "+doc" in (f.get("class_method") or "")),
        "llm": llm.usage_report(), "models": vars(settings.models), "offline": settings.offline,
        "sources": {"prices": "Yahoo Finance (yfinance) → screener.in fallback", "filings": "BSE corporate announcements API → NSE fallback",
                    "fundamentals": "screener.in standardised statements + concall transcripts (BSE)", "people": "LODR profile annexures in filings"},
    }
    _write("meta.json", meta)
    _write("portfolio.json", port)
    _write("feed.json", {"filings": fs, "stories": stories})
    _write("people.json", filed_people)
    shutil.copy(DATA / "companies.json", OUT / "companies.json")
    shutil.copy(DATA / "network" / "demo_network.json", OUT / "network-demo.json")
    log.info("snapshot written to %s", OUT)
    return meta
