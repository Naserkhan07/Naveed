"""The thread-safe meeting point between the UI, the screen and the agent.

A desktop companion has a structural problem: the mascot must animate
continuously on the GUI thread, while watching the screen and driving the mouse
block for seconds at a time.  Everything in this project therefore runs on
worker threads and reports back through plain callbacks, and this bridge is the
one object that owns that boundary.

It is deliberately free of Qt: it publishes events by calling whatever callbacks
it was given, and :mod:`naveed.overlay.bridge` forwards them to Qt signals (which
is what makes them safe to touch widgets from).  That split is also why the whole
agent can be tested headlessly.

Responsibilities
----------------
* own the :class:`~naveed.screen.watch.ScreenWatcher` and the
  :class:`~naveed.agent.executor.NaveedAgent`;
* run one task at a time on a worker thread, with a queue of pending requests;
* translate the agent's callbacks into the panel's vocabulary (status, speech,
  action log, questions) and the mascot's expressions;
* keep the mascot out of its own screenshots (the capture service is wired to
  hide the overlay) and make it click-through while the agent clicks;
* expose the quick actions the panel's shortcut grid and tray menu call.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..config import Config, write_env_file
from ..control.os_control import ActionResult, OsController
from ..control.safety import SafetyGuard
from ..screen.capture import CaptureError, CaptureService
from ..screen.focus import active_window
from ..screen.retention import ScreenshotStore
from ..screen.watch import ScreenWatcher
from .executor import NaveedAgent, Task, TaskStatus

logger = logging.getLogger("naveed.bridge")

__all__ = ["AgentBridge", "BridgeEvents", "QUICK_ACTIONS"]


@dataclass
class BridgeEvents:
    """Callbacks the UI implements.  Every one is optional."""

    on_status: Optional[Callable[[str, str], None]] = None      # state, detail
    on_say: Optional[Callable[[str], None]] = None              # text to speak/show
    on_action: Optional[Callable[[ActionResult], None]] = None  # action log entry
    on_question: Optional[Callable[[str], None]] = None         # agent needs the user
    on_task: Optional[Callable[[Task], None]] = None            # task started/finished
    on_state: Optional[Callable[[Dict[str, Any]], None]] = None  # panel status snapshot
    on_error: Optional[Callable[[str], None]] = None


#: The shortcut grid and the tray menu.  ``__action__`` entries are handled
#: directly by the bridge; everything else is sent to the agent as a task prompt.
QUICK_ACTIONS: Dict[str, str] = {
    "look": "What is on my screen right now? Describe it briefly.",
    "summarise": "Summarise what is on my screen in two sentences.",
    "explain_error": "Look at my screen. If there is an error, explain it and tell me how to fix it.",
    "screenshot": "__screenshot__",
    "write": "Write the reply or text that is needed on screen right now, using my screen as context, and put it in the right place.",
    "clean_up": "Tidy up my desktop: close the windows and tabs that are clearly not needed, and leave my work untouched.",
    "translate": "Translate the main text visible on my screen into English.",
    "automate": "Look at what I am doing on screen and do the repetitive part of it for me.",
    "summarise_actions": "__stats__",
}


class AgentBridge:
    """Owns the agent, the watcher and the worker threads."""

    def __init__(
        self,
        config: Config,
        *,
        events: Optional[BridgeEvents] = None,
        hide_overlay: Optional[Callable[[], None]] = None,
        show_overlay: Optional[Callable[[], None]] = None,
        click_through: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self.config = config
        self.events = events or BridgeEvents()
        self._hide_overlay = hide_overlay
        self._show_overlay = show_overlay
        self._click_through = click_through

        self.store = ScreenshotStore(str(config.screenshots_dir), max_captures=config.capture.max_captures)
        self.capture = CaptureService(
            store=self.store,
            hide_overlay=hide_overlay,
            show_overlay=show_overlay,
        )
        self.watcher = ScreenWatcher(
            capture=self.capture,
            store=self.store,
            interval=config.capture.interval,
            idle_interval=config.capture.idle_interval,
            settle_after=config.capture.settle_after,
            max_history=config.capture.max_history,
            save_frames=config.capture.save_frames,
            target=config.capture.target,
        )
        self.safety = SafetyGuard(
            config.safety,
            confirm=self._confirm_from_ui,
            announce=self._announce,
        )
        self.controller = OsController(
            config,
            watcher=self.watcher,
            guard=self.safety,
            before_pointer=lambda: self._set_click_through(True),
            after_pointer=lambda: self._set_click_through(False),
        )
        self.agent = NaveedAgent(
            config,
            watcher=self.watcher,
            controller=self.controller,
            on_status=self._on_status,
            on_say=self._on_say,
            on_action=self._on_action,
            on_question=self._on_question,
            on_finish=self._on_finish,
            on_step=self._on_step,
        )

        self._pending: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._confirmations: Dict[str, threading.Event] = {}
        self._running_task = False
        self.last_task: Optional[Task] = None
        #: why the last task never finished (the headless modes have nowhere else
        #: to say it: without this, a crashed worker looked like "no task ran")
        self.last_error: str = ""
        self.started_at = time.time()

    # --- lifecycle ------------------------------------------------------
    def start(self) -> "AgentBridge":
        """Start watching the screen and the task worker."""
        self.watcher.start()
        if self._worker is None or not self._worker.is_alive():
            self._stop.clear()
            self._worker = threading.Thread(target=self._work, name="naveed-agent", daemon=True)
            self._worker.start()
        self._publish_state()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._pending.put(None)
        self.agent.cancel()
        self.watcher.stop()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=3.0)
        self._worker = None

    # --- public API ------------------------------------------------------
    @property
    def busy(self) -> bool:
        """True from the moment a task is accepted until its worker is done.

        The queued-but-not-yet-started case matters: `submit()` returns before the
        worker has picked the item up, so a caller that waits on `busy` used to
        see False straight away and give up — which is how `-p "..."` reported
        "no task ran" while the task was in fact still running.
        """
        return self._running_task or self.agent.busy or not self._pending.empty()

    @property
    def model_ready(self) -> bool:
        return self.config.llm.configured

    def submit(self, prompt: str, *, extra_context: str = "") -> bool:
        """Queue a task (starting the worker if needed). Returns False if busy."""
        prompt = (prompt or "").strip()
        if not prompt:
            return False
        if prompt == "__screenshot__":
            self.quick_screenshot()
            return True
        if prompt == "__stats__":
            self._publish_state()
            return True
        if self.busy:
            self.say("I am still working on the last thing — press Stop if you want me to drop it.")
            return False
        self.last_error = ""
        self._ensure_worker()
        # Marked before the queue, not by the worker: the caller may check `busy`
        # the instant submit() returns.
        self._running_task = True
        self._pending.put((prompt, extra_context))
        return True

    def cancel(self) -> None:
        """Stop the current task (the panel's Stop button)."""
        self.agent.cancel()
        self._on_status("idle", "stopped")

    def answer(self, text: str) -> None:
        """Answer the question the agent asked."""
        self.agent.provide_answer(text)

    def quick_screenshot(self) -> Optional[str]:
        """Take a screenshot without the model, and report where it went."""
        path = self.agent.quick_capture()
        if path:
            self.say("Screenshot saved.")
            self._emit("on_action", ActionResult(ok=True, action=_pseudo_action("screenshot"), message=path))
        else:
            self.say("I could not take a screenshot just now.")
        return path

    def run_quick(self, key: str) -> bool:
        """Run one of :data:`QUICK_ACTIONS` by key."""
        prompt = QUICK_ACTIONS.get(key)
        if not prompt:
            return False
        return self.submit(prompt)

    # --- question / confirmation plumbing ---------------------------------
    def _on_question(self, question: str) -> None:
        self._emit("on_question", question)
        self._emit("on_state", {"question": question})

    def _confirm_from_ui(self, prompt: str, timeout: float) -> bool:
        """Ask the user to confirm a destructive action."""
        if not self.config.safety.confirm_destructive:
            return True
        token = f"confirm-{int(time.time() * 1000)}"
        event = threading.Event()
        self._confirmations[token] = event
        self._emit("on_state", {"confirm": {"token": token, "prompt": prompt, "timeout": timeout}})
        self.say(prompt)
        approved = event.wait(timeout=max(1.0, float(timeout)))
        self._confirmations.pop(token, None)
        self._emit("on_state", {"confirm": None})
        return bool(approved and self.safety.__dict__.get("_last_answer_yes", True))

    def resolve_confirmation(self, token: str, approved: bool) -> None:
        """Called by the panel when the user presses Allow or Deny."""
        self.safety.__dict__["_last_answer_yes"] = bool(approved)
        event = self._confirmations.get(token)
        if event is not None:
            event.set()

    def _announce(self, message: str) -> None:
        self.say(message)

    # --- agent callbacks ---------------------------------------------------
    def _on_status(self, state: str, detail: str = "") -> None:
        self._emit("on_status", state, detail)
        self._emit("on_state", {"agent_state": state, "detail": detail})

    def _on_say(self, text: str) -> None:
        if not text:
            return
        self.say(text)

    def say(self, text: str) -> None:
        """Show *text* in the panel and speak it (the UI decides how)."""
        self._emit("on_say", text)

    def _on_action(self, result: ActionResult) -> None:
        self._emit("on_action", result)
        self._publish_state()

    def _on_step(self, step: Dict[str, Any]) -> None:
        self._publish_state({"last_step": step})

    def _on_finish(self, task: Task) -> None:
        self.last_task = task
        self._emit("on_task", task)
        if task.status is TaskStatus.DONE:
            self._emit("on_state", {"mascot_state": "success"})
        elif task.status is TaskStatus.FAILED:
            self._emit("on_state", {"mascot_state": "error"})
        else:
            self._emit("on_state", {"mascot_state": "idle"})
        self._publish_state()

    # --- worker ------------------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._stop.clear()
            self._worker = threading.Thread(target=self._work, name="naveed-agent", daemon=True)
            self._worker.start()

    def _work(self) -> None:
        while not self._stop.is_set():
            item = self._pending.get()
            try:
                if item is None:
                    return
                prompt, extra_context = item
                self._running_task = True
                self._emit("on_state", {"mascot_state": "thinking", "task": prompt})
                task = self.agent.run(prompt, extra_context=extra_context)
                if task.status is TaskStatus.DONE:
                    logger.info("task done in %.1fs: %s", task.duration, task.result)
            except Exception as error:
                logger.exception("task worker failed")
                self.last_error = f"{type(error).__name__}: {error}"
                self._emit("on_error", self.last_error)
            finally:
                self._running_task = False
                self._publish_state()

    # --- status snapshot ----------------------------------------------------
    # --- learned routines ------------------------------------------------
    def run_recipe(self, recipe: Any, arguments: Optional[Dict[str, Any]] = None, *, on_step: Optional[Callable[[Dict[str, Any]], None]] = None) -> str:
        """Replay a recorded routine through the real controller.

        No model is involved: the steps are the ones the user demonstrated, so
        replay works offline and gives the same result every time. Every step
        still passes the safety guard and is logged like any other action — a
        learned routine is not a way around the checks, it is a way of *being*
        them.
        """
        from ..control.actions import normalize_action
        from ..skills.base import render_recipe

        self.start()
        steps = [normalize_action(payload) for payload in render_recipe(recipe, arguments or {})]
        steps = self.agent.expand_recipes(steps)
        controller = self.controller
        frame = None
        failures: List[str] = []
        for index, action in enumerate(steps, 1):
            if action.needs_pointer:
                try:
                    frame = self.watcher.snapshot(fresh=True, save=True)
                except Exception:
                    frame = None
            result = controller.perform(action, frame=frame, context=recipe.app or "")
            if on_step is not None:
                on_step(result.as_dict())
            if not result.ok:
                failures.append(f"step {index} ({action.kind}): {result.message}")
                if result.blocked:
                    break
            time.sleep(min(max(getattr(action, "delay", 0.35) or 0.35, 0.05), 2.0))
        if failures:
            return "I could not finish " + recipe.name + ": " + "; ".join(failures[:3])
        return f"ran {recipe.name}: {len(steps)} step(s) from the recording"

    def status(self) -> Dict[str, Any]:
        """Everything the panel's status card shows, in one dict."""
        watcher_stats = self.watcher.stats_payload() if self.watcher else {}
        window = active_window()
        return {
            "model": self.config.llm.label,
            "model_ready": self.model_ready,
            "provider": self.config.llm.base_url,
            "watching": self.watcher.running if self.watcher else False,
            "watching_what": self.watcher.state_line() if self.watcher else "off",
            "busy": self.busy,
            "task": self.agent.current.prompt if self.agent.current else "",
            "window": window.describe(),
            "actions": self.controller.log[-1].message if self.controller.log else "",
            "action_count": len(self.controller.log),
            "watcher": watcher_stats.get("watcher", {}),
            "capture": watcher_stats.get("capture", {}),
            "input_backend": self.controller.input.backend_name,
            "speech": {
                "microphone": _mic_available(),
                "voice": self.config.voice.tts,
            },
            "uptime": round(time.time() - self.started_at, 1),
        }

    def _publish_state(self, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = self.status()
        if extra:
            payload.update(extra)
        self._emit("on_state", payload)

    # --- settings -----------------------------------------------------------
    def update_settings(self, **overrides: Any) -> str:
        """Apply dotted overrides, persist them, and return the config path."""
        self.config = self.config.merged(**overrides)
        # Keep the live components in step with the new values.
        self.agent.config = self.config
        self.controller.config = self.config
        self.safety.settings = self.config.safety
        self.watcher.interval = max(0.25, self.config.capture.interval)
        self.watcher.idle_interval = max(self.watcher.interval, self.config.capture.idle_interval)
        self.watcher.save_frames = self.config.capture.save_frames
        self.watcher.store = ScreenshotStore(str(self.config.screenshots_dir), max_captures=self.config.capture.max_captures)
        path = write_env_file(self.config)
        self._publish_state()
        return path

    # --- helpers ------------------------------------------------------------
    def _set_click_through(self, enabled: bool) -> None:
        if self._click_through is not None:
            try:
                self._click_through(bool(enabled))
            except Exception:
                pass

    def _emit(self, name: str, *args: Any) -> None:
        callback = getattr(self.events, name, None)
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            logger.debug("bridge callback %s raised", name, exc_info=True)

    def recent_captures(self, limit: int = 12) -> List[Dict[str, Any]]:
        """Thumbnail list for the panel's capture gallery."""
        try:
            return self.store.recent(limit=limit)
        except Exception:
            return []

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Recent tasks, newest first."""
        return [task.as_dict() for task in reversed(self.agent.tasks[-limit:])]

    def screenshot_frame(self) -> Any:
        """One fresh frame (used by the panel's mini preview)."""
        try:
            return self.watcher.snapshot(fresh=True)
        except CaptureError:
            return None


def _mic_available() -> bool:
    try:
        from ..speech import mic_available

        return mic_available()
    except Exception:
        return False


def _pseudo_action(kind: str):
    from ..control.actions import Action

    return Action(kind=kind, params={})
