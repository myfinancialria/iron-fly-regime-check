"""Assemble the published signal: combine both stages, pick the structure and the
position size, and write ``signal.json`` (which the static site renders)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import config as cfg
from .calendar import now_ist
from .scorecard import Scorecard


# Strike-selection / structure guidance per grade (from the rule book).
STRUCTURES = {
    "STANDARD_ENTRY": {
        "grade": "A",
        "structure": "Standard defined-risk iron fly",
        "legs": "Sell ATM CE + ATM PE; buy OTM CE + OTM PE hedges",
        "hedge_rule": "Hedge width ≈ 0.75–1.00× the ATM straddle premium, rounded to nearest strike",
        "risk_pct": cfg.DEFAULT.sizing.standard_risk_pct,
    },
    "HALF_RISK_ENTRY": {
        "grade": "B",
        "structure": "Half-size ATM iron fly OR 15–20 delta iron condor",
        "legs": "Half quantity ATM iron fly, or sell 15–20Δ CE/PE with OTM hedges",
        "hedge_rule": "Condor variant sacrifices premium to cut immediate gamma",
        "risk_pct": cfg.DEFAULT.sizing.reduced_risk_pct,
    },
    "WAIT_0930": {
        "grade": "C",
        "structure": "No 09:20 entry — reassess at 09:30",
        "legs": "Wait for VWAP re-touch, OR expansion to stop, no fresh 10-min high/low",
        "hedge_rule": "If the 09:30 conditions can't be automated, skip",
        "risk_pct": 0.0,
    },
    "SKIP": {
        "grade": "—",
        "structure": "No trade",
        "legs": "—",
        "hedge_rule": "—",
        "risk_pct": 0.0,
    },
}


@dataclass
class Signal:
    trade_date: str
    generated_at: str
    stage: str                       # "premarket" | "opening"
    premarket: dict | None
    opening: dict | None
    decision: str                    # final human action
    grade: str
    structure: dict | None
    sizing: dict | None

    def to_dict(self) -> dict:
        return {
            "trade_date": self.trade_date,
            "generated_at": self.generated_at,
            "stage": self.stage,
            "premarket": self.premarket,
            "opening": self.opening,
            "decision": self.decision,
            "grade": self.grade,
            "structure": self.structure,
            "sizing": self.sizing,
        }


def _sizing_block(action: str, conf: cfg.Config) -> dict:
    s = conf.sizing
    risk_pct = STRUCTURES.get(action, {}).get("risk_pct", 0.0)
    planned = s.capital * risk_pct / 100.0
    return {
        "capital": s.capital,
        "planned_risk_pct": risk_pct,
        "planned_risk_rupees": round(planned),
        "max_daily_loss_rupees": round(s.max_daily_loss_rupees),
        "lot_size": s.lot_size,
        "note": ("Lots = floor(permitted risk / estimated loss-per-lot at strategy stop). "
                 "Never up-size just because margin is available."),
    }


def build_signal(
    trade_date: date,
    premarket: Scorecard | None,
    opening: Scorecard | None,
    conf: cfg.Config,
) -> Signal:
    if opening is not None:
        action = opening.status
        decision = opening.action
        stage = "opening"
    elif premarket is not None:
        action = premarket.status
        decision = premarket.action
        stage = "premarket"
    else:
        raise ValueError("build_signal needs at least one stage result")

    struct = STRUCTURES.get(action)
    grade = struct["grade"] if struct else "—"
    sizing = _sizing_block(action, conf) if action in ("STANDARD_ENTRY", "HALF_RISK_ENTRY") else None

    return Signal(
        trade_date=trade_date.isoformat(),
        generated_at=now_ist().isoformat(timespec="seconds"),
        stage=stage,
        premarket=premarket.to_dict() if premarket else None,
        opening=opening.to_dict() if opening else None,
        decision=decision,
        grade=grade,
        structure=struct,
        sizing=sizing,
    )


def write_signal(sig: Signal, site_dir: str | Path, data_dir: str | Path) -> Path:
    """Write signal.json into the site dir (for Pages) and archive under data/."""
    site_dir = Path(site_dir)
    data_dir = Path(data_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    payload = sig.to_dict()
    live = site_dir / "signal.json"
    live.write_text(json.dumps(payload, indent=2))
    (data_dir / f"signal_{sig.trade_date}.json").write_text(json.dumps(payload, indent=2))
    return live
