"""Deterministic research: everything that is arithmetic, done without a model.

Snapshot, trajectory, balance sheet, cash quality and red flags come straight from the
standardised statements. Models are reserved for reading prose (transcripts / annual reports).
Each statement carries the numbers that justify it so the UI can show its working.
"""
from __future__ import annotations

import re

from .results import is_lender, quarter_card


def _row(t: dict | None, *names: str) -> list:
    if not t:
        return []
    for n in names:
        if n in t["rows"]:
            return t["rows"][n]
    for n in names:  # prefix match ('CFO/EBITDA Share of ...')
        for k in t["rows"]:
            if k.startswith(n):
                return t["rows"][k]
    return []


def _years(t: dict | None) -> list[str]:
    return [c for c in (t or {}).get("cols", [])]


def cagr(series: list, years: int) -> float | None:
    vals = [v for v in series if v is not None]
    if len(series) <= years or series[-1] is None or series[-1 - years] in (None, 0):
        return None
    a, b = series[-1 - years], series[-1]
    if a <= 0 or b <= 0:
        return None
    return round(((b / a) ** (1 / years) - 1) * 100, 1)


def _num(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"-?[\d,]+(\.\d+)?", s.replace("₹", ""))
    return float(m.group(0).replace(",", "")) if m else None


def snapshot(c: dict) -> dict:
    tr = c.get("topRatios", {})
    pl = c.get("pl")
    years = _years(pl)
    ttm = years.index("TTM") if "TTM" in years else None
    rev = _row(pl, "Sales", "Revenue")
    pat = _row(pl, "Net Profit")
    opm = _row(pl, "OPM %")
    return {
        "name": c.get("name"), "symbol": c.get("symbol"), "basis": c.get("basis"),
        "sector": c.get("sector", [])[-2:], "about": c.get("about"),
        "mcap_cr": _num(tr.get("Market Cap")), "price": _num(tr.get("Current Price")),
        "pe": _num(tr.get("Stock P/E")), "roce": _num(tr.get("ROCE")), "roe": _num(tr.get("ROE")),
        "div_yield": _num(tr.get("Dividend Yield")), "book_value": _num(tr.get("Book Value")),
        "high_low": tr.get("High / Low"),
        "ttm_revenue": rev[ttm] if ttm is not None and rev else None,
        "ttm_pat": pat[ttm] if ttm is not None and pat else None,
        "opm": opm[ttm] if ttm is not None and opm and opm[ttm] is not None else (opm[-1] if opm else None),
        "lender": bool(c.get("quarters") and is_lender(c["quarters"])),
        "latest_quarter": quarter_card(c),
    }


def trajectory(c: dict) -> dict:
    pl = c.get("pl")
    years = [y for y in _years(pl) if y != "TTM"]
    n = len(years)
    rev = _row(pl, "Sales", "Revenue")[:n]
    op = _row(pl, "Operating Profit", "Financing Profit")[:n]
    pat = _row(pl, "Net Profit")[:n]
    opm = _row(pl, "OPM %", "Financing Margin %")[:n]
    eps = _row(pl, "EPS in Rs")[:n]
    out = {"years": years[-10:], "revenue": rev[-10:], "operating_profit": op[-10:], "pat": pat[-10:],
           "opm": opm[-10:], "eps": eps[-10:], "cagr": {}}
    for label, s in (("revenue", rev), ("pat", pat), ("eps", eps)):
        out["cagr"][label] = {"3y": cagr(s, 3), "5y": cagr(s, 5), "10y": cagr(s, 9 if len(s) > 9 else len(s) - 1)}
    notes = []
    r3, r5 = out["cagr"]["revenue"]["3y"], out["cagr"]["revenue"]["5y"]
    if r3 is not None and r5 is not None:
        if r3 > r5 + 3:
            notes.append(("up", f"Growth is accelerating: revenue CAGR {r5:.0f}% over 5y → {r3:.0f}% over 3y"))
        elif r3 < r5 - 3:
            notes.append(("down", f"Growth is slowing: revenue CAGR {r5:.0f}% over 5y → {r3:.0f}% over 3y"))
        else:
            notes.append(("flat", f"Steady compounding: revenue CAGR ~{r3:.0f}% (3y) vs {r5:.0f}% (5y)"))
    lender = bool(c.get("quarters") and is_lender(c["quarters"]))
    growth = _row(pl, "Sales growth", "Revenue growth")[:n]
    for y, g in list(zip(years, growth))[-5:]:
        if g is not None and g >= 60 and (rev[-1] or 0) > 5000:
            notes.insert(0, ("flat", f"{y} revenue jumped {g:.0f}% — a step change (merger/acquisition?); CAGRs that straddle it overstate organic growth"))
            break
    m = [x for x in opm[-6:] if x is not None] if not lender else []
    if len(m) >= 4:
        d = m[-1] - sum(m[:-1]) / (len(m) - 1)
        if d >= 2:
            notes.append(("up", f"Margins expanding: OPM {m[-1]:.0f}% vs {sum(m[:-1]) / (len(m) - 1):.0f}% avg of prior years"))
        elif d <= -2:
            notes.append(("down", f"Margins compressing: OPM {m[-1]:.0f}% vs {sum(m[:-1]) / (len(m) - 1):.0f}% avg of prior years"))
    p3 = out["cagr"]["pat"]["3y"]
    if p3 is not None and r3 is not None and abs(p3 - r3) >= 5:
        notes.append(("up" if p3 > r3 else "down",
                      f"Profit {'outgrowing' if p3 > r3 else 'lagging'} revenue: PAT CAGR {p3:.0f}% vs revenue {r3:.0f}% (3y)"))
    out["notes"] = [{"tone": t, "text": x} for t, x in notes]
    return out


def balance_sheet(c: dict) -> dict:
    bs = c.get("bs")
    cols = _years(bs)
    eq = [(a or 0) + (b or 0) for a, b in zip(_row(bs, "Equity Capital"), _row(bs, "Reserves"))]
    debt = _row(bs, "Borrowings", "Borrowing")
    cwip = _row(bs, "CWIP")
    fa = _row(bs, "Fixed Assets")
    inv = _row(bs, "Investments")
    ratios = c.get("ratios")
    out = {"cols": cols[-6:], "equity": eq[-6:], "debt": debt[-6:], "cwip": cwip[-6:],
           "de": [round(d / e, 2) if e else None for d, e in zip(debt, eq)][-6:],
           "wc": {k: _row(ratios, k)[-6:] for k in ("Debtor Days", "Inventory Days", "Days Payable",
                                                     "Cash Conversion Cycle", "Working Capital Days")},
           "ratio_cols": _years(ratios)[-6:], "notes": []}
    lender = bool(c.get("quarters") and is_lender(c["quarters"]))
    if lender:
        dep = _row(bs, "Deposits")
        if dep and eq and eq[-1]:
            out["notes"].append({"tone": "flat", "text": f"Lender: leverage is structural (deposits+borrowings ≈ {((dep[-1] or 0) + (debt[-1] or 0)) / eq[-1]:.1f}× equity); judge on asset quality, not D/E"})
        return out
    if debt and eq and eq[-1]:
        de = (debt[-1] or 0) / eq[-1]
        prev = (debt[-4] or 0) / eq[-4] if len(debt) >= 4 and eq[-4] else None
        tone = "down" if de > 1 else "flat" if de > 0.3 else "up"
        trend = f", from {prev:.2f} three periods ago" if prev is not None else ""
        out["notes"].append({"tone": tone, "text": f"Debt/Equity {de:.2f}{trend}"})
        if inv and debt[-1] is not None and inv[-1] is not None and inv[-1] > debt[-1]:
            out["notes"].append({"tone": "up", "text": f"Investments (₹{inv[-1]:,.0f} Cr) exceed borrowings (₹{debt[-1]:,.0f} Cr)"})
    if cwip and fa and fa[-1] and cwip[-1] is not None and cwip[-1] / fa[-1] > 0.2:
        out["notes"].append({"tone": "flat", "text": f"Capex in progress: CWIP is {cwip[-1] / fa[-1] * 100:.0f}% of fixed assets — growth capacity not yet earning"})
    ccc = out["wc"].get("Cash Conversion Cycle") or []
    ccc = [x for x in ccc if x is not None]
    if len(ccc) >= 3:
        d = ccc[-1] - ccc[-3]
        if d >= 15:
            out["notes"].append({"tone": "down", "text": f"Working capital stretching: cash conversion cycle {ccc[-3]:.0f} → {ccc[-1]:.0f} days"})
        elif d <= -15:
            out["notes"].append({"tone": "up", "text": f"Working capital tightening: cash conversion cycle {ccc[-3]:.0f} → {ccc[-1]:.0f} days"})
    dd = [x for x in (out["wc"].get("Debtor Days") or []) if x is not None]
    if len(dd) >= 3 and dd[-1] - dd[-3] >= 15:
        out["notes"].append({"tone": "down", "text": f"Receivables lengthening: debtor days {dd[-3]:.0f} → {dd[-1]:.0f}"})
    return out


def cash_quality(c: dict) -> dict:
    cf, pl = c.get("cf"), c.get("pl")
    cols = _years(cf)
    cfo = _row(cf, "Cash from Operating Activity")
    fcf = _row(cf, "Free Cash Flow")
    conv = _row(cf, "CFO/EBITDA")
    pl_years = [y for y in _years(pl) if y != "TTM"]
    pat_by_year = dict(zip(pl_years, _row(pl, "Net Profit")))
    pat = [pat_by_year.get(y) for y in cols]
    out = {"cols": cols[-6:], "cfo": cfo[-6:], "pat": pat[-6:], "fcf": fcf[-6:], "cfo_ebitda": conv[-6:], "notes": []}
    lender = bool(c.get("quarters") and is_lender(c["quarters"]))
    if lender:
        out["notes"].append({"tone": "flat", "text": "Lender: operating cash flow mostly reflects loan-book growth; cash conversion isn't a useful lens"})
        return out
    n = min(5, len(cfo))
    s_cfo = sum(x for x in cfo[-n:] if x is not None)
    s_pat = sum(x for x in pat[-n:] if x is not None)
    if s_pat > 0:
        r = s_cfo / s_pat
        tone = "up" if r >= 0.9 else "flat" if r >= 0.7 else "down"
        out["notes"].append({"tone": tone, "text": f"{n}-yr cumulative CFO is {r:.2f}× PAT (₹{s_cfo:,.0f} Cr vs ₹{s_pat:,.0f} Cr)"})
        out["cfo_pat_5y"] = round(r, 2)
    s_fcf = sum(x for x in fcf[-n:] if x is not None)
    neg = sum(1 for x in fcf[-n:] if x is not None and x < 0)
    out["notes"].append({"tone": "up" if s_fcf > 0 and neg <= 1 else "down" if s_fcf < 0 else "flat",
                         "text": f"{n}-yr free cash flow ₹{s_fcf:,.0f} Cr; negative in {neg} of {n} years"})
    return out


def shareholding(c: dict) -> dict:
    shp = c.get("shp")
    out = {"cols": _years(shp)[-8:], "rows": {k: v[-8:] for k, v in (shp or {}).get("rows", {}).items()
                                              if k != "No. of Shareholders"}, "notes": []}
    pr = [x for x in _row(shp, "Promoters") if x is not None]
    if len(pr) >= 4 and pr[-1] - pr[-4] <= -1:
        out["notes"].append({"tone": "down", "text": f"Promoter holding down {pr[-4]:.1f}% → {pr[-1]:.1f}% over 3 quarters"})
    for k in ("FIIs", "DIIs"):
        s = [x for x in _row(shp, k) if x is not None]
        if len(s) >= 5 and abs(s[-1] - s[-5]) >= 3:
            out["notes"].append({"tone": "flat", "text": f"{k} {s[-5]:.1f}% → {s[-1]:.1f}% over the year"})
    return out


def red_flags(c: dict, tq: dict, bs: dict, cq: dict) -> list[dict]:
    flags = [n for n in bs["notes"] + cq["notes"] + tq["notes"] if n["tone"] == "down"]
    pl = c.get("pl")
    oi, pbt = _row(pl, "Other Income"), _row(pl, "Profit before tax")
    lender = bool(c.get("quarters") and is_lender(c["quarters"]))
    if not lender and oi and pbt and pbt[-1] and oi[-1] is not None and pbt[-1] > 0 and oi[-1] / pbt[-1] > 0.2:
        flags.append({"tone": "down", "text": f"Other income is {oi[-1] / pbt[-1] * 100:.0f}% of TTM PBT"})
    return flags


def dossier_numbers(c: dict) -> dict:
    tq, bs, cq = trajectory(c), balance_sheet(c), cash_quality(c)
    return {"snapshot": snapshot(c), "trajectory": tq, "balance_sheet": bs, "cash": cq,
            "shareholding": shareholding(c), "red_flags": red_flags(c, tq, bs, cq),
            "quarters": {"cols": c["quarters"]["cols"][-9:],
                         "rows": {k: v[-9:] for k, v in c["quarters"]["rows"].items()
                                  if k in ("Sales", "Revenue", "Operating Profit", "Financing Profit", "OPM %",
                                           "Financing Margin %", "Profit before tax", "Net Profit", "Interest",
                                           "Other Income")}} if c.get("quarters") else None}
