"""Pull: on-demand research dossier for any NSE symbol screener covers.

Pipeline (each step reports progress so the app can show it live):
  1. fundamentals      screener page -> standardised statements           (no model)
  2. numbers           snapshot / trajectory / balance sheet / cash       (no model)
  3. transcripts       last 5 concall PDFs -> management turns -> filter  (no model)
  4. guidance          per transcript, explicit + directional guidance    ('extract' tier, cached forever)
  5. promise check     guidance vs reported quarters                      ('reason' tier, once)
  6. business mix      segments from the company's own words              ('extract' tier)
  7. bull / bear       over the facts assembled above only                ('reason' tier)

Primary sources only: screener statements are built from the company's filings; transcripts and
annual reports are the company's own words. No news, broker notes, or model memory.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable

from .. import llm
from ..config import RAW, settings
from ..sources import bse, docs, screener
from . import transcripts as tx
from .fundamentals import dossier_numbers

log = logging.getLogger(__name__)
SEED = RAW / "llm_seed"   # build-time outputs for the committed demo snapshot (same schemas)


def _seed(symbol: str) -> dict | None:
    p = SEED / f"{symbol}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _company(symbol: str) -> dict:
    cap = RAW / "screener.json"
    if settings.offline and cap.exists():
        data = json.loads(cap.read_text(encoding="utf-8"))
        if symbol in data:
            return data[symbol]
    return screener.fetch_company(symbol)


def _transcript_pages(link: dict) -> list[str]:
    if not link.get("file"):
        return []
    local = RAW / "transcripts" / link["file"].replace(".pdf", ".txt")
    if local.exists():
        return [local.read_text(encoding="utf-8")]
    return docs.cached_text(link["file"], lambda: bse.document(link["file"]))


def facts_for_debate(name: str, nums: dict, promises: dict | None) -> list[str]:
    s, t, b, c = nums["snapshot"], nums["trajectory"], nums["balance_sheet"], nums["cash"]
    out = [f"ROCE {s['roce']}%; ROE {s['roe']}%"]   # no price-based numbers: keeps the prompt (and cache key) stable
    lq = s.get("latest_quarter")
    if lq:
        out.append(f"Latest quarter {lq['period']}: {lq['headline']}")
    out += [n["text"] for n in t["notes"] + b["notes"] + c["notes"]]
    if promises:
        for p in promises.get("promises", [])[:6]:
            out.append(f"Guidance check [{p['said_in']}] {p['metric']}: {p['promise']} → {p['verdict']} ({p['outcome']})")
    return out


def build(symbol: str, progress: Callable[[str, str], None] = lambda step, msg: None) -> dict:
    symbol = symbol.upper().strip()
    progress("fundamentals", f"Reading {symbol}'s financial statements")
    c = _company(symbol)
    nums = dossier_numbers(c)
    progress("numbers", "Computed trajectory, balance sheet and cash quality")
    seed = _seed(symbol) if not llm.available() else None

    links = screener.transcript_links(c, n=5)
    guidance: list[dict] = []
    first_pages: list[str] = []
    if seed:
        guidance = seed.get("guidance", [])
    else:
        for i, link in enumerate(links):
            progress("transcripts", f"Reading {link['period']} earnings call")
            try:
                pages = _transcript_pages(link)
            except Exception as e:  # missing / scanned PDFs shouldn't sink the dossier
                log.warning("transcript %s failed: %s", link, e)
                continue
            if i == 0:
                first_pages = pages
            excerpts = tx.prefilter(pages)
            guidance += tx.extract_guidance(link["period"], excerpts)
    progress("guidance", f"{len(guidance)} guidance statements found")

    promises = seed.get("promises") if seed else (
        tx.promise_vs_delivered(c["name"], guidance, nums["quarters"]) if guidance else None)
    progress("promises", "Checked promises against reported numbers")
    mix = seed.get("business_mix") if seed else (tx.business_mix(c["name"], first_pages) if first_pages else None)
    debate = seed.get("bull_bear") if seed else tx.bull_bear(c["name"], facts_for_debate(c["name"], nums, promises))
    progress("debate", "Drafted bull and bear cases")

    llm_method = "seeded" if seed else ("llm" if llm.available() else "unavailable")
    return {
        "symbol": symbol, "name": c.get("name"), "generated_by": {
            "numbers": "deterministic (screener standardised statements)",
            "prose": llm_method if (guidance or promises or debate) else "unavailable",
            "models": vars(settings.models) if llm_method == "llm" else (seed or {}).get("_generator"),
        },
        "sources": {"transcripts": [{"period": l["period"], "url": l["url"]} for l in links],
                    "annual_reports": c.get("annualReports", [])[:2], "statements": f"https://www.screener.in{c.get('url') or f'/company/{symbol}/'}"},
        **nums,
        "business_mix": mix,
        "guidance": guidance,
        "promises": promises,
        "bull_bear": debate,
    }


def safe_symbol(s: str) -> str:
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", s.upper()):
        raise ValueError("bad symbol")
    return s.upper()
