"""Central configuration. Everything is overridable with environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root
DATA = Path(os.getenv("FINN_DATA_DIR", ROOT / "data"))
RAW = DATA / "raw"                                  # captured source payloads (cache)
CACHE = DATA / "cache"                              # http + llm cache (gitignored)
OUT = Path(os.getenv("FINN_OUT_DIR", ROOT / "web" / "public" / "data"))  # snapshot for the app


@dataclass(frozen=True)
class ModelTiers:
    """Model routing. Cheap model for bulk, mid for extraction, strongest only for judgment.

    Defaults use Google's rolling aliases so the code keeps working as model versions roll;
    pin exact versions in production for reproducibility.
    """
    bulk: str = os.getenv("FINN_MODEL_BULK", "gemini-flash-lite-latest")     # classify, one-liners
    extract: str = os.getenv("FINN_MODEL_EXTRACT", "gemini-flash-latest")    # tables, guidance, bios
    reason: str = os.getenv("FINN_MODEL_REASON", "gemini-flash-latest")      # promise-vs-delivered, bull/bear
    # On a paid key set FINN_MODEL_REASON=gemini-pro-latest; free tier keeps Pro rate-limited/unavailable.


@dataclass(frozen=True)
class Settings:
    gemini_key: str | None = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    openai_compat_key: str | None = os.getenv("OPENAI_COMPAT_API_KEY")          # Groq / OpenRouter
    openai_compat_base: str = os.getenv("OPENAI_COMPAT_BASE_URL", "https://api.groq.com/openai/v1")
    models: ModelTiers = field(default_factory=ModelTiers)
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
