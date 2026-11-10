"""End-of-day price & volume.

Primary: Yahoo Finance via yfinance (SYMBOL.NS). Fallback: screener.in chart endpoint.
Both return the same shape: {dates: [YYYY-MM-DD], close: [float], volume: [int|None], source}.
"""
from __future__ import annotations

import logging

from . import screener

log = logging.getLogger(__name__)


def yahoo(symbol: str, days: int = 400) -> dict:
    import yfinance as yf  # imported lazily: heavy and only needed by the daily job

    period = "2y" if days > 365 else "1y" if days > 180 else "6mo"
    df = yf.Ticker(f"{symbol}.NS").history(period=period, interval="1d", auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError(f"yahoo returned nothing for {symbol}")
    df = df.dropna(subset=["Close"]).tail(days)
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "close": [round(float(x), 2) for x in df["Close"]],
        "volume": [int(x) if x == x else None for x in df["Volume"]],
        "source": "yahoo",
    }


def eod(symbol: str, company_id: str | None, days: int = 400) -> dict:
    try:
        return yahoo(symbol, days)
    except Exception as e:  # rate limits / delisted alias / network
        log.warning("yahoo failed for %s (%s); falling back to screener", symbol, e)
        if not company_id:
            raise
        s = screener.price_series(company_id, days)
        s["source"] = "screener"
        return s


def drop_partial_session(series: dict, today: str, market_closed: bool) -> dict:
    """If we run before 15:30 IST, today's bar is intraday — EOD logic must not see it."""
    if series["dates"] and series["dates"][-1] == today and not market_closed:
        return {k: (v[:-1] if isinstance(v, list) else v) for k, v in series.items()}
    return series
