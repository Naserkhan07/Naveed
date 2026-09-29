from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Vote:
    seat: str
    cabin: int
    approve: bool
    score: float
    reason: str
    label: str
    ms: int = 0

    def dict(self) -> dict:
        return {"seat": self.seat, "cabin": self.cabin, "vote": "approve" if self.approve else "reject",
                "score": round(self.score, 3), "reason": self.reason, "label": self.label, "ms": self.ms}


@dataclass
class Ticket:
    id: str
    idx: int
    sym: str
    cls: str
    direction: int
    emitter: str
    conviction: float
    entry: float
    sl: float
    tp: float
    atr: float
    rr: float
    t0: float                      # sim time of signal
    desk: int = -1
    status: str = "spawned"        # spawned, to_desk, seated, review, exec, approved, rejected
    stage: str = "spawn"
    cabin: int = 0
    votes: list[Vote] = field(default_factory=list)
    ceo: dict | None = None
    verdict: str = ""              # ENTRY | EXIT
    verdict_path: str = ""         # unanimous | split->CEO | rejected
    # paper outcome
    paper: str = "pending"         # pending, filled, tp, sl, timeout, unfilled
    t_fill: float | None = None
    r: float | None = None
    resolved_t: float | None = None
    info: dict = field(default_factory=dict)
    kc_idx: list[int] = field(default_factory=list)
    senses: list[float] = field(default_factory=list)
    mb: list[float] = field(default_factory=list)
    regime: str = ""
    features: dict = field(default_factory=dict)
    walker_id: str = ""
    finished: bool = False         # walker has left the floor
    dopamine: float | None = None
    trace: list = field(default_factory=list)

    @property
    def approvals(self) -> int:
        return sum(1 for v in self.votes if v.approve)

    def open_risk(self) -> bool:
        """counts against the pipe cap / correlated-risk gate"""
        if not self.finished:
            return True
        return self.verdict == "ENTRY" and self.paper in ("pending", "filled")

    def card(self) -> dict[str, Any]:
        return {"id": self.id, "sym": self.sym, "cls": self.cls, "dir": "LONG" if self.direction > 0 else "SHORT",
                "emitter": self.emitter, "conviction": round(self.conviction, 3), "entry": self.entry, "sl": self.sl,
                "tp": self.tp, "rr": round(self.rr, 2), "desk": self.desk, "status": self.status, "stage": self.stage,
                "cabin": self.cabin, "approvals": self.approvals, "votes": [v.dict() for v in self.votes], "ceo": self.ceo,
                "verdict": self.verdict, "path": self.verdict_path, "paper": self.paper, "r": None if self.r is None else round(self.r, 3),
                "t0": round(self.t0, 1), "info": self.info, "regime": self.regime, "dopamine": self.dopamine,
                "features": self.features}
