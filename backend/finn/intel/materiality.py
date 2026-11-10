"""Materiality: decide what earns the investor's attention.

score = base(category, kind, signals) scaled by company context, + price reaction.
Then filings about the same underlying event are clustered into one *story*
(e.g. five Jio IPO filings, four NCLAT updates) so the feed shows events, not paperwork.

Tiers: >= 60 'act' (Needs you), 30-59 'glance' (one-liner), < 30 'routine' (collapsed).
Network relevance is added on the device (the server never sees the network).
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

BASE = {
    ("results", "results"): 72, ("results", "board_outcome"): 70, ("results", "press"): 45,
    ("results", "deck"): 30, ("results", "results_doc"): 35, ("results", "board_intimation"): 12,
    ("results", "newspaper"): 4,
    ("management_change", None): 45,
    ("M&A", "acquisition"): 62, ("M&A", "merger"): 75, ("M&A", "scheme"): 70, ("M&A", "restructuring"): 68,
    ("M&A", "divestment"): 55, ("M&A", "jv"): 55, ("M&A", "listing"): 66, ("M&A", "subsidiary_admin"): 8, ("M&A", "newspaper"): 6,
    ("fund_raise", "equity_issue"): 58, ("fund_raise", "qip"): 65, ("fund_raise", "rights"): 62,
    ("fund_raise", "buyback"): 60, ("fund_raise", "allotment"): 14, ("fund_raise", "cp_repayment"): 4,
    ("litigation", "insolvency"): 80, ("litigation", "regulatory"): 70, ("litigation", None): 60,
    ("capex", None): 52, ("credit_rating", None): 20,
    ("press_release", "order_win"): 40, ("press_release", "clarification"): 48, ("press_release", "press"): 22,
    ("press_release", "monthly_update"): 30, ("press_release", "contract"): 62, ("capex", "commissioning"): 45,
    ("insider_trading", None): 42, ("pledging", None): 55,
    ("earnings_call", "transcript"): 28, ("earnings_call", "recording"): 6, ("earnings_call", None): 8,
    ("investor_meetings", None): 5, ("dividend", "dividend"): 22, ("dividend", None): 6,
    ("bonus_split", None): 38, ("postal_ballot", None): 8, ("agm_egm", None): 10, ("unclassified", None): 3,
}

WHY = {
    "results": "Quarterly numbers", "management_change": "Leadership change", "M&A": "Corporate action",
    "litigation": "Legal / regulatory", "fund_raise": "Capital raise", "capex": "Capacity / capex",
    "credit_rating": "Credit rating", "press_release": "Company news", "pledging": "Promoter pledge",
    "insider_trading": "Insider dealing", "earnings_call": "Earnings call", "investor_meetings": "Investor meetings",
    "dividend": "Dividend", "bonus_split": "Bonus / split", "postal_ballot": "Shareholder vote",
    "agm_egm": "General meeting", "unclassified": "Routine filing",
}


def base_score(f: dict) -> tuple[float, list[str]]:
    cat, kind, sig = f["category"], f.get("kind"), f.get("signals", {})
    s = BASE.get((cat, kind), BASE.get((cat, None), 10))
    why: list[str] = []
    if cat == "management_change":
        sen = sig.get("seniority", 1)
        s = {3: 82, 2: 58, 1: 32}[sen]
        if "independent director" in sig.get("roles", []) and sen < 3:
            s = 24
        why.append({3: "top-level role", 2: "senior management", 1: "board seat"}[sen])
    if cat == "credit_rating":
        s = {"downgrade": 72, "upgrade": 48, "reaffirm": 12}.get(sig.get("direction"), 20)
        why.append(f"rating {sig.get('direction', 'update')}")
    if cat == "M&A" and sig.get("wos_only"):
        s = min(s, 26)
        why.append("new subsidiary only")
    if (f.get("exch_subcategory") or "").lower() == "board meeting" and cat != "management_change":
        s = min(s, 30)   # an intimation of a future board decision is a calendar item, not news
        why.append("board meeting notice")
    if f.get("critical"):
        s += 5
    return s, why


def results_surprise(f: dict, weight: float | None) -> None:
    """Results matter when they move: re-score a results filing from its own numbers (no consensus needed).

    In-line quarters drop to 'worth a glance' with the headline numbers; big swings, margin
    shocks and quality flags stay at the top.
    """
    card = f.get("results")
    if not card:
        return
    m = {x["label"]: x for x in card["metrics"]}
    yoys = [abs(m[k]["yoy"]) for k in ("PAT", "EBITDA", "NII") if k in m and m[k]["yoy"] is not None]
    big = max(yoys, default=0)
    mg = abs((card.get("margin") or {}).get("yoy_pp") or 0)
    falls = [m[k]["yoy"] for k in ("PAT", "EBITDA", "NII") if k in m and m[k]["yoy"] is not None and m[k]["yoy"] <= -20]
    s = (40 + min(25, big * 0.35) + min(12, mg * 2.5) + 6 * len(card.get("flags", []))
         + (6 if falls else 0) + (4 if (weight or 0) >= 6 else 0))
    why = []
    if falls:
        why.append(f"profit line fell {abs(min(falls)):.0f}% YoY")
    elif big >= 20:
        why.append(f"profit line moved {big:.0f}% YoY")
    if mg >= 2:
        why.append(f"margin {mg:.1f}pp vs last year")
    if card.get("flags"):
        why.append("quality flag")
    if not why:
        why.append("in-line quarter")
    f["score"] = round(min(95, s), 1)
    f["tier"] = tier(f["score"])
    f["reasons"] = why


def order_relevance(f: dict, annual_revenue_cr: float | None) -> tuple[float, str | None]:
    """An order's size relative to the company. A 'significant' L&T order is ~0.4% of revenue: noise."""
    sig = f.get("signals", {})
    lo, hi = sig.get("order_min_cr"), sig.get("order_max_cr")
    if not lo or not annual_revenue_cr:
        return 0, None
    pct = lo / annual_revenue_cr * 100
    rng = f"{pct:.1f}–{hi / annual_revenue_cr * 100:.1f}%" if hi else f"≥{pct:.1f}%"
    if pct >= 5:
        return 30, f"order {rng} of annual revenue"
    if pct >= 2:
        return 12, f"order {rng} of annual revenue"
    return -15, f"order {rng} of annual revenue — routine for its size"


def price_reaction(f: dict, prices: dict | None) -> tuple[float, str | None]:
    """Did the stock react on the filing's trading day (or next)? z-score vs 60d daily moves."""
    if not prices or not prices.get("dates"):
        return 0, None
    d = f["date"]
    dates, close = prices["dates"], prices["close"]
    idx = next((i for i, x in enumerate(dates) if x >= d), None)
    if idx is None or idx == 0:
        return 0, None
    # after-hours filings move the next session
    if f.get("ts", "")[11:13] >= "15" and idx + 1 < len(dates) and dates[idx] == d:
        idx += 1
    rets = [close[i] / close[i - 1] - 1 for i in range(max(1, idx - 60), idx)]
    if len(rets) < 20:
        return 0, None
    sd = (sum(r * r for r in rets) / len(rets)) ** 0.5 or 1e-9
    r = close[idx] / close[idx - 1] - 1
    z = r / sd
    if abs(z) >= 2.5:
        return 10, f"stock {r * 100:+.1f}% that session ({z:+.1f}σ)"
    return 0, None


def tier(score: float) -> str:
    return "act" if score >= 60 else "glance" if score >= 30 else "routine"


STORY_KEYS = {
    "management_change": lambda f: "mgmt",
    "litigation": lambda f: "legal",
    "M&A": lambda f: "listing" if f.get("kind") == "listing" else f"ma-{f['id']}",
    "results": lambda f: "results",
}


def cluster(filings: list[dict], gap_days: int = 21) -> list[dict]:
    """Group filings on the same symbol & storyline. Returns stories sorted by score."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for f in filings:
        key_fn = STORY_KEYS.get(f["category"])
        k = (f["symbol"], f["category"], key_fn(f) if key_fn else f["id"])
        groups[k].append(f)
    stories = []
    for (sym, cat, _), fs in groups.items():
        fs.sort(key=lambda x: x["ts"] or "", reverse=True)
        # results: keep only the actual results/outcome as lead; decks/press/ads become attachments
        top = max(x["score"] for x in fs)
        near = [x for x in fs if x["score"] >= top - 12 and x.get("kind") != "newspaper"] or fs
        # the freshest near-top filing tells the story best (e.g. the company's clarification, not the exchange's query)
        lead = max(near, key=lambda x: (bool(x.get("results")), x["ts"] or "", x["score"]))
        bonus = 0 if cat == "results" else min(4, 2 * (len(fs) - 1))   # a developing story > a one-off
        score = round(min(100, lead["score"] + bonus), 1)
        stories.append({
            "id": "S-" + lead["id"], "symbol": sym, "category": cat, "lead": lead["id"],
            "score": score, "tier": tier(score), "latest": fs[0]["ts"], "first": fs[-1]["ts"],
            "filings": [x["id"] for x in fs], "why": WHY.get(cat, cat),
        })
    stories.sort(key=lambda s: (-s["score"], s["latest"] or ""))
    return stories


def score_all(filings: list[dict], revenue: dict[str, float], prices: dict[str, dict]) -> None:
    for f in filings:
        s, why = base_score(f)
        add, w = order_relevance(f, revenue.get(f["symbol"]))
        s += add
        if w:
            why.append(w)
        add, w = price_reaction(f, prices.get(f["symbol"]))
        s += add
        if w:
            why.append(w)
        f["score"] = round(max(0, min(100, s)), 1)
        f["tier"] = tier(f["score"])
        f["reasons"] = why


ROLE_SENIORITY = [(r"md ?& ?ceo|managing director|chief executive|\bceo\b|\bcfo\b|chief financial|^chairman|\bchairman\b(?! emeritus)", 3),
                  (r"deputy managing|whole[- ]time|director \(|group head|general counsel|senior management|kmp|vice[- ]chairman", 2)]


def rescore_people(f: dict, people: list[dict]) -> None:
    """Once we know *who* changed (from the filing's annexure), score on their role, not on keywords."""
    if not people:
        return
    people = [p for p in people if not re.search(r"additional charge", p.get("event", {}).get("change") or "", re.I)] or people
    sen = 1
    for p in people:
        role = (p.get("event", {}).get("role") or "").lower()
        for pat, lvl in ROLE_SENIORITY:
            if re.search(pat, role):
                sen = max(sen, lvl)
                break
    confirm = all(re.search(r"approv", (p.get("event", {}).get("change") or ""), re.I) for p in people)
    s = 40 if confirm else {3: 82, 2: 58, 1: 32}[sen]
    if f.get("critical"):
        s += 5
    f["score"] = s
    f["tier"] = tier(s)
    f["reasons"] = ["confirms an earlier-announced appointment"] if confirm else [{3: "top-level role", 2: "senior management", 1: "board seat"}[sen]]


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(re.sub(r"\.\d+$", "", ts[:23]))
