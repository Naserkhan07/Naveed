"""Test doubles: a fake screen, a fake model and a fake clock.

The agent loop is the part of Naveed that is hardest to trust and easiest to get
wrong (stale frames, dead clicks, infinite retries), so it is tested without a
real desktop: :class:`FakeFrame` paints real pixels with Pillow, :class:`FakeWatcher`
serves them and can be told to "change the screen" after an action, and
:class:`ScriptedPlanner` replays a fixed list of JSON replies.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from naveed.control.actions import ActionPlan, normalize_plan
from naveed.screen.diff import frame_hash, to_signature
from naveed.screen.displays import Monitor


@dataclass
class FakeFrame:
    """Stand-in for :class:`naveed.screen.capture.Frame` with real pixels."""

    image: Any
    width: int
    height: int
    monitor: Monitor
    via: str = "fake"
    captured_at: float = field(default_factory=time.time)
    saved_path: str = ""

    @property
    def size(self):
        return (self.width, self.height)

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.captured_at)

    def png_bytes(self) -> bytes:
        import io

        stream = io.BytesIO()
        self.image.save(stream, format="PNG")
        return stream.getvalue()

    def signature(self) -> bytes:
        return to_signature(self.image)

    def frame_hash(self) -> str:
        return frame_hash(self.signature())


def make_frame(seed: int = 0, *, width: int = 640, height: int = 360, monitor: Optional[Monitor] = None) -> FakeFrame:
    """A deterministic, visibly different image per *seed*.

    Real pixel data matters: the diff logic under test compares actual signatures,
    so a mock with a fake hash would not exercise it.
    """
    from naveed.render.pillow_canvas import PillowCanvas

    monitor = monitor or Monitor(index=0, x=0, y=0, width=width, height=height, scale=1.0, name="fake", is_primary=True)
    canvas = PillowCanvas(width, height, background="#101018")
    for row in range(4):
        for column in range(6):
            shade = (seed * 37 + row * 11 + column * 7) % 200
            canvas.rect(
                column * (width / 6) + 4,
                row * (height / 4) + 4,
                width / 6 - 8,
                height / 4 - 8,
                radius=6,
                fill=(40 + shade, 80 + (shade * 3) % 150, 200 - shade // 2, 255),
            )
    canvas.text(12, 12, f"frame {seed}", size=22, color="#FFFFFF", weight="bold")
    if seed % 3 == 1:
        canvas.circle(width - 40, 40, 18, fill="#FF5A5F")  # a "button"
    return FakeFrame(image=canvas.image, width=width, height=height, monitor=monitor)


class FakeWatcher:
    """A watcher whose screen changes only when a test says so."""

    def __init__(self, *, frames: Optional[Sequence[int]] = None, auto_change: bool = False) -> None:
        self._seeds = list(frames or [0, 0, 0])
        self._index = 0
        self.auto_change = auto_change
        self.paused = 0
        self.snapshots = 0
        self._monitors = [Monitor(index=0, x=0, y=0, width=640, height=360, scale=1.0, name="fake", is_primary=True)]
        self.capture = self  # OsController calls watcher.capture.invalidate()

    # --- test control ---------------------------------------------------
    def next_frame(self, seed: int) -> None:
        self._seeds.append(seed)

    def invalidate(self) -> None:
        return None

    # --- watcher surface ------------------------------------------------
    @property
    def current(self) -> FakeFrame:
        seed = self._seeds[min(self._index, len(self._seeds) - 1)]
        return make_frame(seed, width=self._monitors[0].width, height=self._monitors[0].height, monitor=self._monitors[0])

    def _advance(self) -> None:
        if self.auto_change:
            # A busy screen: every capture is a genuinely different image.
            self._seeds.append(self._seeds[-1] + 1)
        if self._index < len(self._seeds) - 1:
            self._index = min(self._index + 1, len(self._seeds) - 1)

    def snapshot(self, *, fresh: bool = True, save: bool = False) -> FakeFrame:
        self.snapshots += 1
        frame = self.current
        self._advance()
        return frame

    def pause(self) -> None:
        self.paused += 1

    def resume(self) -> None:
        self.paused = max(0, self.paused - 1)

    def wait_until_settled(self, *, timeout: float = 4.0, required_stable: int = 2, poll: float = 0.1) -> bool:
        return True

    def world_summary(self, *, lines: int = 6) -> str:
        return "  10:00:00 fake.exe, changed 12%\n* 10:00:02 fake.exe, screen changed completely (55%)"


class ScriptedPlanner:
    """Planner double that replays scripted JSON replies in order."""

    class _Client:
        def __init__(self, outer: "ScriptedPlanner") -> None:
            self.outer = outer

        @property
        def configured(self) -> bool:
            return True

        def chat(self, messages, **kwargs):
            raise AssertionError("ScriptedPlanner should be used through plan()")

    def __init__(self, replies: Sequence[Any]) -> None:
        self.replies = list(replies)
        self.calls: List[Dict[str, Any]] = []
        self.client = ScriptedPlanner._Client(self)
        self.prompts: List[str] = []

    def plan(self, task: str, **kwargs) -> ActionPlan:
        self.calls.append({"task": task, **{k: v for k, v in kwargs.items() if k != "frame"}})
        reply = self.replies.pop(0) if self.replies else {"done": True, "summary": "finished"}
        if isinstance(reply, ActionPlan):
            return reply
        payload = reply
        if isinstance(payload, str):
            payload = {"actions": [payload]}
        elif isinstance(payload, dict) and "actions" in payload and isinstance(payload["actions"], list):
            payload = {"actions": payload["actions"], "summary": payload.get("summary", ""), "done": payload.get("done", False), "question": payload.get("question", "")}
        plan = normalize_plan(payload, limit=4)
        if not plan.actions and not plan.done:
            plan.actions = [normalize_plan([{"type": "done", "summary": plan.summary or "done"}]).actions[0]]
        return plan

    def describe_screen(self, question: str = "", **kwargs) -> str:
        return f"scripted answer to {question!r}"
