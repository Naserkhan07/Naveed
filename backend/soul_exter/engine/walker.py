from __future__ import annotations

import math
import random


def _ang_lerp(a: float, b: float, t: float) -> float:
    d = (b - a + math.pi) % (2 * math.pi) - math.pi
    return a + d * t


class Walker:
    """A person on the NavGrid.  heading = atan2(dx, dz) (three.js rotation.y for a +z-facing model)."""

    def __init__(self, wid: str, kind: str, label: str, x: float, z: float, color: str, rng: random.Random):
        self.id, self.kind, self.label, self.color = wid, kind, label, color
        self.x, self.z = x, z
        self.h = math.pi
        self.speed = rng.uniform(1.35, 1.75)
        self.path: list[tuple[float, float]] = []
        self.pi = 0
        self.sitting = False
        self.stage = "idle"
        self.timer = 0.0
        self.ticket = None
        self.gone = False
        self.fade = 0.0
        self.data: dict = {}
        self.walked = 0.0

    @property
    def moving(self) -> bool:
        return self.pi < len(self.path)

    def route(self, pts: list[tuple[float, float]]):
        self.path = [p for p in pts]
        if self.path and math.dist(self.path[0], (self.x, self.z)) < 0.05:
            self.path = self.path[1:]
        self.pi = 0

    def step(self, dt: float) -> bool:
        """advance along the path; True when the path was completed during this step"""
        if not self.moving:
            self.h = _ang_lerp(self.h, self.data.get("face", self.h), min(1.0, dt * 4)) if self.sitting else self.h
            return False
        left = self.speed * dt
        while left > 1e-9 and self.pi < len(self.path):
            tx, tz = self.path[self.pi]
            dx, dz = tx - self.x, tz - self.z
            d = math.hypot(dx, dz)
            if d <= left:
                self.x, self.z = tx, tz
                left -= d
                self.walked += d
                self.pi += 1
            else:
                self.x += dx / d * left
                self.z += dz / d * left
                self.walked += left
                left = 0
            if d > 1e-6:
                self.h = _ang_lerp(self.h, math.atan2(dx, dz), min(1.0, 0.35 + dt * 3))
        return not self.moving

    def pose(self) -> dict:
        return {"id": self.id, "x": round(self.x, 2), "z": round(self.z, 2), "h": round(self.h, 2), "sit": self.sitting,
                "l": self.label, "c": self.color, "k": self.kind, "st": self.stage, "gone": self.gone}
