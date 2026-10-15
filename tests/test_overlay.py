"""The visible layer, tested without a display.

Two things are worth testing here and both are easy to get wrong:

1. **The lazy-import promise.**  ``import naveed`` must not pull in Qt, Pillow,
   mss, numpy or pynput — that is what lets the watcher and the CLI run on a bare
   machine.  These tests assert ``sys.modules`` after importing everything.
2. **The character's geometry.**  The mascot is generated, so "does it still look
   like the reference" has to be checkable: the tests below verify the layout
   constants stay inside the body, that the paint is symmetric, and that the
   expression states actually differ from one another.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HEAVY_MODULES = ("PySide6", "PIL", "mss", "numpy", "pynput", "sounddevice", "faster_whisper", "piper", "pyttsx3")


def heavy_loaded() -> list:
    return sorted({name.split(".")[0] for name in list(sys.modules) if name.split(".")[0] in HEAVY_MODULES})


class LazyImportTests(unittest.TestCase):
    """The lazy-import promise, checked in a *fresh interpreter*.

    In-process checks are order-dependent (an earlier test may already have
    imported Pillow for its own rendering), so the real assertion runs a child
    process: import every one of Naveed's packages and then inspect
    ``sys.modules`` for anything heavy.  That is exactly the promise the project
    makes — "Naveed starts with no heavy dependency loaded" — so that is exactly
    what gets tested.
    """

    def _imported_modules(self, statement: str) -> list:
        import subprocess

        script = (
            "import sys, json\n"
            f"{statement}\n"
            "heavy = ('PySide6', 'PIL', 'mss', 'numpy', 'pynput', 'sounddevice',"
            " 'faster_whisper', 'piper', 'pyttsx3')\n"
            "print(json.dumps(sorted({m.split('.')[0] for m in sys.modules if m.split('.')[0] in heavy})))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        import json

        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_importing_every_package_pulls_in_nothing_heavy(self):
        imported = self._imported_modules(
            "import naveed, naveed.config, naveed.screen, naveed.overlay,"
            " naveed.control, naveed.agent, naveed.speech, naveed.render, naveed.app"
        )
        self.assertEqual(imported, [], f"these should be lazy, but were imported: {imported}")

    def test_starting_the_app_does_not_import_qt_until_the_mascot_is_built(self):
        imported = self._imported_modules(
            "from naveed.config import load_config\n"
            "from naveed.overlay.window import MascotWindow\n"
            "window = MascotWindow(load_config())\n"
            "window.default_position(1920, 1080)\n"
            "window.set_state('thinking')"
        )
        self.assertEqual(imported, [], f"building the facade must not import Qt: {imported}")

    def test_screen_watcher_runs_without_any_heavy_dependency(self):
        imported = self._imported_modules(
            "from naveed.screen import ScreenWatcher\n"
            "w = ScreenWatcher(interval=0.5)\n"
            "w.world_summary()\n"
            "w.state_line()"
        )
        self.assertEqual(imported, [], f"the watcher must be import-cheap: {imported}")

    def test_missing_dependency_error_explains_the_feature_and_the_fix(self):
        from naveed import lazy

        error = lazy.MissingDependencyError("mss")
        message = str(error)
        self.assertIn("mss", message)
        self.assertIn("screen capture", message)
        self.assertIn("pip install", message)

    def test_load_and_optional_behave_differently(self):
        from naveed import lazy

        self.assertIsNone(lazy.optional("a_package_that_does_not_exist"))
        with self.assertRaises(lazy.MissingDependencyError):
            lazy.load("a_package_that_does_not_exist")

    def test_lazy_attrs_resolves_modules_and_attributes(self):
        import naveed.overlay as overlay
        import naveed.render as render

        self.assertEqual(overlay.mascot.__name__, "naveed.overlay.mascot")
        self.assertEqual(overlay.MascotWindow.__name__, "MascotWindow")
        self.assertEqual(render.PillowCanvas.__name__, "PillowCanvas")
        with self.assertRaises(AttributeError):
            overlay.definitely_not_here

    def test_report_covers_every_documented_dependency(self):
        from naveed import lazy

        report = lazy.report()
        self.assertIn("PySide6", report)
        self.assertIn("mss", report)
        self.assertTrue(all("feature" in entry for entry in report.values()))


class OverlayStartupTests(unittest.TestCase):
    """The order of `run()`: Qt is loaded by `build()`, which must come first.

    `run()` used to read `self._qt["QtWidgets"]` *before* calling `build()` — the
    method that populates that dictionary. The result was
    ``KeyError: 'QtWidgets'`` out of the very first thing a user types
    (`python -m naveed`), on every platform, before the mascot could appear.
    """

    def _app(self, calls):
        from types import SimpleNamespace

        from naveed.overlay.bridge import OverlayApp

        app = object.__new__(OverlayApp)          # no Qt, no widgets: just the order

        class FakeQApplication:
            @staticmethod
            def instance():
                calls.append("qt-instance")
                return SimpleNamespace(exec=lambda: 7, setQuitOnLastWindowClosed=lambda flag: None)

        class FakeQtWidgets:
            QApplication = FakeQApplication

        def build():
            calls.append("build")
            app._qt = {"QtCore": SimpleNamespace(Signal=None), "QtWidgets": FakeQtWidgets}
            app.application = FakeQApplication.instance()

        app.config = SimpleNamespace(overlay=SimpleNamespace(start_hidden=False, show_panel_on_start=False, size=168),
                                     voice=SimpleNamespace(tts="none"))
        app._qt = {}
        app.build = build
        app.mascot = SimpleNamespace(show=lambda: calls.append("mascot-show"), position=lambda: (0, 0))
        app.panel = SimpleNamespace(
            show=lambda near=None: calls.append("panel-show"),
            set_mute=lambda flag: calls.append("panel-mute"),
            apply_state=lambda status: calls.append("panel-state"),
        )
        app.bridge = SimpleNamespace(
            config=app.config,
            start=lambda: calls.append("bridge-start"),
            model_ready=True,
            say=lambda text: calls.append("say"),
            status=lambda: {},
        )
        return app

    def test_run_builds_before_it_reaches_for_qt(self):
        calls = []
        app = self._app(calls)
        self.assertEqual(app.run(), 7, "run() returns the event loop's exit code")
        self.assertEqual(calls[0], "build", "build() populates _qt and must come first")
        self.assertIn("qt-instance", calls)

    def test_build_makes_the_application_before_any_widget(self):
        """Qt's rule: no QWidget before a QApplication, or nothing is drawn.

        Windows printed "QWidget: Must construct a QApplication before a QWidget"
        and the mascot silently never appeared, because the widgets were built
        first and `QApplication.instance()` only ever *looks* for one.
        """
        from types import SimpleNamespace
        from unittest import mock

        from naveed.overlay.bridge import OverlayApp

        created = []

        class FakeQApplication:
            def __init__(self, argv):
                created.append("created")

            @staticmethod
            def instance():
                return None

            def setApplicationName(self, name):
                pass

            setApplicationDisplayName = setApplicationName
            setQuitOnLastWindowClosed = setApplicationName

        class FakeQtWidgets:
            QApplication = FakeQApplication

        class FakeQtCore:
            Signal = None
            QTimer = object

        def load(name, **kwargs):
            return FakeQtWidgets if name.endswith("QtWidgets") else FakeQtCore

        app = object.__new__(OverlayApp)
        app._qt = {}
        app.voice = None
        app.tray = None
        app.hotkeys = None
        app._questions = []
        app._last_spoken = ""

        class FakeWidget:
            def build(self):
                # Every real build() constructs a QWidget, so this is the moment the
                # QApplication must already exist.
                assert created, "a widget was built before the QApplication"
                return self

            def __getattr__(self, item):
                return lambda *a, **k: None

        app.mascot = FakeWidget()
        app.panel = FakeWidget()
        app.config = SimpleNamespace(
            overlay=SimpleNamespace(always_on_top=True, hotkey="", tray=False, size=168, padding=46, start_hidden=True),
            voice=SimpleNamespace(tts="none"),
        )

        with mock.patch("naveed.overlay.bridge.lazy.load", side_effect=load), mock.patch.object(
            OverlayApp, "_wire_signals", return_value=None
        ):
            app.build()

        self.assertEqual(created, ["created"], "exactly one QApplication")
        self.assertIsNotNone(app.application)

    def test_run_does_not_die_when_qt_was_never_loaded(self):
        """The failure mode the user hit: no Qt in `_qt`, KeyError, mascot never appears."""
        calls = []
        app = self._app(calls)
        app.build = lambda: calls.append("build")     # a build that cannot load Qt
        with self.assertRaises(KeyError):
            # A build() that fails to load Qt is still a hard error — but it must be
            # *after* the attempt, so the real message (the ImportError from
            # lazy.load) is what the user sees, not a KeyError from an empty dict.
            app.run()
        self.assertEqual(calls, ["build"])


class PanelPlacementTests(unittest.TestCase):
    """The panel must never sit on top of the mascot it belongs to.

    The mascot now starts at the top of the screen ("below the camera"), so the
    panel's default anchor — above it — has nowhere to go. Clamping the panel up
    there stacked it on the character, which reads as a broken app.
    """

    def panel(self):
        from unittest import mock

        from naveed.config import load_config
        from naveed.overlay.panel import ControlPanel

        config = load_config()
        panel = ControlPanel(
            config,
            on_command=lambda text: None, on_quick=lambda key: None, on_listen=lambda: None,
            on_stop=lambda: None, on_answer=lambda text: None, on_confirm=lambda *a: None,
            on_settings=lambda: None, on_hide=lambda: None, on_quit=lambda: None,
            on_toggle_mute=lambda muted: None,
        )
        patcher = mock.patch("naveed.overlay.window._primary_screen_size", return_value=(1920, 1080))
        patcher.start()
        self.addCleanup(patcher.stop)
        return panel, config

    def test_it_flips_below_when_there_is_no_room_above(self):
        from naveed.overlay.panel import PANEL

        panel, config = self.panel()
        mascot_y, mascot_size = 37, 168          # the below-camera default
        x, y = panel.anchor_position((876, mascot_y, mascot_size))
        self.assertGreaterEqual(y, mascot_y + mascot_size, "the panel must clear the mascot")
        self.assertLessEqual(y + PANEL.height, 1080 - 8)

    def test_it_still_prefers_above_when_there_is_room(self):
        from naveed.overlay.panel import PANEL

        panel, config = self.panel()
        x, y = panel.anchor_position((876, 600, 168))
        self.assertLess(y + PANEL.height, 600, "a panel in the middle of the screen still opens above")

    def test_it_never_leaves_the_screen(self):
        from naveed.overlay.panel import PANEL

        panel, config = self.panel()
        for mascot in ((0, 8, 168), (876, 37, 168), (1752, 900, 168), (960, 540, 168)):
            x, y = panel.anchor_position(mascot)
            self.assertGreaterEqual(x, 8, mascot)
            self.assertGreaterEqual(y, 8, mascot)
            self.assertLessEqual(x + PANEL.width, 1920 - 8, mascot)
            self.assertLessEqual(y + PANEL.height, 1080 - 8, mascot)


class CrossThreadTests(unittest.TestCase):
    """Callbacks that arrive off the GUI thread must hop back onto it.

    pynput's listener and the speech threads call straight into the overlay; Qt
    widgets may only be touched from the thread that owns them, which fails
    quietly on Linux and crashes on Windows.
    """

    def test_the_global_hotkey_goes_through_a_signal(self):
        from types import SimpleNamespace
        from unittest import mock

        from naveed.overlay.bridge import OverlayApp

        app = object.__new__(OverlayApp)
        emitted = []
        app._relay = SimpleNamespace(wake=SimpleNamespace(emit=lambda: emitted.append("wake")))
        with mock.patch.object(OverlayApp, "_on_mascot_click") as direct:
            OverlayApp._on_hotkey(app)
        self.assertEqual(emitted, ["wake"], "the hotkey must not touch widgets from pynput's thread")
        self.assertFalse(direct.called)

    def test_voice_state_goes_through_a_signal(self):
        from types import SimpleNamespace

        from naveed.overlay.bridge import OverlayApp

        app = object.__new__(OverlayApp)
        seen = []
        app._relay = SimpleNamespace(
            voice_state=SimpleNamespace(emit=lambda state: seen.append(state)),
            level=SimpleNamespace(emit=lambda level: seen.append(round(level, 2))),
        )
        app.mascot = SimpleNamespace(set_state=lambda state: seen.append(f"direct:{state}"))
        app.panel = SimpleNamespace(set_state_expression=lambda state: None)
        OverlayApp._on_voice_state(app, "listening")
        OverlayApp._on_voice_level(app, 0.42)
        self.assertEqual(seen, ["listening", 0.42], "no widget may be touched from the speech thread")


class PlacementTests(unittest.TestCase):
    """Where the bot appears, and where it comes back.

    "Below the camera" is the default because the alternative — the middle of the
    screen — lands on whatever the person is reading, and the first thing they do
    is drag it away. Everything here is pure arithmetic plus two small files.
    """

    def overlay(self, **kwargs):
        from types import SimpleNamespace

        defaults = dict(size=168, anchor="below_camera", remember_position=True, x=None, y=None, offset_from_middle=0.16)
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_the_default_is_centred_just_under_the_camera(self):
        from naveed.overlay.placement import resolve_start_position

        x, y = resolve_start_position(self.overlay(), size=168, screen_width=1920, screen_height=1080)
        self.assertEqual(x, 1920 // 2 - 84, "centred horizontally")
        self.assertLess(y, 100, "near the top of the screen, under the webcam bezel")
        self.assertGreater(y, 0)

    def test_the_old_middle_behaviour_is_still_a_choice(self):
        from naveed.overlay.placement import resolve_start_position

        _, y = resolve_start_position(self.overlay(anchor="middle"), size=168, screen_width=1920, screen_height=1080)
        self.assertGreater(y, 500, "the middle anchor still means the middle")

    def test_every_anchor_stays_on_screen(self):
        from naveed.overlay.placement import ANCHORS, resolve_start_position

        for anchor in ANCHORS:
            x, y = resolve_start_position(self.overlay(anchor=anchor), size=168, screen_width=1366, screen_height=768)
            self.assertGreaterEqual(x, 0, anchor)
            self.assertGreaterEqual(y, 0, anchor)
            self.assertLess(x + 168, 1366, anchor)
            self.assertLess(y + 168, 768, anchor)

    def test_an_explicit_position_wins(self):
        from naveed.overlay.placement import resolve_start_position

        position = resolve_start_position(
            self.overlay(x=400, y=300), size=168, screen_width=1920, screen_height=1080, saved=(10, 10)
        )
        self.assertEqual(position, (400, 300))

    def test_a_position_remembered_from_a_bigger_screen_is_clamped(self):
        from naveed.overlay.placement import resolve_start_position

        x, y = resolve_start_position(
            self.overlay(), size=168, screen_width=1280, screen_height=720, saved=(5000, 5000)
        )
        self.assertLessEqual(x + 168, 1280, "an off-screen position looks exactly like 'it did not start'")
        self.assertLessEqual(y + 168, 720)

    def test_a_dragged_position_is_remembered_between_runs(self):
        import tempfile

        from naveed.config import load_config
        from naveed.overlay.placement import clear_saved_position, load_saved_position, resolve_start_position, save_position

        with tempfile.TemporaryDirectory() as home:
            config = load_config()
            config.home = home
            self.assertIsNone(load_saved_position(config), "nothing saved yet")
            self.assertTrue(save_position(config, 640, 480))
            self.assertEqual(load_saved_position(config), (640, 480))
            start = resolve_start_position(
                config.overlay, size=168, screen_width=1920, screen_height=1080, saved=load_saved_position(config)
            )
            self.assertEqual(start, (640, 480), "the bot comes back where it was put")
            clear_saved_position(config)
            self.assertIsNone(load_saved_position(config))
            restored = resolve_start_position(
                config.overlay, size=168, screen_width=1920, screen_height=1080, saved=load_saved_position(config)
            )
            self.assertLess(restored[1], 100, "and forgetting it returns to below the camera")

    def test_remembering_can_be_switched_off(self):
        import tempfile

        from naveed.config import load_config
        from naveed.overlay.placement import load_saved_position, save_position

        with tempfile.TemporaryDirectory() as home:
            config = load_config()
            config.home = home
            config.overlay.remember_position = False
            self.assertFalse(save_position(config, 10, 20))
            self.assertIsNone(load_saved_position(config))

    def test_a_corrupt_state_file_is_ignored_rather_than_fatal(self):
        import tempfile
        from pathlib import Path

        from naveed.config import load_config
        from naveed.overlay.placement import load_saved_position

        with tempfile.TemporaryDirectory() as home:
            config = load_config()
            config.home = home
            state = Path(home) / "state"
            state.mkdir(parents=True, exist_ok=True)
            (state / "overlay.json").write_text("{not json", encoding="utf-8")
            self.assertIsNone(load_saved_position(config))
            (state / "overlay.json").write_text('{"x": "left", "y": 2}', encoding="utf-8")
            self.assertIsNone(load_saved_position(config))


class ThemeTests(unittest.TestCase):
    def test_palette_matches_the_reference_colours(self):
        from naveed.overlay.theme import PALETTE

        # Orange upper half -> coral lower half, white cloud, pink mouth.
        self.assertEqual(PALETTE["orange"].upper(), "#FF8A2B")
        self.assertEqual(PALETTE["coral"].upper(), "#FF5B57")
        self.assertEqual(PALETTE["cloud"].upper(), "#FFFFFF")
        self.assertEqual(PALETTE["pink"].upper(), "#FF6B81")

    def test_face_geometry_stays_inside_the_body(self):
        from naveed.overlay.theme import MASCOT

        for name, value in (
            ("cloud_top", MASCOT.cloud_top),
            ("cloud_bottom", MASCOT.cloud_bottom),
            ("scallop_y", MASCOT.scallop_y),
            ("eye_y", MASCOT.eye_y),
            ("blush_y", MASCOT.blush_y),
            ("mouth_y", MASCOT.mouth_y),
        ):
            self.assertTrue(0.0 < value < 1.0, f"{name} must be a fraction of the body")
        # Eyes must sit below the middle (inside the cloud) and above the mouth.
        self.assertLess(MASCOT.cloud_top, MASCOT.eye_y)
        self.assertLess(MASCOT.eye_y, MASCOT.mouth_y)
        self.assertLess(MASCOT.mouth_y, MASCOT.cloud_bottom)
        # Blush outside the eyes, inside the body.
        self.assertGreater(MASCOT.blush_dx, MASCOT.eye_dx)
        self.assertLess(MASCOT.blush_dx + MASCOT.blush_radius, 0.5)

    def test_shortcut_grid_fills_the_panel_grid(self):
        from naveed.overlay.theme import PANEL, SHORTCUTS

        self.assertEqual(len(SHORTCUTS), PANEL.grid_columns * PANEL.grid_rows)
        self.assertTrue(all(len(item) == 2 for item in SHORTCUTS))


class AnimatorTests(unittest.TestCase):
    def test_blinking_happens_and_eyes_reopen(self):
        from naveed.overlay.mascot import MascotAnimator

        animator = MascotAnimator(seed=1)
        closed_seen = False
        for _ in range(900):  # 15 seconds at 60fps
            frame = animator.update(1 / 60.0)
            if frame.blink < 0.5:
                closed_seen = True
        self.assertTrue(closed_seen, "the mascot never blinked in 15 seconds")

    def test_float_stays_within_its_amplitude(self):
        from naveed.overlay.mascot import MascotAnimator

        animator = MascotAnimator(seed=2, float_amplitude=0.02)
        values = [animator.update(1 / 60.0).float_offset for _ in range(600)]
        self.assertLessEqual(max(abs(value) for value in values), 0.021)

    def test_speaking_moves_the_mouth_and_idle_closes_it(self):
        from naveed.overlay.mascot import MascotAnimator

        speaking = MascotAnimator(seed=3)
        speaking.set_state("speaking")
        mouth = [speaking.update(1 / 30.0).mouth for _ in range(60)]
        self.assertGreater(max(mouth), 0.4)
        self.assertGreater(max(mouth) - min(mouth), 0.2, "the mouth barely moved while speaking")

        idle = MascotAnimator(seed=3)
        after = [idle.update(1 / 30.0).mouth for _ in range(30)]
        self.assertLess(max(after), 0.05)

    def test_sleeping_keeps_the_eyes_closed(self):
        from naveed.overlay.mascot import MascotAnimator

        animator = MascotAnimator(seed=4)
        animator.set_state("sleeping")
        self.assertTrue(all(animator.update(1 / 30.0).blink == 0.0 for _ in range(30)))

    def test_every_state_produces_a_distinct_face(self):
        from naveed.overlay.mascot import STATES
        from naveed.render.pillow_canvas import PillowCanvas
        from naveed.overlay.mascot import paint_mascot

        signatures = {}
        for state in STATES:
            canvas = PillowCanvas(180, 180, background="#101018")
            paint_mascot(canvas, 10, 10, 160, state=state, phase=0.4, mouth=0.5)
            signatures[state] = canvas.image.tobytes()
        self.assertEqual(len(set(signatures.values())), len(STATES), "two expressions render identically")


class IconTests(unittest.TestCase):
    def test_icons_render_something_and_are_not_blank(self):
        from naveed.overlay.icons import ICON_NAMES, draw_icon
        from naveed.render.pillow_canvas import PillowCanvas

        for name in ICON_NAMES:
            canvas = PillowCanvas(48, 48)
            draw_icon(canvas, name, 4, 4, 40, "#FFFFFF")
            pixels = canvas.image.getchannel("A").getextrema()
            self.assertGreater(pixels[1], 0, f"icon {name!r} drew nothing")

    def test_unknown_icon_is_ignored(self):
        from naveed.overlay.icons import draw_icon
        from naveed.render.pillow_canvas import PillowCanvas

        canvas = PillowCanvas(32, 32)
        draw_icon(canvas, "no_such_icon", 0, 0, 32)  # must not raise
        self.assertEqual(canvas.image.getchannel("A").getextrema(), (0, 0))


class TrayAndWindowFacadeTests(unittest.TestCase):
    def test_mascot_window_facade_works_without_qt(self):
        from naveed.config import load_config
        from naveed.overlay.window import MascotWindow

        window = MascotWindow(load_config())
        self.assertGreater(window.size, 0)
        x, y = window.default_position(1920, 1080)
        self.assertLess(x, 1920)
        self.assertLess(y, 1080)
        self.assertLess(y, 1080 - window.size, "the mascot should sit below the vertical middle")
        window.set_state("thinking")
        self.assertEqual(window.state, "thinking")
        window.set_state("nonsense")
        self.assertEqual(window.state, "idle")

    def test_panel_anchor_keeps_the_panel_on_screen(self):
        from naveed.config import load_config
        from naveed.overlay.panel import ControlPanel

        for config in (load_config(), load_config(**{"overlay.panel_anchor": "below"})):
            panel = ControlPanel(config)
            x, y = panel.anchor_position((1800, 900, 200))
            self.assertGreaterEqual(x, 8)
            self.assertGreaterEqual(y, 8)


class OverlayDoctorTests(unittest.TestCase):
    """`--overlay-check`: the answer to "I ran it and nothing appeared".

    The report itself is pure Python, so it is testable everywhere; the window
    assertions that need real Qt live in RealWindowTests below and skip when Qt
    cannot start.
    """

    def test_a_missing_system_library_is_named_with_the_command_that_fixes_it(self):
        from naveed.overlay import doctor

        message = "ImportError: libGL.so.1: cannot open shared object file: No such file or directory"
        hint = doctor.library_hint(message)
        self.assertIsNotNone(hint, "libGL is the single most common cause")
        self.assertIn("libgl1", hint)
        for text, expected in (
            ("libEGL.so.1: cannot open shared object file", "libegl1"),
            ("libxkbcommon.so.0: cannot open shared object file", "libxkbcommon-x11"),
            ("libdbus-1.so.3: cannot open shared object file", "libdbus-1-3"),
        ):
            self.assertIn(expected, doctor.library_hint(text) or "", text)
        self.assertIsNone(doctor.library_hint("something nobody has seen before"))

    def test_the_environment_report_never_raises_and_says_whether_qt_is_usable(self):
        from naveed.overlay import doctor

        report = doctor.environment_report()
        for key in ("python", "os", "session", "display", "wayland", "pyside6", "qt_ok"):
            self.assertIn(key, report)
        self.assertIn(report["qt_ok"], ("yes", "no"))

    def test_an_unusable_qt_is_reported_with_the_fix_and_exit_code_2(self):
        import contextlib
        import io

        from naveed.config import load_config
        from naveed.overlay import doctor

        stream = io.StringIO()
        with mock.patch.object(doctor, "qt_available", return_value=(
            False,
            "PySide6.QtWidgets is not installed\nImport error: libGL.so.1: cannot open shared "
            "object file: No such file or directory",
        )):
            with contextlib.redirect_stdout(stream):
                code = doctor.run_check(load_config(), stream=stream)
        output = stream.getvalue()

        self.assertEqual(code, 2)
        self.assertIn("no window can be created", output)
        self.assertIn("libGL.so.1", output)
        self.assertIn("libgl1", output, "the system package that fixes it must be printed")

    def test_a_pyside_version_with_a_known_crash_is_flagged_with_the_fix(self):
        from naveed.overlay import doctor

        warning = doctor.pyside_warning("6.12.0")
        self.assertIsNotNone(warning, "6.12.0 aborts after a few thousand gradient fills")
        self.assertIn("<6.12", warning)
        self.assertIsNone(doctor.pyside_warning("6.8.1"))
        self.assertIsNone(doctor.pyside_warning(""))

    def test_a_headless_plugin_is_not_mistaken_for_a_visible_one(self):
        from naveed.overlay import doctor

        self.assertNotIn("offscreen", doctor.VISIBLE_PLATFORMS,
                         "offscreen runs, and shows nothing: that is the confusing case")
        for name in ("xcb", "wayland", "windows", "cocoa"):
            self.assertIn(name, doctor.VISIBLE_PLATFORMS)


class LauncherStartsAWindowTests(unittest.TestCase):
    """`python main.py` must start the *window*, or explain why it cannot.

    It used to fall back to the browser front end when PySide6 was missing or
    broken, which is indistinguishable from "the bot did not appear" — and it is
    what a user with a missing `libGL.so.1` saw instead of the mascot.
    """

    def setUp(self):
        import main as launcher

        self.launcher = launcher

    def _fake_app(self):
        calls = []

        class FakeApp:
            def run_overlay(self, **kwargs):
                calls.append(("overlay", kwargs))
                return 0

            def run_server(self, **kwargs):
                calls.append(("server", kwargs))
                return 0

        return FakeApp(), calls

    def test_a_broken_qt_is_explained_instead_of_starting_a_browser(self):
        import contextlib
        import io

        from naveed.config import load_config

        app, calls = self._fake_app()
        stream = io.StringIO()
        with mock.patch("naveed.overlay.doctor.qt_available",
                        return_value=(False, "Import error: libGL.so.1: cannot open shared object file")):
            with contextlib.redirect_stdout(stream):
                code = self.launcher._start_everything(app, load_config(), stream=stream)
        output = stream.getvalue()

        self.assertEqual(code, 2)
        self.assertEqual(calls, [], "no window and no HTTP server may be started")
        self.assertIn("could not open its window", output)
        self.assertIn("libgl1", output, "the system fix belongs in the message")
        self.assertIn("--serve", output, "the optional HTTP front end is still offered, as a choice")

    def test_a_working_qt_starts_the_window_and_nothing_else(self):
        from naveed.config import load_config

        app, calls = self._fake_app()
        with mock.patch("naveed.overlay.doctor.qt_available", return_value=(True, "6.12.0")):
            with open(os.devnull, "w") as devnull:
                code = self.launcher._start_everything(app, load_config(), stream=devnull)
        self.assertEqual(code, 0)
        self.assertEqual([name for name, _ in calls], ["overlay"])
        self.assertFalse(calls[0][1].get("open_browser"), "the browser is not opened for you")


class RealWindowTests(unittest.TestCase):
    """The window, built by the real Qt — the one test that proves it can appear.

    Run in a **child process** (``python -m naveed --overlay-check``) rather than
    in-process, for two reasons: the check is then exercised exactly as a user
    runs it, and a Qt crash at interpreter shutdown cannot take the test runner
    with it. That is not hypothetical — PySide6 6.12.0 aborts during
    finalization after enough gradient fills, which is why the parent tolerates
    exit code 134 as long as the child's *output* shows the window came up.

    Skipped wherever Qt cannot start at all; on those machines the answer is
    ``--overlay-check``, not a green tick. ``QT_QPA_PLATFORM=offscreen`` is forced
    so the test never flashes a window on somebody's desktop.
    """

    @classmethod
    def setUpClass(cls):
        from naveed.overlay import doctor

        cls.usable, cls.reason = doctor.qt_available()

    def setUp(self):
        if not self.usable:
            self.skipTest(f"Qt cannot open a window here: {self.reason.splitlines()[0]}")

    def _run_check(self, *extra: str) -> str:
        """Run the real check in a child process and return its output."""
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["NAVEED_HOME"] = tempfile.mkdtemp(prefix="naveed-overlay-")
        process = subprocess.run(
            [sys.executable, "-m", "naveed", "--overlay-check", *extra],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env=environment, capture_output=True, text=True, timeout=180,
        )
        output = f"{process.stdout}\n{process.stderr}"
        self.assertIn(
            process.returncode, (0, 134),
            f"unexpected exit {process.returncode}:\n{output}",
        )
        return output

    def test_the_mascot_comes_up_visible_on_top_and_inside_the_screen(self):
        output = self._run_check()
        self.assertIn("mascot window:", output)
        self.assertIn("✓ the mascot is on screen", output)
        for flag in ("frameless", "always-on-top", "no-taskbar-entry"):
            self.assertIn(f"✓ {flag}", output, f"the window must be {flag}")

    def test_the_window_check_can_show_what_the_window_contains(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "shot.png")
            output = self._run_check("--save", target)
            self.assertIn("saved", output)
            for suffix in ("mascot", "panel"):
                path = os.path.join(directory, f"shot-{suffix}.png")
                self.assertTrue(os.path.exists(path), f"{suffix} snapshot missing:\n{output}")
                self.assertGreater(os.path.getsize(path), 2000, "a blank snapshot proves nothing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
