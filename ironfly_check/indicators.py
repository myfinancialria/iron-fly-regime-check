"""Pure indicator math — no I/O, fully unit-testable.

Everything the two scorecards need is derived here from plain candle sequences:
ATR, EMAs, VWAP, and the single-candle shape ratios (body / close-location).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .upstox_client import Candle


def ema(values: Sequence[float], period: int) -> float | None:
    """Exponential moving average of the last ``period``-seeded series.

    Seeded with the SMA of the first ``period`` values, then smoothed. Returns
    the final EMA value, or ``None`` if there is not enough data.
    """
    n = len(values)
    if n < period or period <= 0:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1.0 - k)
    return e


def atr(candles: Sequence[Candle], period: int) -> float | None:
    """Wilder-style Average True Range over ``period`` completed sessions.

    Needs ``period + 1`` candles (the first is only used for its close as the
    previous close of the second). Uses the last ``period`` true ranges.
    """
    if len(candles) < period + 1 or period <= 0:
        return None
    trs: list[float] = []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i - 1]
        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )
        trs.append(tr)
    window = trs[-period:]
    return sum(window) / len(window)


def daily_range(candle: Candle) -> float:
    return candle.high - candle.low


def close_location(candle: Candle) -> float | None:
    """(close − low) / (high − low). 1.0 = closed on the high, 0 = on the low."""
    rng = candle.high - candle.low
    if rng <= 0:
        return None
    return (candle.close - candle.low) / rng


def body_ratio(candle: Candle) -> float | None:
    """|close − open| / (high − low). High = strong directional (marubozu-ish)."""
    rng = candle.high - candle.low
    if rng <= 0:
        return None
    return abs(candle.close - candle.open) / rng


def vwap(candles: Sequence[Candle]) -> float | None:
    """Volume-weighted average price using typical price per candle.

    Index spot has no volume; when total volume is zero this falls back to a
    simple mean of typical prices (documented approximation — with only the
    09:15–09:20 candle available at 09:20 the VWAP distance is near-zero anyway,
    exactly as the rule book expects). Prefer feeding NIFTY *futures* candles
    when a volume-weighted VWAP is wanted.
    """
    if not candles:
        return None
    tps = [(c.high + c.low + c.close) / 3.0 for c in candles]
    vols = [c.volume for c in candles]
    total_vol = sum(vols)
    if total_vol > 0:
        return sum(tp * v for tp, v in zip(tps, vols)) / total_vol
    return sum(tps) / len(tps)


def pct(a: float, b: float) -> float:
    """abs(a − b) / b × 100.  Percentage distance of a from reference b."""
    if b == 0:
        return 0.0
    return abs(a - b) / b * 100.0


def signed_return_pct(start: float, end: float) -> float:
    """Signed % return from start to end."""
    if start == 0:
        return 0.0
    return (end - start) / start * 100.0


@dataclass(frozen=True)
class OpeningCandle:
    """The synthesised 09:15–09:20 five-minute candle from 1-min bars."""
    open: float
    high: float
    low: float
    close: float
    volume: float

    def as_candle(self) -> Candle:
        return Candle("09:15-09:20", self.open, self.high, self.low, self.close, self.volume)


def build_opening_candle(minute_candles: Sequence[Candle]) -> OpeningCandle | None:
    """Aggregate the first five 1-minute bars (09:15–09:19) into the OR5 candle.

    Upstox 1-minute bars are stamped at their *start* minute, so 09:15..09:19
    inclusive make up the 09:15–09:20 five-minute candle.
    """
    bars = [c for c in minute_candles if _is_open_bar(c.ts)]
    if not bars:
        return None
    return OpeningCandle(
        open=bars[0].open,
        high=max(c.high for c in bars),
        low=min(c.low for c in bars),
        close=bars[-1].close,
        volume=sum(c.volume for c in bars),
    )


def _is_open_bar(ts: str) -> bool:
    """True for a 1-min bar starting 09:15..09:19 (any date, IST)."""
    # ts like '2026-07-17T09:15:00+05:30'
    m = ts[11:16] if len(ts) >= 16 else ts
    return m in ("09:15", "09:16", "09:17", "09:18", "09:19")
