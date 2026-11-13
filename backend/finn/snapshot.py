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
import os
import re
import shutil
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import http, llm
from .config import DATA, OUT, RAW, settings
from .intel import classify, materiality, people, research, results
from .sources import bse, docs, nse, prices, screener

log = logging.getLogger("finn")
IST = timezone(timedelta(hours=5, minutes=30))

# Run report: what each source and model step actually did. Written to meta.json["run"] and the
# GitHub Actions step summary, so a degraded refresh is visible instead of silently committed.
REPORT: dict = {}
DOCS: Counter = Counter()
_DOC_MEMO: dict[str, str | None] = {}


def _reset_report() -> None:
    REPORT.clear()
    REPORT.update({"sources": {"fundamentals": {}, "prices": {}, "filings": {}}, "warnings": [], "notes": [],
                   "people": Counter(), "summaries": Counter(), "research": {}})
    DOCS.clear()
    _DOC_MEMO.clear()


def note(msg: str) -> None:
    """Something expected that the pipeline already handled (shown, but doesn't lower run health)."""
    if msg not in REPORT.setdefault("notes", []):
        REPORT["notes"].append(msg)
    log.info(msg)


def warn(msg: str) -> None:
    if msg not in REPORT.setdefault("warnings", []):
        REPORT["warnings"].append(msg)
    log.warning(msg)


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
    rep = REPORT.setdefault("sources", {}).setdefault("fundamentals", {})
    for s in symbols:
        if settings.offline and s in cap:
            out[s], rep[s] = cap[s], "capture"
            continue
        try:
            out[s], rep[s] = screener.fetch_company(s), "live"
        except Exception as e:
            log.warning("screener %s: %s (using capture if any)", s, e)
            if s in cap:
                out[s], rep[s] = cap[s], "capture (stale)"
            else:
                rep[s] = "missing"
    return out


def price_data(symbols: list[str], cos: dict) -> dict[str, dict]:
    cap = _load_raw("prices.json") or {}
    now = datetime.now(IST)
    closed = now.hour > 15 or (now.hour == 15 and now.minute >= 35)
    out = {}
    rep = REPORT.setdefault("sources", {}).setdefault("prices", {})
    for s in symbols:
        if settings.offline and s in cap:
            out[s], rep[s] = cap[s], "capture"
            continue
        try:
            ser = prices.eod(s, cos.get(s, {}).get("companyId"), settings.price_days)
            out[s] = prices.drop_partial_session(ser, now.strftime("%Y-%m-%d"), closed)
            rep[s] = ser.get("source", "live") if isinstance(ser, dict) else "live"
        except Exception as e:
            log.warning("prices %s: %s", s, e)
            if s in cap:
                out[s], rep[s] = cap[s], "capture (stale)"
            else:
                rep[s] = "missing"
    return out


def filings(codes: dict[str, str], days: int) -> list[dict]:
    """BSE first; NSE when BSE refuses. BSE's API answers 403 to GitHub-hosted runners, so after the
    first 403 the rest of the run goes straight to NSE instead of paying for 21 refusals."""
    end = datetime.now(IST).date()
    start = end - timedelta(days=days)
    cap = _load_raw("bse_announcements.json") or {}
    rep = REPORT.setdefault("sources", {}).setdefault("filings", {})
    rows: list[dict] = []
    bse_refused: str | None = None
    for sym, code in codes.items():
        if settings.offline and sym in cap:
            rows += [bse.normalise(r, sym) for r in cap[sym]]
            rep[sym] = "capture"
            continue
        if not bse_refused:
            try:
                rows += [bse.normalise(r, sym) for r in bse.announcements(code, start, end)]
                rep[sym] = "BSE"
                continue
            except http.PermanentError as e:
                bse_refused = str(e)
                note(f"BSE announcements API refused this runner ({str(e).split(' for ')[0]}); "
                     "filings for this run come from NSE.")
            except Exception as e:
                log.warning("BSE %s: %s — trying NSE", sym, e)
        try:
            rows += [nse.normalise(r, sym) for r in nse.announcements(sym, start, end)]
            rep[sym] = "NSE"
            continue
        except Exception as e2:
            log.warning("NSE %s: %s (using capture if any)", sym, e2)
        kept = [bse.normalise(r, sym) for r in cap.get(sym, [])]
        kept = [f for f in kept if (f.get("date") or "") >= start.isoformat()]
        rows += kept
        rep[sym] = "capture (stale)" if kept else "none"
    seen, out = set(), []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


_STOP = {"the", "of", "and", "to", "for", "in", "on", "a", "an", "has", "is", "regarding", "about", "under",
         "regulation", "sebi", "lodr", "intimation", "disclosure", "company", "limited", "ltd", "exchange",
         "informed", "submitted", "the", "with", "by", "from", "as", "at", "copy", "updates", "update"}


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (t or "").lower()) if w not in _STOP}


def bridge_to_bse(fs: list[dict]) -> int:
    """Find the BSE twin of each NSE filing in the BSE capture (same company, filed within 20 min,
    overlapping words). Lets NSE-sourced runs reuse BSE-keyed build-time data: extracted filing text,
    one-line summaries and the people profiles in people_from_filings.json."""
    cap = _load_raw("bse_announcements.json") or {}
    pool: dict[str, list[dict]] = {}
    for sym, arr in cap.items():
        pool[sym] = [b for b in (bse.normalise(r, sym) for r in arr) if b.get("ts") and b.get("attachment")]
    n = 0
    for f in fs:
        if f.get("exchange") != "NSE":
            f["seed_key"] = f.get("attachment")
            continue
        try:
            t = datetime.fromisoformat(f["ts"][:19])
        except (KeyError, ValueError):
            continue
        cands = []
        for b in pool.get(f["symbol"], []):
            try:
                dt = abs((datetime.fromisoformat(b["ts"][:19]) - t).total_seconds())
            except ValueError:
                continue
            if dt <= 20 * 60:
                shared = len(_words(f["subject"] + " " + f["headline"]) &
                             _words(" ".join([b["subject"], b["headline"], b["exch_category"], b["exch_subcategory"]])))
                cands.append((shared, -dt, b))
        if not cands:
            continue
        cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
        shared, neg_dt, b = cands[0]
        if shared == 0 and not (len(cands) == 1 and -neg_dt <= 5 * 60):
            continue            # ambiguous: never attach another filing's people or text
        f["bse_twin"] = {"id": b["id"], "attachment": b["attachment"], "url": b["url"]}
        f["seed_key"] = b["attachment"]
        n += 1
    return n


def doc_text(f: dict) -> str | None:
    """First pages of a filing PDF. Small files only: annual reports etc. are never pulled here.

    The PDF comes from the exchange the filing came from (NSE filings live on nsearchives.nseindia.com).
    Each filing is fetched at most once per run, successes are cached on disk forever, and every
    outcome is counted in the run report.
    """
    att = f.get("attachment")
    if not att:
        return None
    if f["id"] in _DOC_MEMO:
        return _DOC_MEMO[f["id"]]
    text = None
    for key in (f.get("seed_key"), att):
        local = RAW / "filings" / (key or "-").replace(".pdf", ".txt")
        if key and local.exists():
            DOCS["repo text"] += 1
            text = local.read_text(encoding="utf-8")
            break
    if text is None:
        size = int(f.get("size") or 0)
        if settings.offline:
            DOCS["skipped (offline)"] += 1
        elif size > 3_000_000:
            DOCS["skipped (large file)"] += 1
        else:
            ex = f.get("exchange", "BSE")
            name = att                       # same text-cache key as earlier runs
            cached = (docs.TEXT_CACHE / (name.rsplit(".", 1)[0] + ".pages.txt")).exists()
            try:
                loader = (lambda: nse.document(f.get("url") or att)) if ex == "NSE" else (lambda: bse.document(att))
                pages = docs.cached_text(name, loader)
                text = "\n".join(pages[:3])
                DOCS["cache" if cached else f"fetched from {ex}"] += 1
                if not text.strip():
                    DOCS["no text (scanned PDF)"] += 1
                    text = None
            except Exception as e:
                code = re.search(r"\b(4\d\d|5\d\d)\b", str(e))
                DOCS[f"failed from {ex} ({code.group(1) if code else type(e).__name__})"] += 1
                log.info("doc %s %s: %s", ex, att, e)
    _DOC_MEMO[f["id"]] = text
    return text


SUMMARY_SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "line": {"type": "string", "description": "<= 18 words, plain English, what happened + why it matters"}},
    "required": ["i", "line"]}}


def summarise(items: list[dict]) -> None:
    """One-liners for stories worth a glance. Batched on the cheapest tier; seeded/fallback otherwise."""
    seed = _load_raw("llm_seed/_summaries.json") or {}
    todo = []
    cnt = REPORT.setdefault("summaries", Counter())
    for f in items:
        key = f.get("seed_key") or f.get("attachment") or f["id"]
        if key in seed:
            f["summary"], f["summary_by"] = seed[key], "seeded"
            cnt["seeded (build-time)"] += 1
        else:
            todo.append(f)
    for i in range(0, len(todo), 25):
        chunk = todo[i:i + 25]
        listing = "\n\n".join(f"{j}. [{f['symbol']}] {f['subject']} | {f['headline'][:300]} | {(f.get('doc_excerpt') or '')[:700]}"
                              for j, f in enumerate(chunk))
        res = llm.run("bulk", task=f"summaries {i // 25 + 1}", system=(
            "Write a one-line summary (<= 18 words) of each Indian exchange filing for a busy fund manager: "
            "what happened and the number that matters. No fluff, no 'the company announced'. "
            "Use only the text given for that filing."),
            prompt=listing, schema=SUMMARY_SCHEMA)
        out = res.data if res.ok and isinstance(res.data, list) else []
        got = {o["i"]: o["line"] for o in out if isinstance(o, dict) and isinstance(o.get("i"), int) and o.get("line")}
        for j, f in enumerate(chunk):
            if j in got:
                f["summary"], f["summary_by"], f["summary_model"] = got[j], "llm", res.model
                cnt["model"] += 1
            else:
                f["summary"], f["summary_by"] = fallback_summary(f), "rule"
                cnt[f"rule (model {res.status})" if not res.ok else "rule (model skipped it)"] += 1


def fallback_summary(f: dict) -> str:
    h = f.get("headline") or ""
    if len(h) < 25 or re.fullmatch(r"(enclosed|announcement as attached|updates?|general updates|please find enclosed.*)", h.strip(), re.I):
        h = f.get("subject") or h
    h = re.sub(r"^(announcement under regulation 30 \(lodr\)-|disclosure under regulation 30.*?-\s*)", "", h, flags=re.I)
    h = re.sub(r"\s+", " ", h).strip()
    return h[:160]


def research_order(universe: list[str], cfg: dict) -> list[str]:
    """Model time is budgeted, so spend it where it matters most: research names without a build-time
    seed, then holdings by weight, then names that have a seed to fall back on."""
    w = {h["symbol"]: h["weight"] for h in cfg["holdings"]}
    seeded = {p.stem for p in (RAW / "llm_seed").glob("*.json") if not p.stem.startswith("_")}
    return sorted(universe, key=lambda s: (s in seeded, s not in cfg["research"], -(w.get(s) or 0), s))


def build(live_research: bool = True) -> dict:
    llm.start_run()
    _reset_report()
    cfg = json.loads((DATA / "portfolio.json").read_text(encoding="utf-8"))
    hold = [h["symbol"] for h in cfg["holdings"]]
    universe = hold + [s for s in cfg["research"] if s not in hold]
    log.info("fundamentals for %d companies", len(universe))
    cos = companies(universe)
    px = price_data(universe, cos)

    log.info("filings")
    fs = filings({s: cfg["bse_codes"][s] for s in universe if s in cfg["bse_codes"]}, settings.window_days)
    twins = bridge_to_bse(fs)
    if any(f.get("exchange") == "NSE" for f in fs):
        log.info("matched %d NSE filings to their BSE twins in the capture", twins)
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
    pcount = REPORT.setdefault("people", Counter())
    by_filing = {}
    for p in filed_people:
        p.setdefault("source", {"method": "build-time capture", "filing": p["event"]["filing"]})
        by_filing.setdefault(p["event"]["filing"].split(":")[-1], []).append(p["id"])
    known_ids = {p["id"] for p in filed_people}
    for f in fs:
        if f["category"] == "results" and f["kind"] in ("results", "board_outcome") and f["symbol"] in cos:
            card = results.quarter_card(cos[f["symbol"]])
            if card:
                f["results"] = card
                materiality.results_surprise(f, weights.get(f["symbol"]))
        if f["category"] == "management_change":
            ids = list(by_filing.get(f.get("seed_key") or "", []) or by_filing.get(f.get("attachment") or "", []))
            if ids:
                pcount["linked from build-time profiles"] += 1
            elif llm.available():
                t = doc_text(f)
                if not t:
                    pcount["no filing text"] += 1
                else:
                    st: dict = {}
                    for p in people.extract(t, f["symbol"], status=st):
                        pid = "p-" + re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-")
                        p["id"] = pid
                        p.setdefault("event", {})["filing"] = f"{f.get('exchange', 'BSE')}:" + (f.get("attachment") or "")
                        if pid not in known_ids:
                            filed_people.append(p)
                            known_ids.add(pid)
                        ids.append(pid)
                    pcount[f"extracted ({st.get('status')})" if st.get("status") in ("ok", "cached")
                           else f"names only — model {st.get('status')}"] += 1
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

    log.info("research dossiers (model budget left: %.0f min)", llm.budget_left() / 60)
    (OUT / "research").mkdir(parents=True, exist_ok=True)
    rrep = REPORT.setdefault("research", {})
    for s in research_order(universe, cfg):
        if s not in cos:
            rrep[s] = {"status": "no_fundamentals", "note": "previous dossier (if any) kept"}
            continue
        try:
            if live_research or settings.offline:
                d = research.build(s, company=cos[s])
            else:
                d = research.numbers_only(s, cos[s], "Live research disabled for this run.")
            _write(f"research/{s}.json", d)
            a = d.get("analysis", {})
            rrep[s] = {"status": a.get("status"), "coverage": a.get("coverage"), "limited_by": a.get("limited_by"),
                       "verified_quotes": a.get("verified_quotes", 0), "rejected": len(a.get("rejected") or [])}
            log.info("research %s: %s, %s", s, a.get("status"), a.get("coverage"))
        except Exception as e:
            log.exception("research %s failed: %s", s, e)
            rrep[s] = {"status": "error", "error": str(e)[:200], "note": "previous dossier (if any) kept"}

    as_of = max((v["dates"][-1] for v in px.values() if v.get("dates")), default=None)
    port = []
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
    feeds = Counter(REPORT["sources"]["filings"].values())
    run = finish_report(universe)
    meta = {
        "generated_at": datetime.now(IST).isoformat(timespec="minutes"), "as_of": as_of,
        "window_days": settings.window_days, "filings": len(fs), "stories": len(stories),
        "classification": {m: sum(1 for f in fs if (f.get("class_method") or "").startswith(m)) for m in ("exchange", "rule", "llm", "default")},
        "doc_pass": sum(1 for f in fs if "+doc" in (f.get("class_method") or "")),
        "llm": llm.usage_report(), "models": {t: settings.models.chain(t) for t in ("bulk", "extract", "reason")},
        "offline": settings.offline, "run": run,
        "sources": {"prices": "Yahoo Finance (yfinance) → screener.in fallback",
                    "filings": "BSE corporate announcements API → NSE fallback" + (
                        f" (this run: {', '.join(f'{k} ×{v}' for k, v in feeds.items())})" if feeds else ""),
                    "fundamentals": "screener.in standardised statements + concall transcripts (BSE)", "people": "LODR profile annexures in filings"},
    }
    _write("meta.json", meta)
    _write("portfolio.json", port)
    _write("feed.json", {"filings": fs, "stories": stories})
    _write("people.json", filed_people)
    shutil.copy(DATA / "companies.json", OUT / "companies.json")
    shutil.copy(DATA / "network" / "demo_network.json", OUT / "network-demo.json")
    log.info("snapshot written to %s (health: %s)", OUT, run["health"])
    write_step_summary(meta)
    return meta


def finish_report(universe: list[str]) -> dict:
    """Turn the counters into a verdict: ok | degraded | failed (failed = do not publish)."""
    src = REPORT["sources"]
    n = max(1, len(universe))
    missing_px = [s for s in universe if src["prices"].get(s) in (None, "missing")]
    missing_fund = [s for s in universe if src["fundamentals"].get(s) in (None, "missing")]
    no_feed = [s for s, v in src["filings"].items() if v == "none"]
    stale = [s for grp in src.values() for s, v in grp.items() if "stale" in str(v)]
    u = llm.usage_report()
    research_bad = {s: r["status"] for s, r in REPORT["research"].items()
                    if r.get("status") not in ("complete", "seeded") and r.get("limited_by") != "sources"}
    thin = [s for s, r in REPORT["research"].items() if r.get("limited_by") == "sources"]
    if thin:
        note("Fewer earnings-call transcripts available than a full analysis needs (not published or not "
             f"readable), so these dossiers are partial: {', '.join(thin)}")
    if missing_px:
        warn(f"No price series for {len(missing_px)} companies: {', '.join(missing_px)}")
    if missing_fund:
        warn(f"No fundamentals for {len(missing_fund)} companies: {', '.join(missing_fund)}")
    if no_feed:
        warn(f"No filings source worked for: {', '.join(no_feed)}")
    if stale:
        warn(f"{len(stale)} source(s) fell back to the build-time capture (stale): {', '.join(sorted(set(stale)))}")
    failed_docs = sum(v for k, v in DOCS.items() if k.startswith("failed"))
    if failed_docs:
        warn(f"{failed_docs} filing PDF(s) could not be fetched; those filings were classified from their titles only.")
    if u.get("auth_error"):
        warn(u["auth_error"])
    retired = {m: s["retired"] for m, s in u["models"].items() if s.get("retired")}
    for m, why in retired.items():
        warn(f"Model {m} retired for this run: {why}")
    tot = u["totals"]
    if tot["failed"] or tot["deferred"]:
        warn(f"Model calls: {tot['calls']} ok, {tot['cached']} cached, {tot['failed']} failed, {tot['deferred']} deferred "
             f"(budget {u['budget_min']:.0f} min, used {u['elapsed_min']} min). Failed/deferred work is labelled in the "
             "app and retried next run.")
    if research_bad:
        by: dict[str, list[str]] = {}
        for sym, st in research_bad.items():
            by.setdefault(st, []).append(sym)
        label = {"unavailable": "no model key", "deferred": "model budget used up — retried next run",
                 "partial": "some calls/sections missing", "failed": "model calls failed — retried next run"}
        warn("Dossiers not fully analysed this run: " + "; ".join(
            f"{st} ×{len(v)} ({label.get(st, st)}): {', '.join(v)}" for st, v in by.items()))
    health = "ok"
    if REPORT["warnings"]:
        health = "degraded"
    if len(missing_px) > n / 2 or len(missing_fund) > n / 2 or len(no_feed) > n / 2:
        health = "failed"
    return {"health": health, "warnings": REPORT["warnings"], "notes": REPORT.get("notes", []), "sources": src, "documents": dict(DOCS),
            "people": dict(REPORT["people"]), "summaries": dict(REPORT["summaries"]),
            "research": REPORT["research"]}


def write_step_summary(meta: dict) -> None:
    """Markdown summary on the GitHub Actions run page (no secrets: only counts, models and statuses)."""
    path = os.getenv("GITHUB_STEP_SUMMARY")
    run, u = meta["run"], meta["llm"]
    lines = [f"## FINN refresh — {run['health'].upper()}", "",
             f"Generated {meta['generated_at']} · prices as of {meta['as_of']} · {meta['filings']} filings, "
             f"{meta['stories']} stories", ""]
    if run["warnings"]:
        lines += ["### Warnings", *[f"- {w}" for w in run["warnings"]], ""]
    if run.get("notes"):
        lines += ["### Notes (expected, handled)", *[f"- {w}" for w in run["notes"]], ""]
    lines += ["### Model calls", "| tier | models | ok | cached | failed | deferred |", "|---|---|---|---|---|---|"]
    for t, v in u["tiers"].items():
        lines.append(f"| {t} | {' → '.join(v['models'])} | {v['calls']} | {v['cached']} | {v['failed']} | {v['deferred']} |")
    if u["models"]:
        lines += ["", "| model | requests | ok | errors | retired |", "|---|---|---|---|---|"]
        for m, v in u["models"].items():
            lines.append(f"| {m} | {v['requests']} | {v['ok']} | {', '.join(f'{k}×{n}' for k, n in v['errors'].items()) or '-'} | {v['retired'] or '-'} |")
    lines += ["", "### Dossiers", "| symbol | status | coverage | verified quotes | rejected |", "|---|---|---|---|---|"]
    for s, r in run["research"].items():
        lines.append(f"| {s} | {r.get('status')} | {r.get('coverage') or '-'} | {r.get('verified_quotes', '-')} | {r.get('rejected', '-')} |")
    lines += ["", "### Filing documents", *[f"- {k}: {v}" for k, v in run["documents"].items()]]
    md = "\n".join(lines) + "\n"
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(md)
    if os.getenv("GITHUB_ACTIONS") == "true":
        for w in run["warnings"]:
            print(f"::warning title=FINN refresh::{w}")
