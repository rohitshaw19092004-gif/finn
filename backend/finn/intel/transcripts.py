"""Concall transcripts -> explicit guidance, then promise-vs-delivered.

Cost discipline: a transcript is ~12-20k tokens. We split it into speaker turns, drop the
moderator and analyst questions, and keep only management answers that contain forward-looking
or quantitative cues. That typically keeps 15-25% of the text. Only that goes to the model.

Step 1 (extract tier, per transcript, cached forever): guidance statements with verbatim quotes.
Step 2 (reason tier, once per company): compare each earlier promise to what was later reported,
        using the deterministic quarterly numbers as the ground truth.

Evidence discipline (enforced here, not just asked for in the prompt):
  * every guidance quote is checked against the transcript text; items whose quote is not found
    are rejected (kept in `rejected` for audit), never shown as evidence;
  * the promise check only sees verified guidance, and each returned promise must point back to
    one of those quotes; a verdict with no cited figures becomes 'unknown';
  * numbers cited as evidence are traced to the reported quarterly table or the transcripts.
"""
from __future__ import annotations

import re
import unicodedata

from .. import llm
from ..sources.docs import speaker_turns

CUES = re.compile(
    r"\b(guid|expect|target|aim|outlook|going forward|next (year|quarter|few)|fy ?2?\d|h[12] ?fy|"
    r"double[- ]digit|high single|low single|mid[- ]teens?|margin|ebitda|growth of|grow(th)? (at|in)|"
    r"capex|capacity|commission|ramp|by (the )?end of|should (be|see)|we will|we would|"
    r"\d+(\.\d+)?\s?(%|percent|per cent|crore|cr\b|bn|billion))", re.I)
NON_MGMT = re.compile(r"moderator|operator|analyst|participant|investor|^q\b|question", re.I)


ANALYST_INTRO = re.compile(r"(?:question|line)\s+(?:is\s+|comes\s+|will\s+be\s+)?(?:from|of)\s+(?:the\s+line\s+of\s+)?(?:Mr\.?|Ms\.?|Mrs\.?)?\s*"
                           r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})")
NOISE = {"encl", "ref", "note", "sub", "subject", "date", "page", "cc", "to"}


def management_names(turns: list[dict]) -> set[str]:
    """Management = recurring speakers who are neither the moderator nor an analyst the moderator introduced."""
    analysts: set[str] = set()
    for t in turns:
        if re.search(r"moderator|operator", t["speaker"], re.I):
            for m in ANALYST_INTRO.finditer(t["text"]):
                analysts.add(" ".join(m.group(1).split()[:2]).lower())
    count: dict[str, int] = {}
    asks: dict[str, int] = {}
    for t in turns:
        count[t["speaker"]] = count.get(t["speaker"], 0) + 1
        asks[t["speaker"]] = asks.get(t["speaker"], 0) + ("?" in t["text"])
    out = set()
    for s, n in count.items():
        first = s.split()[0].lower().rstrip(".")
        low = " ".join(s.split()[:2]).lower()
        is_analyst = any(low == a or (len(a.split()) == 1 and low.split()[0] == a) for a in analysts)
        if asks.get(s, 0) / n >= 0.5:      # people who mostly ask questions are not management
            is_analyst = True
        if NON_MGMT.search(s) or first in NOISE or is_analyst or len(s) < 4 or n < 2:
            continue
        out.add(s)
    return out


def prefilter(pages: list[str], max_chars: int = 14000) -> list[dict]:
    turns = speaker_turns(pages)
    mgmt = management_names(turns)
    keep = []
    for i, t in enumerate(turns):
        if t["speaker"] not in mgmt or NON_MGMT.search(t["speaker"]):
            continue
        sents = re.split(r"(?<=[.!?])\s+", t["text"])
        hits = [s for s in sents if CUES.search(s) and len(s) > 40]
        if not hits:
            continue
        q = turns[i - 1]["text"][-240:] if i and NON_MGMT.search(turns[i - 1]["speaker"]) is None and turns[i - 1]["speaker"] not in mgmt else ""
        keep.append({"speaker": t["speaker"], "page": t["page"], "q": q, "text": " ".join(hits)[:1600]})
    if not keep:
        keep = _fallback_excerpts(pages, turns)
    out, n = [], 0
    for k in keep:
        n += len(k["text"])
        if n > max_chars:
            break
        out.append(k)
    return out


BOILER = re.compile(r"ladies and gentlemen|welcome to the|question.{0,20}answer session|press star|"
                    r"forward[- ]looking statements|safe harbou?r|disclaimer|recording|line of|thank you", re.I)


def _fallback_excerpts(pages: list[str], turns: list[dict]) -> list[dict]:
    """When speakers can't be told apart (transcript layouts that lose 'Name:' markers), keep the
    forward-looking, quantitative sentences from the whole call, minus moderator boilerplate and
    questions. Speaker is unknown; every quote is still verified against the transcript later."""
    out = []
    for i, page in enumerate(pages, start=1):
        sents = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", page))
        hits = [x for x in sents if len(x) > 50 and CUES.search(x) and "?" not in x and not BOILER.search(x)]
        chunk = ""
        for h in hits:
            if len(chunk) + len(h) > 1500 and chunk:
                out.append({"speaker": "unattributed", "page": i, "q": "", "text": chunk.strip()})
                chunk = ""
            chunk += " " + h
        if chunk.strip():
            out.append({"speaker": "unattributed", "page": i, "q": "", "text": chunk.strip()})
    return out


# --------------------------------------------------------------------------- quote verification
_WORD = re.compile(r"[a-z]+|\d+(?:\.\d+)?")


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKC", t or "").lower()
    t = t.replace("\u20b9", " inr ").replace("rs.", " inr ").replace("%", " percent ").replace("per cent", "percent")
    t = re.sub(r"\bcrores?\b|\bcr\b\.?", " crore ", t)
    return t


def tokens(t: str) -> list[str]:
    return _WORD.findall(_norm(t))


class TranscriptIndex:
    """Token index over one or more transcripts, for checking that a quote was really said."""

    def __init__(self, docs: dict[str, list[str]]):
        self.pages: list[tuple[str, int, list[str]]] = []          # (period, page_no, tokens)
        self.paged = {period: len(pages) > 1 for period, pages in docs.items()}
        for period, pages in docs.items():
            for i, p in enumerate(pages, start=1):
                self.pages.append((period, i, tokens(p)))
        self.joined = {(per, pg): " " + " ".join(tk) + " " for per, pg, tk in self.pages}
        self.trigrams = {k: {tuple(tk[i:i + 3]) for i in range(len(tk) - 2)} for k, tk in
                         (((per, pg), tk) for per, pg, tk in self.pages)}

    def find(self, quote: str, period: str | None = None) -> dict:
        """{'status': 'verbatim'|'near'|'not_found', 'period', 'page'}.

        verbatim: the quote's word sequence occurs exactly (ellipses split it into fragments that
        must each occur); near: >= 85% of its word trigrams occur on one page (punctuation, filler
        words or transcription differences). Quotes under 6 words are too short to prove anything.
        """
        frags = [tokens(x) for x in re.split(r"\.\.\.|…|\[\.\.\.\]", quote or "")]
        frags = [f for f in frags if f]
        if sum(len(f) for f in frags) < 6:
            return {"status": "not_found", "reason": "quote too short to verify"}
        claimed = [k for k in self.joined if k[0] == period]
        rest = [k for k in self.joined if k[0] != period]
        best_any = {"status": "not_found", "match": 0.0}
        for keys in (claimed, rest):           # the call it's attributed to first, then every other call
            r = self._find(frags, keys)
            if r["status"] != "not_found":
                return r
            best_any["match"] = max(best_any["match"], r.get("match", 0.0))
        return best_any

    def _find(self, frags: list[list[str]], keys: list) -> dict:
        for k in keys:
            if all(" " + " ".join(f) + " " in self.joined[k] for f in frags):
                return {"status": "verbatim", "period": k[0], "page": k[1]}
        best, where = 0.0, None
        qs = [tuple(f[i:i + 3]) for f in frags for i in range(len(f) - 2)]
        for k in keys:
            if not qs:
                break
            tg = self.trigrams[k]
            r = sum(q in tg for q in qs) / len(qs)
            if r > best:
                best, where = r, k
        if best >= 0.85 and where:
            return {"status": "near", "period": where[0], "page": where[1], "match": round(best, 2)}
        return {"status": "not_found", "match": round(best, 2)}


def verify_guidance(items: list[dict], index: TranscriptIndex) -> tuple[list[dict], list[dict]]:
    """Split model output into (verified, rejected). Verified items get quote_check + the real page."""
    ok, bad = [], []
    for it in items:
        if not isinstance(it, dict) or not (it.get("quote") or "").strip() or not it.get("statement"):
            bad.append({**(it if isinstance(it, dict) else {}), "reason": "missing quote or statement"})
            continue
        chk = index.find(it["quote"], it.get("said_in"))
        if chk["status"] == "not_found":
            bad.append({**it, "reason": "quote not found in transcript", "match": chk.get("match")})
            continue
        it["quote_check"] = chk["status"]
        if index.paged.get(chk.get("period")):
            it["page"] = chk["page"]                            # page in the PDF where the quote really is
        else:
            it.pop("page", None)
        if chk.get("period") and chk["period"] != it.get("said_in"):
            it["said_in"] = chk["period"]                       # the call it was actually said on
        ok.append(it)
    return ok, bad


GUIDANCE_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "metric": {"type": "string", "description": "revenue growth | volume growth | EBITDA margin | gross margin | capex | capacity | market share | other"},
    "statement": {"type": "string", "description": "plain-English paraphrase, <= 20 words"},
    "target": {"type": "string", "description": "the number or range, e.g. '18-20%', '₹500 Cr', 'double digit'"},
    "horizon": {"type": "string", "description": "period it applies to, e.g. 'FY27', 'H2 FY27', 'next 2-3 years'"},
    "quote": {"type": "string", "description": "verbatim, <= 25 words"},
    "speaker": {"type": "string"}, "page": {"type": "integer"},
    "kind": {"type": "string", "enum": ["explicit", "directional"]}},
    "required": ["metric", "statement", "horizon", "quote", "kind"]}}}, "required": ["items"]}


def extract_guidance(period: str, excerpts: list[dict], task: str | None = None) -> tuple[list[dict], llm.Result]:
    """Raw (unverified) guidance items for one call, plus what the model call did."""
    if not excerpts:
        return [], llm.Result("ok", {"items": []})
    body = "\n\n".join(f"[p{e['page']}] {e['speaker']}: {e['text']}" for e in excerpts)
    res = llm.run("extract", task=task or f"guidance {period}", system=(
        "You read management's answers from an Indian company's earnings call. List ONLY forward-looking "
        "guidance management gave about the company's own numbers (growth, margins, capex, capacity, volumes). "
        "Skip industry commentary and past results. 'explicit' = a number or range; 'directional' = qualitative "
        "(e.g. 'margins will improve'). Quote verbatim. Use only this text; no outside knowledge."),
        prompt=f"Call: {period}\n\n{body}", schema=GUIDANCE_SCHEMA)
    if not res.ok:
        return [], res
    out = res.data
    items = out.get("items", []) if isinstance(out, dict) else []
    if not isinstance(out, dict) or not isinstance(items, list):
        return [], llm.Result("failed", model=res.model, error="model output did not match the guidance schema")
    for it in items:
        if isinstance(it, dict):
            it["said_in"] = period
            it["model"] = res.model
    return [it for it in items if isinstance(it, dict)], res


PROMISE_SCHEMA = {"type": "object", "properties": {
    "promises": {"type": "array", "items": {"type": "object", "properties": {
        "said_in": {"type": "string"}, "metric": {"type": "string"}, "promise": {"type": "string"},
        "quote": {"type": "string"}, "outcome": {"type": "string", "description": "what the numbers / later calls show"},
        "evidence": {"type": "string", "description": "the specific figures used"},
        "verdict": {"type": "string", "enum": ["delivered", "partly", "missed", "pending", "moved goalposts", "unknown"]},
        "ref": {"type": "integer", "description": "number of the guidance line this promise comes from"}},
        "required": ["said_in", "metric", "promise", "outcome", "verdict", "ref"]}},
    "narrative_vs_numbers": {"type": "array", "items": {"type": "object", "properties": {
        "theme": {"type": "string"}, "management_says": {"type": "string"}, "numbers_say": {"type": "string"},
        "agree": {"type": "boolean"}}, "required": ["theme", "management_says", "numbers_say", "agree"]}},
    "credibility": {"type": "string", "description": "one sentence overall read on management's guidance record"}},
    "required": ["promises", "narrative_vs_numbers", "credibility"]}


def promise_vs_delivered(company: str, guidance: list[dict], quarters: dict,
                         missing_periods: list[str] | None = None, task: str | None = None) -> llm.Result:
    """Reason tier, over compact structured inputs only (never raw transcripts). Output is validated."""
    if not guidance:
        return llm.Result("ok", None)
    qtable = "\n".join(f"{k}: " + ", ".join(f"{c}={v}" for c, v in zip(quarters["cols"], vals))
                       for k, vals in quarters["rows"].items())
    glist = "\n".join(f"{i}. [{g['said_in']}] {g['metric']}: {g['statement']} (target {g.get('target', '-')}, "
                      f"horizon {g['horizon']}) \"{g['quote']}\"" for i, g in enumerate(guidance))
    gap = ("\n\nCalls NOT analysed (missing evidence): " + ", ".join(missing_periods) +
           ". If a verdict would depend on those calls, use 'unknown'.") if missing_periods else ""
    res = llm.run("reason", task=task or f"promises {company}", system=(
        "You are a sceptical buy-side analyst. Compare what management promised with what was delivered. "
        "Ground every verdict in the reported quarterly numbers provided (INR crore) or in later guidance, and put "
        "the exact figures you used in 'evidence'. Mark 'pending' if the horizon has not ended; 'moved goalposts' "
        "if later calls quietly changed the target; 'unknown' if the numbers given cannot settle it. Set 'ref' to "
        "the guidance line number. Quote only from the guidance lines given. No outside knowledge of the company."),
        prompt=f"Company: {company}\n\nReported quarterly numbers:\n{qtable}\n\nGuidance given over the last year "
               f"(each quote verified against the transcript):\n{glist}{gap}",
        schema=PROMISE_SCHEMA)
    if not res.ok:
        return res
    if not isinstance(res.data, dict) or not isinstance(res.data.get("promises"), list):
        return llm.Result("failed", model=res.model, error="model output did not match the promise schema")
    return llm.Result(res.status, validate_promises(res.data, guidance, quarters), model=res.model)


_NUM = re.compile(r"(?<![\w.])[-+−]?\d[\d,]*(?:\.\d+)?")
VERDICTS = {"delivered", "partly", "missed", "pending", "moved goalposts", "unknown"}


def _numbers(t: str) -> list[float]:
    out = []
    for m in _NUM.findall(t or ""):
        try:
            out.append(float(m.replace(",", "").replace("−", "-").lstrip("+")))
        except ValueError:
            pass
    return out


def _known_numbers(quarters: dict, guidance: list[dict]) -> set[float]:
    known: set[float] = set()
    for vals in quarters.get("rows", {}).values():
        for v in vals:
            if isinstance(v, (int, float)):
                known |= {round(abs(v)), round(abs(v), 1)}
    for g in guidance:
        for v in _numbers(" ".join(str(g.get(k, "")) for k in ("quote", "target", "statement", "horizon"))):
            known |= {round(abs(v)), round(abs(v), 1)}
    return known


_DATES = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-' ]?\d{2,4}\b|\b[hq][1-4]\b|"
                    r"\bfy ?'?\d{2,4}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", re.I)


def figures(t: str) -> list[float]:
    """Numbers in a piece of evidence, ignoring period labels (Sep-26, Q3, FY27) and years."""
    return [n for n in _numbers(_DATES.sub(" ", t or "")) if not (2000 <= abs(n) <= 2040 and n == int(n))]


def validate_promises(out: dict, guidance: list[dict], quarters: dict) -> dict:
    """Tie each promise to a verified guidance quote; downgrade unevidenced verdicts; trace numbers."""
    known = _known_numbers(quarters, guidance)
    kept, dropped = [], []
    for p in out.get("promises") or []:
        if not isinstance(p, dict):
            continue
        ref = p.get("ref")
        g = guidance[ref] if isinstance(ref, int) and 0 <= ref < len(guidance) else None
        if g is None:   # fall back to matching on period + metric
            g = next((x for x in guidance if x["said_in"] == p.get("said_in") and x["metric"] == p.get("metric")), None)
        if g is None:
            dropped.append({**p, "reason": "does not correspond to any verified guidance statement"})
            continue
        p["said_in"], p["quote"], p["quote_check"] = g["said_in"], g["quote"], g.get("quote_check")
        p.setdefault("metric", g["metric"])
        if p.get("verdict") not in VERDICTS:
            p["verdict"] = "unknown"
        ev = (p.get("evidence") or "").strip()
        if p["verdict"] not in ("pending", "unknown") and not ev:
            p["verdict_note"] = f"model said '{p['verdict']}' without citing figures"
            p["verdict"] = "unknown"
        nums = figures(ev)
        traced = [n for n in nums if round(abs(n)) in known or round(abs(n), 1) in known]
        p["evidence_check"] = ("no figures" if not nums else "traced" if len(traced) == len(nums)
                               else "partly traced" if traced else "untraced")
        p.pop("ref", None)
        kept.append(p)
    out["promises"] = kept
    if dropped:
        out["rejected"] = dropped
    out.setdefault("narrative_vs_numbers", [])
    return out


BULLBEAR_SCHEMA = {"type": "object", "properties": {
    "bull": {"type": "array", "items": {"type": "string"}}, "bear": {"type": "array", "items": {"type": "string"}},
    "what_would_change_my_mind": {"type": "string"}}, "required": ["bull", "bear"]}


def annotate_promises(out: dict | None, index: TranscriptIndex, guidance: list[dict], quarters: dict) -> dict | None:
    """For build-time (seeded) promise checks: mark quote + evidence checks without rewriting them."""
    if not out:
        return out
    known = _known_numbers(quarters, guidance)
    for p in out.get("promises") or []:
        p["quote_check"] = index.find(p.get("quote", ""), p.get("said_in"))["status"] if index.pages else "not_checked"
        nums = figures(p.get("evidence", ""))
        traced = [n for n in nums if round(abs(n)) in known or round(abs(n), 1) in known]
        p["evidence_check"] = ("no figures" if not nums else "traced" if len(traced) == len(nums)
                               else "partly traced" if traced else "untraced")
    return out


def bull_bear(company: str, facts: list[str], task: str | None = None) -> llm.Result:
    res = llm.run("extract", task=task or f"bull/bear {company}", system=(
        "Write a tight bull case and bear case (3 bullets each, <= 22 words per bullet) using ONLY the facts "
        "given. Each bullet must cite a number from the facts. No outside knowledge."),
        prompt=f"Company: {company}\nFacts:\n" + "\n".join(f"- {x}" for x in facts), schema=BULLBEAR_SCHEMA)
    if not res.ok:
        return res
    d = res.data if isinstance(res.data, dict) else {}
    if not isinstance(d.get("bull"), list) or not isinstance(d.get("bear"), list):
        return llm.Result("failed", model=res.model, error="model output did not match the bull/bear schema")
    fx = _numbers(" ".join(facts))
    known = {round(abs(n), 1) for n in fx} | {float(round(abs(n))) for n in fx}
    for side in ("bull", "bear"):
        d[side] = [b for b in d[side] if isinstance(b, str) and b.strip()]
    flagged = [b for side in ("bull", "bear") for b in d[side]
               if any(round(abs(n), 1) not in known and float(round(abs(n))) not in known for n in figures(b))]
    if flagged:
        d["untraced"] = flagged          # bullets citing a figure not present in the facts given
    return llm.Result(res.status, d, model=res.model)


SEGMENT_SCHEMA = {"type": "object", "properties": {
    "what_it_does": {"type": "string"}, "segments": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "share_pct": {"type": "number"}, "note": {"type": "string"}}}},
    "source": {"type": "string"}}, "required": ["what_it_does", "segments"]}


def business_mix(company: str, pages: list[str], task: str | None = None) -> llm.Result:
    """From the latest transcript / AR pages that mention segments or revenue mix."""
    keep = [p for p in pages if re.search(r"segment|revenue mix|contribution|share of revenue|portfolio", p, re.I)][:4]
    if not keep:
        return llm.Result("ok", None)
    res = llm.run("extract", task=task or f"business mix {company}", system=(
        "From this Indian listed company's own disclosure, describe what it does in one sentence and list its "
        "business segments with % of revenue if stated. Use only the text."),
        prompt=f"Company: {company}\n\n" + "\n---\n".join(keep)[:20000], schema=SEGMENT_SCHEMA)
    if res.ok and not (isinstance(res.data, dict) and res.data.get("what_it_does")):
        return llm.Result("failed", model=res.model, error="model output did not match the segment schema")
    return res
