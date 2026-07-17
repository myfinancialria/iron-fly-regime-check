"""Upstox v2 live-data client for the regime check.

Only the read endpoints needed by the two-stage filter are wrapped:

    1. GET /v2/historical-candle/{key}/day/{to}/{from}          -> daily OHLC history
    2. GET /v2/historical-candle/intraday/{key}/{interval}       -> today's candles
    3. GET /v2/market-quote/quotes?instrument_key=k1,k2,...      -> full quote (OHLC + LTP)
    4. GET /v2/market-quote/ltp?instrument_key=k1,k2,...         -> last price only

Access tokens expire daily ~03:30 IST; a 401 raises ``TokenExpiredError`` so the
caller re-runs the login flow rather than scoring on stale/empty data.
"""
from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

BASE_URL = "https://api.upstox.com/v2"
DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 5
DEFAULT_BACKOFF = 1.0
MAX_BACKOFF = 20.0
RATE_LIMIT_DELAY = 0.25
QUOTE_BATCH = 250  # market-quote accepts many keys per call; batch conservatively


class UpstoxError(Exception):
    """Any non-recoverable Upstox failure."""


class TokenExpiredError(UpstoxError):
    """401 — access token expired or invalid (tokens rotate daily ~03:30 IST)."""


@dataclass(frozen=True)
class Candle:
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_row(cls, row: list) -> "Candle":
        # Upstox candle row: [timestamp, open, high, low, close, volume, oi]
        return cls(
            ts=str(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]) if len(row) > 5 and row[5] is not None else 0.0,
        )


@dataclass(frozen=True)
class Quote:
    instrument_key: str
    last_price: float
    open: float | None
    high: float | None
    low: float | None
    close: float | None       # today's close so far (== last_price intraday)
    prev_close: float | None  # yesterday's close, derived from net_change
    net_change: float | None


class UpstoxClient:
    def __init__(
        self,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
    ) -> None:
        if not token or token in ("PASTE_YOUR_TOKEN_HERE", "your_token_here"):
            raise UpstoxError("Missing Upstox access token (run `login` first)")
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )
        self._timeout = timeout
        self._retries = retries
        self._backoff = backoff

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "UpstoxClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{BASE_URL}{path}"
        last_note = "no attempts made"
        for attempt in range(self._retries):
            try:
                time.sleep(RATE_LIMIT_DELAY)
                r = self._session.get(url, params=params, timeout=self._timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 401:
                    raise TokenExpiredError(
                        "Upstox 401: access token expired or invalid. Tokens "
                        "expire daily around 03:30 IST. Refresh and retry."
                    )
                if r.status_code == 429 or r.status_code >= 500:
                    ra = r.headers.get("Retry-After")
                    wait = float(ra) if (ra and ra.isdigit()) else min(
                        self._backoff * (2 ** attempt), MAX_BACKOFF)
                    last_note = f"HTTP {r.status_code} (waited {wait:.1f}s)"
                    time.sleep(wait)
                    continue
                raise UpstoxError(f"HTTP {r.status_code} on {path}: {r.text[:200]}")
            except (requests.ConnectionError, requests.Timeout) as e:
                last_note = repr(e)
                time.sleep(min(self._backoff * (2 ** attempt), MAX_BACKOFF))
        raise UpstoxError(f"Failed after {self._retries} retries on {path}: {last_note}")

    # ------------------------------------------------------------------ #
    # Daily OHLC history (for prev-day structure, ATR20, EMA5/EMA20)
    # ------------------------------------------------------------------ #
    def daily_candles(
        self, instrument_key: str, from_date: date, to_date: date
    ) -> list[Candle]:
        key = urllib.parse.quote(instrument_key, safe="")
        path = f"/historical-candle/{key}/day/{to_date:%Y-%m-%d}/{from_date:%Y-%m-%d}"
        rows = self._get(path).get("data", {}).get("candles", []) or []
        # Upstox returns most-recent first; normalise to chronological order.
        candles = [Candle.from_row(r) for r in rows]
        candles.sort(key=lambda c: c.ts)
        return candles

    # ------------------------------------------------------------------ #
    # Today's intraday candles (for the 09:15–09:20 opening candle, VWAP)
    # ------------------------------------------------------------------ #
    def intraday_candles(
        self, instrument_key: str, interval: str = "1minute"
    ) -> list[Candle]:
        key = urllib.parse.quote(instrument_key, safe="")
        path = f"/historical-candle/intraday/{key}/{interval}"
        rows = self._get(path).get("data", {}).get("candles", []) or []
        candles = [Candle.from_row(r) for r in rows]
        candles.sort(key=lambda c: c.ts)
        return candles

    # ------------------------------------------------------------------ #
    # Full quotes (LTP + OHLC + net_change -> prev close) for many keys
    # ------------------------------------------------------------------ #
    def quotes(self, instrument_keys: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for i in range(0, len(instrument_keys), QUOTE_BATCH):
            batch = instrument_keys[i:i + QUOTE_BATCH]
            data = self._get(
                "/market-quote/quotes",
                params={"instrument_key": ",".join(batch)},
            ).get("data", {}) or {}
            for _resp_key, q in data.items():
                ikey = q.get("instrument_token") or q.get("instrument_key") or _resp_key
                ohlc = q.get("ohlc", {}) or {}
                last = _num(q.get("last_price"))
                net = _num(q.get("net_change"))
                prev = (last - net) if (last is not None and net is not None) else _num(ohlc.get("close"))
                out[ikey] = Quote(
                    instrument_key=ikey,
                    last_price=last if last is not None else 0.0,
                    open=_num(ohlc.get("open")),
                    high=_num(ohlc.get("high")),
                    low=_num(ohlc.get("low")),
                    close=_num(ohlc.get("close")),
                    prev_close=prev,
                    net_change=net,
                )
        return out

    def ltp(self, instrument_keys: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for i in range(0, len(instrument_keys), QUOTE_BATCH):
            batch = instrument_keys[i:i + QUOTE_BATCH]
            data = self._get(
                "/market-quote/ltp",
                params={"instrument_key": ",".join(batch)},
            ).get("data", {}) or {}
            for _resp_key, q in data.items():
                ikey = q.get("instrument_token") or q.get("instrument_key") or _resp_key
                out[ikey] = _num(q.get("last_price")) or 0.0
        return out


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
