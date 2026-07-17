"""Offline logic check — exercises both scoring engines with synthetic snapshots.

No network, no token. Proves the Green/Amber/Red and STANDARD/HALF/WAIT/SKIP
resolution against hand-built scenarios so the rule book can be trusted before a
live run. Run: ``python -m ironfly_check selftest``.
"""
from __future__ import annotations

from datetime import date

from . import config as cfg
from .data import OpeningData, PremarketData
from .indicators import OpeningCandle
from .stage1 import score_premarket
from .stage2 import score_opening
from .upstox_client import Candle

CONF = cfg.Config()


def _prev_candle(o, h, l, c) -> Candle:
    return Candle("2026-07-16", o, h, l, c, 0.0)


def _premarket(**kw) -> PremarketData:
    base = dict(
        trade_date=date(2026, 7, 17),
        prev_close=24000.0,
        prev_candle=_prev_candle(23950, 24080, 23900, 24000),
        atr20=200.0,
        range_ratio=0.90,
        prev_close_location=0.55,
        ema5=23980.0,
        ema20=23960.0,
        ema_distance_pct=0.17,
        gift=type("G", (), {"ok": True, "value": 24040.0, "source": "test"})(),
        expected_gap_pct=0.17,
        vix_last=14.0,
        vix_prev_close=13.6,
        vix_change_pct=2.9,
        is_expiry_day=False,
        scheduled_event=None,
    )
    base.update(kw)
    return PremarketData(**base)


def _opening(**kw) -> OpeningData:
    or5 = kw.pop("or5", OpeningCandle(24030, 24055, 24010, 24035, 0.0))
    base = dict(
        trade_date=date(2026, 7, 17),
        prev_close=24000.0,
        today_open=or5.open,
        actual_gap_pct=0.12,
        or5=or5,
        atr20=200.0,
        or5_ratio=(or5.high - or5.low) / 200.0,
        body_ratio=abs(or5.close - or5.open) / (or5.high - or5.low),
        close_location=(or5.close - or5.low) / (or5.high - or5.low),
        vwap=24030.0,
        vwap_distance_pct=0.02,
        nifty_ret_pct=0.02,
        banknifty_ret_pct=0.05,
        prev_high=24080.0,
        prev_low=23900.0,
        open_above_prev_high=False,
        open_below_prev_low=False,
        still_above_prev_high=False,
        still_below_prev_low=False,
        breadth_advancing=25,
        breadth_total=50,
        vix_change_pct=2.0,
        data_ok=True,
    )
    base.update(kw)
    return OpeningData(**base)


def run_selftest() -> int:
    failures: list[str] = []

    def check(label: str, got: str, want: str) -> None:
        ok = got == want
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {got}" + ("" if ok else f" (want {want})"))
        if not ok:
            failures.append(label)

    print("Stage 1 — pre-market:")
    check("neutral day → GREEN", score_premarket(_premarket(), CONF).status, "GREEN")
    check("expiry day → RED",
          score_premarket(_premarket(is_expiry_day=True), CONF).status, "RED")
    check("scheduled event → RED",
          score_premarket(_premarket(scheduled_event="RBI policy"), CONF).status, "RED")
    check("expected gap 0.9% → RED",
          score_premarket(_premarket(expected_gap_pct=0.9, gift=type("G", (), {"ok": True, "value": 24216.0, "source": "t"})()), CONF).status, "RED")
    check("VIX 22 → RED", score_premarket(_premarket(vix_last=22.0), CONF).status, "RED")
    check("VIX spike +12% → RED",
          score_premarket(_premarket(vix_change_pct=12.0), CONF).status, "RED")
    check("prev trend-extreme + drift → AMBER/RED",
          _one_of(score_premarket(_premarket(range_ratio=1.4, prev_close_location=0.95,
                                             ema_distance_pct=1.2, vix_last=17.9), CONF).status,
                  ("AMBER", "RED")), "yes")

    print("Stage 2 — 09:20 confirmation:")
    a = score_opening(_opening(), "GREEN", CONF)
    check("A-grade neutral → STANDARD_ENTRY", a.status, "STANDARD_ENTRY")
    check("premarket RED → SKIP", score_opening(_opening(), "RED", CONF).status, "SKIP")
    # big directional opening candle (body 0.9, OR5 100pt=0.5 ratio) → hard red skip
    big = OpeningCandle(24030, 24130, 24025, 24122, 0.0)
    check("big directional candle → SKIP",
          score_opening(_opening(or5=big, actual_gap_pct=0.12), "GREEN", CONF).status, "SKIP")
    # wide gap
    check("actual gap 0.7% → SKIP",
          score_opening(_opening(actual_gap_pct=0.7), "GREEN", CONF).status, "SKIP")
    # strong NIFTY+BANKNIFTY alignment
    check("strong index alignment → SKIP",
          score_opening(_opening(nifty_ret_pct=0.30, banknifty_ret_pct=0.40), "GREEN", CONF).status, "SKIP")
    # amber premarket caps to half at best
    check("amber premarket strong 09:20 → HALF_RISK_ENTRY",
          score_opening(_opening(), "AMBER", CONF).status, "HALF_RISK_ENTRY")

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
    return 0 if not failures else 1


def _one_of(value: str, allowed: tuple[str, ...]) -> str:
    return "yes" if value in allowed else f"no({value})"
