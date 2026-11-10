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


def _squash(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def _in_text(name: str, text_sq: str) -> bool:
    parts = [x for x in re.split(r"[\s.]+", name or "") if len(x) > 1]
    return bool(parts) and all(_squash(x) in text_sq for x in parts)


def extract(doc_text: str, symbol: str, status: dict | None = None) -> list[dict]:
    """LLM path: only the profile/annexure part of the filing is sent (public text).

    Model output is checked against the filing: a person whose name is not in the text is
    dropped, and career rows naming an organisation that is not in the text are removed.
    `status` (optional dict) receives what happened, for the run report.
    """
    m = re.search(r"(brief profile|profile of|annexure)", doc_text, re.I)
    body = doc_text[max(0, (m.start() if m else 0) - 1500):][:12000]
    res = llm.run("extract", task=f"{symbol} people", system=(
        "From this Indian stock-exchange filing, list each person whose appointment, resignation, retirement or "
        "cessation is disclosed. Use ONLY facts in the text. Dates as YYYY or YYYY-MM when stated; leave empty if not."),
        prompt=body, schema=SCHEMA)
    if status is not None:
        status.update(status=res.status, model=res.model, error=res.error)
    if res.ok and isinstance(res.data, dict):
        sq = _squash(doc_text)
        people, dropped = [], 0
        for p in res.data.get("people", []) or []:
            if not isinstance(p, dict) or not _in_text(p.get("name", ""), sq):
                dropped += 1
                continue
            career = [r for r in p.get("career") or [] if isinstance(r, dict) and _squash(r.get("org"))
                      and _squash(r.get("org")) in sq]
            dropped_rows = len(p.get("career") or []) - len(career)
            p["career"] = career
            p["education"] = [e for e in p.get("education") or [] if isinstance(e, dict)
                              and _squash(e.get("school")) and _squash(e.get("school")) in sq]
            p["symbol"] = symbol
            p["source"] = {"method": "llm", "model": res.model, "unverified_rows_removed": dropped_rows}
            people.append(p)
        if status is not None:
            status["dropped_people"] = dropped
        if people:
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
                    "career": [], "education": [], "enrichment": "pending", "source": {"method": "rule"}})
    return out[:6]
