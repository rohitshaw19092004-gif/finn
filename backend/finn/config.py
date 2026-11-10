"""Central configuration. Everything is overridable with environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root
DATA = Path(os.getenv("FINN_DATA_DIR", ROOT / "data"))
RAW = DATA / "raw"                                  # captured source payloads + build-time seeds
CACHE = DATA / "cache"                              # http + llm cache (gitignored, persisted by Actions cache)
OUT = Path(os.getenv("FINN_OUT_DIR", ROOT / "web" / "public" / "data"))  # snapshot for the app


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class ModelTiers:
    """Model routing, chosen for the Gemini *free tier* as it actually behaves.

    Free-tier quotas read in AI Studio (Oct–Nov 2026): Flash ≈ 5 RPM / 20 requests per DAY,
    Flash-Lite ≈ 15 RPM / 500 requests per day. A first refresh needs ~150 calls, so the
    high-volume reading work (filings, transcripts) runs on Flash-Lite, and Flash is reserved
    for the one judgment step per company (promised vs delivered), capped per run.
    Every tier falls back to the next model when one is overloaded (503), slow, or out of quota.
    Override with env vars on a paid key (e.g. FINN_MODEL_EXTRACT=gemini-flash-latest).
    """
    bulk: str = os.getenv("FINN_MODEL_BULK", "gemini-flash-lite-latest")      # classify, one-liners
    extract: str = os.getenv("FINN_MODEL_EXTRACT", "gemini-flash-lite-latest")  # guidance, people, segments, bull/bear
    reason: str = os.getenv("FINN_MODEL_REASON", "gemini-flash-latest")       # promised vs delivered
    fallback: str = os.getenv("FINN_MODEL_FALLBACK", "gemini-flash-lite-latest")

    def chain(self, tier: str) -> list[str]:
        out = []
        for m in (getattr(self, tier), self.fallback):
            if m and m not in out:
                out.append(m)
        return out


@dataclass(frozen=True)
class LLMLimits:
    timeout_s: float = _f("FINN_LLM_TIMEOUT", 90)            # per request read timeout
    retries: int = int(_f("FINN_LLM_RETRIES", 2))            # extra attempts per model on 503/500/timeout
    budget_min: float = _f("FINN_LLM_BUDGET_MIN", 45)        # wall-clock budget for all model work in one run
    breaker: int = int(_f("FINN_LLM_BREAKER", 3))            # consecutive failures before a model cools down
    cooldown_s: float = _f("FINN_LLM_COOLDOWN", 600)
    flash_cap: int = int(_f("FINN_FLASH_CAP", 15))           # max calls per run to non-Lite Flash (free tier: 20/day)
    rpm_lite: float = _f("FINN_RPM_LITE", 13)                # pacing (requests/min) for Flash-Lite
    rpm_flash: float = _f("FINN_RPM_FLASH", 4.5)             # pacing for Flash
    thinking: str = os.getenv("FINN_THINKING", "low")        # Gemini 3.x thinkingLevel (default is 'high' = slow); '' to omit
    # Gemini 3 docs: keep temperature at the default 1.0 — lower values can cause looping (long, slow,
    # truncated answers). So FINN sends no temperature unless FINN_TEMPERATURE is set explicitly.
    temperature: float | None = float(os.environ["FINN_TEMPERATURE"]) if os.getenv("FINN_TEMPERATURE") else None
    max_output_tokens: int = int(_f("FINN_MAX_OUTPUT_TOKENS", 8192))   # bounds a runaway answer


@dataclass(frozen=True)
class Settings:
    gemini_key: str | None = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    openai_compat_key: str | None = os.getenv("OPENAI_COMPAT_API_KEY")          # Groq / OpenRouter
    openai_compat_base: str = os.getenv("OPENAI_COMPAT_BASE_URL", "https://api.groq.com/openai/v1")
    models: ModelTiers = field(default_factory=ModelTiers)
    limits: LLMLimits = field(default_factory=LLMLimits)
    window_days: int = int(os.getenv("FINN_WINDOW_DAYS", "21"))   # announcements kept in the snapshot
    price_days: int = int(os.getenv("FINN_PRICE_DAYS", "400"))
    offline: bool = os.getenv("FINN_OFFLINE", "0") == "1"           # read only from data/raw captures
    user_agent: str = os.getenv(
        "FINN_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
    )


settings = Settings()

for d in (RAW, CACHE, OUT):
    d.mkdir(parents=True, exist_ok=True)
