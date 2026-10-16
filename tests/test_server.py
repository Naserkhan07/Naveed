"""The browser front end: the HTTP surface, the page, and the wiring.

These run anywhere — no Qt, no display, no model. The bot's bridge is replaced by
a stand-in that records what the page asked for, which is the point: the HTTP
layer must be testable without an agent behind it, or nobody will test it.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _request(url: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None, token: str = ""):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("X-Naveed-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


class _StubBridge:
    """Enough of AgentBridge for the HTTP layer, and nothing more."""

    def __init__(self, *, busy: bool = False, model_ready: bool = True, refuse: bool = False) -> None:
        self.config = SimpleNamespace(llm=SimpleNamespace(base_url="http://127.0.0.1:11434/v1"))
        self.events = SimpleNamespace()
        self.busy = busy
        self.model_ready = model_ready
        self.refuse = refuse
        self.submitted: List[str] = []
        self.answers: List[str] = []
        self.cancelled = 0
        self.started = 0
        self.stopped = 0
        self.recipes: List[tuple] = []

    def start(self) -> "_StubBridge":
        self.started += 1
        return self

    def stop(self) -> None:
        self.stopped += 1

    def submit(self, prompt: str, **kwargs: Any) -> bool:
        if self.refuse:
            return False
        self.submitted.append(prompt)
        return True

    def answer(self, text: str) -> None:
        self.answers.append(text)

    def cancel(self) -> None:
        self.cancelled += 1

    def run_recipe(self, recipe: Any, arguments: Optional[Dict[str, Any]] = None) -> str:
        self.recipes.append((getattr(recipe, "name", recipe), arguments))
        return f"ran {getattr(recipe, 'name', recipe)}"

    def recent_captures(self, limit: int = 1) -> List[Dict[str, Any]]:
        return []


def _server(**kwargs: Any):
    """A started BotServer on a free port, with a stub bridge."""
    from naveed.config import Config
    from naveed.server import BotServer

    home = tempfile.mkdtemp(prefix="naveed-web-")
    config = Config(home=home)
    config.web.host = "127.0.0.1"
    config.web.port = 0
    bridge = kwargs.pop("bridge", None) or _StubBridge(**kwargs)
    server = BotServer(config, bridge=bridge, host="127.0.0.1", port=0)
    server.start()
    server.bridge = bridge
    return server, bridge


class ApiTests(unittest.TestCase):
    """The endpoints the page talks to."""

    def setUp(self):
        from naveed.server import BotServer

        self._servers: List[BotServer] = []
        self.addCleanup(self._stop_all)

    def _stop_all(self):
        for server in self._servers:
            server.stop()

    def server(self, **kwargs: Any):
        server, bridge = _server(**kwargs)
        self._servers.append(server)
        # The model probe would otherwise hit the network; the page's reachability
        # line is asserted separately with an explicit stub.
        server._probe = lambda force=False: {"at": time.time(), "ok": True, "sentence": "a model answered"}
        return server, bridge

    # --- the page -----------------------------------------------------------
    def test_the_page_is_served_at_the_root(self):
        server, _ = self.server()
        status, headers, body = _request(server.url)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        page = body.decode("utf-8")
        self.assertIn("<title>Naveed</title>", page)
        self.assertIn("id=\"prompt\"", page)
        self.assertIn("naveed", page.lower())
        # Never framed out: a local dashboard may embed the bot on purpose.
        self.assertIsNone(headers.get("X-Frame-Options"))

    def test_the_page_only_uses_relative_urls(self):
        """A page that fetched localhost:8765 would break behind any proxy."""
        from naveed.webui import PAGE

        self.assertNotIn("http://localhost", PAGE)
        self.assertNotIn("http://127.0.0.1", PAGE)
        self.assertNotIn("https://", PAGE.replace("http://www.w3.org/2000/svg", ""))
        self.assertIn('fetch(url', PAGE)

    def test_state_reports_the_bot(self):
        server, _ = self.server()
        status, _, body = _request(server.url + "api/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertTrue(state["model_reachable"])
        self.assertFalse(state["busy"])
        self.assertEqual(state["capture"], [])
        self.assertEqual(state["events"], [])
        self.assertTrue(state["chips"], "the quick-action chips come from QUICK_ACTIONS")
        self.assertIn("port", state)

    def test_state_only_returns_what_the_page_has_not_seen(self):
        server, _ = self.server()
        server.log.add("say", "first")
        _, _, body = _request(server.url + "api/state?since=0")
        events = json.loads(body)["events"]
        self.assertEqual([event["text"] for event in events], ["first"])
        cursor = events[-1]["seq"]
        server.log.add("say", "second")
        _, _, body = _request(f"{server.url}api/state?since={cursor}")
        self.assertEqual([event["text"] for event in json.loads(body)["events"]], ["second"])

    # --- tasks --------------------------------------------------------------
    def test_a_task_is_accepted_and_shows_in_the_log(self):
        server, bridge = self.server()
        status, _, body = _request(server.url + "api/task", "POST", {"prompt": "open my inbox"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(bridge.submitted, ["open my inbox"])
        said = [event["text"] for event in server.state()["events"] if event["kind"] == "you"]
        self.assertEqual(said, ["open my inbox"])

    def test_an_empty_task_is_refused_with_a_reason(self):
        server, bridge = self.server()
        status, _, body = _request(server.url + "api/task", "POST", {"prompt": "   "})
        self.assertEqual(status, 400)
        self.assertIn("empty", json.loads(body)["error"])
        self.assertEqual(bridge.submitted, [])

    def test_a_busy_bot_refuses_a_second_task(self):
        server, bridge = self.server(busy=True)
        status, _, body = _request(server.url + "api/task", "POST", {"prompt": "and another thing"})
        self.assertEqual(status, 409)
        self.assertIn("still working", json.loads(body)["error"])
        self.assertEqual(bridge.submitted, [])

    def test_an_unreachable_model_is_reported_not_queued(self):
        """The headless bug the page must not repeat: a task queued against a dead
        endpoint, then reported as "no answer yet"."""
        server, bridge = self.server()
        server._probe = lambda force=False: {
            "at": time.time(),
            "ok": False,
            "sentence": "nothing is answering at http://127.0.0.1:11434/v1 (Connection refused)",
        }
        status, _, body = _request(server.url + "api/task", "POST", {"prompt": "what is on screen?"})
        self.assertEqual(status, 503)
        payload = json.loads(body)
        self.assertIn("could not reach my model", payload["error"])
        self.assertIn("Connection refused", payload["error"])
        self.assertIn("hint", payload)
        self.assertEqual(bridge.submitted, [], "nothing may be queued against a dead model")

    def test_answering_a_question_reaches_the_agent(self):
        server, bridge = self.server()
        server.log.add("question", "which project?")
        _, _, body = _request(server.url + "api/state")
        self.assertEqual(json.loads(body)["question"], "which project?")
        status, _, _ = _request(server.url + "api/answer", "POST", {"text": "Polarion"})
        self.assertEqual(status, 200)
        self.assertEqual(bridge.answers, ["Polarion"])

    def test_stop_cancels_the_running_task(self):
        server, bridge = self.server(busy=True)
        status, _, _ = _request(server.url + "api/cancel", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(bridge.cancelled, 1)

    def test_a_recipe_can_be_run_by_name(self):
        server, bridge = self.server()
        recipe = SimpleNamespace(name="polarion-set-status")
        with mock.patch("naveed.skills.base.SkillStore.load") as load:
            load.return_value.find_recipe.return_value = recipe
            status, _, body = _request(
                server.url + "api/recipe", "POST", {"name": "polarion-set-status", "args": {"status": "Verified"}}
            )
        self.assertEqual(status, 200)
        self.assertIn("ran polarion-set-status", json.loads(body)["text"])
        self.assertEqual(bridge.recipes, [("polarion-set-status", {"status": "Verified"})])

    def test_an_unknown_recipe_is_a_404(self):
        server, _ = self.server()
        with mock.patch("naveed.skills.base.SkillStore.load") as load:
            load.return_value.find_recipe.return_value = None
            status, _, body = _request(server.url + "api/recipe", "POST", {"name": "nope"})
        self.assertEqual(status, 404)
        self.assertIn("no routine", json.loads(body)["error"])

    def test_unknown_routes_and_methods_are_json_not_html(self):
        server, _ = self.server()
        status, headers, body = _request(server.url + "api/nonsense")
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertIn("no such route", json.loads(body)["error"])

    def test_a_screenshot_that_does_not_exist_yet_says_so(self):
        server, _ = self.server()
        status, _, body = _request(server.url + "api/screen")
        self.assertEqual(status, 404)
        self.assertIn("no screenshot yet", json.loads(body)["error"])

    def test_health_is_readable_without_a_token(self):
        server, _ = self.server()
        status, _, body = _request(server.url + "api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])


class EventFeedTests(unittest.TestCase):
    """The bridge callbacks have to reach the browser *and* the desktop UI."""

    def test_every_event_is_logged_and_forwarded(self):
        from naveed.server import EventFeed, EventLog

        seen: List[str] = []
        inner = SimpleNamespace(
            on_status=lambda state, detail="": seen.append(f"status:{state}"),
            on_say=lambda text: seen.append(f"say:{text}"),
            on_action=lambda result: seen.append("action"),
            on_question=lambda text: seen.append("question"),
            on_task=lambda task: seen.append("task"),
            on_state=lambda snapshot: seen.append("state"),
            on_error=lambda text: seen.append("error"),
        )
        log = EventLog()
        feed = EventFeed(log, inner=inner)
        feed.on_status("thinking", "reading the screen")
        feed.on_say("on it")
        feed.on_action(SimpleNamespace(ok=True, action=SimpleNamespace(describe=lambda: "click"), message="done"))
        feed.on_question("which one?")
        feed.on_task(SimpleNamespace(status=SimpleNamespace(value="done"), prompt="open it", result="opened"))
        feed.on_state({"busy": True})
        feed.on_error("that failed")

        self.assertEqual(
            seen,
            ["status:thinking", "say:on it", "action", "question", "task", "state", "error"],
        )
        kinds = [event["kind"] for event in log.recent(20)]
        self.assertEqual(kinds, ["status", "say", "action", "question", "task", "error"])
        self.assertTrue(feed.state["busy"], "the last snapshot is kept for a page that opens late")

    def test_a_raising_ui_does_not_lose_the_log_line(self):
        """The desktop UI is allowed to blow up; the browser must still see it."""
        from naveed.server import EventFeed, EventLog

        def explode(*args: Any) -> None:
            raise RuntimeError("widget went away")

        log = EventLog()
        feed = EventFeed(log, inner=SimpleNamespace(on_say=explode))
        feed.on_say("still here")  # must not raise
        self.assertEqual([event["text"] for event in log.recent(5)], ["still here"])

    def test_the_log_stays_bounded(self):
        from naveed.server import EventLog

        log = EventLog(limit=16)
        for index in range(50):
            log.add("say", f"line {index}")
        events = log.recent(100)
        self.assertEqual(len(events), 16)
        self.assertEqual(events[-1]["text"], "line 49")
        self.assertGreater(events[0]["seq"], 1, "old lines are dropped, newest kept")


class PolicyTests(unittest.TestCase):
    """Binding, the token, and the port fallback."""

    def test_loopback_needs_no_token(self):
        server, _ = _server()
        self.addCleanup(server.stop)
        self.assertEqual(server.token, "")
        self.assertNotIn("token", server.url)

    def test_a_shared_interface_gets_a_token_and_refuses_without_it(self):
        from naveed.config import Config
        from naveed.server import BotServer

        config = Config(home=tempfile.mkdtemp(prefix="naveed-web-"))
        server = BotServer(config, bridge=_StubBridge(), host="0.0.0.0", port=0)
        self.assertTrue(server.token, "an exposed bot must require its token")
        self.assertNotIn("0.0.0.0", server.url, "the printed URL must be reachable")
        self.assertIn("token=", server.url)

        server.host = "127.0.0.1"       # bind locally, but keep the token on
        server.start()
        self.addCleanup(server.stop)
        status, _, body = _request(f"http://127.0.0.1:{server.port}/api/state")
        self.assertEqual(status, 401)
        self.assertIn("token", json.loads(body)["error"])
        status, _, _ = _request(f"http://127.0.0.1:{server.port}/api/state", token=server.token)
        self.assertEqual(status, 200)

    def test_the_token_can_be_turned_off_on_purpose(self):
        """`--no-token` is for a container port on a network you already trust."""
        from naveed.config import Config
        from naveed.server import BotServer

        config = Config(home=tempfile.mkdtemp(prefix="naveed-web-"))
        config.web.token = False
        server = BotServer(config, bridge=_StubBridge(), host="0.0.0.0", port=0)
        self.assertEqual(server.token, "")
        server.host = "127.0.0.1"
        server.start()
        self.addCleanup(server.stop)
        status, _, _ = _request(f"http://127.0.0.1:{server.port}/api/state")
        self.assertEqual(status, 200)

    def test_a_taken_port_falls_back_instead_of_failing(self):
        """Another copy of Naveed must not stop this one from coming up."""
        from naveed.config import Config
        from naveed.server import BotServer

        first, _ = _server()
        self.addCleanup(first.stop)
        config = Config(home=tempfile.mkdtemp(prefix="naveed-web-"))
        second = BotServer(config, bridge=_StubBridge(), host="127.0.0.1", port=first.port)
        second.start()
        self.addCleanup(second.stop)
        self.assertNotEqual(second.port, first.port)
        status, _, _ = _request(second.url + "api/health")
        self.assertEqual(status, 200)

    def test_the_state_probe_is_cached(self):
        from naveed.server import BotServer

        server = BotServer(
            mock.MagicMock(),
            bridge=_StubBridge(),
            host="127.0.0.1",
            port=0,
        )
        with mock.patch("naveed.agent.llm.LLMClient.probe", return_value=(True, "answered")) as probe:
            first = server._probe(force=True)
            second = server._probe()
        self.assertEqual(first["ok"], True)
        self.assertEqual(second["sentence"], "answered")
        self.assertEqual(probe.call_count, 1, "the page polls once a second; the endpoint is asked once")

    def test_quitting_answers_before_it_stops(self):
        server, _ = self.server_with_stub()
        status, _, body = _request(server.url + "api/quit", "POST", {})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        deadline = time.time() + 5
        while server._httpd is not None and time.time() < deadline:
            time.sleep(0.05)
        self.assertIsNone(server._httpd, "the socket is closed shortly after the reply")

    def server_with_stub(self):
        server, bridge = _server()
        self.addCleanup(server.stop)
        server._probe = lambda force=False: {"at": time.time(), "ok": True, "sentence": "ok"}
        return server, bridge


class OverlayWiringTests(unittest.TestCase):
    """The mascot starts and stops the browser front end, and never dies for it."""

    def app(self, **attrs: Any):
        from naveed.overlay.bridge import OverlayApp

        app = object.__new__(OverlayApp)
        app.config = SimpleNamespace(web=SimpleNamespace(enabled=True, port=8765, host="127.0.0.1", open_browser=False))
        app.server = None
        app.serve = True
        app.open_browser = False
        app.bridge = SimpleNamespace(busy=False)
        for key, value in attrs.items():
            setattr(app, key, value)
        return app

    def test_the_overlay_shares_its_own_bridge_with_the_browser(self):
        app = self.app()
        started: Dict[str, Any] = {}

        class FakeServer:
            def __init__(self, config, bridge=None, host=None, port=None, console=False):
                started["bridge"] = bridge
                started["port"] = port
                self.url = "http://127.0.0.1:8765/"

            def start(self):
                started["started"] = True
                return self

            def stop(self):
                started["stopped"] = True

        with mock.patch("naveed.server.BotServer", FakeServer), contextlib.redirect_stdout(io.StringIO()):
            url = app.start_browser()

        self.assertEqual(url, "http://127.0.0.1:8765/")
        self.assertIs(started["bridge"], app.bridge, "one bot, not two screen watchers")
        self.assertTrue(started["started"])

    def test_a_failed_browser_does_not_stop_the_mascot(self):
        app = self.app()
        with mock.patch("naveed.server.BotServer", side_effect=OSError("address in use")):
            url = app.start_browser()
        self.assertIsNone(url, "the overlay says nothing and carries on")
        self.assertIsNone(app.server)

    def test_quitting_stops_the_browser_too(self):
        app = self.app()
        stopped: List[bool] = []
        app.server = SimpleNamespace(stop=lambda: stopped.append(True), url="http://127.0.0.1:1/")
        app.hotkeys = app.voice = app.tray = None
        app._qt = {}
        app.panel = SimpleNamespace(close=lambda: None)
        app.mascot = SimpleNamespace(close=lambda: None)
        app.bridge = SimpleNamespace(stop=lambda: None)
        app.quit()
        self.assertEqual(stopped, [True])
        self.assertIsNone(app.server)


class LauncherServeTests(unittest.TestCase):
    """`main.py` brings the bot up as a *window* — the browser is never implied.

    These tests used to assert the opposite: that a machine without Qt, or a Qt
    that could not open a window, quietly got the HTTP front end instead. That
    fallback is exactly what "the bot did not appear" looked like, and it is gone.
    """

    def setUp(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import main

        self.main = main

    def config(self):
        from naveed.config import Config

        config = Config(home=tempfile.mkdtemp(prefix="naveed-main-"))
        return config

    def test_bare_argv_dispatches_to_the_starter(self):
        seen: List[Any] = []
        with mock.patch.object(
            self.main, "_start_everything", side_effect=lambda app, config, **k: seen.append((app, config)) or 0
        ), mock.patch(
            "naveed.app.NaveedApp", lambda config: SimpleNamespace(config=config)
        ), mock.patch.object(self.main, "_make_importable", lambda: None), mock.patch.object(
            self.main, "_first_run_hints", lambda *a, **k: None
        ), mock.patch.object(self.main, "_default_setup_if_possible", lambda *a, **k: None), contextlib.redirect_stdout(
            io.StringIO()
        ):
            code = self.main.main([])
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 1, "no arguments means: start the bot")

    def test_a_machine_without_qt_is_told_what_to_install(self):
        started: List[str] = []
        app = SimpleNamespace(
            run_overlay=lambda **k: started.append("overlay") or 0,
            run_server=lambda **k: started.append("server") or 0,
        )
        stream = io.StringIO()
        with mock.patch("naveed.overlay.doctor.qt_available",
                        return_value=(False, "Import error: libGL.so.1: cannot open shared object file")):
            code = self.main._start_everything(app, self.config(), stream=stream)
        text = stream.getvalue()
        self.assertEqual(code, 2)
        self.assertEqual(started, [], "no mascot, and no page either: say why instead")
        self.assertIn("could not open its window", text)
        self.assertIn("libgl1", text)

    def test_the_mascot_starts_without_a_browser_unless_one_is_asked_for(self):
        called: Dict[str, Any] = {}

        def overlay(**kwargs):
            called.update(kwargs)
            return 0

        app = SimpleNamespace(
            run_overlay=overlay, run_server=lambda **k: called.setdefault("server", k) or 0
        )
        with mock.patch("naveed.overlay.doctor.qt_available", return_value=(True, "6.8.1")):
            code = self.main._start_everything(app, self.config(), stream=io.StringIO())
        self.assertEqual(code, 0)
        self.assertNotIn("server", called, "the HTTP front end is opt-in")
        self.assertFalse(called.get("open_browser"), "and so is opening a browser tab")

    def test_a_window_that_cannot_open_is_explained_not_swapped_for_a_page(self):
        app = SimpleNamespace(run_overlay=lambda **k: 2, run_server=lambda **k: 0)
        stream = io.StringIO()
        with mock.patch("naveed.overlay.doctor.qt_available", return_value=(True, "6.8.1")):
            code = self.main._start_everything(app, self.config(), stream=stream)
        self.assertEqual(code, 2)
        self.assertIn("--overlay-check", stream.getvalue())

    def test_the_first_run_hints_name_the_window_check(self):
        config = self.config()
        stream = io.StringIO()
        with mock.patch("naveed.lazy.find_spec_safe", return_value=None):
            self.main._first_run_hints(config, stream=stream)
        text = stream.getvalue()
        self.assertIn("--overlay-check", text)
        self.assertIn('pip install "naveed[ui,capture,input]"', text)
        self.assertNotIn("come up in your browser", text, "there is no silent browser fallback")


if __name__ == "__main__":
    unittest.main()
