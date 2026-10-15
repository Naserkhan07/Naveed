"""The task loop: does it act, verify, ask, stop, and never spin?

These tests replace the screen with real pixels (:mod:`tests.fakes`) and the
model with a scripted planner, so the loop's decisions are deterministic:

* a normal task runs its actions and finishes with the model's summary;
* a plan that never changes the screen stops after the configured streak instead
  of clicking forever;
* a safety refusal aborts the task *and* tells the user why;
* an ``ask`` action waits for the human and feeds the answer into the next step;
* cancellation and budgets (steps, time) are honoured.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naveed.agent.executor import NaveedAgent, Task, TaskStatus
from naveed.agent.llm import extract_json
from naveed.agent.planner import Planner
from naveed.config import load_config
from tests.fakes import FakeWatcher, ScriptedPlanner


def make_agent(**kwargs):
    config = load_config()
    config.safety.dry_run = True
    config.agent.use_ocr = False
    watcher = kwargs.pop("watcher", None) or FakeWatcher()
    events = {"status": [], "say": [], "actions": [], "steps": [], "finished": []}
    agent = NaveedAgent(
        config,
        watcher=watcher,
        on_status=lambda state, detail="": events["status"].append((state, detail)),
        on_say=lambda text: events["say"].append(text),
        on_action=lambda result: events["actions"].append(result),
        on_step=lambda step: events["steps"].append(step),
        on_finish=lambda task: events["finished"].append(task),
        **kwargs,
    )
    return agent, watcher, events, config


class LoopTests(unittest.TestCase):
    def test_successful_task_runs_actions_and_finishes(self):
        agent, watcher, events, config = make_agent()
        agent._planner = ScriptedPlanner(
            [
                {"summary": "Typing into the search box", "actions": [{"type": "click", "x": 100, "y": 120}]},
                {"summary": "All done", "actions": [{"type": "done", "summary": "Searched for cats."}], "done": True},
            ]
        )
        task = agent.run("search for cats")
        self.assertEqual(task.status, TaskStatus.DONE)
        self.assertEqual(task.result, "Searched for cats.")
        self.assertEqual(len(events["actions"]), 2)
        self.assertIn("done", [event[0] for event in events["status"]])
        # The fresh frame is captured for every step, never reused stale.
        self.assertGreaterEqual(watcher.snapshots, 2)

    def test_no_change_streak_stops_instead_of_clicking_forever(self):
        agent, watcher, events, config = make_agent()
        config.agent.max_steps = 20
        # The fake screen never changes, so every step reports "nothing changed".
        agent._planner = ScriptedPlanner(
            [{"summary": "click", "actions": [{"type": "click", "x": 10, "y": 10}]} for _ in range(20)]
        )
        task = agent.run("click something useless")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("nothing on the screen changed", task.result)
        self.assertLessEqual(task.steps_used, 4)

    def test_blocked_action_aborts_and_explains(self):
        agent, watcher, events, config = make_agent()
        agent._planner = ScriptedPlanner(
            [{"summary": "login", "actions": [{"type": "type", "text": "hunter2"}]}]
        )
        task = agent.run("sign in to my bank and type my password")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("secret", task.result)
        self.assertTrue(any(result.blocked for result in events["actions"]))

    def test_ask_action_waits_for_the_user_and_continues(self):
        agent, watcher, events, config = make_agent()
        config.agent.step_timeout = 3.0
        asked: list = []
        agent.on_question = lambda question: (asked.append(question), agent.provide_answer("the one on the left"))[0]
        agent._planner = ScriptedPlanner(
            [
                {"summary": "need to know which", "question": "which file?", "actions": [{"type": "ask", "question": "which file?"}]},
                {"summary": "opened it", "actions": [{"type": "done", "summary": "Opened the left file."}], "done": True},
            ]
        )
        task = agent.run("open my file")
        self.assertEqual(asked, ["which file?"])
        self.assertEqual(task.status, TaskStatus.DONE)
        self.assertEqual(task.result, "Opened the left file.")

    def test_unanswered_question_ends_the_task_with_the_question(self):
        agent, watcher, events, config = make_agent()
        config.agent.step_timeout = 0.2  # nobody answers
        agent._planner = ScriptedPlanner([{"summary": "ask", "actions": [{"type": "ask", "question": "which monitor?"}]}])
        task = agent.run("arrange my windows")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("which monitor?", task.result)

    def test_step_limit_is_respected(self):
        agent, watcher, events, config = make_agent()
        config.agent.max_steps = 3
        watcher.auto_change = True  # keep the screen moving so the streak never trips
        agent._planner = ScriptedPlanner(
            [{"summary": "step", "actions": [{"type": "scroll", "amount": 200}]} for _ in range(10)]
        )
        task = agent.run("scroll forever")
        self.assertEqual(task.steps_used, 3)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("step limit", task.result)

    def test_cancel_stops_a_running_task(self):
        agent, watcher, events, config = make_agent()
        watcher.auto_change = True
        agent._planner = ScriptedPlanner(
            [{"summary": "step", "actions": [{"type": "wait", "seconds": 0.2}]} for _ in range(50)]
        )
        thread = threading.Thread(target=agent.run, args=("wait a long time",))
        thread.start()
        time.sleep(0.35)
        agent.cancel()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(agent.current.status, TaskStatus.CANCELLED)

    def test_missing_model_is_reported_in_plain_language(self):
        agent, watcher, events, config = make_agent()
        agent._planner = Planner(config)  # real planner, no key configured
        task = agent.run("do something")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("model", task.result.lower())
        self.assertTrue(events["say"])

    def test_planner_failure_becomes_a_question_not_a_crash(self):
        agent, watcher, events, config = make_agent()

        class Exploding:
            class _Client:
                configured = True

            client = _Client()

            def plan(self, task, **kwargs):
                raise RuntimeError("boom")

        agent._planner = Exploding()
        task = agent.run("do the impossible")
        self.assertIn(task.status, (TaskStatus.FAILED, TaskStatus.DONE))
        self.assertTrue(events["status"])


class PlannerParseTests(unittest.TestCase):
    def test_prose_reply_becomes_a_look_action(self):
        config = load_config()
        planner = Planner(config)

        class ProseClient:
            configured = True

            def chat(self, messages, **kwargs):
                class Reply:
                    text = "I think you should click the blue button."
                    json = None

                return Reply()

        planner.client = ProseClient()
        plan = planner.plan("do the thing", frame=None)
        self.assertEqual(plan.actions[0].kind, "look")

    def test_done_without_actions_gets_a_done_action(self):
        config = load_config()
        planner = Planner(config)

        class DoneClient:
            configured = True

            def chat(self, messages, **kwargs):
                class Reply:
                    text = '{"done": true, "summary": "Everything is finished."}'
                    json = {"done": True, "summary": "Everything is finished."}

                return Reply()

        planner.client = DoneClient()
        plan = planner.plan("finish up", frame=None)
        self.assertEqual(plan.actions[0].kind, "done")

    def test_json_extraction_is_forgiving(self):
        self.assertEqual(extract_json('```json\n{"a": 1,}\n```'), {"a": 1})
        self.assertEqual(extract_json('blah {"b": [1,2]} trailing'), {"b": [1, 2]})
        self.assertIsNone(extract_json("no json"))


class HeadlessRunTests(unittest.TestCase):
    """`python -m naveed -p "..."` must wait for the task and say why if it fails.

    Two bugs lived here, both invisible until someone ran the CLI on a real
    machine:

    * ``submit()`` returned before the worker had touched the queue, so a caller
      polling ``busy`` saw False immediately and gave up — printing
      *"no task ran"* while the task was in fact still running;
    * a worker that crashed said nothing at all in the headless modes, because
      they subscribed to every event except ``on_error``.
    """

    def bridge(self, agent):
        from naveed.agent.bridge import AgentBridge

        config = load_config()
        config.safety.dry_run = True
        config.agent.use_ocr = False
        bridge = AgentBridge(config)
        bridge.agent = agent          # the real one would need a model and a screen
        # The agent reports completion through the callback the bridge gave it, so
        # the stand-in gets the same wiring rather than pretending to be an agent.
        agent.on_finish = bridge._on_finish
        return bridge

    def test_busy_is_true_the_moment_a_task_is_accepted(self):
        release = threading.Event()
        started = threading.Event()

        class BlockingAgent:
            busy = False
            current = None
            tasks: list = []

            def run(self, prompt, *, extra_context=""):
                started.set()
                release.wait(5.0)
                task = Task(prompt=prompt, status=TaskStatus.DONE, result="done")
                self.on_finish(task)
                return task

            def cancel(self):
                release.set()

            def provide_answer(self, text):
                pass

        bridge = self.bridge(BlockingAgent())
        self.assertTrue(bridge.submit("open notepad and type hello"))
        self.assertTrue(bridge.busy, "a queued task is not an idle bridge — this is the -p race")
        try:
            self.assertTrue(started.wait(5.0))
            self.assertTrue(bridge.busy, "still busy while the agent is working")
        finally:
            release.set()
        deadline = time.time() + 5.0
        while bridge.busy and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(bridge.busy)
        self.assertIsNotNone(bridge.last_task)
        self.assertEqual(bridge.last_task.status, TaskStatus.DONE)

    def test_a_crashing_worker_leaves_a_reason_behind(self):
        class ExplodingAgent:
            busy = False
            current = None
            tasks: list = []

            def run(self, prompt, *, extra_context=""):
                raise RuntimeError("the model endpoint refused the connection")

            def cancel(self):
                pass

            def provide_answer(self, text):
                pass

        bridge = self.bridge(ExplodingAgent())
        bridge.submit("open notepad and type hello")
        deadline = time.time() + 5.0
        while bridge.busy and time.time() < deadline:
            time.sleep(0.02)
        self.assertIn("RuntimeError", bridge.last_error)
        self.assertIn("refused the connection", bridge.last_error)

    def test_run_task_reports_the_reason_instead_of_a_bare_no_task_ran(self):
        import contextlib
        import io as io_module
        from unittest import mock

        from naveed.agent import bridge as bridge_module
        from naveed.app import NaveedApp

        class DeadBridge:
            def __init__(self, config, **kwargs):
                self.config = config
                self.model_ready = True
                self.busy = False
                self.last_task = None
                self.last_error = "RuntimeError: the model endpoint refused the connection"

            def start(self):
                return self

            def submit(self, prompt, **kwargs):
                return True

            def stop(self):
                pass

        app = object.__new__(NaveedApp)
        app.config = load_config()
        app.bridge = None

        out, err = io_module.StringIO(), io_module.StringIO()
        with mock.patch.object(bridge_module, "AgentBridge", DeadBridge):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = NaveedApp.run_task(app, "open notepad and type hello")
        self.assertEqual(code, 1)
        self.assertIn("no task ran", err.getvalue())
        self.assertIn("refused the connection", err.getvalue(), "the user must be told why")


if __name__ == "__main__":
    unittest.main(verbosity=2)
