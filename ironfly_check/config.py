"""All tunable thresholds and the scheduled-event calendar in one place.

Every number here traces directly to the rule book in README.md. Thresholds are
expressed as percentages / ratios (never fixed NIFTY points) so they stay valid
as the index level drifts. Override any of these via environment variables of the
same name (see ``_env_*`` helpers) without editing code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from datetime import date


# --------------------------------------------------------------------------- #
# Instrument keys (Upstox v2 instrument_key format)
# --------------------------------------------------------------------------- #
NIFTY_KEY = "NSE_INDEX|Nifty 50"
BANKNIFTY_KEY = "NSE_INDEX|Nifty Bank"
INDIA_VIX_KEY = "NSE_INDEX|India VIX"

NIFTY_LOT_SIZE = 65          # NSE lot in effect for the Jul-2026 expiry cycle
NIFTY_ATM_STEP = 50          # strike interval


# --------------------------------------------------------------------------- #
# Stage 1 — pre-market thresholds
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PremarketThresholds:
    # Expected opening-gap (|GIFT − prev close| / prev close × 100)
    gap_green_below: float = 0.40         # < 0.40%  -> green
    gap_amber_below: float = 0.70         # 0.40–0.70% -> amber; >= red
    gap_hard_red: float = 0.70            # a > 0.70% expected gap overrides the score

    # India VIX absolute level
    vix_low_amber_below: float = 11.0     # < 11 -> amber (thin premium)
    vix_green_low: float = 11.0           # 11–18 -> green
    vix_green_high: float = 18.0
    vix_amber_high: float = 21.0          # 18–21 -> amber; > 21 -> red
    vix_hard_red: float = 21.0

    # India VIX 1-day change (%)
    vix_change_normal_below: float = 5.0  # < +5%  -> normal
    vix_change_amber_below: float = 10.0  # +5–10% -> amber; > +10% -> red
    vix_change_hard_red: float = 10.0

    # Previous-day structure
    range_ratio_trend: float = 1.20       # prev range / ATR20 above this = large range
    close_loc_high: float = 0.85          # close in top 15% of range = extreme
    close_loc_low: float = 0.15           # close in bottom 15% of range = extreme

    # Daily trend filter (distance of price from 20-EMA, %)
    ema_dist_green_below: float = 1.0     # within ~1% of 20-EMA -> neutral
    ema_dist_amber_below: float = 1.5     # 1–1.5% -> amber; > 1.5% -> red

    # Scorecard cut-offs
    score_green_min: int = 5              # 5–6 -> green
    score_amber: int = 4                  # 4   -> amber; <= 3 -> red


# --------------------------------------------------------------------------- #
# Stage 2 — 09:20 confirmation thresholds
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OpeningThresholds:
    # Actual gap (|open − prev close| / prev close × 100)
    gap_pass_below: float = 0.35          # < 0.35% -> pass
    gap_caution_below: float = 0.60       # 0.35–0.60% -> caution; > 0.60% -> skip
    gap_hard_red: float = 0.60

    # OR5 ratio = (first-candle range) / ATR20
    or5_compressed_below: float = 0.10    # < 0.10 -> too compressed, delay
    or5_pass_below: float = 0.30          # 0.10–0.30 -> acceptable
    or5_reduced_below: float = 0.40       # 0.30–0.40 -> reduced risk; > 0.40 -> skip
    or5_hard_red: float = 0.40

    # Candle body ratio = |close − open| / range
    body_pass_below: float = 0.45         # < 0.45 -> balanced
    body_reduced_below: float = 0.65      # 0.45–0.65 -> reduced/delay; > 0.65 -> skip
    body_hard_red: float = 0.75           # > 0.75 -> hard red

    # Candle close location = (close − low) / range
    close_loc_low: float = 0.25           # enter only when 0.25–0.75
    close_loc_high: float = 0.75
    close_loc_extreme_low: float = 0.15
    close_loc_extreme_high: float = 0.85

    # VWAP distance (%)
    vwap_pass_below: float = 0.10         # < 0.10% -> pass
    vwap_caution_below: float = 0.20      # 0.10–0.20% -> caution; > 0.20% -> skip

    # NIFTY / BANKNIFTY 09:15->09:20 return alignment (%)
    nifty_align: float = 0.25             # |NIFTY ret| above this AND ...
    banknifty_align: float = 0.35         # |BANKNIFTY ret| above this = strong alignment

    # Breadth: advancing count out of NIFTY 50
    breadth_balanced_low: int = 18        # 18–32 -> balanced
    breadth_balanced_high: int = 32
    breadth_strong_high: int = 38         # > 38 or < 12 -> strong, skip
    breadth_strong_low: int = 12

    vix_intraday_hard_red_change: float = 10.0  # VIX up > ~10% intraday -> skip

    # Scorecard cut-offs (out of 8)
    score_standard_min: int = 7           # 7–8 -> standard risk
    score_half: int = 6                   # 6   -> half risk
    score_wait_min: int = 4               # 4–5 -> wait until 09:30; <= 3 -> skip


# --------------------------------------------------------------------------- #
# Position sizing (risk defined from capital, never from lots)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Sizing:
    capital: float = 2_000_000.0          # ₹20 lakh
    standard_risk_pct: float = 0.40       # standard-day planned risk, % of capital
    reduced_risk_pct: float = 0.20        # reduced-risk day
    max_daily_loss_pct: float = 0.50      # absolute daily stop
    lot_size: int = NIFTY_LOT_SIZE

    @property
    def standard_risk_rupees(self) -> float:
        return self.capital * self.standard_risk_pct / 100.0

    @property
    def reduced_risk_rupees(self) -> float:
        return self.capital * self.reduced_risk_pct / 100.0

    @property
    def max_daily_loss_rupees(self) -> float:
        return self.capital * self.max_daily_loss_pct / 100.0


# --------------------------------------------------------------------------- #
# Scheduled-event calendar — hard-red days for the standard strategy
# --------------------------------------------------------------------------- #
# Maintain this list from RBI / exchange / government calendars. A day listed here
# forces PREMARKET_STATUS = RED regardless of the score. NIFTY *expiry* days are
# handled separately (skip in the initial optimized version) via EXPIRY_WEEKDAY.
SCHEDULED_EVENTS: dict[date, str] = {
    # date(2026, 8, 6): "RBI monetary-policy decision",
    # date(2026, 2, 1): "Union Budget",
}

# NIFTY weekly expiry weekday. NSE moved the NIFTY weekly expiry to Tuesday
# (circular effective 2025). 0=Mon … 4=Fri. Verify against the current circular.
EXPIRY_WEEKDAY: int = 1  # Tuesday


# --------------------------------------------------------------------------- #
# Data / lookback settings
# --------------------------------------------------------------------------- #
ATR_LOOKBACK = 20            # 20-day ATR and the 20-EMA use this many sessions
EMA_FAST = 5
EMA_SLOW = 20
DAILY_HISTORY_DAYS = 60      # calendar days of daily candles to pull (covers ATR20/EMA20)


def _f(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v not in (None, "") else default


def _i(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v not in (None, "") else default


@dataclass(frozen=True)
class Config:
    premarket: PremarketThresholds = field(default_factory=PremarketThresholds)
    opening: OpeningThresholds = field(default_factory=OpeningThresholds)
    sizing: Sizing = field(default_factory=Sizing)

    @classmethod
    def from_env(cls) -> "Config":
        """Build config, letting a few high-value knobs be overridden by env."""
        sizing = Sizing(capital=_f("IFC_CAPITAL", Sizing.capital))
        return cls(sizing=sizing)


DEFAULT = Config()
