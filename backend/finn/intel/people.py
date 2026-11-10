"""People named in filings -> structured public profiles (career, education, the event).

SEBI's LODR rules require a 'brief profile' annexure when a director/KMP is appointed, so the
filing itself is the primary source for 'who is the incoming person'. The 'extract' tier turns
that prose into career/education rows the device-side network matcher can join on.
When a filing has no profile (e.g. a re-designation), a licensed profile provider would fill
the gap — see docs/architecture.md; the demo marks those as `enrichment: pending`.
"""
from __future__ import annotations

import re

from .. import llm

SCHEMA = {"type": "object", "properties": {"people": {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"},
    "event": {"type": "object", "properties": {"role": {"type": "string"}, "change": {"type": "string"},
                                               "effective": {"type": "string", "description": "YYYY-MM-DD"}}},
    "summary": {"type": "string", "description": "<= 40 words: who they are and where they come from"},
    "career": {"type": "array", "items": {"type": "object", "properties": {
        "org": {"type": "string"}, "title": {"type": "string"},
        "from": {"type": "string", "description": "YYYY or YYYY-MM; empty if not stated"},
        "to": {"type": "string"}}}},
    "education": {"type": "array", "items": {"type": "object", "properties": {
        "school": {"type": "string"}, "degree": {"type": "string"}}}}},
    "required": ["name", "event", "career"]}}}, "required": ["people"]}

HONORIFIC = r"(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Shri|Smt\.?)"
NAME = re.compile(HONORIFIC + r"\s+([A-Z][A-Za-z.'’]*(?:\s+[A-Z][A-Za-z.'’]*){0,3})")


def extract(doc_text: str, symbol: str) -> list[dict]:
    """LLM path: only the profile/annexure part of the filing is sent (public text)."""
    m = re.search(r"(brief profile|profile of|annexure)", doc_text, re.I)
    body = doc_text[max(0, (m.start() if m else 0) - 1500):][:12000]
    out = llm.call("extract", system=(
        "From this Indian stock-exchange filing, list each person whose appointment, resignation, retirement or "
        "cessation is disclosed. Use ONLY facts in the text. Dates as YYYY or YYYY-MM when stated; leave empty if not."),
        prompt=body, schema=SCHEMA)
    if out and isinstance(out, dict):
        people = out.get("people", [])
        for p in people:
            p["symbol"] = symbol
        return people
    return fallback(doc_text, symbol)


def fallback(doc_text: str, symbol: str) -> list[dict]:
    """No-key path: names + the role phrase next to them. Thin, but never wrong about who."""
    seen, out = set(), []
    for m in NAME.finditer(doc_text):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .")
        if name in seen or len(name.split()) < 2:
            continue
        seen.add(name)
        ctx = doc_text[m.end(): m.end() + 200]
        role = re.search(r"(Managing Director|Chief Executive Officer|Chief Financial Officer|Chairman|"
                         r"Independent Director|Director|Company Secretary)", ctx)
        out.append({"name": name, "symbol": symbol, "event": {"role": role.group(1) if role else None},
                    "career": [], "education": [], "enrichment": "pending"})
    return out[:6]
