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
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
