"""Filing classification -> the 17 categories in the reference document.

Strategy (cheapest first):
  1. Exchange sub-category map (BSE already labels most filings).
  2. Keyword rules on subject + headline (catches 'General' and mislabelled filings,
     e.g. a 'Change in Management' filing that is really an auditor appointment).
  3. Residuals -> one batched call on the cheapest model tier.
Each record also gets a `kind` (finer label used for materiality) and `signals`.
"""
from __future__ import annotations

import json
import re

from .. import llm

CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
              "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
              "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified"]

SUBCAT = {
    "financial results": ("results", "results"),
    "outcome of board meeting": ("results", "board_outcome"),
    "board meeting": ("results", "board_intimation"),
    "investor presentation": ("results", "deck"),
    "earnings call transcript": ("earnings_call", "transcript"),
    "audio / video recording of earnings call": ("earnings_call", "recording"),
    "analyst / investor meet": ("investor_meetings", "meet"),
    "change in management": ("management_change", "management"),
    "change in directorate": ("management_change", "director"),
    "resignation of director": ("management_change", "director_exit"),
    "retirement": ("management_change", "retirement"),
    "appointment of director": ("management_change", "director"),
    "resignation of chief financial officer (cfo)": ("management_change", "cfo_exit"),
    "appointment of chief financial officer (cfo)": ("management_change", "cfo"),
    "acquisition": ("M&A", "acquisition"),
    "amalgamation / merger": ("M&A", "merger"),
    "scheme of arrangement": ("M&A", "scheme"),
    "restructuring": ("M&A", "restructuring"),
    "diversification / disinvestment": ("M&A", "divestment"),
    "joint venture": ("M&A", "jv"),
    "issue of securities": ("fund_raise", "equity_issue"),
    "allotment of equity shares": ("fund_raise", "allotment"),
    "qualified institutional placement": ("fund_raise", "qip"),
    "rights issue": ("fund_raise", "rights"),
    "buy back": ("fund_raise", "buyback"),
    "intimation of repayment of commercial paper (cp)": ("fund_raise", "cp_repayment"),
    "credit rating": ("credit_rating", "rating"),
    "dividend": ("dividend", "dividend"),
    "dividend updates": ("dividend", "dividend_admin"),
    "date of payment of dividend": ("dividend", "dividend_admin"),
    "record date": ("dividend", "record_date"),
    "bonus issue": ("bonus_split", "bonus"),
    "stock split": ("bonus_split", "split"),
    "award of order / receipt of order": ("press_release", "order_win"),
    "press release / media release": ("press_release", "press"),
    "clarification": ("press_release", "clarification"),
    "postal ballot": ("postal_ballot", "postal_ballot"),
    "egm": ("agm_egm", "egm"),
    "agm": ("agm_egm", "agm"),
    "updates - corporate insolvency resolution process (cirp)": ("litigation", "insolvency"),
    "allotment of esop / esps": ("unclassified", "esop"),
    "newspaper publication": ("unclassified", "newspaper"),
    "certificate under reg. 74 (5) of sebi (dp) regulations, 2018": ("unclassified", "compliance"),
    "monitoring agency report": ("unclassified", "compliance"),
    "reg. 32 (1), (3) - statement of deviation & variation": ("unclassified", "compliance"),
    "appointment of statutory auditor/s": ("unclassified", "auditor"),
    "trading window": ("unclassified", "compliance"),
    "pledge of shares": ("pledging", "pledge"),
    "insider trading / sast": ("insider_trading", "insider"),
}

_ROLE = (r"(managing director|md ?& ?ceo|chief executive|\bceo\b|\bcfo\b|chief financial|chairman|chairperson|"
         r"whole[- ]time director|key managerial|\bkmp\b|senior management|director|general counsel|company secretary)")
_ACT = r"(appoint|resign|cessation|retire|superannuat|vacat|assum\w* (charge|office)|step(s|ped)? down|re-?appoint|change in)"
_MGMT = rf"{_ACT}.{{0,140}}{_ROLE}|{_ROLE}.{{0,140}}{_ACT}"

# (regex, category, kind) — checked in order on subject+headline+more; first hit wins.
RULES: list[tuple[str, str, str]] = [
    (r"\bauditor", "unclassified", "auditor"),
    (r"\b(esop|esps|employee stock|stock options)", "unclassified", "esop"),
    (r"registrar and (share )?transfer agent|\bRTA\b|loss of share certificate|reg(ulation)?\.? ?74|"
     r"investor education and protection|\biepf\b|certificate pursuant|esg rating|guarantee|indemnity|"
     r"partly paid|call money|reminder notice|trading window", "unclassified", "compliance"),
    (r"audio recording|recording of .{0,40}call|transcript of .{0,30}call", "earnings_call", "recording"),
    (r"insolven|\bnclt\b|\bnclat\b|\bcirp\b|winding up", "litigation", "insolvency"),
    (r"\b(penalt|show cause|sebi order|adjudicat|demand order|tax demand|gst demand|warning letter|import alert|"
     r"halt|suspend(ed)? (production|operations)|regulatory action|lawsuit|litigation|arbitra)", "litigation", "regulatory"),
    (_MGMT, "management_change", "management"),
    (r"\b(acqui|merger|amalgamat|demerger|scheme of arrangement|divest|stake sale|joint venture|business transfer|"
     r"incorporat\w* (of )?(a |an )?(new )?(company|wholly[- ]owned subsidiar|subsidiar|step[- ]down))", "M&A", "acquisition"),
    (r"listing of equity shares|ipo|initial public offer", "M&A", "listing"),
    (r"\b(qip|qualified institutional|preferential|rights issue|warrants|buy-?back|fund rais|"
     r"non-convertible|\bncd|commercial paper)", "fund_raise", "equity_issue"),
    (r"\b(capex|capacity (addition|expansion)|expansion|new (plant|facility|unit)|greenfield|brownfield|commission(ed|ing))",
     "capex", "capex"),
    (r"\bcredit rating|rating (re-?affirm|upgrade|downgrade|assigned)", "credit_rating", "rating"),
    (r"\bpledge|encumbrance", "pledging", "pledge"),
    (r"\b(reg(ulation)? ?7\(2\)|reg(ulation)? ?29|sast|insider)", "insider_trading", "insider"),
    (r"\b(financial results|quarterly results|unaudited|audited) .{0,40}(results|quarter)", "results", "results"),
    (r"to announce .{0,40}results on|results presentation|shareholders'? letter|half[- ]yearly report|"
     r"financial statements|financial results|results for the (quarter|half)|performance of the company for the quarter",
     "results", "results_doc"),
    (r"production volume|sales in (january|february|march|april|may|june|july|august|september|october|november|december)|"
     r"business update|operational update", "press_release", "monthly_update"),
    (r"strike off|struck off", "M&A", "subsidiary_admin"),
    (r"earnings call|con(ference)? ?call|concall", "earnings_call", "notice"),
    (r"analyst|investor (meet|conference)|institutional investor", "investor_meetings", "meet"),
    (r"\bdividend", "dividend", "dividend"),
    (r"\bbonus|stock split|sub-division", "bonus_split", "bonus"),
    (r"postal ballot", "postal_ballot", "postal_ballot"),
    (r"\b(agm|egm|annual general meeting|extra-?ordinary general)", "agm_egm", "agm"),
    (r"\b(order|contract) (win|award|receiv|secur)|bags .{0,30}order|wins .{0,30}order", "press_release", "order_win"),
    (r"contract(ual)? (tenure|extension|amendment|renewal)|extend(ing|s)? the contract|supply (agreement|contract)|"
     r"long[- ]term (contract|agreement)|\$ ?\d+ ?(million|mn|bn)", "press_release", "contract"),
    (r"product trials|commercial production|commercialis|commercializ", "capex", "commissioning"),
    (r"clarification|news (item|report)|media statement", "press_release", "clarification"),
    (r"press release|launch|partnership|collaborat|agreement|award|delivers|advances|selects|wins\b", "press_release", "press"),
    (r"newspaper|advertisement|publication", "unclassified", "newspaper"),
]


BOILERPLATE = re.compile(r"[^.]*(debarred|by virtue of any sebi order|not related to any (other )?director|listing obligations and disclosure requirements|"
                         r"master circular|this is for your information)[^.]*\.?", re.I)


def strip_boilerplate(t: str) -> str:
    """Remove LODR boilerplate that otherwise trips keyword rules ('...not debarred ... by any SEBI order')."""
    t = re.sub(r"\b(?:\w ){3,}\w\b", lambda m: m.group(0).replace(" ", ""), t)  # 'd e b a r r e d' -> 'debarred'
    return BOILERPLATE.sub(" ", t)


def _text(f: dict) -> str:
    return strip_boilerplate(" ".join([f.get("subject", ""), f.get("headline", ""), f.get("more", "")])).lower()


def classify_rule(f: dict) -> tuple[str, str, str] | None:
    """Return (category, kind, method) or None if rules can't decide."""
    sub = (f.get("exch_subcategory") or "").strip().lower()
    txt = _text(f)
    # Board meetings: results first (the most common reason), otherwise read the agenda.
    if sub in ("board meeting", "outcome of board meeting") and re.search(r"financial results|unaudited|audited", txt):
        return ("results", "board_intimation" if sub == "board meeting" else "results", "exchange")
    # Press releases about the quarter are results material, not general news.
    if sub == "press release / media release" and re.search(r"financial results|results for the|performance .{0,30}quarter", txt):
        return "results", "press", "exchange"
    # Rules first when the exchange label is generic or known to be overloaded.
    generic = sub in ("", "general", "others", "change in management", "board meeting", "outcome of board meeting",
                      "clarification")
    if generic:
        for pat, cat, kind in RULES:
            if re.search(pat, txt, re.I):
                return cat, kind, "rule"
    if sub in SUBCAT:
        cat, kind = SUBCAT[sub]
        # Board meeting intimations for results are calendar entries, not news.
        if sub == "board meeting" and not re.search(r"result", txt):
            return "unclassified", "board_intimation_other", "exchange"
        if sub == "outcome of board meeting" and re.search(r"result", txt):
            return "results", "results", "exchange"
        if sub == "newspaper publication" and re.search(r"result", txt):
            return "results", "newspaper", "exchange"
        return cat, kind, "exchange"
    if not generic:
        for pat, cat, kind in RULES:
            if re.search(pat, txt, re.I):
                return cat, kind, "rule"
    return None


SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "category": {"type": "string", "enum": CATEGORIES},
    "kind": {"type": "string"}}, "required": ["i", "category"]}}


NEEDS_DOC = {"clarification", "management", "director", "press", "results_doc", "equity_issue", "acquisition"}
ROUTINE_KINDS = {"esop", "compliance", "auditor", "newspaper"}


def needs_document(f: dict) -> bool:
    """Second pass: opaque titles ('Disclosure under Regulation 30') or thin headlines get the PDF read."""
    return (f.get("category") is None or f.get("kind") in NEEDS_DOC
            or (f.get("category") == "management_change" and not f.get("signals", {}).get("roles")))


def deep_classify(f: dict, doc_text: str) -> None:
    """Re-run the rules on the filing's own first page. Still no LLM."""
    probe = dict(f, more=(f.get("more", "") + " " + doc_text[:2500]))
    body = strip_boilerplate(f.get("subject", "") + " " + doc_text[:3000]).lower()
    r = next(((c, k, "rule") for pat, c, k in RULES if re.search(pat, body, re.I)), None) or classify_rule(probe)
    if r and (f.get("category") in (None, "unclassified", "press_release") or r[0] == f.get("category")
              or r[0] in ("litigation", "management_change") or r[1] in ROUTINE_KINDS):
        f["category"], f["kind"], f["class_method"] = r[0], r[1], r[2] + "+doc"
    f["doc_excerpt"] = re.sub(r"\s+", " ", doc_text)[:1500]
    f["signals"] = signals(probe | {"category": f.get("category"), "kind": f.get("kind")})


def classify_batch(filings: list[dict], doc_text=None) -> None:
    """Classify in place. Rules for most; PDF first page for opaque ones; batched cheap LLM for the rest.

    doc_text: optional callable(filing) -> str|None returning the filing PDF's leading text.
    """
    residual = []
    for f in filings:
        r = classify_rule(f)
        f["category"], f["kind"], f["class_method"] = r if r else (None, None, None)
        f["signals"] = signals(f) if r else {}
        if doc_text and needs_document(f):
            t = doc_text(f)
            if t:
                deep_classify(f, t)
        if not f["category"]:
            residual.append(f)
            continue
        head = (f.get("subject", "") + " " + f.get("headline", "")).lower()
        if f["category"] in ("results", "M&A") and re.search(r"newspaper|advertisement|clipping", head):
            f["kind"] = "newspaper"   # an ad *about* an event is not the event
    for i in range(0, len(residual), 40):
        chunk = residual[i:i + 40]
        listing = "\n".join(f"{j}. [{f['symbol']}] {f['subject']} — {f['headline'][:220]}" for j, f in enumerate(chunk))
        out = llm.call("bulk", system=(
            "You classify Indian listed-company exchange filings. Categories: " + ", ".join(CATEGORIES) +
            ". Routine compliance paperwork is 'unclassified'. Reply as JSON."),
            prompt=listing, schema=SCHEMA) or []
        got = {o["i"]: o for o in out if isinstance(o, dict) and "i" in o}
        for j, f in enumerate(chunk):
            o = got.get(j)
            f["category"] = o["category"] if o else "unclassified"
            f["kind"] = (o or {}).get("kind") or "other"
            f["class_method"] = "llm" if o else "default"
            f["signals"] = signals(f)


ORDER_SCALE = [("ultra-mega", 15000, None), ("mega", 10000, 15000), ("major", 5000, 10000), ("large", 2500, 5000), ("significant", 1000, 2500)]


def signals(f: dict) -> dict:
    """Cheap structured signals pulled from the filing text (no LLM)."""
    txt = _text(f)
    s: dict = {}
    if f.get("category") == "credit_rating":
        s["direction"] = ("downgrade" if re.search(r"downgrad|negative|watch with negative", txt)
                          else "upgrade" if re.search(r"upgrad|positive", txt)
                          else "reaffirm" if re.search(r"re-?affirm|reaffirm", txt) else "unknown")
    if f.get("category") == "management_change":
        roles = re.findall(r"\b(managing director|md & ceo|chief executive officer|ceo|chief financial officer|cfo|"
                           r"chairman|chairperson|vice[- ]chairman|whole[- ]time director|independent director|"
                           r"company secretary|director \(operations\)|director|general counsel|senior management)", txt)
        s["roles"] = sorted(set(roles))
        ex = bool(re.search(r"resign|cessation|retire|superannuat|vacat|step(ped)? down", txt))
        en = bool(re.search(r"appoint|assum|join|designat|takes? charge", txt))
        s["direction"] = "succession" if ex and en else "exit" if ex else "entry" if en else "change"
        s["seniority"] = (3 if re.search(r"managing director|md & ceo|chief executive|\bceo\b|(?<!vice-)(?<!vice )chairman|chairperson|\bcfo\b|chief financial", txt)
                          else 2 if re.search(r"whole[- ]time|key managerial|senior management|director \(|general counsel|deputy managing", txt)
                          else 1)
    if f.get("kind") == "order_win":
        for label, lo, hi in ORDER_SCALE:
            if label in txt:
                s["order_bucket"] = label
                s["order_min_cr"] = lo
                s["order_max_cr"] = hi
                break
    if f.get("category") == "M&A":
        head = (f.get("subject", "") + " " + f.get("headline", "")).lower()
        s["wos_only"] = bool(re.search(r"incorporat|wholly[- ]owned", head)) and not re.search(r"acquisition of|acquire[sd]? |stake in|merger", head)
    return s


def dump_rules() -> str:
    return json.dumps({"subcategory_map": SUBCAT, "rules": RULES}, indent=1)
