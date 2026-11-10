"""LLM router: tiered models with fallback, bounded retries, a run budget, a cache, and an honest ledger.

Tiers (see config.ModelTiers):
  bulk    -> residual filing classification, one-line summaries (batched, many per call)
  extract -> structured extraction: results tables, people bios, guidance statements, bull/bear
  reason  -> judgment over *already-extracted, verified* facts: promised vs delivered

What this module guarantees (the first live run showed why each one matters):
  * Bounded cost per call. A model gets at most 1 + FINN_LLM_RETRIES attempts, each with a
    FINN_LLM_TIMEOUT read timeout and short jittered backoff; then the call moves to the
    tier's fallback model. Nothing ever waits minutes on one request.
  * Bounded cost per run. After FINN_LLM_BUDGET_MIN minutes of wall-clock, remaining calls
    return status "deferred" immediately, so the snapshot still gets written and committed.
  * Quota awareness. A per-day 429, 404 (model gone) or 403 retires that model for the run;
    a per-minute 429 honours Google's retryDelay; 3 consecutive failures trip a breaker that
    cools the model down. Flash (20 requests/day on the free tier) is capped per run.
  * No silent success. `run()` returns a Result whose status is one of
    ok | cached | unavailable | deferred | failed, with the model that answered and the error
    if any. Callers must record non-ok outcomes; `call()` (legacy) returns None for them.
  * Cache by content. sha256(system, prompt, schema) — whichever model in the chain answered,
    the answer is reused by the next run (filings never change). Failures are never cached.
  * Only public documents are ever sent. The investor's network is never an input here.
  * The API key is sent in a header and is never logged, cached, or written to the snapshot.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import http
from .config import CACHE, settings

log = logging.getLogger(__name__)
_DB = CACHE / "llm.sqlite"
_lock = threading.Lock()
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

TRANSIENT = {500, 502, 503, 504}


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB)
    con.execute("create table if not exists cache (k text primary key, model text, out text, "
                "tin int, tout int, ts real)")
    return con


# --------------------------------------------------------------------------- results + ledger
@dataclass
class Result:
    status: str                     # ok | cached | unavailable | deferred | failed
    data: Any = None
    model: str | None = None
    error: str | None = None
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "cached")

    def __bool__(self) -> bool:     # `if res:` means "we have usable model output"
        return self.ok


@dataclass
class Usage:
    calls: int = 0          # successful live calls
    cached: int = 0
    failed: int = 0
    deferred: int = 0
    unavailable: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class ModelState:
    requests: int = 0       # HTTP requests sent this run (incl. retries)
    ok: int = 0
    errors: Counter = field(default_factory=Counter)
    consecutive_fail: int = 0
    cool_until: float = 0.0
    dead: str | None = None             # reason the model was retired for this run
    no_thinking: bool = False           # model rejected thinkingConfig -> send without it
    last_sent: float = 0.0


LEDGER: dict[str, Usage] = {}
MODELS: dict[str, ModelState] = {}
EVENTS: list[dict] = []                 # bounded log of notable failures (for meta + step summary)
_run_start = time.time()
_auth_dead: str | None = None


def start_run() -> None:
    """Reset per-run state (budget clock, breakers, ledger). Called by snapshot.build()."""
    global _run_start, _auth_dead
    _run_start = time.time()
    _auth_dead = None
    LEDGER.clear()
    MODELS.clear()
    EVENTS.clear()


def _ledger(tier: str) -> Usage:
    return LEDGER.setdefault(tier, Usage())


def _state(model: str) -> ModelState:
    return MODELS.setdefault(model, ModelState())


def _redact(s: str) -> str:
    k = settings.gemini_key
    if k:
        s = s.replace(k, "[redacted]")
    return re.sub(r"(key=)[A-Za-z0-9_\-]+", r"\1[redacted]", s)


def _event(tier: str, task: str | None, model: str | None, kind: str, detail: str = "") -> None:
    e = {"t": round(time.time() - _run_start, 1), "tier": tier, "task": task, "model": model,
         "kind": kind, "detail": _redact(detail)[:240]}
    if len(EVENTS) < 300:
        EVENTS.append(e)
    log.warning("LLM %s/%s on %s: %s %s", tier, task or "-", model or "-", kind, e["detail"])


def available() -> bool:
    return bool(settings.gemini_key or settings.openai_compat_key) and _auth_dead is None


def budget_left() -> float:
    return settings.limits.budget_min * 60 - (time.time() - _run_start)


def _is_flash_capped(model: str) -> bool:
    if "lite" in model:
        return False
    return _state(model).requests >= settings.limits.flash_cap


def _usable(model: str) -> str | None:
    """None if the model may be called now, else the reason it may not."""
    st = _state(model)
    if st.dead:
        return st.dead
    if st.cool_until > time.time():
        return f"cooling down after {settings.limits.breaker} consecutive failures"
    if _is_flash_capped(model):
        return f"per-run cap of {settings.limits.flash_cap} requests reached (free tier ≈ 20/day)"
    return None


def _pace(model: str) -> None:
    rpm = settings.limits.rpm_lite if "lite" in model else settings.limits.rpm_flash
    st = _state(model)
    wait = st.last_sent + 60.0 / max(rpm, 0.1) - time.time()
    if wait > 0:
        time.sleep(min(wait, max(0.0, budget_left())))
    st.last_sent = time.time()


def _retry_delay(body: str) -> float | None:
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body)
    return float(m.group(1)) if m else None


class _Fail(Exception):
    def __init__(self, kind: str, detail: str, transient: bool, retire: bool = False, delay: float | None = None):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail, self.transient, self.retire, self.delay = kind, detail, transient, retire, delay


# --------------------------------------------------------------------------- providers
def _gemini_once(model: str, system: str, prompt: str, schema: dict | None, temperature: float):
    st = _state(model)
    cfg: dict = {"maxOutputTokens": settings.limits.max_output_tokens}
    if settings.limits.temperature is not None:      # see config.LLMLimits.temperature
        cfg["temperature"] = settings.limits.temperature
    if schema:
        cfg["responseMimeType"] = "application/json"
        cfg["responseSchema"] = schema
    lvl = settings.limits.thinking
    if lvl and not st.no_thinking:
        cfg["thinkingConfig"] = {"thinkingLevel": lvl}
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": cfg}
    _pace(model)
    st.requests += 1
    try:
        r = http.client().post(API.format(model=model), json=body,
                               headers={"x-goog-api-key": settings.gemini_key},
                               timeout=httpx.Timeout(settings.limits.timeout_s, connect=10.0))
    except httpx.TimeoutException:
        raise _Fail("timeout", f"no response in {settings.limits.timeout_s:.0f}s", transient=True)
    except httpx.TransportError as e:
        raise _Fail("network", type(e).__name__, transient=True)

    txt = r.text
    if r.status_code == 400 and "thinking" in txt.lower() and "thinkingConfig" in cfg:
        st.no_thinking = True             # older model: no thinkingLevel -> resend without it
        raise _Fail("thinking_unsupported", "resending without thinkingConfig", transient=True, delay=0)
    if r.status_code == 401:
        raise _Fail("auth", "API key rejected (401)", transient=False, retire=True)
    if r.status_code == 403:
        raise _Fail("forbidden", "403 for this model/key", transient=False, retire=True)
    if r.status_code == 404:
        raise _Fail("model_not_found", f"404 for {model}", transient=False, retire=True)
    if r.status_code == 429:
        if re.search(r"per ?day|perday|RequestsPerDay", txt, re.I):
            raise _Fail("quota_day", "daily free-tier quota exhausted", transient=False, retire=True)
        raise _Fail("rate_minute", "per-minute limit", transient=True, delay=_retry_delay(txt) or 20.0)
    if r.status_code in TRANSIENT:
        raise _Fail(f"http_{r.status_code}", _msg(txt), transient=True)
    if r.status_code >= 400:
        raise _Fail(f"http_{r.status_code}", _msg(txt), transient=False)

    j = r.json()
    cand = (j.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        fr = cand.get("finishReason") or (j.get("promptFeedback") or {}).get("blockReason") or "empty"
        raise _Fail("no_content", f"finishReason={fr}", transient=False)
    if cand.get("finishReason") == "MAX_TOKENS" and schema:
        raise _Fail("truncated", f"answer hit maxOutputTokens={settings.limits.max_output_tokens}", transient=False)
    u = j.get("usageMetadata", {})
    return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


def _msg(body: str) -> str:
    try:
        return (json.loads(body).get("error") or {}).get("message", "")[:200]
    except Exception:
        return body[:200]


def _openai_compat_once(model: str, system: str, prompt: str, schema: dict | None, temperature: float):
    body = {"model": model, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if schema:
        body["response_format"] = {"type": "json_object"}
        body["messages"][0]["content"] += "\nReturn only JSON matching this schema:\n" + json.dumps(schema)
    _state(model).requests += 1
    try:
        r = http.client().post(f"{settings.openai_compat_base}/chat/completions", json=body,
                               timeout=httpx.Timeout(settings.limits.timeout_s, connect=10.0),
                               headers={"Authorization": f"Bearer {settings.openai_compat_key}"})
    except httpx.TimeoutException:
        raise _Fail("timeout", "no response", transient=True)
    if r.status_code == 429 or r.status_code in TRANSIENT:
        raise _Fail(f"http_{r.status_code}", r.text[:200], transient=True, delay=_retry_delay(r.text))
    if r.status_code >= 400:
        raise _Fail(f"http_{r.status_code}", r.text[:200], transient=False, retire=r.status_code in (401, 403, 404))
    j = r.json()
    u = j.get("usage", {})
    return j["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


# --------------------------------------------------------------------------- the call
def _keys(system: str, prompt: str, schema: dict | None, chain: list[str]) -> list[str]:
    content = hashlib.sha256(json.dumps(["v2", system, prompt, schema], sort_keys=True).encode()).hexdigest()
    legacy = [hashlib.sha256(json.dumps([m, system, prompt, schema], sort_keys=True).encode()).hexdigest()
              for m in chain]                       # rows written by the previous router
    return [content, *legacy]


def _cached(keys: list[str], schema: dict | None):
    with _lock:
        con = _db()
        for k in keys:
            row = con.execute("select out, model from cache where k=?", (k,)).fetchone()
            if row:
                try:
                    return (json.loads(row[0]) if schema else row[0]), row[1]
                except json.JSONDecodeError:
                    return None
    return None


def _store(key: str, model: str, text: str, tin: int, tout: int) -> None:
    with _lock:
        con = _db()
        con.execute("insert or replace into cache values (?,?,?,?,?,?)", (key, model, text, tin, tout, time.time()))
        con.commit()


def run(tier: str, system: str, prompt: str, schema: dict | None = None,
        temperature: float = 0.1, task: str | None = None) -> Result:
    """Run one model task on a tier with fallback. Never raises; always says what happened."""
    global _auth_dead
    led = _ledger(tier)
    compat = not settings.gemini_key and bool(settings.openai_compat_key)
    chain = [getattr(settings.models, tier)] if compat else settings.models.chain(tier)
    keys = _keys(system, prompt, schema, chain)

    hit = _cached(keys, schema)
    if hit is not None:
        led.cached += 1
        return Result("cached", hit[0], model=hit[1])
    if not available():
        led.unavailable += 1
        return Result("unavailable", error=_auth_dead or "no API key configured")
    if budget_left() <= 0:
        led.deferred += 1
        return Result("deferred", error=f"run budget of {settings.limits.budget_min:.0f} min used up")

    once = _openai_compat_once if compat else _gemini_once
    attempts, errors = 0, []
    for model in chain:
        why = _usable(model)
        if why:
            errors.append(f"{model}: skipped ({why})")
            continue
        st = _state(model)
        mine: Counter = Counter()                  # this call's failures on this model
        tries, max_tries = 0, 1 + max(0, settings.limits.retries)
        while tries < max_tries:
            if budget_left() <= 0:
                led.deferred += 1
                _event(tier, task, model, "deferred", "run budget used up mid-call")
                return Result("deferred", model=model, attempts=attempts,
                              error="; ".join(errors + ["run budget used up"]))
            tries += 1
            attempts += 1
            try:
                text, tin, tout = once(model, system, prompt, schema, temperature)
            except _Fail as f:
                if f.kind == "thinking_unsupported":
                    tries -= 1                     # free retry with the corrected request
                    continue
                st.errors[f.kind] += 1
                mine[f.kind] += 1
                _event(tier, task, model, f.kind, f.detail)
                if f.kind == "auth":
                    _auth_dead = "API key rejected by Gemini (401) — check the GEMINI_API_KEY secret"
                    led.failed += 1
                    return Result("failed", model=model, attempts=attempts, error=_auth_dead)
                if f.retire:
                    st.dead = f.detail
                    break
                if not f.transient or tries >= max_tries:
                    break
                delay = f.delay if f.delay is not None else min(20.0, 2.0 * 2 ** (tries - 1)) + random.uniform(0, 1.5)
                if delay > 60 or delay >= budget_left():
                    break                              # don't park the run on one model; try the next
                time.sleep(delay)
                continue
            # got text
            out: Any = text
            if schema:
                try:
                    out = json.loads(text)
                except json.JSONDecodeError:
                    st.errors["bad_json"] += 1
                    mine["bad_json"] += 1
                    _event(tier, task, model, "bad_json", text[:120])
                    break
            st.ok += 1
            st.consecutive_fail = 0
            led.calls += 1
            led.tokens_in += tin
            led.tokens_out += tout
            _store(keys[0], model, text, tin, tout)
            return Result("ok", out, model=model, attempts=attempts)
        # this model failed for this task
        st.consecutive_fail += 1
        if st.consecutive_fail >= settings.limits.breaker and not st.dead:
            st.cool_until = time.time() + settings.limits.cooldown_s
            _event(tier, task, model, "breaker_open", f"cooling down {settings.limits.cooldown_s:.0f}s")
        errors.append(f"{model}: {', '.join(f'{k}×{v}' for k, v in mine.items()) or 'failed'}")

    led.failed += 1
    return Result("failed", attempts=attempts, error="; ".join(errors) or "no usable model")


def call(tier: str, system: str, prompt: str, schema: dict | None = None,
         temperature: float = 0.1, task: str | None = None) -> dict | str | None:
    """Legacy wrapper: parsed output, or None for any non-ok outcome (already recorded in the ledger)."""
    res = run(tier, system, prompt, schema, temperature, task)
    return res.data if res.ok else None


def usage_report() -> dict:
    """Run-level picture for meta.json, /health and the Actions step summary. Contains no secrets."""
    tiers = {t: vars(u) | {"models": settings.models.chain(t)} for t, u in LEDGER.items()}
    models = {m: {"requests": s.requests, "ok": s.ok, "errors": dict(s.errors), "retired": s.dead,
                  "thinking": None if s.no_thinking else (settings.limits.thinking or None)}
              for m, s in MODELS.items()}
    tot = Usage()
    for u in LEDGER.values():
        for k in vars(tot):
            setattr(tot, k, getattr(tot, k) + getattr(u, k))
    return {"tiers": tiers, "models": models, "totals": vars(tot),
            "budget_min": settings.limits.budget_min,
            "elapsed_min": round((time.time() - _run_start) / 60, 1),
            "auth_error": _auth_dead, "events": EVENTS[-60:]}
