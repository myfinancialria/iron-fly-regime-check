"""Assemble the raw inputs each stage needs from Upstox + GIFT + constituents.

This is the only I/O-heavy module. It turns live API responses into two flat,
fully-populated snapshot dataclasses (``PremarketData`` / ``OpeningData``) that the
pure scoring engines consume. Every field that can be missing is Optional, and the
scoring engines degrade gracefully rather than crash.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import config as cfg
from . import giftnifty
from . import constituents
from .calendar import IST, NSECalendar
from .indicators import (
    atr, build_opening_candle, close_location, daily_range, ema,
    OpeningCandle, pct, signed_return_pct, vwap,
)
from .upstox_client import Candle, UpstoxClient


# --------------------------------------------------------------------------- #
# Stage-1 snapshot
# --------------------------------------------------------------------------- #
@dataclass
class PremarketData:
    trade_date: date
    prev_close: float
    prev_candle: Candle                 # previous session's daily OHLC
    atr20: float | None
    range_ratio: float | None           # prev range / ATR20
    prev_close_location: float | None
    ema5: float | None
    ema20: float | None
    ema_distance_pct: float | None      # |last close − EMA20| / EMA20 × 100
    gift: giftnifty.GiftNifty
    expected_gap_pct: float | None      # |GIFT − prev close| / prev close × 100
    vix_last: float | None
    vix_prev_close: float | None
    vix_change_pct: float | None
    is_expiry_day: bool
    scheduled_event: str | None


def fetch_premarket(
    client: UpstoxClient,
    trade_date: date,
    conf: cfg.Config,
    calendar: NSECalendar | None = None,
) -> PremarketData:
    calendar = calendar or NSECalendar()

    # --- daily history for prev-day structure, ATR20, EMAs ---
    start = trade_date - timedelta(days=cfg.DAILY_HISTORY_DAYS)
    dailies = client.daily_candles(cfg.NIFTY_KEY, start, trade_date - timedelta(days=1))
    if not dailies:
        raise RuntimeError("No daily NIFTY candles returned — cannot score pre-market.")
    prev_candle = dailies[-1]
    prev_close = prev_candle.close
    closes = [c.close for c in dailies]

    atr20 = atr(dailies, cfg.ATR_LOOKBACK)
    ema5 = ema(closes, cfg.EMA_FAST)
    ema20 = ema(closes, cfg.EMA_SLOW)
    rng = daily_range(prev_candle)
    range_ratio = (rng / atr20) if (atr20 and atr20 > 0) else None
    prev_cl = close_location(prev_candle)
    ema_dist = pct(prev_close, ema20) if ema20 else None

    # --- GIFT NIFTY expected gap ---
    gift = giftnifty.fetch()
    expected_gap = pct(gift.value, prev_close) if gift.ok and gift.value else None

    # --- India VIX ---
    vix_last = vix_prev = vix_chg = None
    try:
        q = client.quotes([cfg.INDIA_VIX_KEY])
        vq = _first(q)
        if vq:
            vix_last = vq.last_price or None
            vix_prev = vq.prev_close
            if vix_last and vix_prev:
                vix_chg = (vix_last - vix_prev) / vix_prev * 100.0
    except Exception:
        pass

    return PremarketData(
        trade_date=trade_date,
        prev_close=prev_close,
        prev_candle=prev_candle,
        atr20=atr20,
        range_ratio=range_ratio,
        prev_close_location=prev_cl,
        ema5=ema5,
        ema20=ema20,
        ema_distance_pct=ema_dist,
        gift=gift,
        expected_gap_pct=expected_gap,
        vix_last=vix_last,
        vix_prev_close=vix_prev,
        vix_change_pct=vix_chg,
        is_expiry_day=calendar.is_expiry_day(trade_date, cfg.EXPIRY_WEEKDAY),
        scheduled_event=cfg.SCHEDULED_EVENTS.get(trade_date),
    )


# --------------------------------------------------------------------------- #
# Stage-2 snapshot
# --------------------------------------------------------------------------- #
@dataclass
class OpeningData:
    trade_date: date
    prev_close: float
    today_open: float
    actual_gap_pct: float
    or5: OpeningCandle
    atr20: float | None
    or5_ratio: float | None
    body_ratio: float | None
    close_location: float | None
    vwap: float | None
    vwap_distance_pct: float | None
    nifty_ret_pct: float | None         # 09:15 -> 09:20 signed return
    banknifty_ret_pct: float | None
    prev_high: float
    prev_low: float
    open_above_prev_high: bool
    open_below_prev_low: bool
    still_above_prev_high: bool
    still_below_prev_low: bool
    breadth_advancing: int | None
    breadth_total: int | None
    vix_change_pct: float | None
    data_ok: bool
    note: str = ""


def fetch_opening(
    client: UpstoxClient,
    trade_date: date,
    conf: cfg.Config,
    data_dir: str | Path,
    premarket: PremarketData | None = None,
) -> OpeningData:
    # Reuse pre-market daily stats if provided; else refetch prev day + ATR.
    if premarket is not None:
        prev_close = premarket.prev_close
        atr20 = premarket.atr20
        prev_high = premarket.prev_candle.high
        prev_low = premarket.prev_candle.low
        vix_prev = premarket.vix_prev_close
    else:
        start = trade_date - timedelta(days=cfg.DAILY_HISTORY_DAYS)
        dailies = client.daily_candles(cfg.NIFTY_KEY, start, trade_date - timedelta(days=1))
        if not dailies:
            raise RuntimeError("No daily NIFTY candles — cannot score 09:20.")
        prev_close = dailies[-1].close
        atr20 = atr(dailies, cfg.ATR_LOOKBACK)
        prev_high, prev_low = dailies[-1].high, dailies[-1].low
        vix_prev = None

    # --- today's 1-min candles -> the 09:15–09:20 opening candle + VWAP ---
    minutes = client.intraday_candles(cfg.NIFTY_KEY, "1minute")
    or5 = build_opening_candle(minutes)
    if or5 is None:
        raise RuntimeError(
            "No 09:15–09:20 candle available yet — run the confirm step after 09:20 IST."
        )
    today_open = or5.open
    actual_gap = pct(today_open, prev_close)
    or5_range = or5.high - or5.low
    or5_ratio = (or5_range / atr20) if (atr20 and atr20 > 0) else None
    body = (abs(or5.close - or5.open) / or5_range) if or5_range > 0 else None
    cl = ((or5.close - or5.low) / or5_range) if or5_range > 0 else None

    # VWAP from the opening-window 1-min bars (index has no volume -> typical-price mean).
    open_bars = [c for c in minutes if _in_open_window(c.ts)]
    vw = vwap(open_bars) if open_bars else None
    vwap_dist = pct(or5.close, vw) if vw else None

    # --- NIFTY & BANKNIFTY 09:15->09:20 return ---
    nifty_ret = signed_return_pct(or5.open, or5.close)
    banknifty_ret = None
    try:
        bn_min = client.intraday_candles(cfg.BANKNIFTY_KEY, "1minute")
        bn_or5 = build_opening_candle(bn_min)
        if bn_or5:
            banknifty_ret = signed_return_pct(bn_or5.open, bn_or5.close)
    except Exception:
        pass

    # --- previous-day high/low location (open vs now) ---
    open_above = today_open > prev_high
    open_below = today_open < prev_low
    now = or5.close
    still_above = now > prev_high
    still_below = now < prev_low

    # --- breadth (best-effort) ---
    adv = total = None
    note = ""
    try:
        keys = constituents.resolve_keys(data_dir, trade_date.isoformat())
        if keys:
            quotes = client.quotes(list(keys.values()))
            # match resolved keys against returned quotes (keys may differ in casing)
            qmap = {q.instrument_key: q for q in quotes.values()}
            advancing = 0
            counted = 0
            for k in keys.values():
                q = qmap.get(k) or _find_quote(quotes, k)
                if q and q.prev_close:
                    counted += 1
                    if q.last_price > q.prev_close:
                        advancing += 1
            if counted:
                adv, total = advancing, counted
        else:
            note = "breadth unavailable (instrument master not resolved)"
    except Exception as e:
        note = f"breadth unavailable ({type(e).__name__})"

    # --- VIX intraday change (vs prev close) ---
    vix_chg = None
    try:
        vq = _first(client.quotes([cfg.INDIA_VIX_KEY]))
        if vq and vq.last_price and (vix_prev or vq.prev_close):
            base = vix_prev or vq.prev_close
            vix_chg = (vq.last_price - base) / base * 100.0
    except Exception:
        pass

    return OpeningData(
        trade_date=trade_date,
        prev_close=prev_close,
        today_open=today_open,
        actual_gap_pct=actual_gap,
        or5=or5,
        atr20=atr20,
        or5_ratio=or5_ratio,
        body_ratio=body,
        close_location=cl,
        vwap=vw,
        vwap_distance_pct=vwap_dist,
        nifty_ret_pct=nifty_ret,
        banknifty_ret_pct=banknifty_ret,
        prev_high=prev_high,
        prev_low=prev_low,
        open_above_prev_high=open_above,
        open_below_prev_low=open_below,
        still_above_prev_high=still_above,
        still_below_prev_low=still_below,
        breadth_advancing=adv,
        breadth_total=total,
        vix_change_pct=vix_chg,
        data_ok=True,
        note=note,
    )


def _in_open_window(ts: str) -> bool:
    m = ts[11:16] if len(ts) >= 16 else ts
    return m in ("09:15", "09:16", "09:17", "09:18", "09:19")


def _first(quotes: dict):
    for v in quotes.values():
        return v
    return None


def _find_quote(quotes: dict, key: str):
    # Upstox sometimes returns keys with ':' vs '|' — match loosely on the tail.
    tail = key.split("|")[-1]
    for v in quotes.values():
        if v.instrument_key.endswith(tail):
            return v
    return None
