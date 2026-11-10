"""LLM router: tiered models, content-addressed cache, usage ledger, graceful degradation.

Tiers (see config.ModelTiers):
  bulk    -> residual filing classification, one-line summaries (batched, many per call)
  extract -> structured extraction: results tables, people bios, guidance statements
  reason  -> judgment over *already-extracted* facts: promise-vs-delivered, bull/bear

Rules this module enforces:
  * Every call is cached by sha256(model, system, prompt, schema). Filings never change,
    so a re-run of the daily job costs ~0 tokens for anything already seen.
  * Only public documents are ever sent. The investor's network is never an input here.
  * No key configured -> callers get `None` and fall back to deterministic output.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass

from . import http
from .config import CACHE, settings

log = logging.getLogger(__name__)
_DB = CACHE / "llm.sqlite"
_lock = threading.Lock()


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB)
    con.execute("create table if not exists cache (k text primary key, model text, out text, "
                "tin int, tout int, ts real)")
    return con


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


LEDGER: dict[str, Usage] = {}
_quota_dead = False


def _ledger(tier: str) -> Usage:
    return LEDGER.setdefault(tier, Usage())


def available() -> bool:
    return bool(settings.gemini_key or settings.openai_compat_key)


def _gemini(model: str, system: str, prompt: str, schema: dict | None, temperature: float) -> tuple[str, int, int]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    cfg: dict = {"temperature": temperature}
    if schema:
        cfg["responseMimeType"] = "application/json"
        cfg["responseSchema"] = schema
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": cfg}
    global _quota_dead
    for attempt in range(5):
        http.throttle(url)
        r = http.client().post(url, headers={"x-goog-api-key": settings.gemini_key}, json=body, timeout=120)
        if r.status_code == 429 and "PerDay" in r.text:
            _quota_dead = True                    # daily quota gone: stop calling, fall back for the rest of the run
            raise RuntimeError("gemini daily quota exhausted")
        if r.status_code == 429 or r.status_code >= 500:   # per-minute limits -> back off
            time.sleep(min(60, 4 * 2 ** attempt))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"gemini {r.status_code}: {r.text[:300]}")
        j = r.json()
        cand = (j.get("candidates") or [{}])[0]
        if "content" not in cand:
            raise RuntimeError(f"gemini returned no content (finishReason={cand.get('finishReason')})")
        text = "".join(p.get("text", "") for p in cand["content"]["parts"])
        u = j.get("usageMetadata", {})
        return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)
    raise RuntimeError("gemini: rate limited after retries")


def _openai_compat(model: str, system: str, prompt: str, schema: dict | None, temperature: float):
    body = {"model": model, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if schema:
        body["response_format"] = {"type": "json_object"}
        body["messages"][0]["content"] += "\nReturn only JSON matching this schema:\n" + json.dumps(schema)
    r = http.client().post(f"{settings.openai_compat_base}/chat/completions", json=body, timeout=120,
                           headers={"Authorization": f"Bearer {settings.openai_compat_key}"})
    r.raise_for_status()
    j = r.json()
    u = j.get("usage", {})
    return j["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def call(tier: str, system: str, prompt: str, schema: dict | None = None,
         temperature: float = 0.1) -> dict | str | None:
    """Run one model call on a tier. Returns parsed JSON when a schema is given."""
    model = getattr(settings.models, tier)
    key = hashlib.sha256(json.dumps([model, system, prompt, schema], sort_keys=True).encode()).hexdigest()
    led = _ledger(tier)
    with _lock:
        row = _db().execute("select out from cache where k=?", (key,)).fetchone()
    if row:
        led.cached += 1
        return json.loads(row[0]) if schema else row[0]
    if not available() or _quota_dead:
        return None
    try:
        if settings.gemini_key:
            text, tin, tout = _gemini(model, system, prompt, schema, temperature)
        else:
            text, tin, tout = _openai_compat(model, system, prompt, schema, temperature)
    except Exception as e:
        log.warning("LLM %s failed: %s", tier, e)
        return None
    led.calls += 1
    led.tokens_in += tin
    led.tokens_out += tout
    out = text
    if schema:
        try:
            out = json.loads(text)
        except json.JSONDecodeError:
            log.warning("LLM returned non-JSON on tier %s", tier)
            return None
    with _lock:
        con = _db()
        con.execute("insert or replace into cache values (?,?,?,?,?,?)", (key, model, text, tin, tout, time.time()))
        con.commit()
    return out


def usage_report() -> dict:
    return {t: vars(u) | {"model": getattr(settings.models, t)} for t, u in LEDGER.items()}
