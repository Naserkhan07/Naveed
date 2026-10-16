"""The browser front end: the same bot, reachable over HTTP.

Naveed is a desktop overlay — the mascot that floats over your other windows is
still the main way to use it.  This module adds the second way the same bot can be
used: an HTTP server with a small page at ``http://127.0.0.1:8765``.  It exists
because the two are good at different things:

* the mascot is always there, sees what you see, and needs no window;
* the browser gives you a real text box, a scrollback of what the bot did, and a
  way to reach the same bot from a tablet or another machine on your LAN.

Both front ends drive **one** :class:`~naveed.agent.bridge.AgentBridge` when they
run in the same process (the overlay starts the server and hands it over), so a
task submitted from the browser moves the mascot on screen and vice versa.

Three deliberate choices:

``http.server``
    No web framework.  The bot already has a long dependency list; making the
    browser front end require ``fastapi``/``flask`` would mean the browser half is
    the one that fails to install.  ``ThreadingHTTPServer`` is in the standard
    library and is more than enough for one user.
``127.0.0.1`` by default
    Binding wider is opt-in (``--host 0.0.0.0``) and then a token is required on
    every request, because an agent that can type into your window is not
    something to expose by accident.
``no external assets``
    The page is one string in :mod:`naveed.webui`; it works on a machine with no
    internet access and behind any proxy.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import Config
from .webui import PAGE

logger = logging.getLogger("naveed.server")

__all__ = ["BotServer", "EventLog", "EventFeed", "DEFAULT_HOST", "DEFAULT_PORT", "serve", "main"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
#: how long a reachability answer is trusted before asking the model endpoint again
PROBE_TTL = 15.0
#: ring buffer size — the browser only ever shows the tail, and a long session
#: must not grow a list forever
LOG_LIMIT = 400


def _is_loopback(host: str) -> bool:
    return host.strip().strip("[]") in ("", "127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1")


def _free_port(host: str) -> int:
    """Ask the OS for a port (used when the configured one is taken)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host if host else DEFAULT_HOST, 0))
        return int(probe.getsockname()[1])


class EventLog:
    """A thread-safe, bounded, numbered log of everything the bot did.

    Numbered because the page asks only for what it has not seen
    (``/api/state?since=N``), which keeps polling cheap and means a browser tab
    that was in the background for an hour catches up in one request.
    """

    def __init__(self, limit: int = LOG_LIMIT) -> None:
        self.limit = max(16, int(limit))
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._seq = 0

    def add(self, kind: str, text: str, **extra: Any) -> Dict[str, Any]:
        text = (text or "").strip()
        with self._lock:
            self._seq += 1
            event: Dict[str, Any] = {"seq": self._seq, "kind": kind, "text": text, "at": round(time.time(), 3)}
            event.update(extra)
            self._events.append(event)
            if len(self._events) > self.limit:
                del self._events[: len(self._events) - self.limit]
        return event

    def since(self, seq: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(event) for event in self._events if event["seq"] > int(seq or 0)]

    def recent(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(event) for event in self._events[-max(1, int(limit)):]]

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def clear(self) -> None:
        with self._lock:
            self._events = []


class EventFeed:
    """Forwards the bridge's callbacks to a UI *and* to an :class:`EventLog`.

    The overlay already owns its ``BridgeEvents``; rather than teach the bridge
    about the browser, this wrapper is dropped in front of them.  Every attribute
    is optional on both sides, so a bridge created by a test (or by the headless
    CLI) still works.
    """

    _NAMES = ("on_status", "on_say", "on_action", "on_question", "on_task", "on_state", "on_error")

    def __init__(
        self,
        log: EventLog,
        inner: Optional[Any] = None,
        *,
        echo: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.log = log
        self.inner = inner
        self.echo = echo
        #: the most recent status snapshot, so a page opened mid-task shows it
        self.state: Dict[str, Any] = {}
        for name in self._NAMES:
            setattr(self, name, self._make(name))

    # -- the callback factory -------------------------------------------------
    def _make(self, name: str) -> Callable[..., None]:
        def callback(*args: Any) -> None:
            try:
                self.translate(name, args)
            except Exception:  # a logging bug must never break the agent
                logger.debug("event translation failed for %s", name, exc_info=True)
            target = getattr(self.inner, name, None)
            if target is None:
                return
            try:
                target(*args)
            except Exception:
                logger.debug("bridge callback %s raised", name, exc_info=True)

        callback.__name__ = name
        return callback

    def translate(self, name: str, args: tuple) -> None:
        """Turn one bridge callback into one log line (and an optional echo)."""
        event: Optional[Dict[str, Any]] = None
        if name == "on_status":
            state, detail = (list(args) + ["", ""])[:2]
            event = self.log.add("status", f"{state}{(' — ' + detail) if detail else ''}", state=state, detail=detail)
        elif name == "on_say":
            text = args[0] if args else ""
            event = self.log.add("say", str(text))
        elif name == "on_error":
            event = self.log.add("error", str(args[0] if args else "something went wrong"))
        elif name == "on_question":
            event = self.log.add("question", str(args[0] if args else ""))
        elif name == "on_action":
            result = args[0] if args else None
            event = self.log.add("action", _describe_action(result), ok=bool(getattr(result, "ok", True)))
        elif name == "on_task":
            task = args[0] if args else None
            event = self.log.add("task", _describe_task(task))
        elif name == "on_state":
            snapshot = args[0] if args else {}
            if isinstance(snapshot, dict):
                self.state = snapshot
        if event is not None and self.echo is not None:
            try:
                self.echo(event)
            except Exception:
                pass


def _describe_action(result: Any) -> str:
    if result is None:
        return "an action finished"
    action = getattr(result, "action", None)
    try:
        described = action.describe()
    except Exception:
        described = str(action or "action")
    message = str(getattr(result, "message", "") or "")
    return f"{described} — {message}" if message else described


def _describe_task(task: Any) -> str:
    if task is None:
        return "task finished"
    status = getattr(getattr(task, "status", None), "value", "") or "?"
    prompt = str(getattr(task, "prompt", "") or "").strip()
    note = str(getattr(task, "result", "") or "").strip()
    head = f"{status.upper()}: {prompt}" if prompt else status.upper()
    return f"{head}\n{note}" if note else head


class BotServer:
    """Serves the browser front end and owns the bridge when nobody else does.

    ``bridge`` is optional on purpose: pass the overlay's bridge and the browser
    becomes a second window onto the *same* running bot (one screen watcher, one
    task queue); leave it out and this object creates, starts and stops its own,
    which is what ``python -m naveed --serve`` does on a machine with no Qt.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        *,
        bridge: Optional[Any] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        console: bool = False,
    ) -> None:
        from .config import load_config

        self.config = config or load_config()
        self.host = (host if host is not None else getattr(self.config.web, "host", "")) or DEFAULT_HOST
        self.port = int(port if port is not None else getattr(self.config.web, "port", DEFAULT_PORT) or DEFAULT_PORT)
        self.console = console
        self.log = EventLog()
        wants_token = bool(getattr(self.config.web, "token", True))
        self.token = "" if _is_loopback(self.host) or not wants_token else secrets.token_urlsafe(18)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._owns_bridge = bridge is None
        self._probe_cache: Dict[str, Any] = {"at": 0.0, "ok": None, "sentence": ""}
        self._probe_lock = threading.Lock()
        self._overlay_process: Optional[subprocess.Popen] = None
        self._chips: List[Dict[str, str]] = []

        if bridge is None:
            from .agent.bridge import AgentBridge, QUICK_ACTIONS

            self.feed = EventFeed(self.log, echo=self._echo)
            self.bridge = AgentBridge(self.config, events=self.feed)
            self._chips = _chips_from(QUICK_ACTIONS)
        else:
            # Wrap whatever the overlay installed, so both UIs see every event.
            self.bridge = bridge
            self.feed = EventFeed(self.log, inner=getattr(bridge, "events", None), echo=self._echo)
            bridge.events = self.feed
            try:
                from .agent.bridge import QUICK_ACTIONS

                self._chips = _chips_from(QUICK_ACTIONS)
            except Exception:
                self._chips = []

    # --- lifecycle ----------------------------------------------------------
    @property
    def url(self) -> str:
        host = self.host or DEFAULT_HOST
        shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        query = f"?token={self.token}" if self.token else ""
        return f"http://{shown}:{self.port}/{query}"

    def start(self) -> "BotServer":
        """Bind and serve in a background thread. Never raises for a busy port."""
        if self._httpd is not None:
            return self
        try:
            self._httpd = self._make_server(self.port)
        except OSError as error:
            # A port clash must not stop the bot from coming up (another copy of
            # Naveed, or something else already on 8765).
            fallback = _free_port(self.host)
            logger.info("port %s is busy (%s) — using %s instead", self.port, error, fallback)
            self._httpd = self._make_server(fallback)
        # Read the port back: with port 0 (or a fallback) the OS picked it, and
        # the URL that gets printed has to be the one that works.
        try:
            self.port = int(self._httpd.server_address[1])
        except (IndexError, TypeError, ValueError):  # pragma: no cover - never on a real socket
            pass
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="naveed-http", daemon=True)
        self._thread.start()
        if self._owns_bridge:
            self.bridge.start()
        # Warm the reachability answer off the request path: the first page load
        # should not wait on a network probe.
        threading.Thread(target=self._probe, kwargs={"force": True}, name="naveed-probe", daemon=True).start()
        logger.info("browser bot on %s", self.url)
        return self

    def _make_server(self, port: int) -> ThreadingHTTPServer:
        handler = _make_handler()
        httpd = ThreadingHTTPServer((self.host, int(port)), handler)
        httpd.daemon_threads = True
        httpd.bot = self  # type: ignore[attr-defined]
        return httpd

    def serve_forever(self) -> int:
        """Run in the calling thread until stopped (``python -m naveed --serve``)."""
        self.start()
        assert self._httpd is not None
        print(f"Naveed is at {self.url}", file=sys.stdout)
        print("  open that in a browser.  Ctrl+C stops it.", file=sys.stdout)
        try:
            while True:
                time.sleep(0.4)
        except KeyboardInterrupt:
            print("\nstopping…", file=sys.stdout)
        finally:
            self.stop()
        return 0

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                logger.debug("http shutdown failed", exc_info=True)
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if self._owns_bridge:
            try:
                self.bridge.stop()
            except Exception:
                logger.debug("bridge stop failed", exc_info=True)

    def __enter__(self) -> "BotServer":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # --- console echo -------------------------------------------------------
    def _echo(self, event: Dict[str, Any]) -> None:
        if not self.console:
            return
        kind = event.get("kind", "?")
        text = str(event.get("text", "")).replace("\n", "  ")
        prefix = {"say": "say:   ", "you": "you:   ", "action": "action:", "error": "error: "}.get(kind, f"[{kind}]")
        print(f"  {prefix} {text}", file=sys.stdout, flush=True)

    # --- state --------------------------------------------------------------
    def _probe(self, *, force: bool = False) -> Dict[str, Any]:
        """(is the model answering, what it said), cached for :data:`PROBE_TTL`."""
        with self._probe_lock:
            fresh = (time.time() - float(self._probe_cache.get("at") or 0.0)) < PROBE_TTL
            if fresh and not force and self._probe_cache.get("ok") is not None:
                return dict(self._probe_cache)
            try:
                from .agent.llm import LLMClient

                ok, sentence = LLMClient(self.config.llm).probe()
            except Exception as error:  # a probe must never break the page
                logger.debug("probe failed: %s", error)
                ok, sentence = True, ""
            self._probe_cache = {"at": time.time(), "ok": bool(ok), "sentence": str(sentence)}
            return dict(self._probe_cache)

    def report(self) -> Dict[str, Any]:
        """Environment + capability report (never raises)."""
        from .app import describe_environment

        try:
            return describe_environment(self.config, probe=False)
        except Exception as error:
            logger.debug("describe failed: %s", error)
            return {}

    def skills_summary(self) -> str:
        try:
            from .skills.base import SkillStore

            store = SkillStore(self.config).load()
            recipes = len(store.all_recipes())
            packs = len(store.summaries())
            return f"{packs} pack(s), {recipes} routine(s)"
        except Exception:
            return "—"

    def state(self, *, since: int = 0) -> Dict[str, Any]:
        """Everything the page needs in one poll."""
        probe = self._probe()
        report = self.report()
        snapshot = self.feed.state or {}
        overlay_available = bool(report.get("ui"))
        question = ""
        for event in reversed(self.log.recent(12)):
            if event["kind"] == "question":
                question = event["text"]
                break
            if event["kind"] in ("say", "error"):
                break
        return {
            "version": __version__,
            "url": self.url if not self.token else self.url.split("?")[0],
            "host": self.host,
            "port": self.port,
            "home": str(self.config.home or ""),
            "model": self.config.llm.label,
            "model_ready": bool(self.config.llm.configured),
            "model_reachable": probe.get("ok"),
            "probe": probe.get("sentence", ""),
            "busy": bool(getattr(self.bridge, "busy", False)),
            "status": snapshot.get("status") or ("working" if getattr(self.bridge, "busy", False) else "idle"),
            "task": snapshot.get("task", ""),
            "window": snapshot.get("window", ""),
            "watching": bool(snapshot.get("watching")),
            "capture": report.get("capture_backends", []),
            "input": report.get("input_backends", []),
            "ocr": report.get("ocr", []),
            "speech": report.get("speech", {}),
            "overlay_available": overlay_available,
            "overlay_running": self.overlay_running,
            "skills": self.skills_summary(),
            "chips": self._chips,
            "question": question,
            "events": self.log.since(since),
        }

    # --- actions ------------------------------------------------------------
    def submit(self, prompt: str) -> Dict[str, Any]:
        """Queue a task, after checking the model actually answers."""
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "code": 400, "error": "nothing to do — the task was empty"}
        if getattr(self.bridge, "busy", False):
            return {"ok": False, "code": 409, "error": "still working on the last thing — press Stop to drop it"}
        # Asked fresh, not cached: the answer decides whether this task is going
        # to work, and "your model stopped answering 14 seconds ago" is exactly
        # the situation the cached value would hide.
        probe = self._probe(force=True)
        if probe.get("ok") is False:
            from .agent.executor import model_unreachable_message

            return {
                "ok": False,
                "code": 503,
                "error": model_unreachable_message(self.config, str(probe.get("sentence") or "")),
                "hint": "run `python main.py --check`, or pick another provider with `python -m naveed --setup`",
            }
        self.log.add("you", prompt)
        accepted = self.bridge.submit(prompt)
        if not accepted:
            return {"ok": False, "code": 409, "error": "the bot did not accept the task (it is busy)"}
        return {"ok": True, "code": 200, "text": "on it"}

    def answer(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "code": 400, "error": "empty answer"}
        self.log.add("you", text)
        self.bridge.answer(text)
        return {"ok": True, "code": 200, "text": "answered"}

    def cancel(self) -> Dict[str, Any]:
        self.bridge.cancel()
        self.log.add("status", "stopped")
        return {"ok": True, "code": 200, "text": "stopped"}

    def skill_recipe(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run a taught routine by name (the taught Polarion routines, usually)."""
        try:
            from .skills.base import SkillStore

            recipe = SkillStore(self.config).load().find_recipe(name)
        except Exception as error:
            return {"ok": False, "code": 500, "error": f"could not load the packs: {error}"}
        if recipe is None:
            return {"ok": False, "code": 404, "error": f"no routine called {name!r}"}
        if getattr(self.bridge, "busy", False):
            return {"ok": False, "code": 409, "error": "still working on the last thing"}
        self.log.add("you", f"run routine {name}")
        try:
            message = self.bridge.run_recipe(recipe, arguments or {})
        except Exception as error:
            self.log.add("error", str(error))
            return {"ok": False, "code": 500, "error": str(error)}
        return {"ok": True, "code": 200, "text": message}

    def latest_screen(self) -> Optional[tuple]:
        """(bytes, content type) for the newest capture, or None."""
        try:
            captures = self.bridge.recent_captures(limit=1)
        except Exception:
            return None
        for record in captures or []:
            path = record.get("path") or ""
            if not path or not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as handle:
                    return handle.read(), "image/png"
            except OSError:
                return None
        return None

    # --- the desktop mascot, from the browser ------------------------------
    @property
    def overlay_running(self) -> bool:
        process = self._overlay_process
        return bool(process is not None and process.poll() is None)

    def launch_overlay(self) -> Dict[str, Any]:
        """Start the floating mascot as its own process (browser → desktop).

        Its own process on purpose: Qt wants the main thread for its event loop,
        and Naveed's main thread is already serving HTTP here.  Plain
        ``python -m naveed`` now starts the window *and nothing else*, so the new
        copy cannot try to bind this port too.
        """
        if self.overlay_running:
            return {"ok": True, "code": 200, "message": "the mascot is already on screen"}
        if not self.report().get("ui"):
            # "PySide6 is installed" and "a window can open" are different
            # questions, so the hint is the *system* answer when that is the
            # problem (a missing libGL.so.1) rather than another pip command.
            hint = 'pip install "naveed[ui]"'
            from .overlay.doctor import library_hint, qt_available

            usable, detail = qt_available()
            if not usable:
                hint = library_hint(str(detail)) or detail.splitlines()[0]
            return {
                "ok": False,
                "code": 400,
                "error": "the floating window cannot start on this machine",
                "hint": hint,
            }
        command = [sys.executable, "-m", "naveed"]
        try:
            self._overlay_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                cwd=_project_root(),
            )
        except Exception as error:
            return {"ok": False, "code": 500, "error": f"could not start the mascot: {error}"}
        return {"ok": True, "code": 200, "message": "the mascot should appear under your camera now"}

    def quit(self) -> Dict[str, Any]:
        """Stop the server (and the desktop mascot, if this process shows one)."""
        if self.overlay_running:
            try:
                self._overlay_process.terminate()  # type: ignore[union-attr]
            except Exception:
                pass
        threading.Thread(target=self._delayed_stop, name="naveed-quit", daemon=True).start()
        return {"ok": True, "code": 200, "text": "stopping"}

    def _delayed_stop(self) -> None:
        time.sleep(0.25)  # let the response reach the browser first
        self.stop()


def _project_root() -> Optional[str]:
    """The checkout root, when running from one (so ``-m naveed`` resolves)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _chips_from(quick_actions: Dict[str, str]) -> List[Dict[str, str]]:
    labels = {
        "look": "What's on screen?",
        "summarise": "Summarise",
        "explain_error": "Explain the error",
        "screenshot": "Screenshot",
        "write": "Write it for me",
        "clean_up": "Tidy up",
        "translate": "Translate",
        "automate": "Automate the boring part",
        "edit": "Edit this text",
    }
    chips: List[Dict[str, str]] = []
    for key, prompt in quick_actions.items():
        if key not in labels:
            continue
        chips.append({"key": key, "label": labels[key], "prompt": prompt})
    return chips


def _make_handler():
    """The request handler class, closed over the module's helpers."""

    class Handler(BaseHTTPRequestHandler):
        server_version = f"Naveed/{__version__}"
        protocol_version = "HTTP/1.1"

        # -- plumbing ------------------------------------------------------
        @property
        def bot(self) -> BotServer:
            return self.server.bot  # type: ignore[attr-defined]

        def log_message(self, fmt: str, *args: Any) -> None:  # keep stderr clean
            logger.debug("%s %s", self.address_string(), fmt % args)

        def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                # Deliberately no X-Frame-Options: embedding the local bot in a
                # dashboard is fine. The server is loopback-only unless asked
                # otherwise, and then it needs a token.
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser navigated away mid-response

        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"))

        def _authorised(self, query: Dict[str, List[str]]) -> bool:
            bot = self.bot
            if not bot.token:
                return True
            given = self.headers.get("X-Naveed-Token", "")
            if not given:
                values = query.get("token") or []
                given = values[0] if values else ""
            return bool(given) and hmac.compare_digest(str(given), bot.token)

        def _body(self) -> Dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return {}
            if length <= 0:
                return {}
            if length > 1_000_000:
                return {}
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                return {}
            return parsed if isinstance(parsed, dict) else {}

        # -- routes --------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            route = parsed.path.rstrip("/") or "/"
            if route == "/favicon.ico":
                self._send(200, b"", "image/x-icon")
                return
            if route in ("/", "/index.html", "/bot"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if not self._authorised(query):
                self._json(401, {"error": "this bot needs its token (see the URL it printed on startup)"})
                return
            if route == "/api/health":
                self._json(200, {"ok": True, "version": __version__, "busy": bool(getattr(self.bot.bridge, "busy", False))})
                return
            if route == "/api/state":
                try:
                    since = int((query.get("since") or ["0"])[0])
                except ValueError:
                    since = 0
                self._json(200, self.bot.state(since=since))
                return
            if route == "/api/screen":
                frame = self.bot.latest_screen()
                if frame is None:
                    self._json(404, {"error": "no screenshot yet — ask me to look at the screen"})
                    return
                self._send(200, frame[0], frame[1])
                return
            self._json(404, {"error": f"no such route: {parsed.path}"})

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            route = parsed.path.rstrip("/")
            if not self._authorised(query):
                self._json(401, {"error": "this bot needs its token (see the URL it printed on startup)"})
                return
            payload = self._body()
            try:
                if route == "/api/task":
                    result = self.bot.submit(str(payload.get("prompt", "")))
                elif route == "/api/answer":
                    result = self.bot.answer(str(payload.get("text", "")))
                elif route == "/api/cancel":
                    result = self.bot.cancel()
                elif route == "/api/quit":
                    result = self.bot.quit()
                elif route == "/api/overlay":
                    result = self.bot.launch_overlay()
                elif route == "/api/recipe":
                    arguments = payload.get("args")
                    result = self.bot.skill_recipe(
                        str(payload.get("name", "")),
                        arguments if isinstance(arguments, dict) else {},
                    )
                else:
                    self._json(404, {"error": f"no such route: {parsed.path}"})
                    return
            except Exception as error:  # never die with a stack trace on the wire
                logger.exception("request failed: %s", route)
                self._json(500, {"error": f"the bot hit a problem: {error}"})
                return
            status = int(result.pop("code", 200))
            if status == 200:
                self._json(200, {"ok": True, **result, "state": self.bot.state(since=self.bot.log.last_seq)})
            else:
                self._json(status, {"ok": False, **result})

    return Handler


def serve(
    config: Optional[Config] = None,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    console: bool = True,
    open_browser: bool = False,
) -> int:
    """Blocking helper: ``python -m naveed --serve`` ends up here."""
    server = BotServer(config, host=host, port=port, console=console)
    if open_browser:
        threading.Timer(0.6, lambda: _open_url(server.url)).start()
    return server.serve_forever()


def _open_url(url: str) -> None:
    """Open *url* in the desktop browser, ignoring a machine that has none."""
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        logger.debug("no browser for %s", url)


def main(argv: Optional[List[str]] = None) -> int:
    """``naveed-web``: the browser front end as its own command.

    The same thing as ``python -m naveed --serve``, for people who installed the
    package and never want to think about a window::

        naveed-web                       # http://127.0.0.1:8765
        naveed-web --host 0.0.0.0        # reachable from your LAN (token required)
        naveed-web --port 0 --quiet      # any free port, no event echo
    """
    import argparse

    from .config import load_config

    parser = argparse.ArgumentParser(
        prog="naveed-web",
        description="Naveed in your browser — the same bot, served over HTTP (no GUI needed).",
    )
    parser.add_argument("--host", metavar="HOST", help="interface to listen on (default 127.0.0.1)")
    parser.add_argument("--port", type=int, metavar="PORT", help="port to listen on (default 8765, or the next free one)")
    parser.add_argument("--open-browser", action="store_true", help="open the page once it is up")
    parser.add_argument("--no-token", action="store_true", help="do not require the token when listening beyond loopback")
    parser.add_argument("--quiet", action="store_true", help="do not echo every event to the terminal")
    parser.add_argument("--check", action="store_true", help="print the environment report and exit")
    args = parser.parse_args(argv)

    config = load_config(**({"web.token": False} if args.no_token else {}))
    if args.host:
        config.web.host = args.host
    if args.port is not None:
        config.web.port = int(args.port)
    if args.check:
        from .app import NaveedApp

        NaveedApp(config).print_report()
        return 0
    return serve(
        config,
        host=config.web.host,
        port=config.web.port,
        console=not args.quiet,
        open_browser=args.open_browser,
    )
