"""Shared scorecard primitives used by both stages."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Condition:
    """One scored line item on a scorecard."""
    name: str
    passed: bool | None       # True=point earned, False=not, None=couldn't evaluate
    detail: str               # human-readable value + verdict
    color: str = "neutral"    # green | amber | red | neutral

    @property
    def point(self) -> int:
        return 1 if self.passed else 0


@dataclass
class Scorecard:
    stage: str                            # "premarket" | "opening"
    conditions: list[Condition] = field(default_factory=list)
    hard_red: list[str] = field(default_factory=list)   # any hard-red trigger reasons
    status: str = ""                      # GREEN/AMBER/RED  or  the 09:20 action
    action: str = ""                      # human-readable next action
    score: int = 0
    max_score: int = 0
    notes: list[str] = field(default_factory=list)

    def add(self, cond: Condition) -> None:
        self.conditions.append(cond)

    def finalize_score(self) -> None:
        self.score = sum(c.point for c in self.conditions)
        self.max_score = len(self.conditions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "action": self.action,
            "score": self.score,
            "max_score": self.max_score,
            "hard_red": self.hard_red,
            "conditions": [asdict(c) for c in self.conditions],
            "notes": self.notes,
        }
