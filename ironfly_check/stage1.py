"""Stage 1 — pre-market regime check (run once 08:45–09:10 IST).

Output: GREEN (standard risk permitted) / AMBER (half risk or wait) / RED (no trade).
A hard-red event or gap overrides the six-point score.
"""
from __future__ import annotations

from . import config as cfg
from .data import PremarketData
from .scorecard import Condition, Scorecard


def score_premarket(d: PremarketData, conf: cfg.Config) -> Scorecard:
    t = conf.premarket
    sc = Scorecard(stage="premarket")

    # ---------------- Hard-red overrides ----------------
    if d.scheduled_event:
        sc.hard_red.append(f"Scheduled event: {d.scheduled_event}")
    if d.is_expiry_day:
        sc.hard_red.append("NIFTY expiry day (skip in the initial optimized version)")
    if d.expected_gap_pct is not None and d.expected_gap_pct > t.gap_hard_red:
        sc.hard_red.append(f"Expected gap {d.expected_gap_pct:.2f}% > {t.gap_hard_red:.2f}%")
    if d.vix_last is not None and d.vix_last > t.vix_hard_red:
        sc.hard_red.append(f"India VIX {d.vix_last:.2f} > {t.vix_hard_red:.0f}")
    if d.vix_change_pct is not None and d.vix_change_pct > t.vix_change_hard_red:
        sc.hard_red.append(f"VIX 1-day change +{d.vix_change_pct:.1f}% > +{t.vix_change_hard_red:.0f}%")

    # ---------------- Scored conditions (6) ----------------
    # 1. No major event
    sc.add(Condition(
        "No major scheduled event",
        passed=(d.scheduled_event is None and not d.is_expiry_day),
        detail=("clear" if (d.scheduled_event is None and not d.is_expiry_day)
                else (d.scheduled_event or "expiry day")),
        color=("green" if (d.scheduled_event is None and not d.is_expiry_day) else "red"),
    ))

    # 2. Expected gap below 0.40%
    if d.expected_gap_pct is None:
        sc.add(Condition(
            "Expected gap < 0.40%", None,
            f"GIFT NIFTY unavailable ({d.gift.source}) — cannot compute expected gap",
            "neutral",
        ))
        sc.notes.append("Expected-gap point could not be scored (no GIFT NIFTY).")
    else:
        g = d.expected_gap_pct
        passed = g < t.gap_green_below
        color = "green" if passed else ("amber" if g < t.gap_amber_below else "red")
        sc.add(Condition("Expected gap < 0.40%", passed,
                         f"{g:.2f}% (GIFT {d.gift.value:.0f} vs prev {d.prev_close:.0f})",
                         color))

    # 3. VIX between 11 and 18
    if d.vix_last is None:
        sc.add(Condition("India VIX in 11–18", None, "VIX unavailable", "neutral"))
    else:
        v = d.vix_last
        passed = t.vix_green_low <= v <= t.vix_green_high
        if v < t.vix_low_amber_below or (t.vix_green_high < v <= t.vix_amber_high):
            color = "amber"
        elif passed:
            color = "green"
        else:
            color = "red"
        sc.add(Condition("India VIX in 11–18", passed, f"{v:.2f}", color))

    # 4. VIX change below 5%
    if d.vix_change_pct is None:
        sc.add(Condition("VIX 1-day change < +5%", None, "VIX change unavailable", "neutral"))
    else:
        c = d.vix_change_pct
        passed = c < t.vix_change_normal_below
        color = "green" if passed else ("amber" if c < t.vix_change_amber_below else "red")
        sc.add(Condition("VIX 1-day change < +5%", passed, f"{c:+.1f}%", color))

    # 5. Previous day not a trend-extreme day
    if d.range_ratio is None or d.prev_close_location is None:
        sc.add(Condition("Prev day not a trend-extreme", None, "insufficient daily data", "neutral"))
    else:
        rr, clo = d.range_ratio, d.prev_close_location
        extreme = (rr > t.range_ratio_trend and
                   (clo > t.close_loc_high or clo < t.close_loc_low))
        large_mid = rr > t.range_ratio_trend
        passed = not extreme
        color = "green" if not large_mid else ("red" if extreme else "amber")
        sc.add(Condition("Prev day not a trend-extreme", passed,
                         f"range/ATR {rr:.2f}, close-loc {clo:.2f}", color))

    # 6. Daily structure neutral (price within ~1% of 20-EMA)
    if d.ema_distance_pct is None:
        sc.add(Condition("Daily structure neutral", None, "EMA unavailable", "neutral"))
    else:
        e = d.ema_distance_pct
        passed = e < t.ema_dist_green_below
        color = "green" if passed else ("amber" if e < t.ema_dist_amber_below else "red")
        sc.add(Condition("Daily structure neutral", passed,
                         f"{e:.2f}% from 20-EMA", color))

    sc.finalize_score()

    # ---------------- Status resolution ----------------
    if sc.hard_red:
        sc.status = "RED"
        sc.action = "No trade — hard-red override: " + "; ".join(sc.hard_red)
    elif sc.score >= t.score_green_min:
        sc.status = "GREEN"
        sc.action = "Standard risk permitted (confirm again at 09:20)"
    elif sc.score == t.score_amber:
        sc.status = "AMBER"
        sc.action = "Half risk or delay — reassess at 09:20"
    else:
        sc.status = "RED"
        sc.action = "No standard trade (score too low)"

    return sc
