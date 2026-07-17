"""Stage 2 — 09:20 confirmation (run right after the 09:15–09:20 candle closes).

Consumes actual market data (never the pre-market indication). Output is one of:
STANDARD_ENTRY / HALF_RISK_ENTRY / WAIT_0930 / SKIP. Any hard-red condition forces
SKIP regardless of score. Combined with the Stage-1 status via the operating matrix.
"""
from __future__ import annotations

from . import config as cfg
from .data import OpeningData
from .scorecard import Condition, Scorecard


def score_opening(d: OpeningData, premarket_status: str, conf: cfg.Config) -> Scorecard:
    t = conf.opening
    sc = Scorecard(stage="opening")

    strong_breakout = _strong_breakout(d)
    strong_align = _strong_alignment(d, t)

    # ---------------- Hard-red overrides ----------------
    if d.actual_gap_pct > t.gap_hard_red:
        sc.hard_red.append(f"Actual gap {d.actual_gap_pct:.2f}% > {t.gap_hard_red:.2f}%")
    if d.or5_ratio is not None and d.or5_ratio > t.or5_hard_red:
        sc.hard_red.append(f"OR5 ratio {d.or5_ratio:.2f} > {t.or5_hard_red:.2f}")
    if d.body_ratio is not None and d.body_ratio > t.body_hard_red:
        sc.hard_red.append(f"Candle body {d.body_ratio:.2f} > {t.body_hard_red:.2f}")
    if strong_breakout:
        sc.hard_red.append("Prev-day high/low break with broad-market confirmation")
    if strong_align:
        sc.hard_red.append("NIFTY & BANKNIFTY strong same-direction move")
    if d.vix_change_pct is not None and d.vix_change_pct > t.vix_intraday_hard_red_change:
        sc.hard_red.append(f"India VIX +{d.vix_change_pct:.1f}% intraday")

    # ---------------- Scored conditions (8) ----------------
    # 1. Actual gap below 0.35%
    g = d.actual_gap_pct
    passed = g < t.gap_pass_below
    color = "green" if passed else ("amber" if g < t.gap_caution_below else "red")
    sc.add(Condition("Actual gap < 0.35%", passed, f"{g:.2f}%", color))

    # 2. OR5 ratio between 0.10 and 0.30
    if d.or5_ratio is None:
        sc.add(Condition("OR5 ratio 0.10–0.30", None, "ATR unavailable", "neutral"))
    else:
        r = d.or5_ratio
        passed = t.or5_compressed_below <= r <= t.or5_pass_below
        if r < t.or5_compressed_below:
            color = "amber"  # too compressed -> delay
        elif passed:
            color = "green"
        elif r <= t.or5_reduced_below:
            color = "amber"
        else:
            color = "red"
        sc.add(Condition("OR5 ratio 0.10–0.30", passed,
                         f"{r:.2f} (OR5 {d.or5.high - d.or5.low:.0f} pt)", color))

    # 3. Candle body ratio below 0.45
    if d.body_ratio is None:
        sc.add(Condition("Candle body < 0.45", None, "no candle range", "neutral"))
    else:
        b = d.body_ratio
        passed = b < t.body_pass_below
        color = "green" if passed else ("amber" if b < t.body_reduced_below else "red")
        sc.add(Condition("Candle body < 0.45", passed, f"{b:.2f}", color))

    # 4. Candle close between 25% and 75% of range
    if d.close_location is None:
        sc.add(Condition("Close 25–75% of range", None, "no candle range", "neutral"))
    else:
        cl = d.close_location
        passed = t.close_loc_low <= cl <= t.close_loc_high
        extreme = cl < t.close_loc_extreme_low or cl > t.close_loc_extreme_high
        color = "green" if passed else ("red" if extreme else "amber")
        sc.add(Condition("Close 25–75% of range", passed, f"{cl:.2f}", color))

    # 5. VWAP distance below 0.10%
    if d.vwap_distance_pct is None:
        sc.add(Condition("VWAP distance < 0.10%", None, "VWAP unavailable", "neutral"))
    else:
        v = d.vwap_distance_pct
        passed = v < t.vwap_pass_below
        color = "green" if passed else ("amber" if v < t.vwap_caution_below else "red")
        sc.add(Condition("VWAP distance < 0.10%", passed, f"{v:.3f}%", color))

    # 6. Price inside previous-day range
    inside = not (d.still_above_prev_high or d.still_below_prev_low)
    where = ("above prev high" if d.still_above_prev_high else
             "below prev low" if d.still_below_prev_low else "inside prev range")
    sc.add(Condition("Price inside prev-day range", inside, where,
                     "green" if inside else "red"))

    # 7. No strong NIFTY–BANKNIFTY alignment
    passed = not strong_align
    nr = f"{d.nifty_ret_pct:+.2f}%" if d.nifty_ret_pct is not None else "n/a"
    br = f"{d.banknifty_ret_pct:+.2f}%" if d.banknifty_ret_pct is not None else "n/a"
    sc.add(Condition("No strong NIFTY–BANKNIFTY alignment", passed,
                     f"NIFTY {nr}, BANKNIFTY {br}", "green" if passed else "red"))

    # 8. Breadth between 18 and 32
    if d.breadth_advancing is None or d.breadth_total is None:
        sc.add(Condition("Breadth 18–32 advancing", None, d.note or "breadth unavailable", "neutral"))
        if d.note:
            sc.notes.append(d.note)
    else:
        a, tot = d.breadth_advancing, d.breadth_total
        passed = t.breadth_balanced_low <= a <= t.breadth_balanced_high
        strong = a > t.breadth_strong_high or a < t.breadth_strong_low
        color = "green" if passed else ("red" if strong else "amber")
        sc.add(Condition("Breadth 18–32 advancing", passed, f"{a}/{tot} advancing", color))

    sc.finalize_score()

    # ---------------- Decision resolution (operating matrix) ----------------
    if premarket_status == "RED" or sc.hard_red:
        sc.status = "SKIP"
        reason = "; ".join(sc.hard_red) if sc.hard_red else "pre-market status RED"
        sc.action = f"Skip the day — {reason}"
        return sc

    score = sc.score
    if premarket_status == "GREEN":
        if score >= t.score_standard_min:
            sc.status, sc.action = "STANDARD_ENTRY", "Enter standard-risk iron fly"
        elif score == t.score_half:
            sc.status, sc.action = "HALF_RISK_ENTRY", "Enter half-risk structure"
        elif score >= t.score_wait_min:
            sc.status, sc.action = "WAIT_0930", "Do not enter at 09:20 — reassess at 09:30"
        else:
            sc.status, sc.action = "SKIP", "Skip the day (09:20 score too low)"
    elif premarket_status == "AMBER":
        # Amber pre-market caps the day at half risk.
        if score >= t.score_standard_min:
            sc.status, sc.action = "HALF_RISK_ENTRY", "Amber pre-market → half risk despite strong 09:20"
        else:
            sc.status, sc.action = "SKIP", "Amber pre-market and 09:20 not strong → wait/skip"
    else:
        sc.status, sc.action = "SKIP", "Skip the day"

    return sc


def _strong_alignment(d: OpeningData, t: cfg.OpeningThresholds) -> bool:
    if d.nifty_ret_pct is None or d.banknifty_ret_pct is None:
        return False
    n, b = d.nifty_ret_pct, d.banknifty_ret_pct
    up = n > t.nifty_align and b > t.banknifty_align
    down = n < -t.nifty_align and b < -t.banknifty_align
    return up or down


def _strong_breakout(d: OpeningData) -> bool:
    """Opens beyond prev high/low, still there at 09:20, breakout candle closes
    near its extreme, and BANKNIFTY confirms the direction."""
    if d.close_location is None:
        return False
    up_break = d.open_above_prev_high and d.still_above_prev_high and d.close_location > 0.85
    dn_break = d.open_below_prev_low and d.still_below_prev_low and d.close_location < 0.15
    bn = d.banknifty_ret_pct
    if up_break and (bn is None or bn > 0):
        return True
    if dn_break and (bn is None or bn < 0):
        return True
    return False
