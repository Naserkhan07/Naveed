"""The watcher: Naveed sitting quietly and *seeing* the screen.

This is the loop the whole product is built around.  Its cadence rules come from
**OpenDesktop** (https://github.com/atum246/OpenDesktop, MIT) —
``src/screen-state/index.js``: capture on an interval, reduce the frame, compare
it with the last one, and only record a new state when the difference clears the
threshold.  Everything Naveed adds exists to make that loop survivable on a real
desktop while a human keeps working:

* **Adaptive cadence.**  When nothing changes for a few frames the interval
  stretches out (2s -> 6s by default), and the moment something moves it snaps
  back.  Watching costs almost nothing while you read.
* **Pause during actions.**  The agent calls :meth:`ScreenWatcher.pause` while it
  drives the mouse and keyboard, otherwise every one of its own clicks would
  register as a change and the world model would fill with its own noise.
* **Settle detection.**  :meth:`wait_until_settled` is what turns "I clicked"
  into "the screen stopped moving, here is what appeared" — the single most
  useful signal a computer-use loop can have.
* **Disk discipline.**  Only *changed* frames are written, through
  :class:`~naveed.screen.retention.ScreenshotStore`, which prunes itself.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .capture import CaptureError, CaptureService, Frame
from .diff import ChangeDetector, ChangeReport
from .displays import Monitor, monitors_or_default, primary_monitor
from .focus import active_window
from .retention import ScreenshotStore
from .state import ScreenState, ScreenStateGraph, summarize_state

__all__ = ["ScreenWatcher", "WatcherStats"]

logger = logging.getLogger("naveed.watch")


class WatcherStats:
    """Lightweight counters the control panel and ``--check`` read out."""

    def __init__(self) -> None:
        self.frames = 0
        self.changes = 0
        self.scenes = 0
        self.errors = 0
        self.saved = 0
        self.started_at = time.time()
        self.last_frame_at = 0.0
        self.last_error = ""

    @property
    def uptime(self) -> float:
        return max(0.0, time.time() - self.started_at)

    @property
    def idle_seconds(self) -> float:
        return max(0.0, time.time() - self.last_frame_at) if self.last_frame_at else 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "frames": self.frames,
            "changes": self.changes,
            "scenes": self.scenes,
            "errors": self.errors,
            "saved": self.saved,
            "uptime": round(self.uptime, 1),
            "last_error": self.last_error,
        }


class ScreenWatcher:
    """Background screen watcher with a bounded world model.

    Listener callbacks are invoked on the watcher thread: keep them short, or
    hand off to a queue (the Qt overlay does exactly that through signals).
    """

    def __init__(
        self,
        *,
        capture: Optional[CaptureService] = None,
        store: Optional[ScreenshotStore] = None,
        interval: float = 2.0,
        idle_interval: float = 6.0,
        settle_after: int = 3,
        max_history: int = 100,
        save_frames: bool = True,
        target: str = "active_window",
        detector: Optional[ChangeDetector] = None,
        on_state: Optional[Callable[[ScreenState], None]] = None,
        on_frame: Optional[Callable[[Frame, ScreenState], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        self.interval = max(0.25, float(interval))
        self.idle_interval = max(self.interval, float(idle_interval))
        self.settle_after = max(1, int(settle_after))
        self.save_frames = bool(save_frames)
        self.target = target  # "active_window" | "primary" | "all"
        self.store = store
        self.capture = capture or CaptureService(store=store)
        self.detector = detector or ChangeDetector(settle_frames=self.settle_after)
        self.graph = ScreenStateGraph(max_history=max_history)
        self.stats = WatcherStats()

        self.on_state = on_state
        self.on_frame = on_frame
        self.on_error = on_error

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._capture_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._latest: Optional[ScreenState] = None
        self._latest_frame: Optional[Frame] = None
        self._monitors: List[Monitor] = []

    # --- lifecycle ----------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def start(self) -> "ScreenWatcher":
        if self.running:
            return self
        self._monitors = list(monitors_or_default())
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="naveed-watch", daemon=True)
        self._thread.start()
        logger.info("screen watcher started (every %.1fs, idle %.1fs)", self.interval, self.idle_interval)
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._thread = None

    def pause(self) -> None:
        """Stop recording while the agent drives the machine."""
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def __enter__(self) -> "ScreenWatcher":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    # --- loop ---------------------------------------------------------
    def _loop(self) -> None:
        delay = self.interval
        while not self._stop.is_set():
            started = time.time()
            if self._paused.is_set():
                self._stop.wait(0.25)
                continue
            try:
                report, state = self.tick()
                delay = self.interval if report.changed else self.idle_interval
            except Exception as error:  # never let the watcher die on one bad frame
                self.stats.errors += 1
                self.stats.last_error = f"{type(error).__name__}: {error}"
                logger.debug("watcher tick failed: %s", self.stats.last_error)
                if self.on_error is not None:
                    try:
                        self.on_error(error)
                    except Exception:
                        logger.debug("watcher on_error listener raised", exc_info=True)
                delay = min(self.idle_interval, self.interval * 3)
            elapsed = time.time() - started
            self._stop.wait(max(0.05, delay - elapsed))

    def tick(self, *, save: Optional[bool] = None, fresh: bool = False) -> tuple:
        """Capture once, update the world model, and return ``(report, state)``."""
        with self._capture_lock:
            frame = self._grab(fresh=fresh)
            signature = frame.signature()
            report = self.detector.observe(signature)
            window = active_window()
            state = self._build_state(frame, report, window)

            if (save if save is not None else self.save_frames) and report.changed and self.store is not None:
                try:
                    with self._capture_lock:
                        state.path = self.store.save_bytes(frame.png_bytes())
                    self.stats.saved += 1
                except Exception:
                    logger.debug("could not save capture", exc_info=True)

            with self._state_lock:
                self.graph.record(state)
                self._latest = state
                self._latest_frame = frame
            self.stats.frames += 1
            if report.changed:
                self.stats.changes += 1
            if report.scene:
                self.stats.scenes += 1

        if self.on_state is not None:
            try:
                self.on_state(state)
            except Exception:
                logger.debug("watcher on_state listener raised", exc_info=True)
        if self.on_frame is not None:
            try:
                self.on_frame(frame, state)
            except Exception:
                logger.debug("watcher on_frame listener raised", exc_info=True)
        return report, state

    def _grab(self, *, fresh: bool = False) -> Frame:
        """Capture according to ``target`` (active window's monitor by default)."""
        if self.target == "all":
            return self.capture.capture(monitor=None, fresh=fresh)
        if self.target == "primary":
            return self.capture.capture(primary_monitor(self._monitors or monitors_or_default()), fresh=fresh)
        return self.capture.capture_for_window(active_window(), monitors=self._monitors or None, fresh=fresh)

    def _build_state(self, frame: Frame, report: ChangeReport, window: Any) -> ScreenState:
        state = ScreenState(
            monitor=frame.monitor.as_dict() if frame.monitor else None,
            window=window.as_dict() if window is not None else None,
            width=frame.width,
            height=frame.height,
            frame_hash=report.frame_hash,
            changed=report.changed,
            scene=report.scene,
            first_frame=report.first_frame,
            diff_ratio=report.ratio,
            by=frame.via,
        )
        state.summary = summarize_state(state)
        return state

    # --- inspection ---------------------------------------------------
    @property
    def latest(self) -> Optional[ScreenState]:
        with self._state_lock:
            return self._latest

    @property
    def latest_frame(self) -> Optional[Frame]:
        with self._state_lock:
            return self._latest_frame

    def snapshot(self, *, fresh: bool = True, save: bool = False) -> Frame:
        """Force a capture right now (used by the agent before planning a step)."""
        with self._capture_lock:
            return self.capture.capture(fresh=fresh, save=save)

    def wait_until_settled(
        self,
        *,
        timeout: float = 6.0,
        required_stable: int = 2,
        poll: float = 0.35,
    ) -> bool:
        """Block until the screen stops changing.

        Returns ``True`` when it settled, ``False`` on timeout.  This is the
        "did my action work?" primitive: after a click, the screen either moves
        (something happened) or it does not (nothing happened).
        """
        deadline = time.time() + max(0.1, timeout)
        detector = ChangeDetector(noise_floor=self.detector.noise_floor, settle_frames=required_stable)
        stable = 0
        while time.time() < deadline:
            try:
                with self._capture_lock:
                    frame = self.capture.capture(fresh=True)
                report = detector.observe(frame.signature())
            except CaptureError:
                return False
            stable = report.stable_frames if not report.changed else 0
            if stable >= required_stable:
                return True
            time.sleep(max(0.05, poll))
        return False

    def wait_for_change(self, *, timeout: float = 5.0, poll: float = 0.25, threshold: Optional[float] = None) -> Optional[ScreenState]:
        """Block until something *does* change, returning the new state."""
        deadline = time.time() + max(0.1, timeout)
        floor = self.detector.noise_floor if threshold is None else threshold
        while time.time() < deadline:
            time.sleep(max(0.05, poll))
            state = self.latest
            if state is not None and state.changed and state.diff_ratio >= floor:
                return state
        return None

    # --- summaries ----------------------------------------------------
    def world_summary(self, *, lines: int = 6) -> str:
        """Multi-line, prompt-ready view of the world model."""
        with self._state_lock:
            history = self.graph.describe(lines)
            stats = self.graph.stats()
        header = (
            f"watching {self.target}: {stats['frames']} frames, {stats['changed']} changes, "
            f"{stats['scenes']} scene switches"
        )
        hint = ""
        if stats.get("oscillating"):
            hint = "\n  ! the screen is flicking between the same two frames — the last action probably did nothing"
        return f"{header}\n{history}{hint}"

    def state_line(self) -> str:
        """One-line status for the panel's status card."""
        latest = self.latest
        if latest is None:
            return "starting up…"
        if latest.first_frame:
            what = "first look"
        elif latest.scene:
            what = "screen changed completely"
        elif latest.changed:
            what = f"changed {latest.percent}%"
        else:
            what = "quiet"
        return f"{latest.app} · {what}"

    def stats_payload(self) -> Dict[str, Any]:
        with self._state_lock:
            graph_stats = self.graph.stats()
        return {
            "watcher": self.stats.as_dict(),
            "graph": graph_stats,
            "capture": self.capture.stats(),
            "paused": self.paused,
            "running": self.running,
        }
