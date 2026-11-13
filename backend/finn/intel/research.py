"""Pull: on-demand research dossier for any NSE symbol screener covers.

Pipeline (each step reports progress so the app can show it live):
  1. fundamentals      screener page -> standardised statements           (no model)
  2. numbers           snapshot / trajectory / balance sheet / cash       (no model)
  3. transcripts       last 5 concall PDFs -> management turns -> filter  (no model)
  4. guidance          per transcript, explicit + directional guidance    ('extract' tier, cached forever)
                       -> every quote verified against the transcript text (no model)
  5. promise check     verified guidance vs reported quarters             ('reason' tier, once)
  6. business mix      segments from the company's own words              ('extract' tier)
  7. bull / bear       over the facts assembled above only                ('extract' tier)

Primary sources only: screener statements are built from the company's filings; transcripts and
annual reports are the company's own words. No news, broker notes, or model memory.

Honesty contract (what the `analysis` block in every dossier records):
  * per transcript: fetched? analysed? by which model? how many statements verified / rejected?
  * status: complete | partial | seeded | deferred | unavailable | failed | numbers_only
  * when live analysis is incomplete and a build-time seed exists, the seed is shown and labelled
    as build-time output with its generator — never as something this refresh produced.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

from .. import http, llm
from ..config import RAW, settings
from ..sources import bse, docs, screener
from . import transcripts as tx
from .fundamentals import dossier_numbers

log = logging.getLogger(__name__)
SEED = RAW / "llm_seed"   # build-time outputs for the committed demo snapshot (same schemas)
IST = timezone(timedelta(hours=5, minutes=30))
MIN_CALLS_FOR_COMPLETE = 3      # analysed calls needed before a live dossier counts as complete
OK = ("ok", "cached")


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


def direct_pdf(url: str) -> str:
    """Company sites often link a viewer page (…/pdf-viewer?pdf=/content/…/call.pdf) instead of the
    file. Pull the PDF address out of the query string so the download gets the document itself."""
    from urllib.parse import parse_qs, unquote, urljoin, urlparse
    u = urlparse(url)
    if u.path.lower().endswith(".pdf"):
        return url
    for key in ("pdf", "file", "url", "src", "doc", "path"):
        for v in parse_qs(u.query).get(key, []):
            v = unquote(v).strip()
            if v.lower().split("?")[0].endswith(".pdf"):
                return urljoin(f"{u.scheme}://{u.netloc}/", v)
    return url


def _transcript_pages(link: dict) -> list[str]:
    if link.get("file"):
        local = RAW / "transcripts" / link["file"].replace(".pdf", ".txt")
        if local.exists():
            return local.read_text(encoding="utf-8").split("\f")
        if settings.offline:
            return []
        return docs.cached_text(link["file"], lambda: bse.document(link["file"]))
    url = direct_pdf(link.get("url") or "")
    if url.startswith("http") and not settings.offline:       # company-hosted transcript
        name = hashlib.sha256(url.encode()).hexdigest()[:24] + ".pdf"
        return docs.cached_text(name, lambda: http.get(url, binary=True, ttl=None))
    return []


def facts_for_debate(name: str, nums: dict, promises: dict | None) -> list[str]:
    s, t, b, c = nums["snapshot"], nums["trajectory"], nums["balance_sheet"], nums["cash"]
    out = [f"ROCE {s['roce']}%; ROE {s['roe']}%"]   # no price-based numbers: keeps the prompt (and cache key) stable
    lq = s.get("latest_quarter")
    if lq:
        out.append(f"Latest quarter {lq['period']}: {lq['headline']}")
    out += [n["text"] for n in t["notes"] + b["notes"] + c["notes"]]
    if promises:
        for p in promises.get("promises", [])[:6]:
            if p.get("verdict") != "unknown":
                out.append(f"Guidance check [{p['said_in']}] {p['metric']}: {p['promise']} → {p['verdict']} ({p['outcome']})")
    return out


def _section(res: llm.Result | None, source: str = "live") -> dict:
    if res is None:
        return {"status": "skipped", "source": source}
    d = {"status": res.status, "source": source, "model": res.model}
    if res.error:
        d["error"] = res.error[:240]
    return d


def numbers_only(symbol: str, c: dict, why: str, status: str = "numbers_only") -> dict:
    """Dossier with deterministic numbers only, and an explicit statement of what is missing and why."""
    links = screener.transcript_links(c, n=5)
    return {
        "symbol": symbol, "name": c.get("name"),
        "generated_by": {"numbers": "deterministic (screener standardised statements)", "prose": "unavailable"},
        "analysis": {"status": status, "source": "none", "as_of": datetime.now(IST).isoformat(timespec="minutes"),
                     "coverage": f"0/{len(links)} calls analysed", "transcripts": [
                         {"period": l["period"], "url": l["url"], "status": "not_attempted"} for l in links],
                     "notes": [why]},
        "sources": {"transcripts": [{"period": l["period"], "url": l["url"]} for l in links],
                    "annual_reports": c.get("annualReports", [])[:2],
                    "statements": f"https://www.screener.in{c.get('url') or f'/company/{symbol}/'}"},
        **dossier_numbers(c), "business_mix": None, "guidance": [], "promises": None, "bull_bear": None,
    }


def build(symbol: str, progress: Callable[[str, str], None] = lambda step, msg: None,
          company: dict | None = None) -> dict:
    symbol = symbol.upper().strip()
    progress("fundamentals", f"Reading {symbol}'s financial statements")
    c = company or _company(symbol)
    nums = dossier_numbers(c)
    progress("numbers", "Computed trajectory, balance sheet and cash quality")
    seed = _seed(symbol)
    links = screener.transcript_links(c, n=5)

    can_call = llm.available() and llm.budget_left() > 0
    if not can_call and not seed:
        why = ("No model key configured: numbers only." if not llm.available() else
               "Model time budget for this refresh was used up before this company; analysis deferred to the next run.")
        return numbers_only(symbol, c, why, "unavailable" if not llm.available() else "deferred")

    # ---- 3-4. transcripts -> guidance (live), each quote verified ----------------------------
    tstat: list[dict] = []
    docs_text: dict[str, list[str]] = {}
    raw_items: list[dict] = []
    first_pages: list[str] = []
    if can_call:
        for link in links:
            row = {"period": link["period"], "url": link["url"]}
            tstat.append(row)
            progress("transcripts", f"Reading {link['period']} earnings call")
            try:
                pages = _transcript_pages(link)
            except Exception as e:          # missing / scanned PDFs shouldn't sink the dossier
                row.update(status="fetch_failed", error=str(e)[:160])
                continue
            if not pages or not "".join(pages).strip():
                row.update(status="no_text")
                continue
            docs_text[link["period"]] = pages
            first_pages = first_pages or pages
            excerpts = tx.prefilter(pages)
            if not excerpts:
                row.update(status="no_management_text")
                continue
            items, res = tx.extract_guidance(link["period"], excerpts, task=f"{symbol} guidance {link['period']}")
            row.update(status=res.status, model=res.model, extracted=len(items))
            if res.error:
                row["error"] = res.error[:200]
            raw_items += items
    index = tx.TranscriptIndex(docs_text)
    guidance, rejected = tx.verify_guidance(raw_items, index)
    for row in tstat:
        row["verified"] = sum(1 for g in guidance if g["said_in"] == row["period"])
        row["rejected"] = sum(1 for g in rejected if g.get("said_in") == row["period"])
    analysed = [r for r in tstat if r.get("status") in OK]
    missing = [r["period"] for r in tstat if r.get("status") not in OK]
    live_complete = bool(links) and len(analysed) >= min(MIN_CALLS_FOR_COMPLETE, len(links)) and not any(
        r.get("status") in ("failed", "deferred") for r in tstat)
    progress("guidance", f"{len(guidance)} guidance statements verified against transcripts "
                         f"({len(rejected)} rejected), {len(analysed)}/{len(links)} calls analysed")

    use_seed = bool(seed) and (not can_call or not live_complete)
    sec_bad: list = []
    model_bad: list = []
    notes: list[str] = []
    sections: dict[str, dict] = {}
    if use_seed:
        why = ("no model key configured" if not llm.available() else
               "model time budget was used up" if not can_call else
               f"live analysis covered {len(analysed)}/{len(links)} calls ({', '.join(missing) or 'none missing'} incomplete)")
        notes.append(f"Showing the build-time analysis because {why}. It was produced before this refresh by: "
                     f"{seed.get('_generator', 'a build-time run')}")
        if not docs_text:   # no live fetch this run: verify against the transcript text kept in the repo
            for link in links:
                local = RAW / "transcripts" / (link.get("file") or "-").replace(".pdf", ".txt")
                if local.exists():
                    docs_text[link["period"]] = local.read_text(encoding="utf-8").split("\f")
            index = tx.TranscriptIndex(docs_text)
        guidance = [dict(g) for g in seed.get("guidance", [])]
        if docs_text:       # the seed is held to the same rule as live output
            guidance, rejected = tx.verify_guidance(guidance, index)
        else:
            rejected = []
            notes.append("Build-time quotes could not be re-checked in this run (transcript text unavailable).")
        promises = tx.annotate_promises(json.loads(json.dumps(seed.get("promises"))), index, guidance, nums["quarters"])
        mix = seed.get("business_mix")
        debate = seed.get("bull_bear")
        for k in ("guidance", "promises", "business_mix", "bull_bear"):
            sections[k] = {"status": "seeded", "source": "seed"}
        status, source = "seeded", "seed"
    else:
        # ---- 5. promise check over verified guidance only ----------------------------------
        promises, pres = None, None
        if guidance:
            pres = tx.promise_vs_delivered(c["name"], guidance, nums["quarters"], missing, task=f"{symbol} promises")
            promises = pres.data if pres.ok else None
        progress("promises", "Checked promises against reported numbers")
        # ---- 6-7. business mix + bull/bear ------------------------------------------------
        mres = tx.business_mix(c["name"], first_pages, task=f"{symbol} business mix") if first_pages else None
        mix = mres.data if mres and mres.ok else None
        dres = tx.bull_bear(c["name"], facts_for_debate(c["name"], nums, promises), task=f"{symbol} bull/bear")
        debate = dres.data if dres.ok else None
        progress("debate", "Drafted bull and bear cases")
        sections = {"guidance": {"status": "ok" if analysed else ("failed" if tstat else "skipped"), "source": "live"},
                    "promises": _section(pres), "business_mix": _section(mres), "bull_bear": _section(dres)}
        if not guidance and analysed:
            notes.append("No forward-looking guidance with a verifiable quote was found in the analysed calls.")
        if not links:
            notes.append("screener.in lists no concall transcripts for this company, so there is no guidance to check.")
        sec_bad = [k for k, v in sections.items() if v["status"] not in (*OK, "skipped")]
        model_bad = [r for r in tstat if r.get("status") in ("failed", "deferred", "unavailable")]
        if analysed:
            status = "complete" if live_complete and not sec_bad else "partial"
        elif model_bad:
            status = "deferred" if all(r["status"] == "deferred" for r in model_bad) else "failed"
        else:               # no readable transcript at all: nothing for a model to analyse
            status = "partial" if debate else "numbers_only"
            if tstat:
                notes.append("No concall transcript could be read (" + ", ".join(
                    f"{r['period']}: {r.get('status')}" for r in tstat) + "); guidance and promise checks need them.")
        source = "live"
    if rejected:
        notes.append(f"{len(rejected)} model-extracted statement(s) were dropped because their quote could not be "
                     "found in the transcript.")
    if missing and analysed and not use_seed:
        notes.append("Not analysed: " + ", ".join(f"{r['period']} ({r.get('status')})" for r in tstat
                                                   if r.get("status") not in OK))

    models_used = sorted({m for m in [*(r.get("model") for r in tstat), *(v.get("model") for v in sections.values())] if m})
    return {
        "symbol": symbol, "name": c.get("name"), "generated_by": {
            "numbers": "deterministic (screener standardised statements)",
            "prose": {"complete": "llm", "partial": "llm (partial)", "seeded": "seeded (build-time)"}.get(status, "unavailable"),
            "models": models_used if source == "live" else seed.get("_generator") if seed else None,
        },
        "analysis": {
            "status": status, "source": source, "as_of": datetime.now(IST).isoformat(timespec="minutes"),
            "coverage": f"{len(analysed)}/{len(links)} calls analysed this refresh",
            "transcripts": tstat or [{"period": l["period"], "url": l["url"], "status": "not_attempted"} for l in links],
            "sections": sections, "verified_quotes": len(guidance), "rejected": rejected[:20], "notes": notes,
            # partial because documents are missing/unreadable (nothing to retry) vs. because model calls failed
            "limited_by": ("sources" if status == "partial" and source == "live" and not sec_bad and not model_bad
                           else "model" if status in ("partial", "failed", "deferred") else None),
        },
        "sources": {"transcripts": [{"period": l["period"], "url": l["url"]} for l in links],
                    "annual_reports": c.get("annualReports", [])[:2],
                    "statements": f"https://www.screener.in{c.get('url') or f'/company/{symbol}/'}"},
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
