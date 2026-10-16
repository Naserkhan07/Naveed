"""The task loop: understand → look → act → verify → report.

This is the piece that makes "it sits and watches my screen, then does the task
there and then" real.  One iteration:

1. pause and take a **fresh** frame (the stale one is exactly the frame that
   still shows the pre-action screen);
2. hand the frame, the world model, and the last few attempts to the planner;
3. safety-review each action, then perform it through
   :class:`~naveed.control.os_control.OsController`;
4. wait for the screen to **settle**, then diff the frame before and after to
   learn whether anything actually happened;
5. feed that verdict back as a fact ("nothing on screen changed"), which is what
   stops a small model from repeating a dead action forever.

Two details worth knowing:

* Coordinate actions in a batch share the *same* frame, so a plan that clicks two
  places is offset-correct; but the frame is re-captured between steps, so the
  second step sees reality.
* The loop is bounded three ways (steps, wall-clock, repeated no-change), because
  an unbounded agent loop on someone's desktop is unacceptable.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..config import Config
from ..control.actions import ActionPlan
from ..control.os_control import ActionResult, OsController
from ..control.actions import Action
from ..skills.base import SkillStore, build_skill_context, match_skills, render_recipe
from ..screen.capture import CaptureError
from ..screen.focus import active_window
from .planner import Planner

__all__ = ["Task", "TaskStatus", "NaveedAgent"]

logger = logging.getLogger("naveed.agent")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"      # waiting on the user (a question)
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def active(self) -> bool:
        return self in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.WAITING)


@dataclass
class Task:
    """One user request and everything that happened while handling it."""

    prompt: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: TaskStatus = TaskStatus.PENDING
    summary: str = ""
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    steps: List[Dict[str, Any]] = field(default_factory=list)
    question: str = ""
    answer: str = ""
    steps_used: int = 0
    no_change_streak: int = 0

    @property
    def duration(self) -> float:
        end = self.finished_at or time.time()
        return max(0.0, end - self.created_at)

    @property
    def ok(self) -> bool:
        return self.status is TaskStatus.DONE

    def add_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"step": len(self.steps) + 1, **payload}
        self.steps.append(payload)
        return payload

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "status": self.status.value,
            "summary": self.summary,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "duration": round(self.duration, 2),
            "steps_used": self.steps_used,
            "steps": self.steps,
        }

    def history_for_prompt(self) -> List[Dict[str, Any]]:
        return [
            {
                "step": entry.get("step"),
                "ok": entry.get("ok"),
                "description": entry.get("description", ""),
                "message": entry.get("message", ""),
                "screen_changed": entry.get("screen_changed"),
            }
            for entry in self.steps[-8:]
        ]


def model_unreachable_message(config: Any, detail: str = "") -> str:
    """What to say when the model endpoint is not answering.

    Written for the two ways this actually happens: a local LLM API that is not
    running (the common one — the address is configured, so nothing complains
    until a task starts) and a hosted API that is refusing the request.
    """
    base = str(getattr(config.llm, "base_url", "") or "")
    local = any(host in base for host in ("127.0.0.1", "localhost", "0.0.0.0", "::1"))
    lines = [f"I could not reach my model at {base or 'the configured endpoint'}."]
    if local:
        lines.append(
            "That address is a server on this machine, and nothing is answering on it. "
            "Start it, or point me at a hosted model instead:"
        )
        lines.append("  ollama serve          # then: ollama pull qwen2.5vl:7b")
        lines.append("  python -m naveed --setup --provider lmstudio   # another local server")
        lines.append("  python -m naveed --api URL --model NAME        # any endpoint; local needs no token")
    else:
        lines.append("That API may be down, or the token it wants may be wrong:")
        lines.append("  python -m naveed --check")
        lines.append("  python -m naveed --setup --provider openai --token YOUR_TOKEN   # or openrouter / groq")
        lines.append("  python -m naveed --setup --provider ollama     # or go local: no token exists")
    if detail:
        lines.append(f"(the server said: {detail})")
    return "\n".join(lines)


class NaveedAgent:
    """Runs tasks against the live screen."""

    def __init__(
        self,
        config: Config,
        *,
        watcher: Any = None,
        controller: Optional[OsController] = None,
        planner: Optional[Planner] = None,
        on_status: Optional[Callable[[str, str], None]] = None,
        on_say: Optional[Callable[[str], None]] = None,
        on_action: Optional[Callable[[ActionResult], None]] = None,
        on_question: Optional[Callable[[str], None]] = None,
        on_finish: Optional[Callable[[Task], None]] = None,
        on_step: Optional[Callable[[Dict[str, Any]], None]] = None,
        skills: Any = None,
    ) -> None:
        self.config = config
        self.watcher = watcher
        self.skills = skills if skills is not None else SkillStore(config)
        if controller is None:
            controller = OsController(config, watcher=watcher, tools=self.resolve_tool)
        elif getattr(controller, "tools", None) is None:
            # An injected controller still needs the packs' tools to be reachable.
            controller.tools = self.resolve_tool
            if getattr(controller, "safety", None) is not None:
                controller.safety.tool_writes = controller._tool_writes
        self.controller = controller
        self._active_skill_ids: Tuple[str, ...] = ()
        self._planner = planner
        self.on_status = on_status
        self.on_say = on_say
        self.on_action = on_action
        self.on_question = on_question
        self.on_finish = on_finish
        self.on_step = on_step

        self._stop = threading.Event()
        self._answer_event = threading.Event()
        self._answer_text = ""
        self._lock = threading.RLock()
        self.current: Optional[Task] = None
        self.tasks: List[Task] = []
        self.speech_queue: List[str] = []
        #: Recipes learned with --teach are saved here, and reported so the user
        #: can see that the demonstration was understood.
        self.last_recipe: Optional[Any] = None

    # --- wiring ---------------------------------------------------------
    @property
    def planner(self) -> Planner:
        if self._planner is None:
            self._planner = Planner(self.config, should_stop=self._stop.is_set)
        return self._planner

    def bind_controller(self, controller: OsController) -> None:
        self.controller = controller
        if getattr(controller, "tools", None) is None:
            controller.tools = self.resolve_tool
            if getattr(controller, "safety", None) is not None:
                controller.safety.tool_writes = controller._tool_writes

    # --- knowledge packs -------------------------------------------------
    def resolve_tool(self, skill_id: str, tool_name: str) -> Any:
        """Find a knowledge pack's tool, for :class:`OsController` to run."""
        store = self.skills.load()
        skill = store.find_skill(skill_id)
        if skill is not None:
            tool = skill.tool(tool_name)
            if tool is not None:
                return tool
        for candidate in store.skills:
            tool = candidate.tool(tool_name)
            if tool is not None:
                return tool
        return None

    def _skill_context(self, task: Task, window: Any) -> str:
        """Knowledge for the app in front, injected only when it changes.

        Re-sending the same notes every step would eat the prompt budget a small
        model needs for the screenshot description, so the block is attached on
        the first step and whenever the matched packs change (including the moment
        the task moves into a different app).
        """
        if not getattr(self.config.skills, "enabled", True) or not getattr(self.config.skills, "inject", True):
            return ""
        try:
            store = self.skills.load()
            matches = match_skills(store, window=window, task=task.prompt, limit=2)
        except Exception as error:
            logger.debug("skill matching failed: %s", error)
            return ""
        ids = tuple(result.skill.id for result in matches)
        if not matches:
            self._active_skill_ids = ()
            return ""
        if ids == self._active_skill_ids and task.steps:
            return ""
        self._active_skill_ids = ids
        try:
            return build_skill_context(matches, task=task.prompt, budget=int(self.config.skills.max_context_chars), config=self.config)
        except Exception as error:
            logger.debug("skill context failed: %s", error)
            return ""

    def expand_recipes(self, actions: Sequence[Any], *, depth: int = 0) -> List[Any]:
        """Replace ``recipe`` actions with the steps they stand for.

        Expansion happens *here*, before execution, so every expanded step goes
        through exactly the same safety check, logging and verification as an
        action the model produced itself. A recipe is not a bypass; it is a
        shorthand.
        """
        from ..control.actions import normalize_action

        expanded: List[Action] = []
        for action in actions:
            if action.kind != "recipe":
                expanded.append(action)
                continue
            name = str(action.params.get("name") or action.params.get("recipe") or "")
            arguments = action.params.get("args") if isinstance(action.params.get("args"), dict) else {}
            recipe = self.skills.load().find_recipe(name)
            if recipe is None:
                expanded.append(
                    normalize_action({"type": "ask", "question": f"I do not know a routine called {name!r}. Should I work it out myself?"})
                )
                continue
            missing = recipe.missing_arguments(arguments)
            if missing:
                expanded.append(
                    normalize_action(
                        {
                            "type": "ask",
                            "question": f"To run {recipe.name} I still need: {', '.join(missing)}.",
                        }
                    )
                )
                continue
            if depth >= 3:
                logger.warning("recipe nesting too deep at %s", recipe.name)
                continue
            logger.info("expanding recipe %s with %s", recipe.name, arguments or "no arguments")
            steps = [normalize_action(payload) for payload in render_recipe(recipe, arguments)]
            expanded.extend(self.expand_recipes(steps, depth=depth + 1))
        return expanded

    # --- control --------------------------------------------------------
    @property
    def busy(self) -> bool:
        task = self.current
        return bool(task and task.status.active)

    def cancel(self) -> None:
        """Stop the current task at the next safe point."""
        self._stop.set()
        self._answer_event.set()
        with self._lock:
            if self.current is not None and self.current.status.active:
                self.current.status = TaskStatus.CANCELLED
                self.current.result = "stopped"

    def provide_answer(self, text: str) -> None:
        """Answer the question the agent is waiting on."""
        self._answer_text = text or ""
        self._answer_event.set()

    def wait_for_answer(self, task: Task, question: str, *, timeout: Optional[float] = None) -> str:
        """Block until the user answers, or the timeout expires."""
        timeout = timeout if timeout is not None else float(self.config.agent.step_timeout)
        self._answer_event.clear()
        self._answer_text = ""
        task.question = question
        task.status = TaskStatus.WAITING
        self._emit_status("waiting", question)
        if self.on_question is not None:
            self._safe(self.on_question, question)
        got = self._answer_event.wait(timeout=timeout)
        task.status = TaskStatus.RUNNING
        if not got or self._stop.is_set():
            self._answer_text = ""
        else:
            task.answer = self._answer_text
        return self._answer_text

    # --- the loop --------------------------------------------------------
    def run(self, prompt: str, *, extra_context: str = "") -> Task:
        """Execute one user request. Blocking; call from a worker thread."""
        self._stop.clear()
        task = Task(prompt=prompt.strip())
        with self._lock:
            self.current = task
            self.tasks.append(task)
            if len(self.tasks) > max(5, self.config.agent.remember_last_tasks):
                del self.tasks[: len(self.tasks) - self.config.agent.remember_last_tasks]
        task.status = TaskStatus.RUNNING
        self._emit_status("thinking", f"Listening: {prompt}")

        if not self.planner.client.configured:
            task.status = TaskStatus.FAILED
            task.error = "no model configured"
            task.result = (
                "I need an LLM API before I can do this. Point me at one in ~/.naveed/config.env, "
                "or point me at a local model (LLM_BASE_URL=http://127.0.0.1:11434/v1)."
            )
            self._emit_status("error", task.result)
            self._safe(self.on_say, task.result)
            return self._finish(task)

        started = time.time()
        deadline = started + float(self.config.agent.max_task_seconds)
        max_steps = max(1, int(self.config.agent.max_steps))
        context = extra_context

        try:
            for step in range(1, max_steps + 1):
                if self._stop.is_set():
                    task.status = TaskStatus.CANCELLED
                    task.result = task.result or "stopped"
                    break
                if time.time() > deadline:
                    task.status = TaskStatus.FAILED
                    task.error = "time limit reached"
                    task.result = "I ran out of time on this one. Tell me to continue if you want me to pick it up again."
                    break

                task.steps_used = step
                plan, frame = self._plan_step(task, step, context)
                if self._stop.is_set():
                    task.status = TaskStatus.CANCELLED
                    break
                if plan is None:
                    # `_plan_step` returns None for two very different reasons: the
                    # screen could not be captured, or the model could not be
                    # reached (which it has already explained, complete with the
                    # address and how to start a server). Do not paper over the
                    # second one with a capture message.
                    if task.status is TaskStatus.FAILED and task.error:
                        break
                    task.status = TaskStatus.FAILED
                    task.error = task.error or "the screen could not be captured"
                    task.result = "I could not see the screen just now."
                    break

                task.summary = plan.summary or task.summary
                if plan.summary and self.config.agent.speak_plan:
                    self._safe(self.on_say, plan.summary)

                outcome = self._run_plan(task, plan, frame, step)
                context = ""  # extra context only applies to the first step

                if outcome.get("finish"):
                    task.status = TaskStatus.DONE if outcome.get("ok", True) else TaskStatus.FAILED
                    task.result = outcome.get("result") or plan.summary or "Done."
                    break
                if outcome.get("cancelled"):
                    task.status = TaskStatus.CANCELLED
                    break
                if outcome.get("answered"):
                    context = f"USER ANSWER: {outcome['answered']}"
                    continue

                if task.no_change_streak >= 3 and self.config.agent.retry_on_no_change >= 0:
                    task.status = TaskStatus.FAILED
                    task.result = (
                        "I clicked but nothing on the screen changed, so I stopped instead of "
                        "guessing. Tell me what you see and I will try a different route."
                    )
                    break
            else:
                task.status = TaskStatus.FAILED
                task.error = "step limit reached"
                task.result = "I hit my step limit on this one. Tell me to keep going and I will continue."
        except CaptureError as error:
            task.status = TaskStatus.FAILED
            task.error = str(error)
            task.result = f"I cannot see the screen: {error}"
        except Exception as error:  # never leak a traceback into the UI
            logger.exception("task failed")
            task.status = TaskStatus.FAILED
            task.error = f"{type(error).__name__}: {error}"
            task.result = f"Something went wrong: {type(error).__name__}: {error}"

        if task.status is TaskStatus.RUNNING:
            task.status = TaskStatus.DONE
        return self._finish(task)

    def _plan_step(self, task: Task, step: int, context: str):
        """Capture the world and ask the planner for the next step."""
        self._emit_status("thinking", "Looking at your screen…")
        frame = self._fresh_frame()
        world = ""
        if self.watcher is not None:
            try:
                world = self.watcher.world_summary(lines=self.config.agent.history_lines)
            except Exception:
                world = ""
        ocr_text = self._ocr_text(frame) if self.config.agent.use_ocr else ""
        window = active_window()
        monitors = self._monitors()
        # What Naveed knows about the app in front is part of the request, not a
        # separate feature: without it the model rediscovers the same UI every
        # time. It is attached only on the step where it changes.
        skill_notes = self._skill_context(task, window)
        if skill_notes:
            context = f"{context}\n\n{skill_notes}" if context else skill_notes
        try:
            plan = self.planner.plan(
                task.prompt,
                frame=frame,
                window=window,
                world=world,
                history=task.history_for_prompt(),
                monitors=monitors,
                step=step,
                ocr_text=ocr_text,
                extra_context=context,
            )
        except Exception as error:
            logger.exception("planner call failed")
            self._safe(self.on_say, f"The model call failed: {error}")
            return None, frame
        if getattr(plan, "error", ""):
            # A model that cannot be reached is not a question for the user: fail
            # the task now, saying which server is not answering and how to start
            # one, instead of waiting for a reply that cannot help.
            task.status = TaskStatus.FAILED
            task.error = plan.error
            task.result = model_unreachable_message(self.config, plan.error)
            self._emit_status("error", task.result)
            self._safe(self.on_say, task.result)
            return None, frame
        return plan, frame

    def _fresh_frame(self):
        """A frame from *now* — the only honest input for a plan."""
        if self.watcher is not None:
            try:
                return self.watcher.snapshot(fresh=True, save=True)
            except CaptureError:
                raise
            except Exception as error:
                logger.debug("watcher snapshot failed: %s", error)
        return self.controller.capture_now() if hasattr(self.controller, "capture_now") else None

    def _monitors(self) -> List[Any]:
        """Monitor list for the prompt, from the watcher when it has one."""
        watcher_monitors = getattr(self.watcher, "_monitors", None)
        if watcher_monitors:
            return list(watcher_monitors)
        from ..screen.displays import monitors_or_default

        try:
            return list(monitors_or_default())
        except Exception:
            return []

    def _ocr_text(self, frame: Any) -> str:
        if frame is None or not self.config.agent.use_ocr:
            return ""
        try:
            from ..control.ocr import read_text

            items = read_text(frame.image, limit=60)
        except Exception:
            return ""
        if not items:
            return ""
        return " | ".join(item.text for item in items)[:1400]

    def _run_plan(self, task: Task, plan: ActionPlan, frame: Any, step: int) -> Dict[str, Any]:
        """Perform the actions of one plan, verifying the screen after the batch."""
        outcome: Dict[str, Any] = {}
        # A `recipe` action is a shorthand for the steps it stands for; expanding
        # it here means every expanded step is safety-checked, logged and verified
        # exactly like an action the model emitted itself.
        plan.actions = self.expand_recipes(plan.actions)
        pointer_actions = sum(1 for action in plan.actions if action.needs_pointer)
        context = self._window_context()
        before_hash = self._frame_hash(frame)

        for index, action in enumerate(plan.actions):
            if self._stop.is_set():
                outcome["cancelled"] = True
                return outcome

            # A fresh frame before each pointer action in a multi-click batch:
            # the previous click may have moved the UI under the next coordinate.
            if action.needs_pointer and (index > 0 or pointer_actions > 1):
                try:
                    frame = self._fresh_frame()
                except Exception:
                    pass

            if action.kind == "ask":
                question = str(action.params.get("question") or plan.question or "Can you tell me more?")
                answer = self.wait_for_answer(task, question)
                if answer:
                    task.add_step({"ok": True, "description": f"Asked: {question}", "message": f"answered: {answer[:80]}"})
                    outcome["answered"] = answer
                else:
                    task.result = question
                    task.status = TaskStatus.FAILED
                    outcome["finish"] = True
                    outcome["ok"] = False
                    outcome["result"] = f"I asked: {question} (no answer yet)"
                    self._safe(self.on_say, question)
                return outcome

            self._emit_status("acting", action.describe())
            if action.kind == "skill_tool":
                self._safe(self.on_say, f"Using the {action.get('skill') or 'pack'} API: {action.get('tool')}")
            result = self.controller.perform(action, frame=frame, context=context, raw_text=task.prompt)
            self._safe(self.on_action, result)
            self._safe(self.on_step, task.add_step(result.as_dict()))

            if result.blocked:
                task.status = TaskStatus.FAILED
                task.result = result.message
                outcome.update({"finish": True, "ok": False, "result": result.message})
                self._safe(self.on_say, result.message)
                return outcome

            if action.kind == "done":
                summary = str(action.params.get("summary") or plan.summary or "Done.")
                task.status = TaskStatus.DONE
                task.result = summary
                outcome.update({"finish": True, "ok": True, "result": summary})
                self._safe(self.on_say, summary)
                return outcome

            if not result.ok:
                # Report and let the next step try something else.
                self._safe(self.on_say, f"That did not work: {result.message}")
                break

            if action.kind == "wait":
                continue

        # Verify: did any of that actually change the screen?
        settled = False
        if self.watcher is not None:
            try:
                settled = self.watcher.wait_until_settled(timeout=self.config.agent.settle_timeout)
            except Exception:
                settled = False
        after = self._fresh_frame()
        after_hash = self._frame_hash(after)
        changed = None if (before_hash is None or after_hash is None) else (before_hash != after_hash)
        if changed is False:
            task.no_change_streak += 1
        else:
            task.no_change_streak = 0
        if task.steps and isinstance(task.steps[-1], dict):
            task.steps[-1].setdefault("screen_changed", changed)
        outcome["screen_changed"] = changed
        if changed is False and not settled:
            self._safe(self.on_say, "Nothing moved on screen.")
        return outcome

    @staticmethod
    def _frame_hash(frame: Any) -> Optional[str]:
        if frame is None:
            return None
        try:
            from ..screen.diff import frame_hash

            return frame_hash(frame.signature())
        except Exception:
            return None

    def _window_context(self) -> str:
        window = active_window()
        parts = [window.title, window.process]
        return " — ".join(part for part in parts if part)

    def _finish(self, task: Task) -> Task:
        task.finished_at = time.time()
        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.DONE
        if not task.result:
            task.result = task.summary or "Done."
        self._emit_status(task.status.value, task.result)
        self._safe(self.on_finish, task)
        return task

    # --- helpers ---------------------------------------------------------
    def _emit_status(self, state: str, detail: str = "") -> None:
        self._safe(self.on_status, state, detail)

    @staticmethod
    def _safe(callback: Optional[Callable], *args: Any) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            logger.debug("agent callback raised", exc_info=True)

    # --- quick, no-planner actions ---------------------------------------
    def quick_capture(self) -> Optional[str]:
        """Take a screenshot without involving the model (panel shortcut)."""
        if self.watcher is None:
            return None
        try:
            frame = self.watcher.snapshot(fresh=True, save=True)
        except Exception:
            return None
        return frame.saved_path or None

    def answer_question(self, question: str) -> str:
        """Answer a question about the screen without changing anything."""
        frame = None
        try:
            frame = self._fresh_frame()
        except Exception:
            pass
        world = ""
        if self.watcher is not None:
            try:
                world = self.watcher.world_summary(lines=self.config.agent.history_lines)
            except Exception:
                world = ""
        ocr_text = self._ocr_text(frame) if frame is not None else ""
        return self.planner.describe_screen(question, frame=frame, window=active_window(), world=world, ocr_text=ocr_text)
