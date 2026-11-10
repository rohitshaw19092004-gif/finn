"""HTTP API for live Pull. Stateless apart from a disk cache; holds no personal data.

GET  /api/health
GET  /api/search?q=navin            -> [{name, symbol}]
GET  /api/research/{symbol}         -> dossier (cached 12h)
GET  /api/research/{symbol}/stream  -> Server-Sent Events: progress steps, then the dossier
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import llm
from .config import CACHE, settings
from .intel import research
from .sources import screener

app = FastAPI(title="FINN research API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
DOSSIERS = CACHE / "dossiers"
DOSSIERS.mkdir(parents=True, exist_ok=True)
TTL = 12 * 3600


def _cached(sym: str) -> dict | None:
    p = DOSSIERS / f"{sym}.json"
    if p.exists() and time.time() - p.stat().st_mtime < TTL:
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _store(sym: str, d: dict) -> None:
    # Only finished dossiers are cached; partial/failed/deferred ones are returned but retried next time.
    st = (d.get("analysis") or {}).get("status")
    if st not in ("complete", "unavailable", "numbers_only") and not (st == "seeded" and not llm.available()):
        return
    tmp = DOSSIERS / f".{sym}.{threading.get_ident()}.tmp"
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, DOSSIERS / f"{sym}.json")   # atomic: a concurrent reader never sees half a file


@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.available(),
            "models": {t: settings.models.chain(t) for t in ("bulk", "extract", "reason")}, "usage": llm.usage_report()}


@app.get("/api/search")
def search(q: str):
    if len(q) < 2:
        return []
    return screener.search(q)[:8]


@app.get("/api/research/{symbol}")
def get_research(symbol: str):
    try:
        sym = research.safe_symbol(symbol)
    except ValueError:
        raise HTTPException(400, "bad symbol")
    d = _cached(sym)
    if d is None:
        try:
            llm.start_run()          # each on-demand dossier gets its own model budget and fresh breakers
            d = research.build(sym)
        except Exception as e:
            raise HTTPException(404, f"could not build {sym}: {e}")
        _store(sym, d)
    return d


@app.get("/api/research/{symbol}/stream")
async def stream_research(symbol: str):
    try:
        sym = research.safe_symbol(symbol)
    except ValueError:
        raise HTTPException(400, "bad symbol")
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(kind: str, payload) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    def work() -> None:
        try:
            d = _cached(sym)
            if d is None:
                llm.start_run()
                d = research.build(sym, progress=lambda step, msg: emit("progress", {"step": step, "msg": msg}))
                _store(sym, d)
            emit("done", d)
        except Exception as e:
            emit("error", {"msg": str(e)})

    threading.Thread(target=work, daemon=True).start()

    async def events():
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), 15)
            except asyncio.TimeoutError:
                yield ": ping\n\n"          # keep proxies from closing an idle stream during model back-off
                continue
            yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if kind in ("done", "error"):
                break

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
