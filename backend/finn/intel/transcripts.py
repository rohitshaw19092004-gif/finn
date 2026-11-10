"""Concall transcripts -> explicit guidance, then promise-vs-delivered.

Cost discipline: a transcript is ~12-20k tokens. We split it into speaker turns, drop the
moderator and analyst questions, and keep only management answers that contain forward-looking
or quantitative cues. That typically keeps 15-25% of the text. Only that goes to the model.

Step 1 (extract tier, per transcript, cached forever): guidance statements with verbatim quotes.
Step 2 (reason tier, once per company): compare each earlier promise to what was later reported,
        using the deterministic quarterly numbers as the ground truth.
"""
from __future__ import annotations

import re

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
    out, n = [], 0
    for k in keep:
        n += len(k["text"])
        if n > max_chars:
            break
        out.append(k)
    return out


GUIDANCE_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "metric": {"type": "string", "description": "revenue growth | volume growth | EBITDA margin | gross margin | capex | capacity | market share | other"},
    "statement": {"type": "string", "description": "plain-English paraphrase, <= 20 words"},
    "target": {"type": "string", "description": "the number or range, e.g. '18-20%', '₹500 Cr', 'double digit'"},
    "horizon": {"type": "string", "description": "period it applies to, e.g. 'FY27', 'H2 FY27', 'next 2-3 years'"},
    "quote": {"type": "string", "description": "verbatim, <= 25 words"},
    "speaker": {"type": "string"}, "page": {"type": "integer"},
    "kind": {"type": "string", "enum": ["explicit", "directional"]}},
    "required": ["metric", "statement", "horizon", "quote", "kind"]}}}, "required": ["items"]}


def extract_guidance(period: str, excerpts: list[dict]) -> list[dict]:
    if not excerpts:
        return []
    body = "\n\n".join(f"[p{e['page']}] {e['speaker']}: {e['text']}" for e in excerpts)
    out = llm.call("extract", system=(
        "You read management's answers from an Indian company's earnings call. List ONLY forward-looking "
        "guidance management gave about the company's own numbers (growth, margins, capex, capacity, volumes). "
        "Skip industry commentary and past results. 'explicit' = a number or range; 'directional' = qualitative "
        "(e.g. 'margins will improve'). Quote verbatim. Use only this text; no outside knowledge."),
        prompt=f"Call: {period}\n\n{body}", schema=GUIDANCE_SCHEMA) or {}
    items = out.get("items", []) if isinstance(out, dict) else []
    for it in items:
        it["said_in"] = period
    return items


PROMISE_SCHEMA = {"type": "object", "properties": {
    "promises": {"type": "array", "items": {"type": "object", "properties": {
        "said_in": {"type": "string"}, "metric": {"type": "string"}, "promise": {"type": "string"},
        "quote": {"type": "string"}, "outcome": {"type": "string", "description": "what the numbers / later calls show"},
        "evidence": {"type": "string", "description": "the specific figures used"},
        "verdict": {"type": "string", "enum": ["delivered", "partly", "missed", "pending", "moved goalposts"]}},
        "required": ["said_in", "metric", "promise", "outcome", "verdict"]}},
    "narrative_vs_numbers": {"type": "array", "items": {"type": "object", "properties": {
        "theme": {"type": "string"}, "management_says": {"type": "string"}, "numbers_say": {"type": "string"},
        "agree": {"type": "boolean"}}, "required": ["theme", "management_says", "numbers_say", "agree"]}},
    "credibility": {"type": "string", "description": "one sentence overall read on management's guidance record"}},
    "required": ["promises", "narrative_vs_numbers", "credibility"]}


def promise_vs_delivered(company: str, guidance: list[dict], quarters: dict) -> dict | None:
    """Reason tier, over compact structured inputs only (never raw transcripts)."""
    if not guidance:
        return None
    qtable = "\n".join(f"{k}: " + ", ".join(f"{c}={v}" for c, v in zip(quarters["cols"], vals))
                       for k, vals in quarters["rows"].items())
    glist = "\n".join(f"- [{g['said_in']}] {g['metric']}: {g['statement']} (target {g.get('target', '-')}, "
                      f"horizon {g['horizon']}) \"{g['quote']}\"" for g in guidance)
    return llm.call("reason", system=(
        "You are a sceptical buy-side analyst. Compare what management promised with what was delivered. "
        "Ground every verdict in the reported quarterly numbers provided (INR crore) or in later guidance. "
        "Mark 'pending' if the horizon has not ended; 'moved goalposts' if later calls quietly changed the target. "
        "No outside knowledge of the company."),
        prompt=f"Company: {company}\n\nReported quarterly numbers:\n{qtable}\n\nGuidance given over the last year:\n{glist}",
        schema=PROMISE_SCHEMA)


BULLBEAR_SCHEMA = {"type": "object", "properties": {
    "bull": {"type": "array", "items": {"type": "string"}}, "bear": {"type": "array", "items": {"type": "string"}},
    "what_would_change_my_mind": {"type": "string"}}, "required": ["bull", "bear"]}


def bull_bear(company: str, facts: list[str]) -> dict | None:
    return llm.call("reason", system=(
        "Write a tight bull case and bear case (3 bullets each, <= 22 words per bullet) using ONLY the facts "
        "given. Each bullet must cite a number from the facts. No outside knowledge."),
        prompt=f"Company: {company}\nFacts:\n" + "\n".join(f"- {x}" for x in facts), schema=BULLBEAR_SCHEMA)


SEGMENT_SCHEMA = {"type": "object", "properties": {
    "what_it_does": {"type": "string"}, "segments": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "share_pct": {"type": "number"}, "note": {"type": "string"}}}},
    "source": {"type": "string"}}, "required": ["what_it_does", "segments"]}


def business_mix(company: str, pages: list[str]) -> dict | None:
    """From the latest transcript / AR pages that mention segments or revenue mix."""
    keep = [p for p in pages if re.search(r"segment|revenue mix|contribution|share of revenue|portfolio", p, re.I)][:4]
    if not keep:
        return None
    return llm.call("extract", system=(
        "From this Indian listed company's own disclosure, describe what it does in one sentence and list its "
        "business segments with % of revenue if stated. Use only the text."),
        prompt=f"Company: {company}\n\n" + "\n---\n".join(keep)[:20000], schema=SEGMENT_SCHEMA)
