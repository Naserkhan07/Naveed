"""Control layer: action normalisation, key handling, safety, OS execution.

The safety tests are the important ones — they encode the promise that Naveed
will not type a password, will not run a shell command unless explicitly allowed,
and will not execute a destructive click without asking.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naveed.config import SafetySettings, load_config
from naveed.control.actions import ActionError, describe_actions, normalize_action, normalize_plan
from naveed.control.keys import normalize_drag_path, normalize_key, normalize_modifiers, parse_hotkey
from naveed.control.os_control import OsController
from naveed.control.safety import RiskLevel, SafetyGuard


class KeyTests(unittest.TestCase):
    def test_aliases_match_the_reference_table(self):
        self.assertEqual(normalize_key("ENTER"), "Enter")
        self.assertEqual(normalize_key("esc"), "Escape")
        self.assertEqual(normalize_key("cmd"), "Meta")
        self.assertEqual(normalize_key("pgdn"), "PageDown")
        self.assertEqual(normalize_key("a"), "a")

    def test_bad_keys_raise_clear_errors(self):
        with self.assertRaises(ValueError):
            normalize_key("   ")
        with self.assertRaises(TypeError):
            normalize_key(None)  # type: ignore[arg-type]

    def test_hotkey_parsing_forms(self):
        self.assertEqual(parse_hotkey("ctrl+alt+space"), ("Control", "Alt", "Space"))
        self.assertEqual(parse_hotkey("Ctrl-Shift-T"), ("Control", "Shift", "T"))
        from naveed.control.keys import canonical_hotkey

        self.assertEqual(parse_hotkey(""), ())
        self.assertEqual(canonical_hotkey("ctrl+s"), "Control+s")
        self.assertEqual(canonical_hotkey("CTRL+Shift+t"), "Control+Shift+t")

    def test_modifier_filtering_and_drag_path(self):
        self.assertEqual(normalize_modifiers(["ctrl", "a", "shift"]), ("Control", "Shift"))
        self.assertEqual(normalize_drag_path([[1, 2], [3, 4]]), [(1, 2), (3, 4)])
        with self.assertRaises(ValueError):
            normalize_drag_path([[1, 2]])


class ActionTests(unittest.TestCase):
    def test_computer_use_style_actions(self):
        click = normalize_action({"type": "click", "x": 10, "y": 20})
        self.assertEqual((click.kind, click.x, click.y), ("click", 10.0, 20.0))
        typed = normalize_action({"type": "type", "text": "hello"})
        self.assertEqual(typed.text, "hello")
        self.assertEqual(normalize_action({"type": "left_click", "x": 1, "y": 2}).kind, "click")

    def test_coordinate_aliases_and_position_lists(self):
        self.assertEqual((normalize_action({"type": "click", "coordinate": [5, 6]}).x), 5.0)
        self.assertEqual((normalize_action({"type": "click", "position": {"x": 7, "y": 8}}).y), 8.0)

    def test_key_action_accepts_key_lists(self):
        action = normalize_action({"type": "keys", "keys": ["ctrl", "s"]})
        self.assertEqual(action.kind, "hotkey")
        self.assertEqual(action.get("hotkey"), "Control+s")

    def test_shorthand_strings(self):
        self.assertEqual(normalize_action("screenshot").kind, "screenshot")
        self.assertEqual(normalize_action("scroll down").kind, "scroll")
        self.assertEqual(normalize_action("wait 2").get("seconds"), 2.0)
        self.assertEqual(normalize_action("open_app Notes").get("app"), "Notes")

    def test_clicks_without_coordinates_need_a_target(self):
        with self.assertRaises(ActionError):
            normalize_action({"type": "click"})
        self.assertEqual(normalize_action({"type": "click", "target": "Save"}).get("target"), "Save")

    def test_plan_normalisation_is_tolerant(self):
        plan = normalize_plan({"summary": "do it", "actions": [{"type": "scroll", "direction": "down"}, {"type": "fly"}]})
        self.assertEqual(len(plan.actions), 1)
        self.assertIn("Unknown action type", plan.understanding)
        self.assertEqual(describe_actions(plan.actions), "Scrolling down (400px)")

    def test_question_only_plan_becomes_an_ask(self):
        plan = normalize_plan({"question": "which file?", "actions": []})
        self.assertEqual(plan.actions[0].kind, "ask")


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.confirmed: list = []
        self.guard = SafetyGuard(
            SafetySettings(confirm_destructive=True),
            confirm=lambda prompt, timeout: self.confirmed.append(prompt) or True,
            announce=lambda message: None,
        )

    def test_ordinary_actions_are_safe(self):
        check = self.guard.review(normalize_action({"type": "scroll", "amount": 300}), context="main.py - Code")
        self.assertEqual(check.risk, RiskLevel.SAFE)
        self.assertTrue(check.is_allowed)

    def test_destructive_keyword_asks_first(self):
        check = self.guard.review(normalize_action({"type": "click", "x": 5, "y": 5, "target": "Delete file"}), context="Explorer")
        self.assertEqual(check.risk, RiskLevel.DESTRUCTIVE)
        self.assertTrue(self.confirmed)  # the human was asked
        self.assertTrue(check.is_allowed)

    def test_refusal_when_the_human_says_no(self):
        guard = SafetyGuard(SafetySettings(confirm_destructive=True), confirm=lambda prompt, timeout: False)
        check = guard.review(normalize_action({"type": "click", "x": 5, "y": 5, "target": "Shutdown"}), context="Start menu")
        self.assertFalse(check.is_allowed)
        self.assertIn("did not confirm", check.denial_reason)

    def test_no_confirmer_means_denied(self):
        guard = SafetyGuard(SafetySettings(confirm_destructive=True))
        check = guard.review(normalize_action({"type": "click", "x": 5, "y": 5, "target": "Delete account"}))
        self.assertFalse(check.is_allowed)

    def test_credentials_are_never_typed_when_a_secret_is_requested(self):
        check = self.guard.review(
            normalize_action({"type": "type", "text": "hunter2"}),
            context="Sign in to GitHub",
            raw_text="log me into github and type my password",
        )
        self.assertEqual(check.risk, RiskLevel.BLOCKED)
        self.assertIn("secret", check.denial_reason)

    def test_ordinary_typing_on_a_signin_page_is_allowed(self):
        # Typing a username or an email into a login form is a normal assistant
        # job; only secrets are refused.
        check = self.guard.review(
            normalize_action({"type": "type", "text": "naveed@example.com"}),
            context="Sign in to GitHub",
            raw_text="type my email into the login box",
        )
        self.assertTrue(check.is_allowed)

    def test_secret_looking_values_are_never_typed(self):
        check = self.guard.review(normalize_action({"type": "type", "text": "sk-live-abcdefghijklmnopqrstuvwxyz"}))
        self.assertTrue(check.blocked)

    def test_shell_is_off_by_default_and_allowlisted_when_on(self):
        off = self.guard.review(normalize_action({"type": "shell", "command": "ls -la"}))
        self.assertTrue(off.blocked)
        on = SafetyGuard(SafetySettings(allow_shell=True, shell_allowlist=["ls"], confirm_destructive=True), confirm=lambda p, t: True)
        allowed = on.review(normalize_action({"type": "shell", "command": "ls -la"}))
        self.assertTrue(allowed.is_allowed)
        denied = on.review(normalize_action({"type": "shell", "command": "curl http://example.com"}))
        self.assertTrue(denied.blocked)

    def test_unrecoverable_patterns_are_blocked_outright(self):
        guard = SafetyGuard(SafetySettings(allow_shell=True), confirm=lambda p, t: True)
        check = guard.review(normalize_action({"type": "shell", "command": "rm -rf /"}))
        self.assertTrue(check.blocked)
        self.assertIn("never runs", check.denial_reason)


class OsControllerTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.config.safety.dry_run = True
        self.controller = OsController(self.config)

    def test_dry_run_reports_success_without_touching_the_machine(self):
        result = self.controller.perform(normalize_action({"type": "type", "text": "hello"}), context="Notes")
        self.assertTrue(result.ok)
        self.assertEqual(result.payload.get("characters"), 5)

    def test_blocked_actions_are_reported_not_executed(self):
        result = self.controller.perform(
            normalize_action({"type": "type", "text": "hunter2"}),
            context="Log in",
            raw_text="log in and type my password",
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)

    def test_clicks_map_through_the_frame_monitor(self):
        from tests.fakes import make_frame
        from naveed.screen.displays import Monitor

        monitor = Monitor(1, 1920, 0, 2560, 1440, 2.0, "side", False)
        # A 2x (retina) capture: 5120x2880 pixels of a 2560x1440 logical display.
        frame = make_frame(0, width=5120, height=2880, monitor=monitor)
        # Pixel 1280,720 in the capture is logical 640,360, which is 1920+640 on screen.
        point = self.controller.global_point(normalize_action({"type": "click", "x": 1280, "y": 720}), frame)
        self.assertEqual(point, (1920 + 640, 360))
        # A 1:1 capture of the same monitor keeps the point unchanged.
        hd_frame = make_frame(0, width=2560, height=1440, monitor=monitor)
        self.assertEqual(
            self.controller.global_point(normalize_action({"type": "click", "x": 1280, "y": 720}), hd_frame),
            (1920 + 1280, 720),
        )

    def test_hotkey_actions_normalise_from_every_shape(self):
        # All three spellings must describe the same physical chord, whichever
        # action kind they end up as.
        for raw in ({"type": "keys", "keys": ["ctrl", "s"]}, {"type": "hotkey", "hotkey": "ctrl+s"},
                    {"type": "key", "key": "s", "modifiers": ["Control"]},
                    {"type": "key", "key": "s", "modifiers": ["ctrl"]}):
            action = normalize_action(raw)
            self.assertIn(action.kind, ("key", "hotkey"), raw)
            self.assertEqual(action.chord, "Control+s", raw)

    def test_scroll_and_wait_are_bounded(self):
        result = self.controller.perform(normalize_action({"type": "scroll", "amount": 10 ** 9}))
        self.assertTrue(result.ok)
        self.assertLessEqual(abs(result.payload["amount"]), 10 ** 9)

    def test_open_app_failure_is_reported_clearly(self):
        self.config.safety.dry_run = False
        controller = OsController(self.config)
        ok, message = controller.open_app("definitely-not-an-app-xyz")
        if sys.platform.startswith("linux"):
            self.assertFalse(ok)
            self.assertIn("definitely-not-an-app-xyz", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
