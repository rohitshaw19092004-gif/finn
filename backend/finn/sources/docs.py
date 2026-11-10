"""PDF documents (filings, concall transcripts, annual reports) -> text.

Text is cached next to the PDF so each document is parsed once, ever.
Transcripts are split into speaker turns so later steps can pre-filter before any LLM call.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from pypdf import PdfReader

from ..config import CACHE

TEXT_CACHE = CACHE / "text"
TEXT_CACHE.mkdir(parents=True, exist_ok=True)


def pdf_text(data: bytes, max_pages: int | None = None) -> list[str]:
    """Return page texts. Scanned PDFs return empty strings (OCR is a deliberate TODO)."""
    r = PdfReader(io.BytesIO(data))
    pages = r.pages if max_pages is None else r.pages[:max_pages]
    out = []
    for p in pages:
        try:
            out.append(p.extract_text() or "")
        except Exception:
            out.append("")
    return out


def cached_text(name: str, loader) -> list[str]:
    p = TEXT_CACHE / (Path(name).stem + ".pages.txt")
    if p.exists():
        return p.read_text(encoding="utf-8").split("\f")
    pages = pdf_text(loader())
    p.write_text("\f".join(pages), encoding="utf-8")
    return pages


def clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


SPEAKER = re.compile(r"^\s*([A-Z][A-Za-z.\- ]{2,40}):\s*", re.M)


def speaker_turns(pages: list[str]) -> list[dict]:
    """Split a transcript into {speaker, text, page} turns. Robust to page breaks mid-turn."""
    turns: list[dict] = []
    cur = {"speaker": "?", "text": "", "page": 1}
    for i, page in enumerate(pages, start=1):
        pos = 0
        for m in SPEAKER.finditer(page):
            cur["text"] += page[pos:m.start()]
            if cur["text"].strip():
                turns.append(cur)
            cur = {"speaker": m.group(1).strip(), "text": "", "page": i}
            pos = m.end()
        cur["text"] += page[pos:] + "\n"
    if cur["text"].strip():
        turns.append(cur)
    for t in turns:
        t["text"] = clean(t["text"])
    return turns
