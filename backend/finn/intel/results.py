"""Quarterly results -> first cut of the headline numbers (Revenue, EBITDA, PBT, PAT; QoQ & YoY).

Two independent paths that check each other:
  A. The results filing itself (PDF) -> 'extract' tier LLM pulls the consolidated P&L columns.
  B. screener.in's standardised quarterly table (built from the same filing).
If A is available and agrees with B within 2%, the card says 'verified against filing';
if they disagree we show A and flag the gap. Without an API key, B alone is used.

Lenders (banks/NBFCs) have no meaningful EBITDA; we show Net Interest Income instead
(interest earned − interest expended), which is what investors actually track.
"""
from __future__ import annotations

from .. import llm

LENDER_HINTS = ("Financing Profit", "Financing Margin %")


def is_lender(q: dict) -> bool:
    return any(h in q["rows"] for h in LENDER_HINTS)


def _row(q: dict, *names: str) -> list | None:
    for n in names:
        if n in q["rows"]:
            return q["rows"][n]
    return None


def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1) * 100 * (1 if b > 0 else -1), 1)


def quarter_card(company: dict, col: int = -1) -> dict | None:
    """Headline numbers for quarter `col` (default latest) with QoQ / YoY deltas."""
    q = company.get("quarters")
    if not q or not q.get("cols"):
        return None
    n = len(q["cols"])
    i = col % n
    lender = is_lender(q)
    rev = _row(q, "Sales", "Revenue")
    pbt = _row(q, "Profit before tax")
    pat = _row(q, "Net Profit")
    if lender:
        interest = _row(q, "Interest")
        mid = [None if (r is None or x is None) else round(r - x, 1) for r, x in zip(rev, interest)]
        mid_label = "NII"
    else:
        mid = _row(q, "Operating Profit")
        mid_label = "EBITDA"
    metrics = []
    for label, series in (("Revenue", rev), (mid_label, mid), ("PBT", pbt), ("PAT", pat)):
        if not series:
            continue
        cur = series[i]
        prev = series[i - 1] if i - 1 >= 0 else None
        yago = series[i - 4] if i - 4 >= 0 else None
        metrics.append({"label": label, "value": cur, "prev": prev, "yago": yago,
                        "qoq": _pct(cur, prev), "yoy": _pct(cur, yago)})
    out = {"period": q["cols"][i], "prev_period": q["cols"][i - 1] if i else None,
           "yago_period": q["cols"][i - 4] if i >= 4 else None, "lender": lender,
           "unit": "₹ Cr", "metrics": metrics, "source": "screener quarterly table (standardised from exchange filing)"}
    # margins & quality flags
    if not lender and rev and mid and rev[i]:
        m_now = mid[i] / rev[i] * 100
        m_prev = mid[i - 1] / rev[i - 1] * 100 if i and rev[i - 1] else None
        m_yago = mid[i - 4] / rev[i - 4] * 100 if i >= 4 and rev[i - 4] else None
        out["margin"] = {"now": round(m_now, 1), "qoq_pp": round(m_now - m_prev, 1) if m_prev else None,
                         "yoy_pp": round(m_now - m_yago, 1) if m_yago else None}
    flags = []
    oi = _row(q, "Other Income")
    if not lender and oi and pbt and pbt[i] and oi[i] is not None and pbt[i] > 0 and oi[i] / pbt[i] > 0.25:
        flags.append(f"Other income is {oi[i] / pbt[i] * 100:.0f}% of PBT — core profit is lower than headline")
    tax = _row(q, "Tax %")
    if tax and tax[i] is not None and i and tax[i - 1] is not None and abs(tax[i] - tax[i - 1]) >= 8:
        flags.append(f"Tax rate moved {tax[i - 1]:.0f}% → {tax[i]:.0f}% — check for one-offs")
    out["flags"] = flags
    out["headline"] = headline(out)
    return out


def headline(card: dict) -> str:
    """One deterministic sentence — no model needed for arithmetic."""
    m = {x["label"]: x for x in card["metrics"]}
    parts = []
    if "Revenue" in m and m["Revenue"]["yoy"] is not None:
        parts.append(f"Revenue {m['Revenue']['yoy']:+.0f}% YoY")
    mid = "NII" if card["lender"] else "EBITDA"
    if mid in m and m[mid]["yoy"] is not None:
        parts.append(f"{mid} {m[mid]['yoy']:+.0f}%")
    if "PAT" in m and m["PAT"]["yoy"] is not None:
        parts.append(f"PAT {m['PAT']['yoy']:+.0f}%")
    if card.get("margin") and card["margin"].get("yoy_pp") is not None:
        mg = card["margin"]
        parts.append(f"margin {mg['now']:.1f}% ({mg['yoy_pp']:+.1f}pp YoY)")
    return ", ".join(parts)


EXTRACT_SCHEMA = {"type": "object", "properties": {
    "period_end": {"type": "string"}, "basis": {"type": "string", "enum": ["consolidated", "standalone"]},
    "unit": {"type": "string"},
    "current": {"type": "object", "properties": {k: {"type": "number"} for k in
                ("revenue_from_operations", "other_income", "finance_costs", "depreciation", "pbt", "pat", "interest_earned", "interest_expended")}},
    "previous_quarter": {"type": "object", "properties": {k: {"type": "number"} for k in ("revenue_from_operations", "pbt", "pat")}},
    "year_ago_quarter": {"type": "object", "properties": {k: {"type": "number"} for k in ("revenue_from_operations", "pbt", "pat")}},
    "exceptional_items": {"type": "number"}}, "required": ["current"]}


def from_filing(pages: list[str]) -> dict | None:
    """Path A: read the P&L table from the results PDF. Only the pages that contain it are sent."""
    keep = [p for p in pages if "profit before tax" in p.lower() or "revenue from operations" in p.lower()][:3]
    if not keep:
        return None
    return llm.call("extract", system=(
        "Extract the CONSOLIDATED statement of profit and loss for the latest quarter from this Indian "
        "listed company's results filing (use standalone only if no consolidated). Return numbers in INR crore "
        "(convert from lakhs/millions if needed). Do not invent numbers; omit fields you cannot find."),
        prompt="\n\n---PAGE---\n".join(keep)[:30000], schema=EXTRACT_SCHEMA)


def verify(card: dict, extracted: dict | None) -> dict:
    if not extracted:
        return card
    cur = extracted.get("current", {})
    m = {x["label"]: x for x in card["metrics"]}
    checks = []
    for label, key in (("Revenue", "revenue_from_operations"), ("PBT", "pbt"), ("PAT", "pat")):
        a, b = cur.get(key), (m.get(label) or {}).get("value")
        if a and b:
            checks.append(abs(a / b - 1) <= 0.02)
    card["verified_against_filing"] = bool(checks) and all(checks)
    card["filing_extract"] = extracted
    return card
