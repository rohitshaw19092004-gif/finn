"""Polite HTTP: one shared client, per-host throttling, retries, and an on-disk cache.

Filings and transcripts are immutable once published, so they are cached forever.
Pages that change (screener company pages, price series) get a TTL.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import CACHE, settings

_client: httpx.Client | None = None


class PermanentError(RuntimeError):
    """4xx or wrong content: retrying won't help, and the response must not be cached."""
_last_hit: dict[str, float] = {}
MIN_GAP = {"www.screener.in": 1.2, "api.bseindia.com": 0.4, "www.bseindia.com": 0.4, "www.nseindia.com": 0.8,
           "generativelanguage.googleapis.com": 4.5}   # free tier ~15 RPM


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en-IN,en;q=0.9"},
        )
    return _client


def throttle(url: str) -> None:
    _throttle(url)


def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    gap = MIN_GAP.get(host, 0.2)
    wait = _last_hit.get(host, 0) + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


def _cache_path(url: str, params: dict | None, kind: str) -> Path:
    key = hashlib.sha256((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()[:24]
    p = CACHE / "http" / kind / key
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get(url: str, *, params: dict | None = None, headers: dict | None = None,
        ttl: float | None = 6 * 3600, binary: bool = False, retries: int = 3) -> bytes | str:
    """GET with cache. ttl=None caches forever (immutable documents)."""
    kind = "bin" if binary else "txt"
    cp = _cache_path(url, params, kind)
    if cp.exists() and (ttl is None or time.time() - cp.stat().st_mtime < ttl):
        return cp.read_bytes() if binary else cp.read_text(encoding="utf-8")
    if settings.offline:
        raise RuntimeError(f"offline mode and no cache for {url}")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            _throttle(url)
            r = client().get(url, params=params, headers=headers)
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt * 2)
                continue
            if 400 <= r.status_code < 500:
                raise PermanentError(f"{r.status_code} for {url}")
            r.raise_for_status()
            data = r.content
            if binary and ".pdf" in url.lower() and not data.startswith(b"%PDF"):
                raise PermanentError(f"not a PDF: {url}")
            cp.write_bytes(data)
            return data if binary else r.text
        except PermanentError:
            raise
        except Exception as e:  # network blips, 5xx
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def get_json(url: str, **kw) -> dict | list:
    return json.loads(get(url, **kw))
